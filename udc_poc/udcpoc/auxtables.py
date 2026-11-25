"""Tablas auxiliares resueltas sin LLM: lengua '=', lugar '(...)', tiempo '"..."' y forma '(0...)'.
Los códigos se resuelven contra las ETIQUETAS del árbol cargado, nunca de memoria."""
from __future__ import annotations
import re
from collections import Counter

import config
from . import locales
from .embed import strip_accents


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(s or "").lower()).strip()


def _en(n, tree) -> str:
    return n.label(tree.label_langs)


# ------------------------------------------------------------------------ lengua =
def _by_notation(tree, notation):
    return next((n for n in tree.nodes.values() if n.notation == notation), None)


def lang_aux(iso: str | None, conf: float, tree) -> dict | None:
    """Tabla de lengua para cualquier idioma: excepción de config.LANG_UDC o nombre inglés CLDR -> nodo."""
    if not iso:
        return None
    if iso in config.LANG_UDC:
        n = _by_notation(tree, config.LANG_UDC[iso]) if config.LANG_UDC[iso] else None
    else:
        name = locales.language_name_en(iso)
        if not name:
            return None
        target = _norm(name)
        nodes = tree.of_kind("lang")
        exact = [n for n in nodes if _norm(_en(n, tree)) == target or _norm(_primary(_en(n, tree))) == target]
        pref = [n for n in nodes if _norm(_en(n, tree)).startswith((target + " ", target + ",", target + "."))]
        pick = sorted(exact or pref, key=lambda n: (len(n.notation), n.notation))
        n = pick[0] if pick else None
    if n is None:
        return None
    return {"code": n.notation, "label": _en(n, tree), "source": "language-detection",
            "confidence": round(conf, 2), "evidence": f"idioma detectado: {iso}"}


# ------------------------------------------------------------------------ lugar (...)
_GENERIC = {"north", "south", "east", "west", "central", "middle", "upper", "lower", "new", "great", "greater"}
# Escrituras sin espacios entre palabras: ahí no sirven los límites de palabra del regex.
_NO_SPACES = re.compile(r"[฀-໿က-႟ក-៿぀-ヿ㐀-鿿가-힯]")


def _primary(label: str) -> str:
    return re.split(r"[,;(]", label)[0].strip()


_QUALIFIED = re.compile(r"\((?:state|province|department|region|municipality|city|county|district|canton|"
                        r"island|commune|capital|microregion|mesoregion|parish|prefecture|oblast)\b", re.I)


def _en_key(name: str) -> str:
    """Normaliza nombres ingleses de CLDR para compararlos con las etiquetas UDC."""
    s = re.sub(r"\s*&\s*", " and ", name)
    s = re.sub(r"\bSt\.\s*", "Saint ", s)
    return _norm(s)


