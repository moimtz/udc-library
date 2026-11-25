"""Enriquecimiento por identificador (ISBN, DOI, arXiv) ANTES de usar heurísticas o IA.

Qué trae cada fuente (comprobado el 2026-11-24):
- Open Library (ISBN): título, editorial, lugar, fecha, páginas y, sobre todo, TEMAS y clasificación LC/Dewey.
  No trae UDC.
- Biblioteca Nacional de Polonia (ISBN): UDC (campo MARC 080) cuando el libro está en su catálogo (sobre todo
  ediciones polacas). Los catálogos nacionales europeos son la fuente real de UDC; se pueden añadir otros aquí.
- Crossref (DOI): título, autores, revista, editorial, fecha, volumen, número, páginas, ISSN, tipo y, a veces,
  áreas temáticas.
- arXiv: título, autores, fecha y categorías (cs.CL, math.AP...), traducidas a etiquetas legibles.

Solo se envía el identificador. Las respuestas se guardan en data/lookup_cache.json (una consulta por
identificador). Los campos entran con confianza config.ENRICH_CONFIDENCE: ganan a lo extraído del PDF, pero un
valor confirmado por una persona (en el servidor) nunca se sobrescribe."""
from __future__ import annotations
import json
import re
import xml.etree.ElementTree as ET

import config

UA = {"User-Agent": "udc-library-poc/0.1 (classification research)"}
_cache: dict | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        p = config.DATA_DIR / "lookup_cache.json"
        try:
            _cache = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except Exception:  # noqa: BLE001
            _cache = {}
    return _cache


def _save_cache():
    p = config.DATA_DIR / "lookup_cache.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(_cache, ensure_ascii=False, indent=1), encoding="utf-8")


def _cached(key: str, fn):
    c = _load_cache()
    if key not in c:
        try:
            c[key] = fn()
        except Exception as e:  # noqa: BLE001  (sin red, límite de uso...): no se guarda, se reintenta luego
            return {"error": str(e)[:200]}
        _save_cache()
    return c[key]


def _get(url, **kw):
    import httpx
    r = httpx.get(url, headers=UA, timeout=config.ENRICH_TIMEOUT, follow_redirects=True, **kw)
    r.raise_for_status()
    return r


# ------------------------------------------------------------------ fuentes
def openlibrary_isbn(isbn: str) -> dict:
    d = _get("https://openlibrary.org/api/books",
             params={"bibkeys": f"ISBN:{isbn}", "format": "json", "jscmd": "data"}).json().get(f"ISBN:{isbn}")
    if not d:
        return {}
    cl = d.get("classifications") or {}
    title = d.get("title", "") + (f": {d['subtitle']}" if d.get("subtitle") else "")
    return {
        "fields": {"title": title, "publisher": ", ".join(p["name"] for p in d.get("publishers", []) if p.get("name")),
                   "place": ", ".join(p["name"] for p in d.get("publish_places", []) if p.get("name")),
                   "date": d.get("publish_date", ""), "numPages": str(d.get("number_of_pages") or ""), "ISBN": isbn},
        "creators": [a["name"] for a in d.get("authors", []) if a.get("name")],
        "subjects": [s["name"] for s in d.get("subjects", []) if s.get("name")],
        "ddc": cl.get("dewey_decimal_class", []), "lcc": cl.get("lc_classifications", []),
        "udc": [v for k, vs in cl.items() if "udc" in k.lower() or "universal" in k.lower() for v in vs],
    }


def bn_poland_isbn(isbn: str) -> dict:
    bibs = _get("https://data.bn.org.pl/api/institutions/bibs.json",
                params={"isbnIssn": isbn, "limit": 3}).json().get("bibs", [])
    udc = []
    for b in bibs:
        for f in b.get("marc", {}).get("fields", []):
            if "080" in f:
                udc += [sf["a"] for sf in f["080"].get("subfields", []) if "a" in sf]
    return {"udc": udc} if udc else {}


