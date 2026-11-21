"""Lectura de PDF con PyMuPDF: texto de primeras/últimas páginas, líneas con tamaño de letra, TOC y OCR opcional.

Toda la lógica de heurísticas (metadata.py) trabaja sobre `PdfDoc`/`Line`, que son estructuras simples;
esta capa es la única que toca PyMuPDF."""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import config


@dataclass
class Line:
    text: str
    size: float
    page: int
    y: float
    bold: bool = False


@dataclass
class PdfDoc:
    path: str
    sha1: str = ""
    n_pages: int = 0
    meta: dict = field(default_factory=dict)
    toc: list = field(default_factory=list)            # [(nivel, título, página)]
    head_text: list = field(default_factory=list)      # texto de las primeras páginas (una cadena por página)
    tail_text: list = field(default_factory=list)      # texto de las últimas páginas
    lines: list = field(default_factory=list)          # líneas de las 2 primeras páginas, con tamaño
    scanned: bool = False
    ocr_used: bool = False
    warnings: list = field(default_factory=list)


def file_sha1(path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _lines_from_page(page, pno: int, textpage=None) -> list[Line]:
    """Líneas con tamaño de letra. `textpage` permite reutilizar esto con el resultado del OCR."""
    out = []
    for b in page.get_text("dict", textpage=textpage).get("blocks", []):
        if b.get("type") != 0:
            continue
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            size = max(s["size"] for s in spans)
            bold = any((s.get("flags", 0) & 16) or "bold" in s.get("font", "").lower() for s in spans)
            out.append(Line(text, float(size), pno, float(ln["bbox"][1]), bool(bold)))
    out.sort(key=lambda l: (l.page, l.y))
    return out


def _ocr_page(page) -> tuple[str, list[Line]]:
    """OCR con Tesseract a través de PyMuPDF. Devuelve texto y líneas (con tamaño estimado por PyMuPDF)."""
    tp = page.get_textpage_ocr(language=config.OCR_LANGS, dpi=config.OCR_DPI, full=True,
                               tessdata=config.TESSDATA_DIR)
    text = page.get_text("text", textpage=tp)
    return text, _lines_from_page(page, page.number, tp)


def read_pdf(path, ocr: bool = False) -> PdfDoc:
    import fitz  # PyMuPDF
    path = str(path)
    d = PdfDoc(path=path, sha1=file_sha1(path))
    doc = fitz.open(path)
    n = doc.page_count
    d.n_pages = n
    d.meta = {k: (v or "").strip() for k, v in (doc.metadata or {}).items()}
    try:
        d.toc = [tuple(t[:3]) for t in doc.get_toc()]
    except Exception:
        d.toc = []
    head_idx = list(range(min(config.HEAD_PAGES, n)))
    tail_idx = [i for i in range(max(config.HEAD_PAGES, n - config.TAIL_PAGES), n)]
    d.head_text = [doc[i].get_text("text") for i in head_idx]
    d.tail_text = [doc[i].get_text("text") for i in tail_idx]
    for i in range(min(2, n)):
        d.lines += _lines_from_page(doc[i], i)
    avg = sum(len(t.strip()) for t in d.head_text) / max(1, len(d.head_text))
    d.scanned = avg < config.MIN_CHARS_PER_PAGE
    if d.scanned:
        if not ocr:
            d.warnings.append("PDF sin texto seleccionable (escaneado). Usa --ocr para extraer.")
        else:
            try:
                d.lines, d.head_text, d.tail_text = [], [], []
                for i in head_idx[:config.OCR_MAX_PAGES]:
                    txt, lns = _ocr_page(doc[i])
                    d.head_text.append(txt)
                    if i < 2:
                        d.lines += lns
                for i in tail_idx[-config.TAIL_PAGES:]:
                    d.tail_text.append(_ocr_page(doc[i])[0])
                d.ocr_used = True
            except Exception as e:  # noqa: BLE001
                msg = str(e)
                if "tessdata" in msg.lower() or "tesseract" in msg.lower() or "language" in msg.lower():
                    d.warnings.append("OCR pedido pero no se encontró Tesseract o el idioma "
                                      f"'{config.OCR_LANGS}' (ver README / config.TESSDATA_DIR): {msg}")
                else:
                    d.warnings.append(f"OCR falló: {msg}")
    doc.close()
    return d
