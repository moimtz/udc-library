#!/usr/bin/env python3
"""Fusiona un snapshot de UDC Online (udc_tree_download.js) con el RDF madre (udcs-skos.rdf), en un solo paso.

    python udc_main_tree_fusion.py ../udc_tree_download/snapshots/udc_snapshot_2026-11-23.json.gz

Qué hace, en orden:
  1. Jerarquía: el árbol del snapshot (orden y etiquetas del sitio) -> UDC_hierarchy.txt.
  2. Completa el árbol: las notaciones vigentes que el sitio muestra en sus fichas o en la búsqueda, pero no en su
     árbol (pasó con 903, 66.047.4/.5, Guadeloupe...), se colocan solas por su notación:
       - padre = el rango más ajustado que la contiene (903.01 -> 903.01/.08; 598.141 -> 598.131/.143);
         si no hay rango, el prefijo más largo que exista (903.36 -> 903.3);
       - posición entre hermanos = orden en que el sitio lista las filas, si alguna página lista al padre y luego
         a la clase; si no (el sitio la muestra fuera de lugar), orden de notación de la UDC (-, .0, `, .1-.9).
     Las que no tienen ficha (sin etiqueta) no se añaden y se avisan. Excepciones: tree_decisions.json.
  3. Fichas -> udc_records.json (udc_records.py); canceladas -> udc_cancelled.json (udc_cancelled.py).
  4. Fusión con el RDF madre (udc_merge.py, modo structure, con extra_notes.json al final). Antes de escribirlo
     guarda la versión anterior en udc_to_rdf_conversion/udcs-skos.rdf.bak (se reemplaza en cada fusión real).
Salidas: el RDF en biblioteca_udc/server/udc_data/ (lo leen el servidor y el PoC); el árbol .txt, los JSON y los
informes, en udc_to_rdf_conversion/generated/ (intermedios: el RDF ya contiene su información).
  5. fusion_report.txt: resumen, añadidas, no añadidas y avisos (más los informes de cada paso).

Idioma: se detecta en el snapshot (subdominio del sitio, p. ej. es.udc-hub.com, o nombres de los campos); --lang
lo fija a mano y, si no coincide con el detectado, la fusión se detiene. Con una descarga en español el árbol solo aporta etiquetas @es
(no cambia la jerarquía), las notas van como @es, no se tocan las canceladas y los archivos llevan sufijo
(UDC_hierarchy_es.txt, udc_records_es.json...), para no pisar los de inglés.

Opciones: --rdf, --workdir (dónde se escriben UDC_hierarchy.txt, los JSON y los informes; por defecto generated/),
--prune (borra del RDF las clases que ya no están en el sitio; solo con un snapshot completo), --dry-run (todo
menos escribir el RDF). Solo biblioteca estándar.
"""
import argparse
import datetime as dt
import gzip
import json
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "modules"))   # udc_merge, udc_records, udc_cancelled
import udc_cancelled  # noqa: E402
import udc_merge  # noqa: E402
import udc_records  # noqa: E402
from udc_merge import COMMA_NOTATIONS, GENERATED_DIR, HEADING_RE, SERVER_UDC_DIR, natural_key, parse_line  # noqa: E402
from udc_records import clean, parse_html, parse_row  # noqa: E402


# ---------------------------------------------------------------- notaciones
def wrapper(nt):
    """Tipo de envoltura: '(' para (4), '"' para "19", '' para el resto."""
    if nt.startswith("(") and nt.endswith(")"):
        return "("
    if nt.startswith('"') and nt.endswith('"') and len(nt) > 1:
        return '"'
    return ""


def core(nt):
    return nt[1:-1] if wrapper(nt) else nt


def is_range(nt):
    return "/" in core(nt) and nt not in COMMA_NOTATIONS


def range_bounds(nt):
    """'598.131/.143' -> ('598.131', '598.143'); '54-1/-7' -> ('54-1', '54-7'); '(1/9)' -> ('1', '9')."""
    a, b = core(nt).split("/", 1)
    end = a[:len(a) - len(b)] + b if 0 < len(b) < len(a) else b
    return a, end


