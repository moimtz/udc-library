"""Lectura de PDF con PyMuPDF: texto de primeras/últimas páginas, líneas con tamaño de letra, TOC y OCR opcional.

Toda la lógica de heurísticas (metadata.py) trabaja sobre `PdfDoc`/`Line`, que son estructuras simples;
esta capa es la única que toca PyMuPDF.

Páginas: se leen las primeras HEAD_PAGES y las últimas TAIL_PAGES páginas **con contenido**. Una página vacía
(guardas, portadas lisas, "intentionally left blank") se salta; una página escaneada se pasa por OCR (con --ocr)
y, si tampoco así da texto legible (ilustración, tapa decorada, manuscrito ilegible), se salta y se toma la
siguiente. Así 6 páginas vacías al principio ya no dejan el documento sin texto."""
from __future__ import annotations
import hashlib
import re
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
    ocr_langs: str = ""                                 # modelos de Tesseract usados y por qué
    pages_used: list = field(default_factory=list)      # índices (base 0) de las páginas leídas
    blank_skipped: int = 0                              # páginas saltadas por vacías o ilegibles
    staff: object = None                                # music.StaffInfo: pentagramas detectados (partituras)
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


# ------------------------------------------------------------------ calidad del texto y páginas vacías
_ALNUM = re.compile(r"\w", re.UNICODE)
_WORD = re.compile(r"^[^\W\d_]{2,}$", re.UNICODE)       # palabra: solo letras, 2 o más
_BLANK_NOTE = re.compile(r"(intentionally|deliberately)\s+(left\s+)?blank|p[áa]gina\s+(dejada\s+)?en\s+blanco|"
                         r"page\s+(laiss[ée]e\s+)?blanche|this\s+page\s+(is\s+)?blank", re.I)


def text_quality(text: str) -> float:
    """Fracción de caracteres (sin espacios) que forman palabras de letras. Texto real ~0.8; basura de OCR
    sobre una ilustración o una tapa decorada ~0.3."""
    toks = [t.strip(".,;:!?¡¿()[]«»\"'“”‘’-–—") for t in text.split()]
    total = sum(len(t) for t in text.split())
    if not total:
        return 0.0
    return sum(len(t) for t in toks if _WORD.match(t)) / total


def readable(text: str) -> bool:
    """¿Texto legible? Páginas largas: el detector de idioma debe estar seguro (texto real ~1.0; basura de OCR
    sobre música, grabados o manuscritos <= 0.65). Páginas cortas (portadas): calidad de caracteres."""
    if len(_ALNUM.findall(text)) < config.BLANK_MAX_CHARS:
        return False
    if len(re.findall(r"[^\W\d_]+", text)) >= config.LONG_PAGE_TOKENS:
        from .metadata import detect_language
        return detect_language(text)[1] >= config.MIN_LANG_CONF
    return text_quality(text) >= config.MIN_TEXT_QUALITY