class PlaceFinder:
    """Nombres de lugar en el texto -> nodo de la tabla de lugar. Siempre busca las etiquetas inglesas del
    árbol; además, para el idioma del documento, los nombres CLDR de países y regiones en ese idioma
    (Mexiko, Мексика, メキシコ...) y los alias de config.PLACE_ALIASES."""

    def __init__(self, tree):
        self.tree = tree
        self.nodes = tree.of_kind("place")
        self.unresolved: list[str] = []
        self._by_code: dict = {}
        self._by_lang: dict[str, list] = {}
        prim: dict[str, list] = {}
        for n in self.nodes:
            lbl = _en(n, tree)
            for key in {_norm(_primary(lbl)), _norm(re.split(r"\.\s|[,;(]", lbl)[0])}:   # "Mexico. United..."
                prim.setdefault(key, []).append(n)
        self._prim = prim
        self._prim_keys = sorted(prim)
        names: dict[str, set[str]] = {n.uri: set() for n in self.nodes}
        for n in self.nodes:
            for lbl in [_en(n, tree)] + list(n.alt):
                p = _primary(lbl)
                if len(p) >= 4 and _norm(p) not in _GENERIC:
                    names[n.uri].add(p)
        self.entries = self._compile((self.tree.nodes[u], nm) for u, ns in names.items() for nm in ns)
        if locales.territory_en("MX"):          # babel disponible: comprobar que los países resuelven
            from babel import Locale
            for code in Locale.parse("en").territories:
                if len(code) == 2 and code.isalpha() and code not in ("ZZ", "EU", "EZ", "UN", "QO", "XA", "XB")                         and self.node_for(code) is None and config.TERRITORY_UDC.get(code, "") != None:
                    self.unresolved.append(f"{code} {locales.territory_en(code)}")

    @staticmethod
    def _compile(pairs, inflected: bool = False) -> list:
        """Regex por nombre. En idiomas con casos gramaticales la última palabra admite otra terminación
        (hasta 3 letras tras quitar la vocal final): Испания -> Испании, Polska -> Polski, Mexiko -> Mexikos."""
        out = []
        for n, nm in pairs:
            t = strip_accents(nm)
            if _NO_SPACES.search(t):
                rx = re.compile(re.escape(t))
            elif inflected and len(t) >= 5:
                stem = t[:-1] if t[-1].lower() in "aeiouyаеиоуыэюяьйαεηιουω" else t
                rx = re.compile(r"(?<!\w)" + re.escape(stem) + r"\w{0,3}(?!\w)")
            else:
                rx = re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)")
            out.append((rx, n, nm))                 # sensible a mayúsculas: "Chad" no es "chad"
        return out

    def node_for(self, code: str):
        """Código CLDR ('MX', '029') o notación UDC ('(729)') -> nodo de lugar, o None."""
        if code in self._by_code:
            return self._by_code[code]
        node, override = None, config.TERRITORY_UDC.get(code, "")
        if code.startswith("("):
            node = _by_notation(self.tree, code)
        elif override is None:
            pass                                            # región sin nodo propio, a propósito
        else:
            if override:
                node = _by_notation(self.tree, override)    # si este árbol no lo tiene, se busca por nombre
            en = locales.territory_en(code) if node is None else None
            if en:
                key = _en_key(en)
                hit = self._prim.get(key) or [n for k in self._prim_keys if k.startswith(key) for n in self._prim[k]]
                if hit:   # el país antes que un homónimo "(state)", "(province)", "(city)"...; luego el más general
                    node = sorted(hit, key=lambda n: (bool(_QUALIFIED.search(_en(n, self.tree))),
                                                      len(n.notation), n.notation))[0]
        self._by_code[code] = node
        return node

    def entries_for(self, lang: str | None) -> list:
        lang = locales.base(lang) or "en"
        if lang not in self._by_lang:
            pairs = []
            aliases = list(locales.territory_names(lang).items()) + list(config.PLACE_ALIASES.get(lang, {}).items())
            for name, code in aliases:
                n = self.node_for(code)
                if n is not None and len(name) >= 2 and _norm(name) not in _GENERIC:
                    pairs.append((n, name))
            self._by_lang[lang] = self._compile(pairs, inflected=lang in locales.INFLECTED)
        return self._by_lang[lang]

    def find(self, segments: list[tuple[str, float]], lang: str | None = None) -> dict | None:
        scores: Counter = Counter()
        seen_names: dict[str, Counter] = {}
        # Los nombres de país/región (CLDR + alias) mandan: si "India" es un país, las etiquetas del árbol
        # que también empiezan por "India" (Indian Ocean...) no compiten con ese mismo nombre.
        entries, names = [], set()
        for e in self.entries_for(lang) + self.entries_for("en"):
            if strip_accents(e[2]) not in names:
                names.add(strip_accents(e[2]))
                entries.append(e)
        entries += [e for e in self.entries if strip_accents(e[2]) not in names]
        # Falsos amigos: un nombre de una palabra que en ESTE texto también aparece en minúsculas es una palabra
        # común ("para" -> Pará, "china", "chile", "turkey"), no un lugar.
        lower_words = Counter(re.findall(r"(?<!\w)[^\W\d_A-Z][^\W\d_]*", strip_accents(
            " ".join(s for s, _ in segments if s))))
        common = {e[2] for e in entries if " " not in e[2] and lower_words[strip_accents(e[2]).lower()] >= 1}
        entries = [e for e in entries if e[2] not in common]
        for text, w in segments:
            t = strip_accents(text or "")
            for rx, n, nm in entries:
                c = len(rx.findall(t))
                if c:
                    scores[n.uri] += w * c
                    seen_names.setdefault(n.uri, Counter())[nm] += c
        if not scores:
            return None
        ranked = scores.most_common()
        top_uri, top = ranked[0]
        node = self.tree.nodes[top_uri]
        # entre un lugar general y uno específico relacionado, preferir el específico si pesa lo bastante
        for uri, sc in ranked[1:4]:
            other = self.tree.nodes[uri]
            if self.tree.is_related(node, other) and other.depth > node.depth and sc >= 0.6 * top:
                node, top = other, sc
                break
        if top < config.PLACE_MIN_SCORE:
            return None
        rivals = [sc for uri, sc in ranked if not self.tree.is_related(self.tree.nodes[uri], node)]
        if rivals and top < config.PLACE_DOMINANCE * rivals[0]:
            return None
        ev = ", ".join(f"{k}×{v}" for k, v in seen_names[node.uri].most_common(3))
        return {"code": node.notation, "label": _en(node, self.tree), "source": "gazetteer",
                "confidence": round(min(1.0, top / 10), 2), "evidence": ev}


