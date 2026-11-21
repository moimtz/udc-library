"""PDF helpers: page images, text for identifier detection, embedded metadata."""
import re
from pathlib import Path

import pymupdf

from textutil import parse_name


class PdfError(Exception):
    pass


def open_pdf(path: Path):
    try:
        doc = pymupdf.open(path)
    except Exception as e:
        raise PdfError(f"This file is not a readable PDF ({e}).")
    if doc.needs_pass:
        doc.close()
        raise PdfError("This PDF is password-protected. Remove the password and try again.")
    if doc.page_count == 0:
        doc.close()
        raise PdfError("This PDF has no pages.")
    return doc


def page_count(path: Path) -> int:
    doc = open_pdf(path)
    try:
        return doc.page_count
    finally:
        doc.close()


def render_page_jpeg(path: Path, page_number: int, width: int = 420) -> bytes:
    doc = open_pdf(path)
    try:
        index = min(max(page_number, 1), doc.page_count) - 1
        page = doc[index]
        zoom = max(0.2, min(width / max(page.rect.width, 1), 4.0))
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("jpeg", jpg_quality=82)
    finally:
        doc.close()


def save_cover(pdf: Path, dest: Path, page_number: int) -> None:
    dest.write_bytes(render_page_jpeg(pdf, page_number, 420))


def extract_text(path: Path, first: int = 6, last: int = 2) -> str:
    doc = open_pdf(path)
    try:
        n = doc.page_count
        idx = list(range(min(first, n))) + [i for i in range(max(n - last, first), n)]
        return "\n".join(doc[i].get_text("text") for i in idx)
    finally:
        doc.close()


_BAD_TITLES = re.compile(r"^(untitled|microsoft word|document\d*|\s*)$|\.(pdf|docx?|tex|indd)$", re.I)


def embedded_metadata(path: Path) -> dict:
    """Best-effort title/authors from the PDF's own info dictionary."""
    doc = open_pdf(path)
    try:
        md = doc.metadata or {}
    finally:
        doc.close()
    title = (md.get("title") or "").strip()
    if _BAD_TITLES.search(title) or title.lower().startswith("microsoft word -"):
        title = ""
    creators = []
    for raw in re.split(r";| and | y |\n", md.get("author") or ""):
        raw = raw.strip()
        if raw:
            creators.append({"role": "author", **parse_name(raw)})
    return {"title": title, "creators": creators}


# --------------------------------------------------------------------------- identifiers
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)
ISBN_RE = re.compile(r"(?i)\bISBN(?:-1[03])?[:\s]*([0-9Xx][0-9Xx\-\s]{8,16}[0-9Xx])")
ISBN_BARE_RE = re.compile(r"\b97[89][\-\s]?(?:\d[\-\s]?){9}\d\b")
ARXIV_RE = re.compile(r"(?i)arxiv:\s*(\d{4}\.\d{4,5})(?:v\d+)?")
ARXIV_OLD_RE = re.compile(r"(?i)arxiv:\s*([a-z\-]+(?:\.[A-Z]{2})?/\d{7})")


def isbn_valid(d: str) -> bool:
    if len(d) == 10:
        if not re.fullmatch(r"\d{9}[\dX]", d):
            return False
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(d))
        return total % 11 == 0
    if len(d) == 13 and d.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d[:12]))
        return (10 - total % 10) % 10 == int(d[12])
    return False


def isbn10_to_13(d: str) -> str:
    core = "978" + d[:9]
    total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core))
    return core + str((10 - total % 10) % 10)


def find_identifiers(text: str) -> dict:
    dois = []
    for m in DOI_RE.finditer(text):
        d = m.group(1).rstrip(".,;)]}'\"")
        if d.lower() not in [x.lower() for x in dois]:
            dois.append(d)
    isbns = []
    candidates = [m.group(1) for m in ISBN_RE.finditer(text)] + [m.group(0) for m in ISBN_BARE_RE.finditer(text)]
    for raw in candidates:
        d = re.sub(r"[^0-9Xx]", "", raw).upper()
        if isbn_valid(d):
            d = isbn10_to_13(d) if len(d) == 10 else d
            if d not in isbns:
                isbns.append(d)
    arxiv = []
    for m in list(ARXIV_RE.finditer(text)) + list(ARXIV_OLD_RE.finditer(text)):
        if m.group(1) not in arxiv:
            arxiv.append(m.group(1))
    return {"doi": dois[:5], "isbn": isbns[:5], "arxiv": arxiv[:3]}
