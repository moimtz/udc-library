#!/usr/bin/env python3
"""Interpreta las fichas descargadas de UDC Online y genera udc_records.json.

Entrada: udc_records_part_NNNN.jsonl.gz (las escribe udc_main_tree_fusion.py a partir del snapshot); cada línea es
{"n": notación, "h": html} o {"n": notación, "error": ...}.
Salida: udc_records.json con el mismo formato que extra_notes.json (lo aplica udc_merge.py) y un
informe con todo lo que no se reconoció.

Cada ficha muestra la clase pedida (en negrita) y sus subdivisiones, cada una con su panel oculto
(div id="rdNNN"): notas, recuadros ◇ (ejemplos de combinación) y ⇨ (véase también). El «Including»
va junto a la etiqueta (icono title="Including"). Una clase aparece en su ficha y en la de su
padre; se usa la de su propia ficha y se avisa si las dos difieren.

Uso:
    python modules/udc_records.py --parts carpeta   (normalmente lo llama udc_main_tree_fusion.py)
Solo biblioteca estándar.
"""
import argparse
import datetime as dt
import glob
import gzip
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from udc_merge import GENERATED_DIR, read_txt, natural_key  # noqa: E402

# Etiquetas de las notas en la interfaz del sitio. Las de español son supuestas: si el sitio usa otras, salen en
# "No reconocido" del informe y se añaden aquí.
NOTE_LABELS = {"Nota de alcance": "scopeNote", "Nota de aplicación": "applicationNote",
               "Nota informativa": "informationNote", "Nota de información": "informationNote",
               "Scope Note": "scopeNote", "Application Note": "applicationNote",
               "Information Note": "informationNote"}
VOID = {"img", "br", "hr", "input", "meta", "link", "wbr", "col", "area", "source"}
SEP = "    "  # separador notación/texto de skos:example


# ---------------------------------------------------------------- mini DOM
class El:
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.kids = tag, dict(attrs), []

    def cls(self):
        return (self.attrs.get("class") or "").split()

    def els(self):
        return [k for k in self.kids if isinstance(k, El)]

    def iter(self):
        for k in self.kids:
            if isinstance(k, El):
                yield k
                yield from k.iter()

    def find(self, pred):
        return next((e for e in self.iter() if pred(e)), None)


class DomBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = El("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        el = El(tag, attrs)
        self.stack[-1].kids.append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(El(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].kids.append(data)


def parse_html(h):
    b = DomBuilder()
    b.feed(h)
    b.close()
    return b.root


def raw_text(node):
    if isinstance(node, str):
        return node
    return "".join(raw_text(k) for k in node.kids)


# UDC Online muestra las notaciones con guiones no separables (U+2011) y similares; el árbol usa '-'.
DASHES = str.maketrans({"‐": "-", "‑": "-", "−": "-"})


def clean(s):
    return " ".join(s.translate(DASHES).split())


def text(node):
    return clean(raw_text(node))


def has_title(el, title):
    return el.find(lambda e: e.attrs.get("title") == title) is not None


# ---------------------------------------------------------------- una fila (clase)
def parse_row(tr, unknown):
    """tr de la tabla principal -> (notación, dict de campos) o None si no es una fila de clase."""
    tds = [e for e in tr.els() if e.tag == "td"]
    nt_td = next((t for t in tds if "table-notation" in t.cls()), None)
    note_td = next((t for t in tds if "notefield" in t.cls()), None)
    if nt_td is None or note_td is None:
        return None
    a = nt_td.find(lambda e: e.tag == "a" and "notation-main" in e.cls())
    if a is None:
        return None
    nt = text(a)
    rec = {"bold": a.find(lambda e: e.tag == "strong") is not None}
    # tipo de auxiliar según la celda de la notación: aux-cell = auxiliar común, spec-aux-cell = especial
    cell = set(nt_td.cls()) - {"table-notation"}
    if "spec-aux-cell" in cell:
        rec["auxType"] = "special"
    elif "aux-cell" in cell:
        rec["auxType"] = "common"
    for c in cell - {"spec-aux-cell", "aux-cell"}:
        unknown.append((nt, f"clase de celda desconocida: {c!r}"))
    caption, including = [], []
    detail = None
    for k in note_td.els():
        if k.tag == "span" and not (k.attrs.get("id") or "").startswith("rs") and not caption:
            # etiqueta [+ icono Including + span con el texto]
            seen_incl = False
            for c in k.kids:
                if isinstance(c, El) and c.tag == "img":
                    if c.attrs.get("title") == "Including" or "incl_square" in (c.attrs.get("src") or ""):
                        seen_incl = True
                    else:
                        unknown.append((nt, f"icono en la etiqueta: {c.attrs.get('title')!r}"))
                elif seen_incl:
                    t = text(c)
                    if t:
                        including.append(t)
                else:
                    caption.append(raw_text(c))
            caption = [clean("".join(caption))]
        elif k.tag == "div" and re.fullmatch(r"rd\d+", k.attrs.get("id") or ""):
            detail = k
    rec["caption"] = caption[0] if caption else ""
    if including:
        rec["includingNote"] = including
    if detail is not None:
        parse_detail(nt, detail, rec, unknown)
    return nt, rec


def table_rows(table):
    return [tr for tr in table.iter() if tr.tag == "tr"]


def parse_box_row(nt, tr, rec, unknown):
    tds = [e for e in tr.els() if e.tag == "td"]
    if len(tds) < 2:
        unknown.append((nt, f"fila de recuadro con {len(tds)} celdas: {text(tr)[:80]!r}"))
        return
    code_td, desc_td = tds[0], tds[1]
    label = text(desc_td)
    # por el símbolo (◇ ejemplo, ⇨ véase también), que no cambia con el idioma de la interfaz
    if has_title(code_td, "Example of combination") or "◇" in raw_text(code_td):
        code = text(code_td).lstrip("◇").strip()
        rec.setdefault("example", []).append(f"{code}{SEP}{label}" if label else code)
    elif has_title(code_td, "See also") or "⇨" in raw_text(code_td):
        a = code_td.find(lambda e: e.tag == "a")
        code = text(a) if a is not None else text(code_td).lstrip("⇨").strip()
        rec.setdefault("related", []).append(code)
        rec.setdefault("_related_labels", {})[code] = label
    else:
        titles = [e.attrs.get("title") for e in code_td.iter() if e.attrs.get("title")]
        unknown.append((nt, f"fila de recuadro desconocida {titles}: {text(tr)[:80]!r}"))


def parse_detail(nt, div, rec, unknown):
    last_note = None
    for k in div.kids:
        if isinstance(k, str):
            if k.strip():
                unknown.append((nt, f"texto suelto en el panel: {k.strip()[:80]!r}"))
            continue
        if k.tag == "p":
            t = text(k)
            if not t:
                continue
            first = next((c for c in k.kids if not (isinstance(c, str) and not c.strip())), None)
            if isinstance(first, El) and first.tag == "strong":
                lab = text(first).rstrip(":").strip()
                field = NOTE_LABELS.get(lab)
                if field is None:
                    unknown.append((nt, f"nota desconocida {lab!r}"))
                    continue
                body = "".join(raw_text(c) for c in k.kids if c is not first)
                body = clean(body)
                if body:
                    rec.setdefault(field, []).append(body)
                    last_note = field
            elif last_note:  # párrafo que continúa la nota anterior
                rec[last_note].append(t)
                unknown.append((nt, f"párrafo sin etiqueta añadido a {last_note}: {t[:60]!r}"))
            else:
                unknown.append((nt, f"párrafo sin etiqueta: {t[:80]!r}"))
        elif k.tag in ("div", "table"):
            rows = table_rows(k)
            if not rows and text(k):
                unknown.append((nt, f"<{k.tag} class={k.cls()}> sin filas: {text(k)[:80]!r}"))
            for tr in rows:
                parse_box_row(nt, tr, rec, unknown)
        else:
            unknown.append((nt, f"elemento <{k.tag}> en el panel: {text(k)[:80]!r}"))


# ---------------------------------------------------------------- todo
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", required=True, help="carpeta con udc_records_part_*.jsonl.gz")
    ap.add_argument("--txt", default=str(GENERATED_DIR / "UDC_hierarchy.txt"), help="árbol (para validar notaciones)")
    ap.add_argument("--out", default=str(GENERATED_DIR / "udc_records.json"))
    ap.add_argument("--report", default=None, help="por defecto udc_records_report.txt junto a --out")
    ap.add_argument("--lang", default="en", help="idioma de la interfaz de UDC Online en la descarga (en, es...)")
    ap.add_argument("--note-labels", default="",
                    help='JSON {"texto de la interfaz": campo}, p. ej. {"Nota de alcance": "scopeNote"} (lo pasa la fusión)')
    args = ap.parse_args(argv)
    if args.note_labels:   # nombres de las notas en el idioma de la descarga (del formulario de búsqueda del sitio)
        NOTE_LABELS.update(json.loads(args.note_labels))
    report_path = args.report or os.path.join(os.path.dirname(os.path.abspath(args.out)), "udc_records_report.txt")

    files = sorted(glob.glob(os.path.join(args.parts, "udc_records_part_*.jsonl.gz")))
    if not files:
        sys.exit(f"No hay udc_records_part_*.jsonl.gz en {args.parts}")
    entries = read_txt(args.txt)
    tree = {key: label for key, nt, label, parent, order in entries if nt is not None}

    own, other = {}, {}          # notación -> campos (de su propia ficha / de la ficha del padre)
    unknown, errors, no_own_row, diffs = [], [], [], []
    records = 0
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                records += 1
                if "error" in r:
                    errors.append((r["n"], r["error"]))
                    continue
                found = False
                for tr in parse_html(r["h"]).iter():
                    if tr.tag != "tr":
                        continue
                    got = parse_row(tr, unknown)
                    if got is None:
                        continue
                    nt, rec = got
                    if nt == r["n"] and rec["bold"]:
                        own[nt] = rec
                        found = True
                    else:
                        other.setdefault(nt, rec)
                if not found and "#p" not in r["n"]:   # página 2+ de una ficha paginada: sin fila en negrita
                    no_own_row.append(r["n"])

    def content(rec):
        return {k: v for k, v in rec.items() if k not in ("bold", "caption", "_related_labels")}

    data = {}
    for nt in set(own) | set(other):
        rec = own.get(nt) or other[nt]
        if nt in own and nt in other and content(own[nt]) != content(other[nt]):
            diffs.append(nt)
        data[nt] = rec

    not_in_tree = sorted((nt for nt in data if nt not in tree), key=natural_key)
    no_record = sorted((nt for nt in tree if nt not in data), key=natural_key)
    caption_diff = [(nt, tree[nt], data[nt]["caption"]) for nt in tree
                    if nt in data and data[nt]["caption"] and data[nt]["caption"] != tree[nt]]
    dangling = []
    order = {key: i for i, (key, *_rest) in enumerate(entries)}
    out = {"_source": {"generated": dt.datetime.now().replace(microsecond=0).isoformat(),
                       "from": "UDC Online records (udc_records.py)", "parts": len(files)}}
    counts = {f: 0 for f in ("scopeNote", "applicationNote", "informationNote", "includingNote",
                             "example", "related", "auxType")}
    for nt in sorted((n for n in data if n in tree), key=lambda n: order[n]):
        rec = data[nt]
        spec = {}
        for field in ("scopeNote", "applicationNote", "informationNote", "includingNote", "example"):
            if rec.get(field):
                spec[field] = {args.lang: list(dict.fromkeys(rec[field]))}
        if rec.get("auxType"):
            spec["auxType"] = rec["auxType"]
        rel = []
        for code in dict.fromkeys(rec.get("related", [])):
            if code in tree:
                rel.append(code)
            else:
                dangling.append((nt, code, rec.get("_related_labels", {}).get(code, "")))
        if rel:
            spec["related"] = rel
        for k in spec:
            counts[k] += 1
        if spec:
            out[nt] = spec

    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    n_ex = sum(len(v["example"][args.lang]) for k, v in out.items() if not k.startswith("_") and "example" in v)
    lines = [f"udc_records report - {dt.datetime.now():%Y-%m-%d %H:%M}",
             f"Partes: {len(files)} ({args.parts})", f"Fichas leídas: {records}  con error: {len(errors)}",
             f"Clases encontradas: {len(data)} (de su propia ficha: {len(own)})",
             f"Clases del árbol sin ficha: {len(no_record)}",
             f"Notaciones de las fichas que no están en el árbol (descartadas): {len(not_in_tree)}",
             f"Fichas sin su fila en negrita: {len(no_own_row)}",
             f"Clases cuya fila difiere entre su ficha y la del padre: {len(diffs)}",
             f"Etiquetas distintas a las del árbol (solo aviso): {len(caption_diff)}",
             f"Véase también hacia clases que no están en el árbol (descartados): {len(dangling)}",
             f"Elementos no reconocidos: {len(unknown)}", "",
             f"Clases con datos en udc_records.json: {len(out) - 1}"]
    lines += [f"  {k}: {v}" for k, v in counts.items()]
    lines.append(f"  ejemplos de combinación en total: {n_ex}")

    def section(title, items, fmt=str, limit=200):
        lines.extend(["", f"== {title} ({len(items)})"])
        lines.extend(fmt(x) for x in items[:limit])
        if len(items) > limit:
            lines.append(f"... y {len(items) - limit} más")

    section("No reconocido", unknown, lambda t: f"{t[0]}: {t[1]}")
    section("Fichas con error", errors, lambda t: f"{t[0]}: {t[1]}")
    section("Clases del árbol sin ficha", no_record)
    section("Notaciones no presentes en el árbol", not_in_tree)
    section("Fichas sin su fila en negrita", no_own_row)
    section("Fila distinta en la ficha del padre", diffs)
    section("Véase también descartados", dangling, lambda t: f"{t[0]} -> {t[1]}  {t[2]}")
    section("Etiquetas distintas (árbol | ficha)", caption_diff, lambda t: f"{t[0]}: {t[1]!r} | {t[2]!r}")
    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:22]))
    print(f"\nEscrito: {args.out}\nInforme: {report_path}")


if __name__ == "__main__":
    main()