def ink_fraction(page) -> float:
    """Fracción de píxeles claramente más oscuros que el fondo (render en gris a BLANK_DPI, sin márgenes)."""
    import numpy as np
    pix = page.get_pixmap(dpi=config.BLANK_DPI, colorspace="gray", alpha=False)
    if pix.width < 4 or pix.height < 4:
        return 0.0
    a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    mh, mw = max(1, a.shape[0] * 6 // 100), max(1, a.shape[1] * 6 // 100)   # bordes del escáner fuera
    a = a[mh:-mh, mw:-mw]
    bg = float(np.median(a))
    return float((a < bg - 60).mean())


def page_kind(page, text: str) -> str:
    """'text' (capa de texto legible), 'image' (hay tinta pero no texto legible: candidata a OCR) o 'blank'."""
    if _BLANK_NOTE.search(text) and len(_ALNUM.findall(text)) < 60:
        return "blank"
    if readable(text):
        return "text"                       # incluye portadas con poca letra ("TÍTULO / Autor")
    return "image" if ink_fraction(page) >= config.BLANK_INK else "blank"


# ------------------------------------------------------------------ OCR
# ISO 639-1 (detector de idioma) -> modelo de Tesseract
TESS_LANG = {
    "es": "spa", "en": "eng", "fr": "fra", "de": "deu", "it": "ita", "pt": "por", "la": "lat", "ca": "cat",
    "gl": "glg", "eu": "eus", "nl": "nld", "sv": "swe", "no": "nor", "nb": "nor", "da": "dan", "fi": "fin",
    "is": "isl", "pl": "pol", "cs": "ces", "sk": "slk", "sl": "slv", "hr": "hrv", "sr": "srp", "bs": "bos",
    "hu": "hun", "ro": "ron", "et": "est", "lv": "lav", "lt": "lit", "ga": "gle", "cy": "cym", "mt": "mlt",
    "sq": "sqi", "tr": "tur", "az": "aze", "id": "ind", "ms": "msa", "tl": "tgl", "vi": "vie", "sw": "swa",
    "af": "afr", "eo": "epo", "oc": "oci", "br": "bre", "lb": "ltz", "qu": "que", "ht": "hat",
    "el": "ell", "ru": "rus", "uk": "ukr", "be": "bel", "bg": "bul", "mk": "mkd", "kk": "kaz", "mn": "mon",
    "he": "heb", "yi": "yid", "ar": "ara", "fa": "fas", "ur": "urd", "ps": "pus", "hy": "hye", "ka": "kat",
    "hi": "hin", "mr": "mar", "ne": "nep", "bn": "ben", "pa": "pan", "gu": "guj", "ta": "tam", "te": "tel",
    "kn": "kan", "ml": "mal", "si": "sin", "th": "tha", "lo": "lao", "km": "khm", "my": "mya", "am": "amh",
    "zh": "chi_sim+chi_tra", "ja": "jpn", "ko": "kor",
    "nn": "nor", "grc": "grc", "hbo": "heb", "sa": "san", "ky": "kir", "tg": "tgk", "tt": "tat", "ug": "uig",
    "uz": "uzb", "jv": "jav", "fo": "fao", "fy": "fry", "gd": "gla", "yo": "yor", "dz": "dzo", "or": "ori",
    "as": "asm", "ku": "kmr", "yue": "chi_tra", "wuu": "chi_sim", "ceb": "ceb", "co": "cos", "iu": "iku",
    "bo": "bod", "syr": "syr", "dv": "div", "chr": "chr", "ti": "tir", "to": "ton", "sd": "snd", "su": "sun",
}


def _fallback() -> str:
    """Sin idioma fiable: el modelo de alfabeto latino (neutro entre lenguas) o OCR_FALLBACK."""
    return config.OCR_PROBE if _have(config.OCR_PROBE) else config.OCR_FALLBACK
# Script de OSD -> modelo (los demás: script/<Nombre>)
TESS_SCRIPT = {"Han": "script/HanS+script/HanT", "Japanese": "jpn", "Korean": "kor", "Hangul": "kor"}


def _have(model: str) -> bool:
    base = Path(config.TESSDATA_DIR) if config.TESSDATA_DIR else None
    if base is None:
        return model == "eng"                       # sin carpeta propia: solo se garantiza el inglés
    return all((base / f"{m}.traineddata").exists() for m in model.split("+"))


def _ocr_page(page, langs: str) -> tuple[str, list[Line]]:
    """OCR con Tesseract a través de PyMuPDF. Devuelve texto y líneas (con tamaño estimado por PyMuPDF)."""
    tp = page.get_textpage_ocr(language=langs, dpi=config.OCR_DPI, full=True, tessdata=config.TESSDATA_DIR)
    text = page.get_text("text", textpage=tp)
    return text, _lines_from_page(page, page.number, tp)


def _osd_script(page) -> tuple[str | None, float]:
    """(script, confianza) con OSD del ejecutable de Tesseract; (None, 0) si no se puede."""
    import subprocess
    import tempfile
    exe = config.TESSERACT_EXE
    if not exe or not Path(exe).exists():
        return None, 0.0
    with tempfile.TemporaryDirectory() as td:
        img = Path(td) / "p.png"
        page.get_pixmap(dpi=200, colorspace="gray").save(img)
        cmd = [exe, str(img), "-", "--psm", "0"]
        if config.TESSDATA_DIR:
            cmd += ["--tessdata-dir", config.TESSDATA_DIR]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
        except Exception:  # noqa: BLE001
            return None, 0.0
    m = re.search(r"Script:\s*(\w+)\s*Script confidence:\s*([\d.]+)", out)
    return (m.group(1), float(m.group(2))) if m else (None, 0.0)


def choose_ocr_langs(pages: list) -> tuple[str, str, int]:
    """Idiomas de OCR para un documento, a partir de sus primeras páginas escaneadas.
    Devuelve (modelos, motivo, páginas OCR gastadas en la prueba).
    1) OCR rápido con el modelo de script latino en hasta OCR_PROBE_PAGES páginas; si el texto es legible,
       se detecta el idioma -> modelo del idioma + inglés.
    2) Si no hay texto latino legible, OSD en esas páginas: un script no latino solo se acepta si al menos
       dos páginas coinciden con confianza >= OSD_MIN_CONF (con poco texto OSD inventa scripts)."""
    if config.OCR_LANGS != "auto":
        return config.OCR_LANGS, "fijo", 0
    if not _have(config.OCR_PROBE):
        return config.OCR_FALLBACK, "sin modelos de tessdata_fast", 0
    from .metadata import detect_language
    probe, used = "", 0
    for p in pages[:config.OCR_PROBE_PAGES]:
        t, _ = _ocr_page(p, config.OCR_PROBE)
        used += 1
        if readable(t):
            probe += "\n" + t
        if len(_ALNUM.findall(probe)) >= 400:
            break
    if readable(probe):
        lang, prob, _ = detect_language(probe)
        if lang and prob >= 0.8:
            model = TESS_LANG.get(lang)
            if model and _have(model):
                if model != "eng" and _have("eng"):
                    model += "+eng"             # portadillas y créditos suelen traer inglés
                return model, f"idioma detectado: {lang} ({prob:.0%})", used
            return config.OCR_PROBE, f"idioma {lang} sin modelo propio: script latino", used
        return config.OCR_PROBE, "idioma incierto: script latino", used
    votes: dict = {}
    for p in pages[:config.OCR_PROBE_PAGES]:
        s, conf = _osd_script(p)
        if s and s != "Latin" and conf >= config.OSD_MIN_CONF:
            votes[s] = votes.get(s, 0) + 1
    best = max(votes.items(), key=lambda kv: kv[1], default=(None, 0))
    if best[1] >= min(2, len(pages)):
        model = TESS_SCRIPT.get(best[0], f"script/{best[0]}")
        if _have(model):
            return model, f"script detectado por OSD: {best[0]}", used
    return _fallback(), "sin texto legible para detectar el idioma", used


# ------------------------------------------------------------------ lectura
ILLEGIBLE = object()        # página escaneada que tras el OCR no dio texto legible


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

    kinds: dict = {}

    def kind(i):
        if i not in kinds:
            t = doc[i].get_text("text")
            kinds[i] = (page_kind(doc[i], t), t)
        return kinds[i]

    head_range = list(range(min(n, config.SCAN_LIMIT)))
    tail_range = list(range(n - 1, max(-1, n - 1 - config.SCAN_LIMIT), -1))
    state = {"langs": None, "budget": config.OCR_MAX_ATTEMPTS, "error": None}

    def ocr_langs():
        if state["langs"] is None:
            cands = [doc[i] for i in head_range + tail_range if kind(i)[0] == "image"]
            langs, why, used = choose_ocr_langs(cands)
            state["langs"], state["budget"] = langs, state["budget"] - used
            d.ocr_langs = f"{langs} ({why})"
        return state["langs"]

    def content(i):
        """(texto, líneas OCR o None, era imagen) si la página aporta; None si se salta."""
        k, t = kind(i)
        if k == "blank":
            return None
        if k == "text":
            return t, None, False
        if not ocr or state["error"]:
            return ("", None, True)                 # escaneada sin OCR: cuenta, pero sin texto (era basura)
        if state["budget"] <= 0:
            return None
        try:
            langs = ocr_langs()
            state["budget"] -= 1
            txt, lns = _ocr_page(doc[i], langs)
        except Exception as e:  # noqa: BLE001
            state["error"] = str(e)
            return ("", None, True)
        d.ocr_used = True
        return (txt, lns, True) if readable(txt) else ILLEGIBLE   # ilustración / música / manuscrito

    def collect(pages, want, stop_before=-1):
        got, skipped, run = [], 0, 0
        for i in pages:
            if i <= stop_before:
                break
            c = content(i)
            if c is None or c is ILLEGIBLE:
                skipped += 1
                run = run + 1 if c is ILLEGIBLE else run
                if run >= config.OCR_GIVE_UP:       # partitura, álbum de grabados...: no hay más texto aquí
                    break
                continue
            run = 0
            got.append((i, c))
            if len(got) == want:
                break
        return got, skipped

    head, s1 = collect(head_range, config.HEAD_PAGES)
    tail, s2 = collect(tail_range, config.TAIL_PAGES, head[-1][0] if head else -1)
    tail.reverse()
    skipped = s1 + s2

    d.pages_used = [i for i, _ in head + tail]
    d.blank_skipped = skipped
    d.head_text = [c[0] for _, c in head]
    d.tail_text = [c[0] for _, c in tail]
    for i, c in head[:2]:
        d.lines += c[1] if c[1] is not None else ([] if c[2] else _lines_from_page(doc[i], i))
    if head:
        d.scanned = sum(c[2] for _, c in head) * 2 >= len(head)
    else:                                           # nada legible: ¿había escaneos (p. ej. manuscrito)?
        d.scanned = any(v[0] == "image" for v in kinds.values())
        if d.scanned and ocr:
            d.warnings.append("Ninguna página dio texto legible con OCR (¿manuscrito, partitura o grabados?).")
    if state["error"]:
        msg = state["error"]
        if "tessdata" in msg.lower() or "tesseract" in msg.lower() or "language" in msg.lower():
            d.warnings.append("OCR pedido pero no se encontró Tesseract o el idioma "
                              f"(ver README / config.TESSDATA_DIR): {msg}")
        else:
            d.warnings.append(f"OCR falló: {msg}")
    elif not ocr and any(c[2] for _, c in head + tail):
        d.warnings.append("PDF con páginas sin texto seleccionable (escaneadas). Usa --ocr para extraer.")
    if ocr and state["budget"] <= 0:
        d.warnings.append(f"OCR: se agotaron los {config.OCR_MAX_ATTEMPTS} intentos; quizá faltan páginas.")
    try:
        from . import music
        d.staff = music.detect(doc)                     # pentagramas: render rápido de unas pocas páginas
    except Exception as e:  # noqa: BLE001
        d.warnings.append(f"Detección de partitura falló: {e}")
    doc.close()
    return d
