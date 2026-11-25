"""Extracción de metadatos SIN LLM: heurísticas de maquetación, regex y (opcional) NER zero-shot.

Cada campo se devuelve con procedencia: {"value": ..., "source": ..., "confidence": 0-1}.
Si un dato no está en el documento, el campo simplemente no existe (nunca se inventa)."""
from __future__ import annotations
import datetime
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import config
from . import locales
from .pdfio import Line, PdfDoc

# ------------------------------------------------------------------ utilidades
YEAR_MAX = datetime.date.today().year + 1


def squash(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# conectores entre día, mes y año ("12 de marzo de 1999", "12. März 1999", "1 di marzo 1999")
_DATE_LINK = r"(?:\s+(?:de|del|di|du|of|van|von)\s+|\.?\s+|\s*,\s*)"


def norm_date(s: str, lang: str | None = None) -> str | None:
    """Fecha -> 'AAAA-MM-DD' / 'AAAA-MM' / 'AAAA'. Meses en inglés y en el idioma del documento (CLDR)."""
    months = locales.month_names(lang)

    def mon(w):
        return months.get(locales.fold(w))

    s = squash(s)
    m = re.search(r"\b((?:1[5-9]|20)\d{2})-(\d{2})-(\d{2})\b", s)
    if m:
        return "-".join(m.groups())
    # con nombre de mes el año puede ser antiguo (1000-2099): "12 de octubre de 1492"
    m = re.search(rf"\b(\d{{1,2}})\.?{_DATE_LINK}([^\W\d_]+)\.?{_DATE_LINK}((?:1\d|20)\d{{2}})\b", s)
    if m and mon(m.group(2)):
        return f"{m.group(3)}-{mon(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b([^\W\d_]+)\.?\s+(\d{1,2}),?\s+((?:1\d|20)\d{2})\b", s)
    if m and mon(m.group(1)):
        return f"{m.group(3)}-{mon(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.search(rf"\b([^\W\d_]+)\.?{_DATE_LINK}((?:1\d|20)\d{{2}})\b", s)
    if m and mon(m.group(1)):
        return f"{m.group(2)}-{mon(m.group(1)):02d}"
    m = re.search(r"\b((?:1[5-9]|20)\d{2})\b", s)
    return m.group(1) if m else None


def similar(a: str, b: str) -> float:
    n = lambda x: re.sub(r"\W+", " ", (x or "").lower()).strip()
    return SequenceMatcher(None, n(a), n(b)).ratio()


# ------------------------------------------------------------------ idioma
_STOP = {
    "es": "de la que el en y los las del se por un para con una su al lo como más pero sus ya este también entre sobre es son fue".split(),
    "en": "the of and to in is that for it as was with be by on not this are or from at which but have an had they were their all can has been if more when will".split(),
    "fr": "le la les des du un une et en est que qui dans pour pas sur au avec ce il elle sont par plus ou mais nous vous".split(),
    "de": "der die das und ist von zu den mit sich des auf für nicht ein eine dem im als auch es an werden aus er hat".split(),
    "it": "il lo la i gli le di che e in un una per con non è sono del della dei si più come anche ma".split(),
    "pt": "o a os as de do da dos das que e em um uma para com não é são por mais como mas ao se foi".split(),
    "ca": "el la els les de del que i en un una per amb no és són més com però al es va".split(),
}
_langid = None


def _get_langid():
    """Crea (una sola vez) el identificador de py3langid: todos sus idiomas (~140), o los de
    config.LANGID_LANGS si se quiere restringir."""
    global _langid
    if _langid is None:
        from py3langid.langid import LanguageIdentifier, MODEL_FILE
        ident = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)  # probabilidades 0..1
        if config.LANGID_LANGS:
            langs = [c for c in config.LANGID_LANGS if c in set(ident.nb_classes)]
            if langs:
                ident.set_languages(langs)
        _langid = ident
    return _langid


def detect_language(text: str) -> tuple[str | None, float, str]:
    text = squash(text)[:8000]
    if len(text) < 40:
        return None, 0.0, "none"
    try:  # 1) py3langid
        lang, prob = _get_langid().classify(text)
        if lang == "zxx":                                   # "sin contenido lingüístico"
            return None, 0.0, "py3langid"
        if prob < config.LANG_MIN_CONF:                     # con ~140 idiomas, una conjetura floja es azar
            return None, round(float(prob), 4), "py3langid"
        return lang, round(float(prob), 4), "py3langid"
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass
    try:  # 2) langdetect
        from langdetect import detect_langs
        r = detect_langs(text)
        if r:
            return r[0].lang.split("-")[0], float(r[0].prob), "langdetect"
    except ImportError:
        pass
    except Exception:  # noqa: BLE001
        pass
    words = re.findall(r"[a-záéíóúñüàèìòùçâêîôûäöß]+", text.lower())  # 3) stopwords
    if not words:
        return None, 0.0, "none"
    scores = {lg: sum(1 for w in words if w in set(sw)) / len(words) for lg, sw in _STOP.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (l1, s1), (_, s2) = ranked[0], ranked[1]
    return (l1, round(min(1.0, 0.5 + (s1 - s2) * 3), 2), "stopwords") if s1 > 0.05 else (None, 0.0, "none")


# ------------------------------------------------------------------ identificadores
def isbn_ok(raw: str) -> bool:
    d = re.sub(r"[^0-9Xx]", "", raw)
    if len(d) == 10:
        return sum((10 - i) * (10 if c in "xX" else int(c)) for i, c in enumerate(d)) % 11 == 0
    if len(d) == 13 and d.isdigit():
        return sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(d)) % 10 == 0
    return False