def range_contains(r, nt):
    """¿El rango r contiene la notación nt (o el rango nt entero)?"""
    if wrapper(r) != wrapper(nt) or r == nt:
        return False
    s, e = range_bounds(r)
    pts = list(range_bounds(nt)) if is_range(nt) else [core(nt)]
    for x in pts:
        if len(x) < len(s) or not (s <= x[:len(s)] and x[:len(e)] <= e):
            return False
    return True


def prefix_parent(nt, known):
    """Prefijo más largo de nt (misma envoltura, sin rangos) que esté en known."""
    w, c = wrapper(nt), core(nt)
    if is_range(nt):
        c = range_bounds(nt)[0]
    for k in range(len(c) - 1, 0, -1):
        p = c[:k]
        cand = f"({p})" if w == "(" else (f'"{p}"' if w == '"' else p)
        if cand in known and not is_range(cand):
            return cand
    return None


def udc_sort_key(nt):
    """Orden de notación de la UDC entre hermanos: auxiliares especiales -x y .0x, luego `x, luego .1-.9."""
    c = core(nt).replace(".0", "\x01").replace("`", "\x02").replace("'", "\x02").replace("-", "\x00")
    return natural_key(c)


# ---------------------------------------------------------------- árbol
class TreeNode:
    __slots__ = ("key", "nt", "line", "parent", "children", "added")

    def __init__(self, key, nt, line, parent=None, added=False):
        self.key, self.nt, self.line, self.parent = key, nt, line, parent
        self.children, self.added = [], added


def build_tree(snapshot_tree, rep):
    """Snapshot -> {clave: TreeNode} (clave = notación, o 'heading-N'); raíces en orden."""
    by_site_key, nodes, roots = {}, {}, []
    for raw in snapshot_tree:   # viene en orden de lectura (padres antes que hijos)
        title = clean(raw["t"])
        if not title:
            continue
        try:
            key, nt, label = parse_line(title)
        except udc_merge.TxtError as e:
            rep["tree_problems"].append(f"{title!r}: {e}")
            continue
        if key in nodes:
            rep["tree_duplicates"].append(title)
            by_site_key[raw["k"]] = nodes[key]
            continue
        parent = by_site_key.get(raw["p"]) if raw.get("p") is not None else None
        n = TreeNode(key, nt, title, parent.key if parent else None)
        nodes[key] = n
        by_site_key[raw["k"]] = n
        (parent.children if parent else roots).append(key)
    return nodes, roots


def tree_to_txt(nodes, roots):
    lines = []

    def walk(keys, depth):
        for k in keys:
            n = nodes[k]
            lines.append("    " * depth + n.line)
            walk(n.children, depth + 1)
    walk(roots, 0)
    return "\n".join(lines)   # sin salto final, como el UDC_hierarchy.txt original


def depth_of(nodes, key):
    d, seen = 0, set()
    while key is not None and key not in seen:
        seen.add(key)
        key = nodes[key].parent if key in nodes else None
        d += 1
    return d


def is_under(nodes, key, ancestor):
    seen = set()
    while key is not None and key not in seen:
        if key == ancestor:
            return True
        seen.add(key)
        key = nodes[key].parent if key in nodes else None
    return False


def site_position(pages, parent, nt):
    """(página, posición) de nt en la primera página del sitio que lista al padre y DESPUÉS a nt; si no, None."""
    for i, rows in enumerate(pages):
        pos = rows.get(nt)
        if pos is not None and rows.get(parent, pos) < pos:
            return i, pos
    return None