def crossref_doi(doi: str) -> dict:
    from urllib.parse import quote
    m = _get(f"https://api.crossref.org/works/{quote(doi, safe='/')}").json().get("message", {})
    first = lambda v: (v or [""])[0]
    dp = (m.get("issued") or m.get("published") or {}).get("date-parts", [[None]])[0]
    date = "-".join(f"{x:02d}" if i else str(x) for i, x in enumerate(dp) if x) if dp and dp[0] else ""
    return {
        "fields": {"title": first(m.get("title")), "publicationTitle": first(m.get("container-title")),
                   "publisher": m.get("publisher", ""), "date": date, "DOI": doi, "volume": m.get("volume", ""),
                   "issue": m.get("issue", ""), "pages": m.get("page", ""), "ISSN": first(m.get("ISSN"))},
        "creators": [" ".join(x for x in (a.get("given"), a.get("family")) if x) for a in m.get("author", [])],
        "subjects": m.get("subject", []), "crossref_type": m.get("type", ""),
    }


ARXIV_CATS = {   # categorías más comunes -> etiqueta legible (para la vista de temas)
    "cs.AI": "Artificial intelligence", "cs.CL": "Computation and language. Natural language processing",
    "cs.CV": "Computer vision. Pattern recognition", "cs.LG": "Machine learning", "cs.NE": "Neural networks",
    "cs.CR": "Cryptography and security", "cs.DS": "Data structures and algorithms", "cs.DB": "Databases",
    "cs.IR": "Information retrieval", "cs.RO": "Robotics", "cs.SE": "Software engineering",
    "cs.NI": "Computer networks", "cs.PL": "Programming languages", "cs.AR": "Computer architecture",
    "stat.ML": "Machine learning. Statistics", "math.ST": "Mathematical statistics", "math.PR": "Probability",
    "math.NA": "Numerical analysis", "math.AP": "Partial differential equations", "math.CO": "Combinatorics",
    "math.NT": "Number theory", "math.AG": "Algebraic geometry", "math.OC": "Optimization and control",
    "physics.optics": "Optics", "quant-ph": "Quantum physics", "cond-mat": "Condensed matter physics",
    "astro-ph": "Astrophysics", "hep-th": "High energy physics theory", "gr-qc": "General relativity",
    "eess.SP": "Signal processing", "eess.SY": "Control systems", "q-bio": "Quantitative biology",
    "econ": "Economics", "q-fin": "Quantitative finance",
}


def arxiv_id(aid: str) -> dict:
    x = _get("http://export.arxiv.org/api/query", params={"id_list": aid}).text
    A = "{http://www.w3.org/2005/Atom}"
    e = ET.fromstring(x).find(f"{A}entry")
    if e is None:
        return {}
    cats = [c.get("term") for c in e.findall(f"{A}category") if c.get("term")]
    labels = [ARXIV_CATS.get(c) or ARXIV_CATS.get(c.split(".")[0]) for c in cats]
    return {
        "fields": {"title": " ".join((e.findtext(f"{A}title") or "").split()),
                   "date": (e.findtext(f"{A}published") or "")[:10], "archiveID": f"arXiv:{aid}",
                   "repository": "arXiv", "abstractNote": " ".join((e.findtext(f"{A}summary") or "").split())},
        "creators": [a.findtext(f"{A}name") for a in e.findall(f"{A}author") if a.findtext(f"{A}name")],
        "subjects": [l for l in labels if l], "arxiv_categories": cats,
    }


# ------------------------------------------------------------------ orquestación
def isbn13(raw: str) -> str:
    d = re.sub(r"[^0-9Xx]", "", raw or "")
    if len(d) == 10:
        core = "978" + d[:9]
        return core + str((10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core)) % 10) % 10)
    return d