def find_identifiers(text: str) -> dict:
    out = {}
    m = re.search(r"\b(10\.\d{4,9}/[^\s\"<>]+)", text)
    if m:
        out["doi"] = m.group(1).rstrip(".,;)]}")
    for m in re.finditer(r"ISBN(?:-1[03])?[:\s]*((?:97[89][\s-]?)?\d[\d\s-]{8,15}[\dXx])", text):
        if isbn_ok(m.group(1)):
            out["isbn"] = re.sub(r"[\s]", "", m.group(1))
            break
    m = re.search(r"arXiv:\s?(\d{4}\.\d{4,5})(?:v\d+)?", text) or \
        re.search(r"arXiv:\s?([a-z\-]+(?:\.[A-Z]{2})?/\d{7})", text)
    if m:
        out["arxiv"] = m.group(1)
    m = re.search(r"ISSN[:\s]*(\d{4}-\d{3}[\dXx])", text)
    if m:
        out["issn"] = m.group(1)
    return out


# ------------------------------------------------------------------ tipo de documento
def detect_doctype(text: str, ids: dict, n_pages: int) -> tuple[str, float, dict]:
    t = text.lower()
    scores = {}
    for typ, rules in config.DOCTYPE_RULES.items():
        hits = [bool(re.search(rx, t)) for rx, _ in rules]
        if typ in config.DOCTYPE_NEEDS_FIRST and not hits[0]:
            scores[typ] = 0            # p. ej. tesis: sin la palabra "tesis/thesis/…", universidad+maestría no basta
            continue
        scores[typ] = sum(w for (_, w), h in zip(rules, hits) if h)
    if ids.get("arxiv"):
        scores["preprint"] = scores.get("preprint", 0) + 4
    if ids.get("isbn"):
        scores["book"] = scores.get("book", 0) + 1
    if n_pages >= config.BOOK_MIN_PAGES:
        scores["book"] = scores.get("book", 0) + 2
    # en empate gana el tipo por defecto (libro): otro tipo necesita MÁS evidencia, no la misma
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0] != config.DEFAULT_DOCTYPE))
    best, bs = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0
    if bs < 2:
        return config.DEFAULT_DOCTYPE, 0.3, scores
    return best, round(min(1.0, bs / 6) * (bs / (bs + second + 1e-9)), 2), scores


# ------------------------------------------------------------------ títulos y autores
NOISE_LINE = re.compile(r"^(?:\W*\d+\W*|page\s*\d+.*|www\.|https?:|doi:|issn|isbn|\S+@\S+|.*©.*|.*all rights reserved.*)$", re.I)
ORG_RE = re.compile(rf"\b(?:{config.ORG_HINTS})\b", re.I)
# Mayúsculas y minúsculas de los alfabetos latino (con Latin-1 y Extended-A), griego y cirílico.
_UP = "A-ZÀ-ÖØ-ÞĀ-ŽΆ-ΫЀ-Я"
_LOW = "a-zß-öø-ÿā-žά-ώа-џ"
NAME_TOKEN = rf"(?:[{_UP}][{_LOW}'’]+(?:-[{_UP}]?[{_LOW}'’]+)*|[{_UP}]\.(?:-[{_UP}]\.)?)"   # Jean-Paul, J.-P.
PARTICLES = {"de", "del", "la", "las", "los", "van", "von", "der", "den", "ten", "ter", "zu", "da", "di",
             "della", "dello", "degli", "dos", "do", "das", "du", "des", "le", "el", "bin", "ibn", "ben", "al",
             "abu", "af", "av"}
PARTICLE = "(?:" + "|".join(sorted(PARTICLES, key=len, reverse=True)) + ")"
NAME_RE = re.compile(rf"^{NAME_TOKEN}(?:\s+(?:{PARTICLE}\s+)*{NAME_TOKEN}){{1,4}}$")


def _usable(l: Line) -> bool:
    t = l.text.strip()
    letters = sum(c.isalpha() for c in t)
    return len(t) >= 3 and letters / max(1, len(t)) >= 0.5 and not NOISE_LINE.match(t)