def place_missing(nodes, roots, candidates, decisions, rep, pages):
    """Coloca en el árbol las notaciones de candidates {nt: etiqueta}. pages: [{notación: posición}] por página."""
    excluded = set(decisions.get("exclude", []))
    forced = decisions.get("parent", {})
    todo = {nt: v for nt, v in candidates.items() if nt not in excluded}
    rep["excluded"] = sorted(set(candidates) & excluded, key=natural_key)
    known = set(nodes) | set(todo)
    ranges = [k for k in known if is_range(k)]

    def choose_parent(nt):
        if nt in forced:
            return forced[nt], "tree_decisions.json"
        p0 = prefix_parent(nt, known)
        inside = [r for r in ranges if range_contains(r, nt)]
        # rangos del árbol: deben colgar del prefijo; los nuevos se aceptan si están bajo el mismo prefijo
        inside = [r for r in inside if p0 is None or (r in nodes and is_under(nodes, r, p0))
                  or (r in todo and prefix_parent(r, known) == p0)]
        if inside:
            # el más ajustado: no contiene a ningún otro candidato; luego el más profundo; luego el que acaba antes
            tight = [r for r in inside if not any(o != r and range_contains(r, o) for o in inside)] or inside
            tight.sort(key=lambda r: (-depth_of(nodes, r) if r in nodes else 0, range_bounds(r)[1]))
            return tight[0], "rango"
        if p0:
            return p0, "prefijo"
        return None, "sin padre"

    parents = {nt: choose_parent(nt) for nt in todo}
    placed = set()
    progress = True
    while progress:   # padres antes que hijos (un nuevo puede colgar de otro nuevo)
        progress = False
        for nt in sorted(todo, key=lambda x: (len(core(x)), natural_key(x))):
            if nt in placed:
                continue
            par, why = parents[nt]
            if par is None:
                continue
            if par not in nodes:
                if par in todo and par not in placed:
                    continue
                if par not in todo:
                    rep["unplaced"].append((nt, f"padre forzado {par} no existe"))
                    placed.add(nt)
                    continue
            label = todo[nt]
            nodes[nt] = TreeNode(nt, nt, f"{nt} {label}", par, added=True)
            sib = nodes[par].children
            where = site_position(pages, par, nt)
            pos = len(sib)
            for i, k in enumerate(sib):
                if where is not None and k in pages[where[0]]:
                    later = pages[where[0]][k] > where[1]          # orden del listado del sitio
                else:
                    later = udc_sort_key(k) > udc_sort_key(nt)     # orden de notación
                if later:
                    pos = i
                    break
            sib.insert(pos, nt)
            placed.add(nt)
            progress = True
            rep["added"].append((nt, label, par, why))
    for nt in todo:
        if nt not in placed:
            rep["unplaced"].append((nt, parents[nt][1]))


# ---------------------------------------------------------------- idioma
EN_UI = {"scopenote": "Scope Note", "examples": "Examples", "including": "Including"}


def snapshot_lang(snap: dict) -> str | None:
    """Idioma de la interfaz con que se hizo la descarga. Lo dice el subdominio del sitio (es.udc-hub.com) o, si
    no lo hay, los nombres de los campos (ui). No se usa snap["lang"]: es el <html lang> de la página, y el sitio
    en español también declara "en"."""
    ui = snap.get("ui") or {}
    if ui and all(ui.get(k, "").rstrip(": ").strip() == v for k, v in EN_UI.items() if k in ui):
        return "en"
    host = str(snap.get("site") or "").lower().split(":")[0]
    first = host.split(".")[0] if host.count(".") >= 2 else ""
    if len(first) in (2, 3) and first.isalpha() and first != "www":
        return first
    return None


def choose_lang(snap: dict, given: str | None, ignore_site: bool) -> str:
    """Una descarga en español fusionada como inglés cambiaría la jerarquía y las etiquetas inglesas: el idioma se
    toma del snapshot y un --lang que no coincide detiene la fusión."""
    found = snapshot_lang(snap)
    if given is None:
        lang = found or "en"
        print(f"Idioma de la descarga: {lang}" + (" (detectado en el snapshot)" if found else
                                                  " (no se pudo detectar; usa --lang si no es inglés)"))
        return lang
    if found and given != found and not ignore_site:
        sys.exit(f"El snapshot es de {snap.get('site')} (idioma «{found}»), pero se pidió --lang {given}. "
                 f"Quita --lang, o añade --ignore-site-lang si estás seguro.")
    return given


