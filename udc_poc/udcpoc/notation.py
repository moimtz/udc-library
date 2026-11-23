"""Tokenización, validación y composición de notaciones UDC."""
from __future__ import annotations
import re
from dataclasses import dataclass

import config

TOKEN_RE = re.compile(r'''
    (?P<time>"[^"]*")
  | (?P<paren>\([^()]*\))
  | (?P<lang>=[0-9][0-9.]*)
  | (?P<view>\.00[0-9.]*)
  | (?P<special>\.0[0-9]+|-[1-9][0-9.]*|['`][0-9][0-9.]*)
  | (?P<common>-0[0-9.]*)
  | (?P<rel>::|[:+/])
  | (?P<main>[0-9][0-9.]*)
''', re.X)
TIME_RE = re.compile(r'^"[0-9][0-9/.\-:+]*"$')


@dataclass
class Token:
    kind: str
    text: str


def tokenize(s: str) -> tuple[list[Token], list[str]]:
    toks, errs, pos = [], [], 0
    s = s.strip()
    while pos < len(s):
        if s[pos].isspace():
            pos += 1
            continue
        m = TOKEN_RE.match(s, pos)
        if not m:
            errs.append(f"carácter inesperado '{s[pos]}' en la posición {pos}")
            pos += 1
            continue
        kind, text = m.lastgroup, m.group()
        if kind == "paren":
            inner = text[1:-1]
            kind = "form" if inner.startswith("0") else "ethnic" if inner.startswith("=") else \
                "place" if inner[:1].isdigit() else "place_other"
        toks.append(Token(kind, text))
        pos = m.end()
    return toks, errs


def components(notation: str) -> dict:
    """Descompone en {'main': [...], 'lang': [...], 'form': [...], ...} para comparar/evaluar."""
    toks, _ = tokenize(notation)
    out: dict[str, list[str]] = {}
    for t in toks:
        if t.kind != "rel":
            out.setdefault(t.kind, []).append(t.text)
    return out


def validate(notation: str, tree=None) -> list[tuple[str, str]]:
    """Devuelve [(nivel, mensaje)]; nivel 'error' (sintaxis o clase principal inexistente) o 'warning'."""
    issues: list[tuple[str, str]] = []
    if not notation or not notation.strip():
        return [("error", "notación vacía")]
    if notation.count("(") != notation.count(")"):
        issues.append(("error", "paréntesis desbalanceados"))
    if notation.count('"') % 2:
        issues.append(("error", "comillas de tiempo desbalanceadas"))
    toks, errs = tokenize(notation)
    issues += [("error", e) for e in errs]
    if not toks:
        return issues or [("error", "sin componentes reconocibles")]
    if toks[-1].kind == "rel":
        issues.append(("error", "la notación termina en un signo de relación"))
    for a, b in zip(toks, toks[1:]):
        if a.kind == "rel" and b.kind == "rel":
            issues.append(("error", "dos signos de relación seguidos"))
    if not any(t.kind == "main" for t in toks):
        issues.append(("warning", "no hay clase principal (solo auxiliares)"))
    if tree is not None:
        toks = _split_main_special(toks, tree)
        last_main = ""
        for t in toks:
            if t.kind == "rel":
                continue
            node = tree.get(t.text)
            canc = tree.cancellation(t.text) if hasattr(tree, "cancellation") else None
            if canc is not None:
                # notación cancelada: mismo nivel que si no existiera, pero se dice por qué y con qué se reemplaza
                if t.kind == "main":
                    last_main = t.text
                level = "error" if t.kind == "main" else "warning"
                repl = "; ".join(canc["replaced_by"]) or "sin reemplazo"
                when = f"{canc['year']}" + (f", {canc['ec']}" if canc["ec"] else "")
                issues.append((level, f"{t.text} fue cancelada en la UDC [{when}] ({canc['label']}); "
                                      f"se reemplaza por: {repl}"))
                continue
            if t.kind == "main":
                last_main = t.text
                if node is None or node.kind != "main":
                    issues.append(("error", f"la clase principal {t.text} no existe en el UDC Summary"))
            elif t.kind == "special":
                # en el árbol, la especial está junto a su clase base ('2-55'): probar los prefijos de la principal
                if not any(tree.get(p + t.text) for p in _prefixes(last_main)) and node is None:
                    issues.append(("warning", f"{t.text} (special) no aparece en el UDC Summary "
                                              "(puede ser válido en la tabla completa)"))
            elif t.kind == "time":
                if not TIME_RE.match(t.text):
                    issues.append(("error", f"tiempo mal formado: {t.text}"))
            elif node is None:
                issues.append(("warning", f"{t.text} ({t.kind}) no aparece en el UDC Summary (puede ser válido en la tabla completa)"))
    return issues


def _prefixes(main: str) -> list[str]:
    """'821.134' -> ['821.134', '821.13', '821.1', '821', '82', '8']"""
    out, s = [], main
    while s:
        out.append(s)
        s = s[:-1].rstrip(".")
    return out


def _split_main_special(toks: list[Token], tree) -> list[Token]:
    """El tokenizador lee '53.08' como una sola clase principal. Si no existe como 'main' en el árbol,
    se separa en principal + especial ('53' + '.08') cuando el prefijo sí es una clase principal."""
    out = []
    for t in toks:
        node = tree.get(t.text) if t.kind == "main" else None
        if t.kind == "main" and (node is None or node.kind != "main"):
            for m in re.finditer(r"\.0", t.text):
                base = tree.get(t.text[:m.start()])
                if base is not None and base.kind == "main":
                    out += [Token("main", t.text[:m.start()]), Token("special", t.text[m.start():])]
                    break
            else:
                out.append(t)
            continue
        out.append(t)
    return out


def compose(mains: list[dict], aux: dict[str, str]) -> str:
    """mains: [{'code': '94', 'special': '', 'common': '', 'view': ''}]; aux: {'lang': '=134.2', ...}.
    Las auxiliares globales se anexan al final, en el orden de config.AUX_ORDER."""
    body = ":".join(m["code"] + m.get("special", "") + m.get("common", "") + m.get("view", "") for m in mains)
    return body + "".join(aux.get(k, "") for k in config.AUX_ORDER)