def pick_title(lines: list[Line]) -> tuple[str | None, float, list[Line], float]:
    """Título = primer bloque contiguo con la letra más grande (descartando encabezados institucionales)."""
    if not lines:
        return None, 0.0, [], 0.0
    by_page: dict[int, list[Line]] = {}
    for l in lines:
        if _usable(l):
            by_page.setdefault(l.page, []).append(l)
    page = next((p for p in sorted(by_page) if len(by_page[p]) >= 3), None)
    if page is None:
        return None, 0.0, [], 0.0
    ls = sorted(by_page[page], key=lambda l: l.y)
    sizes = sorted(ls, key=lambda l: l.size)
    med = sizes[len(sizes) // 2].size or 1.0
    for s in sorted({round(l.size * 2) / 2 for l in ls}, reverse=True)[:5]:
        run, runs = [], []
        for l in ls:
            if abs(l.size - s) <= 0.6 and (not run or l.y - run[-1].y <= 3.2 * s):
                run.append(l)
            else:
                if run:
                    runs.append(run)
                run = [l] if abs(l.size - s) <= 0.6 else []
        if run:
            runs.append(run)
        for r in runs:
            text = squash(" ".join(x.text for x in r)).replace("- ", "")
            if not (4 <= len(text) <= 300):
                continue
            if ORG_RE.search(text) and len(text.split()) <= 4:
                continue
            conf = 0.65 if s >= 1.2 * med else 0.35
            return text, conf, [x for x in ls if x.y > r[-1].y], s
    return None, 0.0, [], 0.0


def _title_case_if_upper(s: str) -> str:
    return s.title() if s.isupper() and len(s) > 4 else s


# "y" (es), "e" (it/pt), "et" (fr/la), "und" (de), "en" (nl), "och" (sv), "og" (da/no), "i" (pl/ca), "и" (ru)...
_AND = r"and|y|e|et|und|en|och|og|ja|és|ve|i|a|и|і|και|ו"
_BY = r"by|por|par|von|di|da|door|av|af|autor(?:es|en|e)?|auteurs?|authors?|автор[ыа]?"


def parse_names(text: str) -> list[str]:
    t = re.sub(rf"^\s*(?:{_BY})\s*[:\-]?\s*", "", text, flags=re.I)
    t = re.sub(r"\S+@\S+|[\d*†‡§¶]+", " ", t)
    t = squash(t)
    if not t or len(t) > 160 or ORG_RE.search(t):
        return []
    parts = [p.strip(" .") for p in re.split(rf"\s*(?:,|;|&|·|\||(?<!\w)(?:{_AND})(?!\w))\s*", t) if p.strip(" .")]
    if len(parts) >= 2 and len(parts) % 2 == 0 and all(len(p.split()) == 1 for p in parts):
        parts = [f"{parts[i + 1]} {parts[i]}" for i in range(0, len(parts), 2)]  # "Pérez, Juan"
    out = []
    for p in parts:
        p = _title_case_if_upper(p)
        if NAME_RE.match(p):
            out.append(p)
    return out if len(out) == len(parts) else []


def parse_meta_authors(raw: str) -> list[str]:
    """Campo 'author' del PDF: 'Zill, Dennis G.;' o 'Pérez, Juan; Gómez, Ana' -> ['Dennis G. Zill', ...]."""
    parts = [p.strip(" ,") for p in re.split(r";|\s+&\s+|\s(?:and|y|et|und|e|и)\s", raw or "") if p.strip(" ,")]
    if parts and all(p.count(",") == 1 for p in parts):  # formato "Apellido, Nombre"
        names = [" ".join(reversed([x.strip() for x in p.split(",")])) for p in parts]
        names = [_title_case_if_upper(n) for n in names]
        if all(NAME_RE.match(n) for n in names):
            return names
    return parse_names(raw)


def name_to_creator(name: str, role="author") -> dict:
    toks = name.split()
    i = len(toks) - 1
    while i > 1 and toks[i - 1].lower() in PARTICLES:
        i -= 1
    return {"creatorType": role, "firstName": " ".join(toks[:i]), "lastName": " ".join(toks[i:])}


def pick_creators(after: list[Line], title_size: float) -> list[str]:
    names, misses = [], 0
    for l in after[:14]:
        if l.size > title_size + 0.1 or len(l.text) > 150:
            continue
        got = parse_names(l.text)
        if got:
            names += [n for n in got if n not in names]
            misses = 0
        elif names:
            misses += 1
            if misses >= 1:
                break
    return names[:8]


_gliner = None


def ner_people(text: str) -> list[str]:
    """NER zero-shot (opcional, CPU). SIN PROBAR en el entorno de desarrollo: revisar en la Fase 2."""
    global _gliner
    from gliner import GLiNER
    if _gliner is None:
        _gliner = GLiNER.from_pretrained("urchade/gliner_multi-v2.1")
    ents = _gliner.predict_entities(text[:1500], ["person"], threshold=0.5)
    seen, out = set(), []
    for e in sorted(ents, key=lambda e: e["start"]):
        n = _title_case_if_upper(squash(e["text"]))
        if NAME_RE.match(n) and not ORG_RE.search(n) and n not in seen:
            seen.add(n)
            out.append(n)
    return out[:8]


# ------------------------------------------------------------------ otros campos
def pick_year(front: str, meta: dict) -> tuple[str | None, float, str]:
    pats = [
        (r"(?:©|\(c\)|copyright)\s*(?:by\s+)?[^\d\n]{0,40}((?:1[5-9]|20)\d{2})", 0.8, "regex:copyright"),
        (rf"(?:{_PUBLISHED_WORDS})[^\n\d]{{0,25}}"
         r"(?:\d{1,2}\.?\s+(?:de\s+|di\s+)?\w+\.?\s+(?:de\s+)?)?((?:1[5-9]|20)\d{2})", 0.6, "regex:fecha"),
        (rf"(?:{_EDITION_WORDS})[^\n\d]{{0,20}}((?:1[5-9]|20)\d{{2}})", 0.6, "regex:edicion"),
    ]
    for rx, c, src in pats:
        m = re.search(rx, front, re.I)
        if m and int(m.group(1)) <= YEAR_MAX:
            return m.group(1), c, src
    years = [y for y in re.findall(r"\b((?:1[5-9]|20)\d{2})\b", front) if int(y) <= YEAR_MAX]
    if years:
        y, n = Counter(years).most_common(1)[0]
        return y, 0.35 if n > 1 else 0.25, "regex:año_más_frecuente"
    m = re.search(r"D:((?:19|20)\d{2})", meta.get("creationDate", ""))
    return (m.group(1), 0.15, "pdfmeta:creationDate") if m else (None, 0.0, "")


# Vocabulario de secciones en los idiomas más comunes (el resto se clasifica igual por embeddings).
_ABSTRACT_WORDS = (r"abstract|summary|resumen|r[ée]sum[ée]|resumo|riassunto|sommario|zusammenfassung|kurzfassung|"
                   r"samenvatting|sammanfattning|sammendrag|resum[ée]|tiivistelm[äa]|streszczenie|abstrakt|"
                   r"[öo]zet|περίληψη|аннотация|реферат|резюме|ملخص|תקציר|摘要|要旨|要約|초록|요약")
_KEYWORDS_WORDS = (r"keywords?|key words|palabras clave|mots[- ]cl[ée]s|schl[üu]sselw[öo]rter|schlagw[öo]rter|"
                   r"parole chiave|palavras[- ]chave|trefwoorden|nyckelord|asiasanat|s[łl]owa kluczowe|"
                   r"anahtar kelimeler|λέξεις[- ]κλειδιά|ключевые слова|الكلمات المفتاحية|מילות מפתח|"
                   r"关键词|關鍵詞|キーワード|주제어|핵심어")
_INTRO_WORDS = (r"introduction|introducci[oó]n|introduzione|einleitung|einf[üu]hrung|introdu[cç][aã]o|inleiding|"
                r"wst[ęe]p|введение|giriş|εισαγωγή|مقدمة|מבוא|引言|绪论|はじめに|序論|서론")
_PUBLISHED_WORDS = (r"published|first published|publicado|publicaci[oó]n|fecha|date|received|accepted|publi[ée]|"
                    r"parution|ver[öo]ffentlicht|erschienen|pubblicato|pubblicazione|publica[cç][aã]o|"
                    r"uitgegeven|utgiven|wydano|опубликовано|издано")
_EDITION_WORDS = (r"edition|edici[oó]n|[ée]dition|edizione|edi[cç][aã]o|auflage|aufl\.|uitgave|druk|upplaga|"
                  r"udgave|painos|wydanie|издание|baskı|版")


def pick_abstract(text: str) -> str | None:
    m = re.search(rf"(?is)(?<!\w)(?:{_ABSTRACT_WORDS})(?!\w)[\s:.\-—]*(.{{200,2500}}?)"
                  rf"(?=(?<!\w)(?:{_KEYWORDS_WORDS}|{_INTRO_WORDS}|1\.\s)|\Z)", text)
    return squash(m.group(1)) if m else None


def pick_keywords(text: str) -> list[str]:
    m = re.search(rf"(?is)(?<!\w)(?:{_KEYWORDS_WORDS})\s*[:\-—：]\s*(.{{5,300}}?)(?:\n\s*\n|\n[^\W_a-z]|\Z)", text)
    if not m:
        return []
    return [k.strip(" .") for k in re.split(r"[,;·、，；]", squash(m.group(1))) if 1 < len(k.strip()) < 60][:12]


PUBLISHER_RE = re.compile(r"(?:editorial|ediciones|[ée]ditions?|[ée]diteur|verlag|edizioni|editrice|editore|"
                          r"editora|uitgeverij|f[öo]rlag|forlag|wydawnictwo|kustannus|yay[ıi]nlar[ıi]|издательство|"
                          r"publishers?|publishing|\bpress\b|springer|elsevier|wiley|pearson|mcgraw|routledge|"
                          r"taylor & francis|\bsage\b|gallimard|hachette|suhrkamp|einaudi|mondadori|alianza|"
                          r"fondo de cultura|siglo xxi|ieee|\bacm\b)|出版社|出版", re.I)
_RIGHTS_RE = re.compile(r"\b(?:all rights|derechos|droits|rechte|diritti|direitos|права|isbn)\b", re.I)


def pick_publisher(text: str) -> str | None:
    for ln in text.splitlines():
        ln = squash(ln)
        if 3 < len(ln) <= 90 and PUBLISHER_RE.search(ln) and not _RIGHTS_RE.search(ln):
            ln = re.sub(r"^(?:©|\(c\)|copyright)?\s*(?:19|20)?\d{0,4}\s*", "", ln, flags=re.I)
            return re.sub(r"^(?:published by|publicado por|publi[ée] par|ver[öo]ffentlicht (?:von|bei)|"
                          r"pubblicato da|editorial:|verlag:)\s*", "", ln, flags=re.I) or None
    return None


def pick_org(lines: list[str]) -> str | None:
    for ln in lines:
        ln = squash(ln)
        if 5 < len(ln) <= 100 and re.search(r"\b(?:universidad|university|universit[ée]|instituto|institute|tecnol[oó]gico)\b", ln, re.I):
            return ln
    return None


# ------------------------------------------------------------------ patentes (códigos INID)
def parse_patent(text: str) -> dict:
    def inid(code, stop=r"\(\d{2}\)"):
        m = re.search(rf"\({code}\)\s*(.+?)(?=\n\s*{stop}|\Z)", text, re.S)
        return squash(m.group(1)) if m else None

    out = {}
    num = inid("11")
    if num:
        num = re.sub(r"^(?:Patent No\.?|Publication Number|Pub\. No\.?)[:\s]*", "", num, flags=re.I)
        out["patentNumber"] = num.split(" (")[0][:40]
    else:
        m = re.search(r"\b((?:US|EP|WO|JP|CN|KR|DE|GB|FR|ES|MX|CA|BR)\s?\d[\d,/.\s]{5,14}\s?[AB]\d?)\b", text)
        if m:
            out["patentNumber"] = squash(m.group(1))
    pn = out.get("patentNumber", "")
    if re.match(r"^[A-Z]{2}", pn):
        out["country"] = pn[:2]
    if inid("54"):
        out["title"] = inid("54").title() if inid("54").isupper() else inid("54")
    for code, field_ in (("72", "inventors"), ("75", "inventors"), ("71", "applicants"), ("73", "assignee")):
        v = inid(code)
        if v:
            v = re.sub(r"^(?:Inventors?|Applicants?|Assignee)[^:]*:\s*", "", v, flags=re.I)
            out.setdefault(field_, v)
    for code, f in (("21", "applicationNumber"), ("22", "filingDate"), ("45", "issueDate"), ("43", "issueDate")):
        v = inid(code)
        if v and f not in out:
            v = re.sub(r"^(?:Appl\. No\.|Filed|Date of Patent|Pub\. Date)[:\s]*", "", v, flags=re.I)
            out[f] = norm_date(v) if "Date" in f or f == "filingDate" else v.split(" ")[0]
    m = re.search(r"\(57\)\s*ABSTRACT\s*(.+?)(?:\n\s*\d+\s+Claims|\Z)", text, re.S | re.I)
    if m:
        out["abstractNote"] = squash(m.group(1))[:2000]
    return out


def split_people(raw: str) -> list[str]:
    raw = re.sub(r"\([^)]*\)", " ", raw)
    return [squash(p).strip(" ,.") for p in re.split(r"[;\n]|\band\b", raw) if len(squash(p)) > 3][:10]


# ------------------------------------------------------------------ edición/año pegados al título
# sufijos ordinales: en (6th), es (6a, 6ª), fr (6e, 6ème), it/pt (6ª, 6º), de/nl/pl/ru (6.), ru (6-е)
_ORD = r"(?:st|nd|rd|th|ra|da|ta|va|na|a|ª|º|°|e|ème|eme|er|re|-?е|-?я)?"
_EDITION_RE = re.compile(rf"(?i)\b(\d{{1,2}})\s*{_ORD}\.?\s*(?:{_EDITION_WORDS}|ed\.)")
_ED_PAREN = re.compile(rf"(?i)^(\d{{1,2}})\s*{_ORD}\.?(?:\s*(?:{_EDITION_WORDS}|ed\.?))?$")
_YEAR = r"(?:1[5-9]|20)\d{2}"


def split_title_extras(s: str) -> tuple[str, str | None, str | None]:
    """'Título, 6th edition (2017)' -> ('Título', '6', '2017'). Quita paréntesis finales de año/edición."""
    s, edition, year = squash(s), None, None
    while True:
        m = re.search(r"\s*[(\[]([^()\[\]]{1,40})[)\]]\s*$", s)
        if not m:
            break
        inner = m.group(1).strip()
        ye, ed = re.search(rf"\b({_YEAR})\b", inner), _ED_PAREN.match(inner) or _EDITION_RE.search(inner)
        if not (ye or ed):
            break
        year = year or (ye.group(1) if ye else None)
        edition = edition or (ed.group(1) if ed else None)
        s = s[:m.start()]
    m = _EDITION_RE.search(s)
    if m:
        edition = edition or m.group(1)
        s = s[:m.start()] + s[m.end():]
    return re.sub(r"[\s,;:\-–]+$", "", squash(s)), edition, year


# ------------------------------------------------------------------ nombre del archivo
# El nombre del archivo es una pista, no una verdad: suele venir desordenado o con basura de la
# descarga. Solo gana a otras fuentes cuando el propio texto del PDF lo confirma.
_FN_JUNK = re.compile(r"(?i)\b(?:imslp\d+|pmlp\d+|z-?library|z-?lib(?:\.org)?|libgen(?:\.\w+)?|b-ok(?:\.\w+)?|"
                      r"ebook|pdfdrive|annas?-archive|www\.\S+|\S+\.(?:com|org|net|info)|[0-9a-f]{16,})\b")
_FN_TOK = rf"[{_UP}][\w'’\-]*\.?"


def _fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")
    return " " + squash(re.sub(r"[^a-z0-9]+", " ", s.lower())) + " "


def _fn_authors(s: str) -> list[str]:
    """'Hayt Jr., Kemmerly, Durbin' -> ['Hayt Jr', 'Kemmerly', 'Durbin']; [] si no parecen nombres."""
    parts = [p.strip(" .") for p in re.split(r"\s*(?:,|;|&|\band\b|\by\b|\bet\b)\s*", s) if p.strip(" .")]
    rx = re.compile(rf"^(?:{_FN_TOK}|{PARTICLE})(?:\s+(?:{_FN_TOK}|{PARTICLE})){{0,4}}$")
    if not parts or len(parts) > 8:
        return []
    ok = all(rx.match(p) and not ORG_RE.search(p) and len(p.split()) <= 4 for p in parts)
    return parts if ok else []


def parse_filename(path: str) -> dict:
    """Pistas del nombre del archivo: título, autores, edición, año e ISBN. {} si el nombre no sirve
    (hash, 'documento(3)', números...)."""
    stem = Path(path).stem
    out = {}
    m = re.search(r"(97[89][\d\-]{10,14}|\b\d{9}[\dXx]\b)", stem)
    if m and isbn_ok(m.group(1)):
        out["isbn"] = m.group(1)
    s = _FN_JUNK.sub(" ", stem.replace("_", " "))
    s = squash(re.sub(r"(?:\s*-\s*){2,}", " - ", s)).strip(" -–")
    words = re.findall(r"[^\W\d_]{3,}", s)
    letters = sum(c.isalpha() for c in s)
    if len(words) < 2 or letters / max(1, len(s.replace(" ", ""))) < 0.6:
        return out
    base, edition, year = split_title_extras(s)
    segs = [x.strip() for x in re.split(r"\s+[-–—]\s+", base) if x.strip()]
    title, authors = base, []
    is_standard = re.search(r"\b(?:ansi|asme|iso|din|astm|ieee|nfpa|une|nom)\b", base, re.I)
    if len(segs) >= 2 and not is_standard:
        a_last, a_first = _fn_authors(segs[-1]), _fn_authors(segs[0])
        avg = lambda a: sum(len(x.split()) for x in a) / len(a)  # palabras por nombre: los títulos tienen más
        if a_last and (not a_first or avg(a_last) <= avg(a_first)):   # empate: "Título - Autor" es lo usual
            title, authors = " - ".join(segs[:-1]), a_last
        elif a_first:
            title, authors = " - ".join(segs[1:]), a_first
    title, ed2, yr2 = split_title_extras(title)
    out.update({"title": title, "authors": authors, "edition": edition or ed2, "year": year or yr2,
                "structured": bool(authors)})
    return out


def _covered(phrase: str, folded: str) -> bool:
    """¿Aparece la frase en el texto? Exacta, o >=80 % de sus palabras (el nombre puede abreviar el título)."""
    p = _fold(phrase)
    if len(p.strip()) >= 4 and p in folded:
        return True
    toks = [t for t in p.split() if len(t) >= 3]
    return len(toks) >= 3 and sum(f" {t} " in folded for t in toks) / len(toks) >= 0.8


def _surname(a: str) -> str:
    toks = a.split()
    return toks[0] if len(toks) > 1 and toks[-1].lower().startswith(("jr", "sr")) else toks[-1]


def _filename_fields(pdf: PdfDoc, f: "FieldSet", front: str, text: str) -> None:
    """Pistas del nombre del archivo. Si coinciden con lo extraído del PDF, lo CONFIRMAN (sube su
    confianza y se conserva el dato más completo); si no, entran como candidato propio, con más
    confianza cuando el texto del PDF las respalda."""
    fn = parse_filename(pdf.path)
    if not fn:
        return
    f_front, f_all = _fold(front), _fold(text)
    if fn.get("title"):
        fold_t = _fold(fn["title"])
        same = lambda v: similar(v, fn["title"]) >= 0.7 or fold_t in _fold(v)  # el nombre puede abreviar
        if not f.confirm("title", same, 0.25):
            conf = (0.45 if fn["structured"] else 0.3) + (0.25 if _covered(fn["title"], f_front) else 0.0)
            f.put("title", fn["title"], "filename", conf)
    if fn.get("authors"):
        surnames = [_fold(_surname(a)).strip() for a in fn["authors"]]
        has_all = lambda v: all(s_ in {_fold(c.get("lastName", "")).strip() for c in v} for s_ in surnames)
        if not f.confirm("creators", has_all, 0.25):  # p. ej. pdfmeta "Daryl L. Logan" confirmado por "Logan"
            conf = 0.45 + (0.2 if all(f" {s_} " in f_all for s_ in surnames) else 0.0)
            f.put("creators", [name_to_creator(a) for a in fn["authors"]], "filename", conf)
    if fn.get("year"):
        if not f.confirm("date", lambda v: v == fn["year"], 0.2):
            f.put("date", fn["year"], "filename", 0.45 + (0.2 if f" {fn['year']} " in f_all else 0.0))
    if fn.get("edition"):
        f.put("edition", fn["edition"], "filename", 0.5)
    if fn.get("isbn"):
        f.put("ISBN", fn["isbn"], "filename", 0.6)


# ------------------------------------------------------------------ construcción del registro
class FieldSet(dict):
    """Campo -> mejor candidato. Guarda también los candidatos perdedores (alts) para poder
    confirmarlos después con otra fuente (p. ej. el nombre del archivo)."""

    def __init__(self):
        super().__init__()
        self.alts: dict[str, list[dict]] = {}

    def put(self, name, value, source, conf):
        if value in (None, "", [], {}):
            return
        cand = {"value": value, "source": source, "confidence": round(float(conf), 2)}
        self.alts.setdefault(name, []).append(cand)
        if name not in self or conf > self[name]["confidence"]:
            self[name] = cand

    def confirm(self, name, matches, delta, by="filename") -> bool:
        """Sube la confianza de los candidatos que cumplen `matches(valor)` y reelige el mejor."""
        hit = False
        for c in self.alts.get(name, []):
            if matches(c["value"]):
                c["confidence"] = round(min(0.95, c["confidence"] + delta), 2)
                c["source"] += f"+{by}"
                hit = True
        if hit:
            self[name] = max(self.alts[name], key=lambda c: c["confidence"])
        return hit


def build_record(pdf: PdfDoc, use_ner: bool = False) -> dict:
    head_all = "\n".join(pdf.head_text)
    tail_all = "\n".join(pdf.tail_text)
    front = "\n".join(pdf.head_text[:2])
    both = head_all + "\n" + tail_all
    ids = find_identifiers(both)
    lang, lang_conf, lang_src = detect_language(head_all or tail_all)
    # el nombre del archivo también da pistas del tipo ("ASME Y14.5", "Handbook", "Tesis")
    dtype, dt_conf, dt_scores = detect_doctype(front + "\n" + Path(pdf.path).stem.replace("_", " "), ids, pdf.n_pages)
    # Partitura: manda la detección visual de pentagramas (ver music.py); las palabras ("Allegro", "piano")
    # aparecen también en libros sobre música, así que solas ya no bastan.
    score_why = ""
    if pdf.staff is not None:
        from . import music
        is_score, score_why = music.decide(pdf.staff, pdf.meta.get("title", ""), Path(pdf.path).stem,
                                           pdf.meta.get("producer", ""))
        if is_score:
            dtype, dt_conf = "score", 0.9
        elif dtype == "score":
            rest = {k: v for k, v in dt_scores.items() if k != "score"}
            best = max(rest, key=lambda k: (rest[k], k == config.DEFAULT_DOCTYPE)) if rest else None
            dtype = best if best and rest[best] >= 2 else config.DEFAULT_DOCTYPE
    is_score = dtype == "score"
    item_type = config.SCORE_ITEM_TYPE if is_score else dtype
    if item_type not in config.ZOTERO_ITEM_TYPES:
        item_type = config.DEFAULT_DOCTYPE

    f = FieldSet()
    # --- título y autores
    title, t_conf, after, t_size = pick_title(pdf.lines)
    mt = squash(pdf.meta.get("title", ""))
    meta_ok = len(mt) >= 8 and not re.search(r"\.(?:pdf|docx?|indd|tex)$|^microsoft|untitled|^\d+$", mt, re.I)
    if title and meta_ok and similar(title, mt) >= 0.7:
        t_conf = min(0.9, t_conf + 0.2)
    # cada candidato se limpia de "6th edition (2017)"; la edición y el año pasan a sus campos
    for cand, src, conf in ((title, "layout", t_conf), (mt if meta_ok else None, "pdfmeta", 0.5)):
        if cand:
            clean, ed, yr = split_title_extras(cand)
            f.put("title", clean or cand, src, conf)
            f.put("edition", ed, src + ":title", 0.5)
            f.put("date", yr, src + ":title", 0.5)
    if not title and not meta_ok:
        first = next((squash(l) for l in front.splitlines() if len(squash(l)) > 8 and not NOISE_LINE.match(squash(l))), None)
        f.put("title", first, "first_line", 0.2)
    people, psrc, pconf = pick_creators(after, t_size), "layout", 0.5
    if use_ner:
        try:
            ner = ner_people(front)
            if ner:
                people, psrc, pconf = ner, "ner", 0.7
        except ImportError:
            pdf.warnings.append("--ner pedido pero falta 'gliner'.")
        except Exception as e:  # noqa: BLE001
            pdf.warnings.append(f"NER falló: {e}")
    role = config.PRIMARY_CREATOR.get(item_type, "author")   # inventor, artist, cartographer, presenter...
    f.put("creators", [name_to_creator(n, role) for n in people], psrc, pconf)
    if pdf.meta.get("author"):  # siempre como candidato: el nombre del archivo puede confirmarlo
        f.put("creators", [name_to_creator(n, role) for n in parse_meta_authors(pdf.meta["author"])], "pdfmeta", 0.4)

    # --- fecha, editorial, resumen, palabras clave, idioma, identificadores
    y, yc, ys = pick_year(front + "\n" + tail_all[:3000], pdf.meta)
    f.put("date", y, ys, yc)
    f.put("publisher", pick_publisher(front + "\n" + tail_all[:3000]), "regex", 0.5)
    f.put("abstractNote", pick_abstract(head_all), "regex", 0.6)
    kws = pick_keywords(head_all)
    f.put("tags", kws, "regex", 0.6)
    f.put("language", lang, lang_src, lang_conf)
    f.put("numPages", pdf.n_pages, "pdf", 1.0)  # dato exacto del archivo
    # al final: así el nombre del archivo puede confirmar lo ya extraído en vez de pisarlo
    _filename_fields(pdf, f, "\n".join(pdf.head_text[:3]), head_all + "\n" + tail_all)
    for k, name in (("doi", "DOI"), ("isbn", "ISBN"), ("issn", "ISSN")):
        f.put(name, ids.get(k), "regex", 0.9)
    if ids.get("arxiv"):
        f.put("archiveID", "arXiv:" + ids["arxiv"], "regex", 0.9)
        f.put("repository", "arXiv", "regex", 0.9)

    # --- específicos por tipo
    lines_front = front.splitlines()
    if dtype == "patent":
        p = parse_patent(front)
        for k, v in p.items():
            if k in ("inventors", "applicants"):
                if k == "inventors":
                    f.put("creators", [name_to_creator(_title_case_if_upper(n), "inventor") for n in split_people(v)], "inid", 0.8)
                continue
            f.put(k, v, "inid", 0.8)
        if p.get("applicants") and "assignee" not in f:
            f.put("assignee", split_people(p["applicants"])[0], "inid", 0.7)
        if "issueDate" in f:
            f.put("date", f["issueDate"]["value"], "inid", 0.8)
    elif dtype == "thesis":
        f.put("university", pick_org(lines_front), "regex", 0.5)
        m = re.search(r"(tesis doctoral|doctoral thesis|ph\.?\s?d\.? thesis|tesis de maestr[ií]a|master'?s thesis|"
                      r"tesis de licenciatura|bachelor'?s thesis|tesina|trabajo fin de (?:grado|m[aá]ster))", front, re.I)
        f.put("thesisType", m.group(1).capitalize() if m else None, "regex", 0.6)
    elif dtype == "report":
        f.put("institution", pick_org(lines_front), "regex", 0.4)
        m = re.search(r"(?:report|informe|reporte)\s*(?:no\.?|n[oº°.]|number|#)\s*[:\-]?\s*([A-Z0-9][\w./\-]+)", front, re.I)
        f.put("reportNumber", m.group(1) if m else None, "regex", 0.6)
    elif dtype in ("journalArticle", "conferencePaper"):
        m = re.search(r"(?:vol\.?|volume|volumen)\s*(\d+)", front, re.I)
        f.put("volume", m.group(1) if m else None, "regex", 0.5)
        m = re.search(r"(?:\bno\.?|n[oº°.]|issue|n[úu]mero)\s*(\d+)", front, re.I)
        f.put("issue", m.group(1) if m else None, "regex", 0.4)
        m = re.search(r"\bpp?\.?\s*(\d+)\s*[-–]\s*(\d+)", front)
        f.put("pages", f"{m.group(1)}-{m.group(2)}" if m else None, "regex", 0.4)
        jl = next((squash(l) for l in lines_front[:15] if re.search(r"\b(?:journal|revista)\b", l, re.I) and len(squash(l)) < 90), None)
        f.put("publicationTitle", jl, "regex", 0.3)
    if is_score:
        extra = [config.SCORE_EXTRA]
        m = re.search(r"\bop(?:us|\.)\s?(\d+[a-z]?)", front, re.I)
        if m:
            extra.append(f"Opus: {m.group(1)}")
        ins = sorted({w.lower() for w in re.findall(r"\b(piano|violin|violín|cello|guitar|guitarra|flute|flauta|orchestra|orquesta|voice|voz|choir|coro)\b", front, re.I)})
        if ins:
            extra.append("Instrumentation: " + ", ".join(ins))
        f.put("extra", "\n".join(extra), "regex", 0.4)   # Extra de Zotero: una línea "Nombre: valor" por dato
        m = re.search(r"(?:composer|compositor|m[uú]sica de|music by|compuesta por)\s*[:\-]?\s*([^\n]{3,60})", front, re.I)
        if m and parse_names(m.group(1)):
            f.put("creators", [name_to_creator(n) for n in parse_names(m.group(1))], "regex:composer", 0.6)

    # --- filtrar por esquema del tipo detectado
    allowed = set(config.ZOTERO_ITEM_TYPES[item_type]) | {"tags", "extra"}
    fields = {k: v for k, v in f.items() if k in allowed}
    unmapped = {k: v for k, v in f.items() if k not in allowed}
    missing = [k for k in config.CRITICAL_FIELDS if k not in fields]
    return {
        "item_type": {"value": item_type, "source": "rules", "confidence": dt_conf, "scores": dt_scores,
                      "subtype": "score" if is_score else None},
        "fields": fields, "unmapped": unmapped, "identifiers": ids,
        "missing_critical": missing, "doc_language": lang,
        "score": ({"why": score_why, "per_system": pdf.staff.per_system,
                   "score_pages": f"{pdf.staff.score_pages}/{pdf.staff.pages_checked}"} if is_score and pdf.staff
                  else ({"why": "palabras clave"} if is_score else None)),
    }


# ------------------------------------------------------------------ vistas para clasificación
def _clean(s: str, n: int) -> str:
    lines = [squash(l) for l in s.splitlines()]
    lines = [l for l in lines if len(l) > 3 and not NOISE_LINE.match(l) and sum(c.isalpha() for c in l) / len(l) > 0.5]
    return " ".join(lines)[:n]


def build_views(pdf: PdfDoc, rec: dict) -> dict:
    f = rec["fields"]
    title = f.get("title", {}).get("value", "")
    abstract = f.get("abstractNote", {}).get("value", "")
    tags = ", ".join(f.get("tags", {}).get("value", []))
    toc = "; ".join(t[1] for t in pdf.toc)[:3000]
    front = " ".join(x for x in (title, abstract, tags) if x)
    if len(front) < config.FRONT_MIN_CHARS:     # sin título/resumen fiable (p. ej. portada escaneada): el texto
        front = (front + " " + _clean("\n".join(pdf.head_text[:2]), 2000)).strip()   # de las primeras páginas
    body = _clean("\n".join(pdf.head_text[2:]), 3000)
    tail = _clean("\n".join(pdf.tail_text[-2:]), 1500)
    return {"front": front, "toc": toc, "body": body, "tail": tail}