# ---------------------------------------------------------------- fusión
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshot", type=Path, help="udc_snapshot_AAAA-MM-DD.json.gz de udc_tree_download.js")
    ap.add_argument("--rdf", type=Path, default=SERVER_UDC_DIR / "udcs-skos.rdf", help="RDF madre (se sobrescribe)")
    ap.add_argument("--backup", type=Path, default=HERE / "udcs-skos.rdf.bak",
                    help="copia del RDF anterior, hecha justo antes de escribirlo")
    ap.add_argument("--workdir", type=Path, default=GENERATED_DIR,
                    help="dónde escribir UDC_hierarchy.txt, udc_records.json, udc_cancelled.json e informes")
    ap.add_argument("--decisions", type=Path, default=HERE / "tree_decisions.json",
                    help="excepciones a la colocación automática")
    ap.add_argument("--lang", help="idioma de la interfaz en la descarga (por defecto, el que se detecta en el snapshot)")
    ap.add_argument("--ignore-site-lang", action="store_true",
                    help="usar --lang aunque no coincida con el idioma detectado en el snapshot")
    ap.add_argument("--prune", action="store_true", help="borra del RDF las clases que ya no están en el sitio")
    ap.add_argument("--dry-run", action="store_true", help="todo menos escribir el RDF")
    args = ap.parse_args(argv)
    work = args.workdir
    work.mkdir(parents=True, exist_ok=True)
    print(f"Leyendo {args.snapshot} …")
    with gzip.open(args.snapshot, "rt", encoding="utf-8") as fh:
        snap = json.load(fh)
    if not str(snap.get("format", "")).startswith("udc-snapshot/"):
        sys.exit("No es un snapshot de udc_tree_download.js (falta 'format').")
    lang = choose_lang(snap, args.lang, args.ignore_site_lang)
    sfx = "" if lang == "en" else f"_{lang}"   # salidas de otro idioma, aparte
    if lang != "en" and args.prune:
        sys.exit("--prune solo tiene sentido con la descarga en inglés (la que define la jerarquía).")
    stats = snap.get("stats", {})
    rep = {"tree_problems": [], "tree_duplicates": [], "added": [], "unplaced": [], "excluded": []}
    if stats.get("partial"):
        print("AVISO: snapshot PARCIAL (exportado a mitad de descarga).")

    # 1. jerarquía del sitio
    nodes, roots = build_tree(snap["tree"], rep)
    site_nodes = len(nodes)

    # filas de las fichas: etiqueta de cada notación vigente y orden de cada página del sitio
    rows, pages = {}, []
    for rec in snap["records"]:
        page = {}
        for tr in parse_html(rec["h"]).iter():
            if tr.tag != "tr":
                continue
            got = parse_row(tr, [])
            if got:
                page.setdefault(got[0], len(page))
                rows.setdefault(got[0], got[1]["caption"])
        pages.append(page)
    live = set()
    for line in snap["search"]:
        if "live" in line:
            live.update(clean(x) for x in line["live"])

    # 2. completar el árbol
    decisions = json.loads(args.decisions.read_text(encoding="utf-8")) if args.decisions.exists() else {}
    missing = {}
    no_data = []
    for nt in (set(rows) | live) - set(nodes):
        if HEADING_RE.match(nt):
            continue
        if rows.get(nt):
            missing[nt] = rows[nt]
        else:
            no_data.append(nt)
    place_missing(nodes, roots, missing, decisions, rep, pages)
    txt = work / f"UDC_hierarchy{sfx}.txt"
    txt.write_text(tree_to_txt(nodes, roots), encoding="utf-8", newline="\n")   # LF, como el original

    # 3. fichas y canceladas (con los scripts de siempre, sobre archivos temporales)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with gzip.open(tmp / "udc_records_part_0001.jsonl.gz", "wt", encoding="utf-8") as fh:
            for rec in snap["records"]:
                n = unquote(rec["q"]) + (f"#p{rec['pg']}" if rec.get("pg") else "")
                fh.write(json.dumps({"n": n, "h": rec["h"]}, ensure_ascii=False) + "\n")
        with gzip.open(tmp / "udc_cancelled_part_01.jsonl.gz", "wt", encoding="utf-8") as fh:
            for line in snap["search"]:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
        print("\n== Fichas")
        ui = snap.get("ui") or {}   # nombres de los campos en el idioma de la interfaz (formulario de búsqueda)
        note_labels = {ui[k].rstrip(": ").strip(): f for k, f in (("scopenote", "scopeNote"), ("appnote", "applicationNote"),
                                                                  ("infonote", "informationNote")) if ui.get(k)}
        udc_records.main(["--parts", str(tmp), "--txt", str(txt), "--lang", lang,
                          "--note-labels", json.dumps(note_labels, ensure_ascii=False),
                          "--out", str(work / f"udc_records{sfx}.json"),
                          "--report", str(work / f"udc_records_report{sfx}.txt")])
        if lang == "en":   # las canceladas guardan una sola etiqueta (inglés): solo desde la descarga en inglés
            print("\n== Canceladas")
            udc_cancelled.main(["--parts", str(tmp), "--txt", str(txt), "--out", str(work / "udc_cancelled.json")])

    # 4. fusión con el RDF madre
    print("\n== Fusión con el RDF")
    if not args.rdf.exists():
        sys.exit(f"No existe el RDF madre {args.rdf}")
    rdf_in = args.rdf
    if not args.dry_run:
        # respaldo de la versión anterior; la fusión lee del respaldo y escribe el RDF del servidor
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.rdf, args.backup)
        rdf_in = args.backup
    margv = ["--rdf", str(rdf_in), "--out", str(args.rdf), "--txt", str(txt), "--lang", lang,
             "--records", str(work / f"udc_records{sfx}.json"), "--report", str(work / f"conversion_report{sfx}.txt")]
    if lang == "en":
        margv += ["--cancelled", str(work / "udc_cancelled.json")]   # con otro idioma se conservan las del RDF
    if (HERE / "extra_notes.json").exists():
        margv += ["--notes", str(HERE / "extra_notes.json")]
    if args.prune:
        margv.append("--prune")
    if args.dry_run:
        margv.append("--dry-run")
    udc_merge.main(margv)

    # 5. informe
    lines = [f"Fusión de snapshot - {dt.datetime.now():%Y-%m-%d %H:%M}",
             f"Snapshot: {args.snapshot.name}  creado {snap.get('created')}  por {snap.get('tool')}"
             + ("  (PARCIAL)" if stats.get("partial") else ""),
             f"RDF: {args.rdf}" + ("  (dry-run: no se escribió)" if args.dry_run else f"  (versión anterior en {args.backup})"),
             f"Errores de descarga registrados en el snapshot: {len(snap.get('errors', []))}",
             f"Ficha de prueba con ejemplos ◇ encontrada: {stats.get('checkExample')}",
             "",
             f"Árbol del sitio: {site_nodes} nodos; añadidos por notación: {len(rep['added'])}; "
             f"total: {len(nodes)}",
             f"Notaciones vigentes sin ficha (no añadidas): {len(no_data)}",
             f"Sin padre posible (no añadidas): {len(rep['unplaced'])}",
             f"Excluidas por tree_decisions.json: {len(rep['excluded'])}",
             f"Títulos repetidos en el árbol del sitio (se dejó el primero): {len(rep['tree_duplicates'])}",
             f"Títulos que no se pudieron leer: {len(rep['tree_problems'])}",
             "",
             "Informes de cada paso: udc_records_report.txt, udc_cancelled_report.txt, conversion_report.txt."]

    def section(title, items, fmt=str):
        if items:
            lines.extend(["", f"== {title} ({len(items)})"] + [fmt(x) for x in items])

    section("Añadidas al árbol (notación, etiqueta, padre, criterio)", rep["added"],
            lambda t: f"{t[0]}  {t[1]}  ->  {t[2]}  [{t[3]}]")
    section("Vigentes sin ficha (sin etiqueta: no se añaden)", sorted(no_data, key=natural_key))
    section("Sin padre posible", rep["unplaced"], lambda t: f"{t[0]}: {t[1]}")
    section("Excluidas por tree_decisions.json", rep["excluded"])
    section("Títulos repetidos", rep["tree_duplicates"])
    section("Títulos ilegibles", rep["tree_problems"])
    section("Errores de descarga", snap.get("errors", []), lambda e: json.dumps(e, ensure_ascii=False))
    (work / f"fusion_report{sfx}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n" + "\n".join(lines[:13]))
    print(f"\nInforme: {work / f'fusion_report{sfx}.txt'}")


if __name__ == "__main__":
    main()