def enrich(ids: dict) -> dict | None:
    """{'sources', 'fields', 'creators', 'subjects', 'ddc', 'lcc', 'udc', 'errors'} o None si no hay identificador."""
    if not ids:
        return None
    out = {"sources": [], "fields": {}, "creators": [], "subjects": [], "ddc": [], "lcc": [], "udc": [], "errors": []}

    def merge(name, r):
        if not r:
            return
        if "error" in r:
            out["errors"].append(f"{name}: {r['error']}")
            return
        out["sources"].append(name)
        for k, v in (r.get("fields") or {}).items():
            if v and k not in out["fields"]:
                out["fields"][k] = v
        if r.get("creators") and not out["creators"]:
            out["creators"] = r["creators"]
        for k in ("subjects", "ddc", "lcc", "udc"):
            out[k] += [v for v in r.get(k, []) if v and v not in out[k]]
        for k in ("crossref_type", "arxiv_categories"):
            if r.get(k):
                out[k] = r[k]

    if ids.get("doi"):
        merge("crossref", _cached(f"doi:{ids['doi'].lower()}", lambda: crossref_doi(ids["doi"])))
    if ids.get("arxiv"):
        merge("arxiv", _cached(f"arxiv:{ids['arxiv']}", lambda: arxiv_id(ids["arxiv"])))
    if ids.get("isbn"):
        i13 = isbn13(ids["isbn"])
        merge("openlibrary", _cached(f"ol:{i13}", lambda: openlibrary_isbn(i13)))
        if config.ENRICH_UDC_CATALOGS:
            merge("bn.org.pl", _cached(f"bnpl:{i13}", lambda: bn_poland_isbn(i13)))
    return out if (out["sources"] or out["errors"]) else None


def is_code(s: str) -> bool:
    """'Qa433 .s28 2005', '515/.63': signaturas que Open Library mezcla con los temas."""
    return bool(re.match(r"^[A-Za-z]{1,3}\s?\d|^\d{3}", s or ""))


def subjects_view(e: dict) -> str:
    """Texto de temas para el clasificador (vista 'subjects'): temas + clases LC/Dewey legibles."""
    parts = [s for s in e.get("subjects", []) if not is_code(s)]               # quita códigos LC/Dewey sueltos
    parts += [lcc_label(c) for c in e.get("lcc", []) if lcc_label(c)]
    parts += [ddc_label(c) for c in e.get("ddc", []) if ddc_label(c)]
    seen, out = set(), []
    for p in parts:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return "; ".join(out)[:1500]


# Clase LC (letras iniciales) -> materia; subclases frecuentes en bibliotecas técnicas y generales.
LCC = {
    "A": "General works", "B": "Philosophy. Psychology. Religion", "BC": "Logic", "BD": "Speculative philosophy",
    "BF": "Psychology", "BJ": "Ethics", "BL": "Religion. Mythology", "BR": "Christianity", "C": "History",
    "D": "World history", "E": "History of the Americas", "F": "History of the Americas (local)", "G": "Geography",
    "GB": "Physical geography", "GC": "Oceanography", "GE": "Environmental sciences", "GN": "Anthropology",
    "GV": "Recreation. Leisure. Sports", "H": "Social sciences", "HA": "Statistics", "HB": "Economic theory. Demography",
    "HC": "Economic history", "HD": "Industries. Land use. Labor", "HE": "Transportation and communications",
    "HF": "Commerce", "HG": "Finance", "HM": "Sociology", "HN": "Social history and conditions",
    "HQ": "The family. Marriage. Women", "HV": "Social pathology. Social welfare", "J": "Political science",
    "K": "Law", "KF": "Law of the United States", "L": "Education", "M": "Music", "ML": "Literature on music",
    "MT": "Musical instruction and study", "N": "Fine arts", "NA": "Architecture", "NK": "Decorative arts",
    "P": "Language and literature", "PA": "Greek and Latin languages and literatures", "PN": "Literature (general)",
    "PQ": "Romance literatures", "PR": "English literature", "PS": "American literature", "Q": "Science",
    "QA": "Mathematics", "QB": "Astronomy", "QC": "Physics", "QD": "Chemistry", "QE": "Geology",
    "QH": "Natural history. Biology", "QK": "Botany", "QL": "Zoology", "QM": "Human anatomy",
    "QP": "Physiology", "QR": "Microbiology", "R": "Medicine", "RA": "Public aspects of medicine",
    "RM": "Therapeutics. Pharmacology", "RS": "Pharmacy and materia medica", "S": "Agriculture",
    "SH": "Aquaculture. Fisheries", "T": "Technology", "TA": "Engineering (general). Civil engineering",
    "TJ": "Mechanical engineering and machinery", "TK": "Electrical engineering. Electronics",
    "TL": "Motor vehicles. Aeronautics", "TN": "Mining engineering. Metallurgy", "TP": "Chemical technology",
    "TS": "Manufactures", "U": "Military science", "Z": "Bibliography. Library science",
}


