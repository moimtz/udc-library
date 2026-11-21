"""Item serialisation, search/sort and duplicate detection (no web framework code here)."""
import difflib
import json
import re

from textutil import fold


class SearchError(ValueError):
    pass


def creators_text(creators: list[dict]) -> str:
    parts = []
    for c in creators:
        last, first = (c.get("last") or "").strip(), (c.get("first") or "").strip()
        parts.append(f"{last}, {first}" if last and first else (last or first))
    return "; ".join(p for p in parts if p)


def row_to_item(row) -> dict:
    creators = json.loads(row["creators"])
    return {
        "id": row["id"], "citekey": row["citekey"], "item_type": row["item_type"],
        "title": row["title"], "year": row["year"], "language": row["language"] or "",
        "udc": row["udc"] or "", "creators": creators, "creators_text": creators_text(creators),
        "data": json.loads(row["data"]), "filename": row["filename"], "sha256": row["sha256"],
        "size": row["size"], "pages": row["pages"], "cover_page": row["cover_page"],
        "added_at": row["added_at"], "modified_at": row["modified_at"], "deleted_at": row["deleted_at"],
    }


# --------------------------------------------------------------------------- search
def build_matcher(query: str, *, regex: bool = False, case: bool = False, whole: bool = False):
    """Return find(text) -> [[start, end], ...] (offsets refer to the original text)."""
    if not query:
        return None
    if regex:
        pattern = query
    else:
        pattern = re.escape(query if case else fold(query))
    if whole:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    try:
        rx = re.compile(pattern, 0 if case else re.IGNORECASE)
    except re.error as e:
        raise SearchError(f"Invalid regular expression: {e}")
    fold_text = (not case) and (not regex)

    def find(text: str) -> list[list[int]]:
        hay = fold(text) if fold_text else text
        spans: list[list[int]] = []
        for m in rx.finditer(hay):
            if m.end() > m.start():
                spans.append([m.start(), m.end()])
                if len(spans) >= 100:
                    break
        return spans

    return find


def searchable_fields(item: dict, type_labels: dict[str, str]) -> dict[str, str]:
    f = {
        "title": item["title"], "creators": item["creators_text"],
        "year": str(item["year"] or ""), "type": type_labels.get(item["item_type"], item["item_type"]),
        "language": item["language"], "udc": item["udc"], "citekey": item["citekey"],
    }
    for k, v in item["data"].items():
        f[k] = str(v)
    return f


def run_search(items: list[dict], matcher, field: str, type_labels: dict[str, str]) -> list[dict]:
    out = []
    for it in items:
        texts = searchable_fields(it, type_labels)
        if field != "all":
            texts = {field: texts.get(field, "")}
        hits = {}
        for k, t in texts.items():
            if t:
                spans = matcher(t)
                if spans:
                    hits[k] = spans
        if hits:
            it["matches"] = hits
            out.append(it)
    return out


def sort_items(items: list[dict], key: str, ascending: bool) -> None:
    def author(it):
        return fold(it["creators"][0].get("last", "")) if it["creators"] else "\uffff"

    keyfun = {
        "title": lambda it: fold(it["title"]),
        "author": author,
        "year": lambda it: (it["year"] is None, it["year"] or 0),
        "added": lambda it: it["added_at"],
    }.get(key, lambda it: fold(it["title"]))
    # Missing years always go last, whichever the direction.
    if key == "year":
        have = [i for i in items if i["year"] is not None]
        miss = [i for i in items if i["year"] is None]
        have.sort(key=lambda it: it["year"], reverse=not ascending)
        items[:] = have + miss
    else:
        items.sort(key=keyfun, reverse=not ascending)


# --------------------------------------------------------------------------- duplicates
def _digits(s: str) -> str:
    return re.sub(r"[^0-9Xx]", "", s or "").upper()


def find_duplicates(conn, *, sha256=None, doi=None, isbn=None, title=None, year=None,
                    first_author=None, exclude_id=None) -> list[dict]:
    found: list[dict] = []
    seen: set[int] = set()
    title_f = fold(title or "")
    doi_n = (doi or "").strip().lower()
    isbn_n = _digits(isbn or "")
    author_f = fold(first_author or "")

    def add(row, reason):
        if row["id"] in seen:
            return
        seen.add(row["id"])
        creators = json.loads(row["creators"])
        found.append({"reason": reason, "id": row["id"], "title": row["title"], "citekey": row["citekey"],
                      "year": row["year"], "creators_text": creators_text(creators),
                      "in_trash": row["deleted_at"] is not None})

    for row in conn.execute("SELECT * FROM items").fetchall():
        if exclude_id is not None and row["id"] == exclude_id:
            continue
        data = json.loads(row["data"])
        if sha256 and row["sha256"] == sha256:
            add(row, "Identical file")
        elif doi_n and (data.get("doi") or "").strip().lower() == doi_n:
            add(row, "Same DOI")
        elif isbn_n and len(isbn_n) >= 10 and _digits(data.get("isbn", "")) == isbn_n:
            add(row, "Same ISBN")
        elif title_f and len(title_f) > 8:
            other = fold(row["title"])
            if difflib.SequenceMatcher(None, title_f, other).ratio() >= 0.9:
                year_ok = year is None or row["year"] is None or year == row["year"]
                creators = json.loads(row["creators"])
                other_author = fold(creators[0].get("last", "")) if creators else ""
                author_ok = not author_f or not other_author or author_f == other_author
                if year_ok and author_ok:
                    add(row, "Very similar title, author and year")
    return found
