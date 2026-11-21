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


CROSSREF_TYPES = {
    "journal-article": "article", "proceedings-article": "article", "posted-content": "article",
    "book": "book", "monograph": "book", "edited-book": "book", "reference-book": "book",
    "book-chapter": "chapter", "book-section": "chapter", "dissertation": "thesis", "report": "report",
}


def parse_crossref(msg: dict) -> dict:
    def first(v):
        return v[0] if isinstance(v, list) and v else ""

    title = first(msg.get("title"))
    sub = first(msg.get("subtitle"))
    if sub and sub.lower() not in title.lower():
        title = f"{title}: {sub}"
    creators = []
    for role, key in (("author", "author"), ("editor", "editor"), ("translator", "translator")):
        for a in msg.get(key, []) or []:
            if a.get("family") or a.get("given"):
                creators.append({"role": role, "first": a.get("given", ""), "last": a.get("family", "")})
            elif a.get("name"):
                creators.append({"role": role, "first": "", "last": a["name"]})
    year = None
    for k in ("issued", "published", "published-print", "published-online"):
        parts = (msg.get(k) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    data = {
        "container": first(msg.get("container-title")), "volume": msg.get("volume", ""),
        "issue": msg.get("issue", ""), "pages_range": msg.get("page", ""),
        "publisher": msg.get("publisher", ""), "doi": msg.get("DOI", ""), "url": msg.get("URL", ""),
        "issn": first(msg.get("ISSN")), "isbn": first(msg.get("ISBN")),
        "abstract": re.sub(r"<[^>]+>", "", msg.get("abstract", "")).strip(),
        "keywords": ", ".join(msg.get("subject", []) or []),
    }
    return {"item_type": CROSSREF_TYPES.get(msg.get("type", ""), "other"), "title": title, "year": year,
            "language": msg.get("language", "") or "", "creators": creators,
            "data": {k: v for k, v in data.items() if v}}


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
    creators = [{"role": "author", **parse_name(a["name"])} for a in d.get("authors", []) if a.get("name")]
    m = re.search(r"\d{4}", d.get("publish_date", "") or "")
    data = {
        "publisher": ", ".join(p["name"] for p in d.get("publishers", []) if p.get("name")),
        "place": ", ".join(p["name"] for p in d.get("publish_places", []) if p.get("name")),
        "isbn": isbn, "url": d.get("url", ""),
        "keywords": ", ".join(s["name"] for s in d.get("subjects", [])[:8] if s.get("name")),
    }
    return {"item_type": "book", "title": title, "year": int(m.group(0)) if m else None, "language": "",
            "creators": creators, "data": {k: v for k, v in data.items() if v}}


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
    creators = [{"role": "author", **parse_name(a.findtext(f"{ATOM}name") or "")}
                for a in entry.findall(f"{ATOM}author")]
    published = entry.findtext(f"{ATOM}published") or ""
    data = {
        "abstract": " ".join((entry.findtext(f"{ATOM}summary") or "").split()),
        "arxiv": arxiv_id, "url": f"https://arxiv.org/abs/{arxiv_id}",
        "doi": entry.findtext(f"{ARXIV_NS}doi") or "",
        "container": entry.findtext(f"{ARXIV_NS}journal_ref") or "",
        "keywords": ", ".join(c.get("term", "") for c in entry.findall(f"{ATOM}category") if c.get("term")),
    }
    return {"item_type": "article", "title": title, "year": int(published[:4]) if published[:4].isdigit() else None,
            "language": "en", "creators": creators, "data": {k: v for k, v in data.items() if v}}


def lookup_arxiv(arxiv_id: str) -> dict | None:
    r = _get("http://export.arxiv.org/api/query", params={"id_list": arxiv_id})
    if r.status_code != 200:
        raise LookupFailed(f"arXiv answered with HTTP {r.status_code}.")
    return parse_arxiv(r.text, arxiv_id)
