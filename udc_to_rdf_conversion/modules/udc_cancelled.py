#!/usr/bin/env python3
"""Interpreta las clases canceladas descargadas de UDC Online y genera udc_cancelled.json.

Entrada: udc_cancelled_part_NN.jsonl.gz (las escribe udc_main_tree_fusion.py a partir del snapshot).
Cada cancelada viene como la celda de la búsqueda:
    x [2011, E&C33] Sauropsida (fossil). Synapsida (fossil)
    → 56; 598                       (o "→ No replacement")
Salida (la aplica udc_merge.py con --cancelled):
    {"568": [{"year": 2011, "ec": "E&C33", "label": "...", "replacedBy": ["56", "598"], "note": ""}], ...}
y udc_cancelled_report.txt, que además compara las notaciones VIGENTES del sitio con el árbol.

Uso:
    python modules/udc_cancelled.py --parts carpeta   (normalmente lo llama udc_main_tree_fusion.py)
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
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from udc_merge import GENERATED_DIR, read_txt, natural_key  # noqa: E402
from udc_records import El, clean, parse_html, raw_text, text  # noqa: E402

HEADER = re.compile(r"^x \[(\d{4})(?:,\s*([^\]]+))?\]\s*(.*)$")   # el número de E&C a veces falta


def parse_cell(h):
    """html de la celda -> dict (year, ec, label, replacedBy, note) o None si no tiene el formato esperado."""
    root = parse_html(h)
    spans = [e for e in root.kids if isinstance(e, El) and e.tag == "span"]
    if not spans:
        return None
    # la etiqueta puede llevar, como en las clases vigentes, el icono "Including" seguido de su texto
    head, incl, seen = [], [], False
    for c in spans[0].kids:
        if isinstance(c, El) and c.tag == "img" and c.attrs.get("title") == "Including":
            seen = True
        else:
            (incl if seen else head).append(raw_text(c))
    m = HEADER.match(clean("".join(head)))
    if not m:
        return None
    rec = {"year": int(m.group(1)), "ec": clean(m.group(2) or "").replace(" ", ""), "label": m.group(3).strip(),
           "replacedBy": [], "note": ""}
    if clean("".join(incl)):
        rec["including"] = clean("".join(incl))
    rest = spans[1:]
    if rest:
        tail = rest[0]
        targets = [text(a) for a in tail.iter() if a.tag == "a"]
        rec["replacedBy"] = [t for t in dict.fromkeys(targets) if t]
        # lo que no son enlaces: separadores y avisos como "No replacement" o texto libre
        note = raw_text(tail)
        for t in targets:
            note = note.replace(t, " ", 1)
        note = clean(note.translate({ord("→"): " "}))
        note = re.sub(r"^[;,\s]+|[;,\s]+$", "", re.sub(r"(\s*[;,]\s*)+", "; ", note))
        rec["note"] = "" if re.fullmatch(r"[;,\s]*", note) else note
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--parts", required=True, help="carpeta con udc_cancelled_part_*.jsonl.gz")
    ap.add_argument("--txt", default=str(GENERATED_DIR / "UDC_hierarchy.txt"), help="árbol (para validar notaciones)")
    ap.add_argument("--out", default=str(GENERATED_DIR / "udc_cancelled.json"))
    ap.add_argument("--report", default=None, help="por defecto udc_cancelled_report.txt junto a --out")
    args = ap.parse_args(argv)
    report_path = args.report or os.path.join(os.path.dirname(os.path.abspath(args.out)), "udc_cancelled_report.txt")

    files = sorted(glob.glob(os.path.join(args.parts, "udc_cancelled_part_*.jsonl.gz")))   # 22+ = repeticiones
    if not files:
        sys.exit(f"No hay udc_cancelled_part_*.jsonl.gz en {args.parts}")
    tree = {key for key, nt, *_ in read_txt(args.txt) if nt is not None}

    data, live, checks, bad, diags = {}, set(), {}, [], []   # checks: el último de cada prefijo gana (repeticiones)
    rows = 0
    for f in files:
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                r = json.loads(line)
                if "diag" in r:
                    diags.append(r["diag"])
                elif "check" in r:
                    checks[r["check"]["prefix"]] = r["check"]
                elif "live" in r:
                    live.update(clean(n) for n in r["live"])
                else:
                    rows += 1
                    nt = clean(r["n"])
                    rec = parse_cell(r["h"])
                    if rec is None:
                        bad.append((nt, clean(re.sub(r"<[^>]+>", " ", r["h"]))[:160]))
                        continue
                    lst = data.setdefault(nt, [])
                    if not any(x["year"] == rec["year"] and x["label"] == rec["label"] for x in lst):
                        lst.append(rec)

    for lst in data.values():
        lst.sort(key=lambda x: x["year"])
    out = {"_source": {"generated": dt.datetime.now().replace(microsecond=0).isoformat(),
                       "from": "UDC Online, search with 'Include cancelled' (udc_cancelled.py)", "parts": len(files)}}
    for nt in sorted(data, key=natural_key):
        out[nt] = data[nt]
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    entries = [x for lst in data.values() for x in lst]
    targets = {t for x in entries for t in x["replacedBy"]}
    dangling = sorted((t for t in targets if t not in tree), key=natural_key)
    still_live = sorted((n for n in data if n in tree), key=natural_key)   # notación reutilizada o reintroducida
    years = {}
    for x in entries:
        years[x["year"]] = years.get(x["year"], 0) + 1
    problems = [c for c in checks.values() if c.get("problem") or
                (c.get("split") and c["total"] - c.get("sumChildren", 0) not in (0, 1)) or
                (not c.get("split") and c.get("rows") is not None and c["rows"] != c["total"])]
    live_not_tree = sorted(live - tree, key=natural_key)
    tree_not_live = sorted(tree - live, key=natural_key)

    lines = [f"udc_cancelled report - {dt.datetime.now():%Y-%m-%d %H:%M}",
             f"Partes: {len(files)} ({args.parts})",
             f"Filas canceladas leídas: {rows}  con formato no reconocido: {len(bad)}",
             f"Notaciones canceladas distintas: {len(data)}  (cancelaciones: {len(entries)})",
             f"  sin reemplazo: {sum(1 for x in entries if not x['replacedBy'])}"
             f"  con 1: {sum(1 for x in entries if len(x['replacedBy']) == 1)}"
             f"  con 2 o más: {sum(1 for x in entries if len(x['replacedBy']) > 1)}"
             f"  con nota: {sum(1 for x in entries if x['note'])}",
             "  por año: " + ", ".join(f"{y}={c}" for y, c in sorted(years.items())),
             f"Reemplazos que no son clases del árbol actual: {len(dangling)} (de {len(targets)})",
             f"Notaciones canceladas que hoy vuelven a existir en el árbol: {len(still_live)}",
             f"Prefijos con cuentas que no cuadran: {len(problems)}",
             "",
             f"Comparación con el árbol (notaciones vigentes vistas en la búsqueda: {len(live)}):",
             f"  vigentes en el sitio que no están en el árbol: {len(live_not_tree)}",
             f"  del árbol que no aparecieron como vigentes: {len(tree_not_live)}"]

    def section(title, items, fmt=str, limit=300):
        lines.extend(["", f"== {title} ({len(items)})"])
        lines.extend(fmt(x) for x in items[:limit])
        if len(items) > limit:
            lines.append(f"... y {len(items) - limit} más")

    section("Formato no reconocido", bad, lambda t: f"{t[0]}: {t[1]}")
    section("Prefijos con cuentas que no cuadran", problems, lambda c: json.dumps(c, ensure_ascii=False))
    section("Páginas incompletas (HTML de la tabla, para diagnosticar)", diags,
            lambda d: f"{d['prefix']} p{d['page']}: {d['rows']}/{d['expected']} filas\n    "
                      + re.sub(r"\s+", " ", d["html"])[:3000])
    section("Reemplazos fuera del árbol actual", dangling)
    section("Canceladas que hoy existen en el árbol", still_live,
            lambda n: f"{n}: {[(x['year'], x['label']) for x in data[n]]}")
    section("Vigentes en el sitio que no están en el árbol", live_not_tree)
    section("Del árbol que no aparecieron como vigentes", tree_not_live)
    section("Canceladas con nota", [(n, x) for n, lst in data.items() for x in lst if x["note"]],
            lambda t: f"{t[0]}: {t[1]['note']}")
    Path(report_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:14]))
    print(f"\nEscrito: {args.out}\nInforme: {report_path}")


if __name__ == "__main__":
    main()