# ------------------------------------------------------------------------ tiempo "..."
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}
_ORD_EN = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
           "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
           "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18, "nineteenth": 19,
           "twentieth": 20, "twenty-first": 21}


def _roman(s: str) -> int:
    t = 0
    for i, ch in enumerate(s):
        v = _ROMAN.get(ch, 0)
        t += -v if i + 1 < len(s) and _ROMAN.get(s[i + 1], 0) > v else v
    return t


def time_aux(text: str, tree, title: str = "") -> dict | None:
    """El tiempo UDC describe el periodo del TEMA, no la fecha de publicación. Solo cuentan periodos
    explícitos ("siglo XIX", "19th century", "1910-1920"); los años sueltos del texto son casi siempre de
    edición, informes o citas, y daban "20" a todo. Un periodo en el título pesa más."""
    if not (text or title):
        return None
    cents: Counter = Counter()
    for chunk, w in ((title, 3), (text, 2)):
        _centuries(strip_accents(chunk or ""), cents, w)
    rng = re.search(r"\b((?:1[0-9]|20)\d{2})\s*[-–/]\s*((?:1[0-9]|20)\d{2})\b", strip_accents(title or ""))
    if rng and 0 < int(rng.group(2)) - int(rng.group(1)) <= 60:
        code = f'"{rng.group(1)}/{rng.group(2)}"'
        return {"code": code, "label": f"{rng.group(1)}-{rng.group(2)}", "source": "regex",
                "confidence": 0.5, "evidence": f"rango explícito en el título {rng.group(0)}"}
    if not cents:
        return None
    c, score = cents.most_common(1)[0]
    if score < config.TIME_MIN_MENTIONS + 1:
        return None
    code = f'"{c - 1}"'
    node = tree.get(code)
    return {"code": code, "label": _en(node, tree) if node else f"siglo {c} (generado por gramática)",
            "source": "regex", "confidence": round(min(0.7, 0.2 + score / 12), 2),
            "evidence": f"siglo {c} (peso {score})"}


def _centuries(t: str, cents: Counter, w: int) -> None:
    # "siglo XIX", "século XIX", "secolo XIX", "XIXe siècle", "XIX secolo", "XIX век", "19. Jahrhundert",
    # "19th century", "19e siècle", "XIX wiek", "XIX. század"... (romano o arábigo, antes o después)
    cent_w = r"(?:siglos?|s[ée]culos?|secol[oi]|si[eè]cles?|jahrhunderts?|eeuw|[aå]rhundrade|århundrede|wieku?|" \
             r"stolet[ií]|vuosisata|sz[aá]zad|y[uü]zy[ıi]l|век[ае]?|столетия?)"
    for m in re.finditer(rf"\b{cent_w}\s+([IVXL]+|\d{{1,2}})\b|\b([IVXL]+|\d{{1,2}})(?:st|nd|rd|th|e|eme|er|\.|-?й|-?го)?"
                         rf"\s+{cent_w}", t, re.I):
        v = m.group(1) or m.group(2)
        c = int(v) if v.isdigit() else _roman(v.upper())
        if 1 <= c <= 21:
            cents[c] += w
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)[\s\-]+century\b", t, re.I):
        c = int(m.group(1))
        if 1 <= c <= 21:
            cents[c] += w
    for m in re.finditer(r"\b((?:twenty-)?[a-z]+)[\s\-]+century\b", t, re.I):   # "Twentieth-century"
        c = _ORD_EN.get(m.group(1).lower())
        if c:
            cents[c] += w


# ------------------------------------------------------------------------ forma (0...)
def form_aux(item_type: str, subtype: str | None, text: str, tree) -> dict | None:
    forms = [n for n in tree.of_kind("form") if n.notation != "(0)"]  # excluye el nodo raíz
    if not forms:
        return None
    keysets: list[tuple[list[str], str]] = []
    low = (text or "").lower()
    for rx, kws in config.FORM_BY_TEXT:
        if re.search(rx, low):
            keysets.append((kws, f"palabra clave en el texto ({rx[:30]}…)"))
    kws = config.FORM_BY_DOCTYPE.get(item_type)
    if kws:
        keysets.append((kws, f"tipo de documento: {item_type}"))
    for kws, why in keysets:
        for kw in kws:
            hits = [n for n in forms if kw in _en(n, tree).lower()]
            if hits:
                n = sorted(hits, key=lambda n: (len(n.notation), n.notation))[0]
                if n.notation == "(075)" and re.search(config.FORM_HIGHER_ED, low):
                    hi = next((x for x in forms if x.notation == "(075.8)"), None)
                    if hi is not None:                   # texto universitario
                        n, why = hi, why + " + educación superior"
                return {"code": n.notation, "label": _en(n, tree), "source": "rules",
                        "confidence": 0.6, "evidence": f"{why} → '{kw}'"}
    return None
