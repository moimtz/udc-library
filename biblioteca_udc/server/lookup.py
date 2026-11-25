"""Free bibliographic APIs: Crossref (DOI), Open Library (ISBN), arXiv."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx

import config
from textutil import parse_name


class LookupFailed(Exception):
    """The service could not be reached or answered with an error."""


def _client() -> httpx.Client:
    ua = "BibliotecaUDC/1.0"
    if config.CONTACT_EMAIL:
        ua += f" (mailto:{config.CONTACT_EMAIL})"
    return httpx.Client(timeout=15, headers={"User-Agent": ua}, follow_redirects=True)


def _get(url: str, **kw):
    try:
        with _client() as c:
            return c.get(url, **kw)
    except httpx.HTTPError as e:
        raise LookupFailed(f"Could not reach {httpx.URL(url).host}: {e}")


# Crossref work type -> Zotero item type (None: let the person choose)
CROSSREF_TYPES = {
    "journal-article": "journalArticle", "proceedings-article": "conferencePaper", "posted-content": "preprint",
    "book": "book", "monograph": "book", "edited-book": "book", "reference-book": "book",
    "book-chapter": "bookSection", "book-section": "bookSection", "book-part": "bookSection",
    "reference-entry": "encyclopediaArticle", "dissertation": "thesis", "report": "report",
    "standard": "standard", "dataset": "dataset",
}


def _date(parts) -> str:
    """Crossref date-parts [[2004, 3, 12]] -> '2004-03-12' (or '2004-03', '2004')."""
    p = [x for x in (parts or [[None]])[0] if x]
    return "-".join([f"{p[0]:04d}"] + [f"{x:02d}" for x in p[1:3]]) if p else ""


def _person(a: dict, ctype: str) -> dict | None:
    if a.get("family") or a.get("given"):
        return {"creator_type": ctype, "last_name": a.get("family", ""), "first_name": a.get("given", ""),
                "field_mode": 0}
    if a.get("name"):
        return {"creator_type": ctype, "last_name": a["name"], "first_name": "", "field_mode": 1}
    return None


def parse_crossref(msg: dict) -> dict:
    """Fields are keyed by Zotero base field (publicationTitle, publisher...); the caller fits them to the
    item type (bookTitle, proceedingsTitle, university...)."""
    def first(v):
        return v[0] if isinstance(v, list) and v else ""

    title = first(msg.get("title"))
    sub = first(msg.get("subtitle"))
    if sub and sub.lower() not in title.lower():
        title = f"{title}: {sub}"
    creators = []
    for ctype, key in (("author", "author"), ("editor", "editor"), ("translator", "translator")):
        for a in msg.get(key, []) or []:
            if c := _person(a, ctype):
                creators.append(c)
    date = ""
    for k in ("issued", "published", "published-print", "published-online"):
        if date := _date((msg.get(k) or {}).get("date-parts")):
            break
    fields = {
        "title": title, "publicationTitle": first(msg.get("container-title")),
        "journalAbbreviation": first(msg.get("short-container-title")), "volume": msg.get("volume", ""),
        "issue": msg.get("issue", ""), "pages": msg.get("page", ""), "publisher": msg.get("publisher", ""),
        "place": msg.get("publisher-location", ""), "date": date, "DOI": msg.get("DOI", ""),
        "url": msg.get("URL", ""), "ISSN": " ".join(msg.get("ISSN") or []), "ISBN": " ".join(msg.get("ISBN") or []),
        "abstractNote": re.sub(r"<[^>]+>", "", msg.get("abstract", "")).strip(),
        "language": msg.get("language", "") or "",
    }
    return {"item_type": CROSSREF_TYPES.get(msg.get("type", "")), "fields": {k: v for k, v in fields.items() if v},
            "creators": creators, "tags": list(msg.get("subject", []) or [])}


def lookup_doi(doi: str) -> dict | None:
    r = _get(f"https://api.crossref.org/works/{quote(doi, safe='/')}")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise LookupFailed(f"Crossref answered with HTTP {r.status_code}.")
    return parse_crossref(r.json().get("message", {}))


def parse_openlibrary(d: dict, isbn: str) -> dict:
    title = d.get("title", "")
    if d.get("subtitle"):
        title = f"{title}: {d['subtitle']}"
    creators = [{"creator_type": "author", "field_mode": 0, **parse_name(a["name"])}
                for a in d.get("authors", []) if a.get("name")]
    fields = {
        "title": title, "date": d.get("publish_date", "") or "",
        "publisher": ", ".join(p["name"] for p in d.get("publishers", []) if p.get("name")),
        "place": ", ".join(p["name"] for p in d.get("publish_places", []) if p.get("name")),
        "numPages": str(d.get("number_of_pages") or ""), "ISBN": isbn, "url": d.get("url", ""),
    }
    return {"item_type": "book", "fields": {k: v for k, v in fields.items() if v}, "creators": creators,
            "tags": [s["name"] for s in d.get("subjects", [])[:8] if s.get("name")]}


def lookup_isbn(isbn: str) -> dict | None:
    r = _get("https://openlibrary.org/api/books",
             params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"})
    if r.status_code != 200:
        raise LookupFailed(f"Open Library answered with HTTP {r.status_code}.")
    entry = r.json().get(f"ISBN:{isbn}")
    return parse_openlibrary(entry, isbn) if entry else None


ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"


def parse_arxiv(xml_text: str, arxiv_id: str) -> dict | None:
    root = ET.fromstring(xml_text)
    entry = root.find(f"{ATOM}entry")
    if entry is None or entry.find(f"{ATOM}title") is None:
        return None
    title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
    if not title or title.lower() == "error":
        return None
    creators = [{"creator_type": "author", "field_mode": 0, **parse_name(a.findtext(f"{ATOM}name") or "")}
                for a in entry.findall(f"{ATOM}author")]
    fields = {
        "title": title, "date": (entry.findtext(f"{ATOM}published") or "")[:10],
        "abstractNote": " ".join((entry.findtext(f"{ATOM}summary") or "").split()),
        "publisher": "arXiv", "archiveID": f"arXiv:{arxiv_id}", "url": f"https://arxiv.org/abs/{arxiv_id}",
        "DOI": entry.findtext(f"{ARXIV_NS}doi") or "", "language": "en",
    }
    return {"item_type": "preprint", "fields": {k: v for k, v in fields.items() if v}, "creators": creators,
            "tags": [c.get("term", "") for c in entry.findall(f"{ATOM}category") if c.get("term")]}


def lookup_arxiv(arxiv_id: str) -> dict | None:
    r = _get("http://export.arxiv.org/api/query", params={"id_list": arxiv_id})
    if r.status_code != 200:
        raise LookupFailed(f"arXiv answered with HTTP {r.status_code}.")
    return parse_arxiv(r.text, arxiv_id)