def lcc_label(code: str) -> str:
    m = re.match(r"^([A-Z]{1,3})", (code or "").strip().upper())
    if not m:
        return ""
    letters = m.group(1)
    for k in (letters, letters[:2], letters[:1]):
        if k in LCC:
            return LCC[k]
    return ""


# Dewey: segundo sumario (divisiones de diez) -> materia.
DDC = {
    "00": "Computer science, information", "01": "Bibliographies", "02": "Library and information sciences",
    "03": "Encyclopedias", "05": "Magazines, journals", "06": "Associations, organizations", "07": "News media, journalism",
    "08": "Quotations", "09": "Manuscripts, rare books", "10": "Philosophy", "11": "Metaphysics", "12": "Epistemology",
    "13": "Parapsychology, occultism", "14": "Philosophical schools of thought", "15": "Psychology", "16": "Logic",
    "17": "Ethics", "18": "Ancient, medieval, eastern philosophy", "19": "Modern western philosophy",
    "20": "Religion", "22": "Bible", "23": "Christianity, Christian theology", "29": "Other religions",
    "30": "Social sciences, sociology", "31": "Statistics", "32": "Political science", "33": "Economics", "34": "Law",
    "35": "Public administration, military science", "36": "Social problems and social services", "37": "Education",
    "38": "Commerce, communications, transportation", "39": "Customs, etiquette, folklore", "40": "Language",
    "41": "Linguistics", "42": "English language", "43": "German language", "44": "French language",
    "45": "Italian language", "46": "Spanish and Portuguese languages", "47": "Latin language", "48": "Greek language",
    "49": "Other languages", "50": "Science", "51": "Mathematics", "52": "Astronomy", "53": "Physics",
    "54": "Chemistry", "55": "Earth sciences, geology", "56": "Palaeontology", "57": "Biology, life sciences",
    "58": "Botany, plants", "59": "Zoology, animals", "60": "Technology", "61": "Medicine and health",
    "62": "Engineering", "63": "Agriculture", "64": "Home and family management", "65": "Management, public relations",
    "66": "Chemical engineering", "67": "Manufacturing", "68": "Manufacture for specific uses",
    "69": "Building and construction", "70": "Arts", "71": "Landscape architecture, area planning", "72": "Architecture",
    "73": "Sculpture, ceramics, metalwork", "74": "Drawing, decorative arts", "75": "Painting", "76": "Graphic arts",
    "77": "Photography", "78": "Music", "79": "Sports, games, entertainment", "80": "Literature, rhetoric",
    "81": "American literature in English", "82": "English literature", "83": "German literature",
    "84": "French literature", "85": "Italian literature", "86": "Spanish and Portuguese literature",
    "87": "Latin literature", "88": "Greek literature", "89": "Other literatures", "90": "History",
    "91": "Geography and travel", "92": "Biography, genealogy", "93": "Ancient history", "94": "History of Europe",
    "95": "History of Asia", "96": "History of Africa", "97": "History of North America",
    "98": "History of South America", "99": "History of other areas",
}


def ddc_label(code: str) -> str:
    m = re.match(r"^(\d)(\d)", (code or "").strip())
    return DDC.get(m.group(1) + m.group(2), "") if m else ""
