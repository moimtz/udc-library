"""Tablas auxiliares resueltas sin LLM: lengua '=', lugar '(...)', tiempo '"..."' y forma '(0...)'.
Los códigos se resuelven contra las ETIQUETAS del árbol cargado, nunca de memoria."""
from __future__ import annotations
import re
from collections import Counter

import config
from .embed import strip_accents


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(s or "").lower()).strip()


def _en(n, tree) -> str:
    return n.label(tree.label_langs)


# ------------------------------------------------------------------------ lengua =
def lang_aux(iso: str | None, conf: float, tree) -> dict | None:
    name = config.LANG_NAMES.get(iso or "")
    if not name:
        return None
    target = _norm(name)
    nodes = tree.of_kind("lang")
    exact = [n for n in nodes if _norm(_en(n, tree)) == target]
    pref = [n for n in nodes if _norm(_en(n, tree)).startswith(target + " ") or _norm(_en(n, tree)).startswith(target + ",")]
    pick = sorted(exact or pref, key=lambda n: (len(n.notation), n.notation))
    if not pick:
        return None
    n = pick[0]
    return {"code": n.notation, "label": _en(n, tree), "source": "language-detection",
            "confidence": round(conf, 2), "evidence": f"idioma detectado: {iso}"}


# ------------------------------------------------------------------------ lugar (...)
_GENERIC = {"north", "south", "east", "west", "central", "middle", "upper", "lower", "new", "great", "greater"}


def _primary(label: str) -> str:
    return re.split(r"[,;(]", label)[0].strip()


class PlaceFinder:
    def __init__(self, tree):
        self.tree = tree
        self.entries: list[tuple[re.Pattern, object, str]] = []
        self.unresolved: list[str] = []
        nodes = tree.of_kind("place")
        names: dict[str, set[str]] = {n.uri: set() for n in nodes}
        for n in nodes:
            for lbl in [_en(n, tree)] + list(n.alt):
                p = _primary(lbl)
                if len(p) >= 4 and _norm(p) not in _GENERIC:
                    names[n.uri].add(p)
        for es, en in config.PLACE_ALIASES_ES.items():
            tgt = _norm(en)
            hit = [n for n in nodes if _norm(_primary(_en(n, tree))) == tgt] or \
                  [n for n in nodes if _norm(_primary(_en(n, tree))).startswith(tgt)]
            if hit:
                names[sorted(hit, key=lambda n: len(n.notation))[0].uri].add(es)
            else:
                self.unresolved.append(f"{es} -> {en}")
        for n in nodes:
            for nm in names[n.uri]:
                rx = re.compile(r"(?<!\w)" + re.escape(strip_accents(nm)) + r"(?!\w)")  # sensible a mayúsculas
                self.entries.append((rx, n, nm))

    def find(self, segments: list[tuple[str, float]]) -> dict | None:
        scores: Counter = Counter()
        seen_names: dict[str, Counter] = {}
        for text, w in segments:
            t = strip_accents(text or "")
            for rx, n, nm in self.entries:
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


def time_aux(text: str, tree) -> dict | None:
    """El tiempo UDC describe el periodo del TEMA, no la fecha de publicación: por eso solo se
    mira título + resumen + índice (nunca bibliografía)."""
    if not text:
        return None
    t = strip_accents(text)
    cents: Counter = Counter()
    for m in re.finditer(r"\bsiglos?\s+([IVXL]+)\b", t, re.I):
        c = _roman(m.group(1).upper())
        if 1 <= c <= 21:
            cents[c] += 2
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)\s+century\b|\bsiglo\s+(\d{1,2})\b", t, re.I):
        c = int(m.group(1) or m.group(2))
        if 1 <= c <= 21:
            cents[c] += 2
    for m in re.finditer(r"\b([a-z\-]+)\s+century\b", t, re.I):
        c = _ORD_EN.get(m.group(1).lower())
        if c:
            cents[c] += 2
    for m in re.finditer(r"\b(?:1[0-9]|20)\d{2}\b", t):
        cents[int(m.group()) // 100 + 1] += 1
    rng = re.search(r"\b((?:1[0-9]|20)\d{2})\s*[-–/]\s*((?:1[0-9]|20)\d{2})\b", t)
    if rng and 0 < int(rng.group(2)) - int(rng.group(1)) <= 60:
        code = f'"{rng.group(1)}/{rng.group(2)}"'
        return {"code": code, "label": f"{rng.group(1)}-{rng.group(2)}", "source": "regex",
                "confidence": 0.5, "evidence": f"rango explícito {rng.group(0)}"}
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
                return {"code": n.notation, "label": _en(n, tree), "source": "rules",
                        "confidence": 0.6, "evidence": f"{why} → '{kw}'"}
    return None
