"""Fusiona un árbol UDC en texto (.txt con sangría) en un archivo SKOS RDF/XML.

Modo "structure" (por defecto con --lang en): el .txt define la jerarquía.
Crea nodos, actualiza padre, orden y etiqueta.
Modo "labels" (por defecto con cualquier otro idioma): solo añade etiquetas
en ese idioma a las notaciones que ya existen; no toca la jerarquía.

Ver README.md para el uso completo. Solo usa la biblioteca estándar.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote, unquote
from xml.sax.saxutils import escape, quoteattr

# ---------------------------------------------------------------- namespaces
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
DC = "http://purl.org/dc/elements/1.1/"
DCT = "http://purl.org/dc/terms/"
FOAF = "http://xmlns.com/foaf/0.1/"
OWL = "http://www.w3.org/2002/07/owl#"
UDC = "http://udcdata.info/udc-schema#"   # applicationNote, includingNote
UDCX = "urn:udc:ext#"                     # propiedades locales: order, nodeType
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
NOTATION_DT = "http://udcdata.info/UDCnotation"

PREFIXES = {"rdf": RDF, "rdfs": RDFS, "skos": SKOS, "dc": DC, "dct": DCT,
            "foaf": FOAF, "owl": OWL, "udc": UDC, "udcx": UDCX}

URI_PREFIX = "urn:udc:"
SCHEME_URI = "urn:udc:scheme"
OLD_SCHEME_URI = "http://udcdata.info/udc-schema"

# Notaciones que contienen ", " y no se pueden separar por el primer espacio.
COMMA_NOTATIONS = ["-1/-9,.01/.09, `0/`9", ":, ::, []", "+, /", "*, A/Z"]

HEADING_RE = re.compile(r"^-+$")  # encabezados '-', '--', '---', '----'


# ---------------------------------------------------------------- modelo
class Node:
    __slots__ = ("key", "notation", "labels", "alt", "hidden", "scope", "app", "including",
                 "examples", "related", "parent", "order", "node_type")

    def __init__(self, key, notation):
        self.key = key              # notación, o 'heading-N' para encabezados
        self.notation = notation    # None en encabezados
        self.labels = {}            # lang -> str
        self.alt = {}               # lang -> [str]
        self.hidden = {}            # lang -> [str]
        self.scope = {}             # lang -> [str]  skos:scopeNote
        self.app = {}               # lang -> [str]  udc:applicationNote
        self.including = {}         # lang -> [str]  udc:includingNote ("Including ...")
        self.examples = {}          # lang -> [str]  skos:example
        self.related = []           # claves
        self.parent = None          # clave del padre
        self.order = None           # posición entre hermanos (int) o None
        self.node_type = None       # 'heading', 'info' o None


def key_to_uri(key):
    return URI_PREFIX + quote(key, safe="")


def heading_key(dashes):
    return f"heading-{len(dashes)}"


def natural_key(s):
    return [(0, int(t), "") if t.isdigit() else (1, 0, t) for t in re.split(r"(\d+)", s or "")]


def add_unique(d, lang, text):
    lst = d.setdefault(lang, [])
    if text not in lst:
        lst.append(text)


# ---------------------------------------------------------------- lectura RDF
def read_rdf(path, keep_langs=None):
    """Devuelve (nodes, scheme_meta, stats). keep_langs=None conserva todos los idiomas."""
    root = ET.parse(path).getroot()
    raw = {}           # uri -> dict de listas
    scheme_meta = []   # (tag, attrs, text) del ConceptScheme
    ignored = {}
    dropped_lang = 0

    def lang_ok(lang):
        return keep_langs is None or not lang or lang in keep_langs

    for el in root:
        about = el.get(f"{{{RDF}}}about")
        if about is None:
            continue
        is_scheme = (el.tag in (f"{{{OWL}}}Ontology", f"{{{SKOS}}}ConceptScheme")
                     or about in (SCHEME_URI, OLD_SCHEME_URI))
        if is_scheme:
            for ch in el:
                if ch.tag in (f"{{{SKOS}}}hasTopConcept", f"{{{DCT}}}modified", f"{{{RDF}}}type"):
                    continue
                lang = ch.get(XML_LANG)
                if not lang_ok(lang):
                    continue
                text = (ch.text or "").strip()
                res = ch.get(f"{{{RDF}}}resource")
                if not text and res is None:
                    continue
                scheme_meta.append((ch.tag, lang, res, text))
            continue
        if el.tag not in (f"{{{SKOS}}}Concept", f"{{{RDF}}}Description"):
            continue  # rdf:Property, etc.
        r = raw.setdefault(about, {"lits": [], "broader": [], "related": [], "notation": None,
                                   "order": None, "type": None, "concept": False})
        if el.tag == f"{{{SKOS}}}Concept":
            r["concept"] = True
        for ch in el:
            tag = ch.tag
            res = ch.get(f"{{{RDF}}}resource")
            text = (ch.text or "").strip()
            lang = ch.get(XML_LANG) or ""
            if tag == f"{{{SKOS}}}notation":
                r["notation"] = text
            elif tag == f"{{{SKOS}}}broader":
                r["broader"].append(res)
            elif tag == f"{{{SKOS}}}related":
                r["related"].append(res)
            elif tag == f"{{{UDCX}}}order":
                r["order"] = int(text)
            elif tag == f"{{{UDCX}}}nodeType":
                r["type"] = text
            elif tag in (f"{{{SKOS}}}narrower", f"{{{SKOS}}}inScheme", f"{{{SKOS}}}topConceptOf"):
                pass  # se recalculan al escribir
            elif tag in (f"{{{SKOS}}}prefLabel", f"{{{SKOS}}}altLabel", f"{{{SKOS}}}hiddenLabel",
                         f"{{{SKOS}}}scopeNote", f"{{{SKOS}}}note", f"{{{UDC}}}applicationNote",
                         f"{{{UDC}}}includingNote", f"{{{SKOS}}}example"):
                if not text:
                    continue
                if not lang_ok(lang):
                    dropped_lang += 1
                    continue
                r["lits"].append((tag, lang or "en", text))
            else:
                ignored[tag] = ignored.get(tag, 0) + 1

    # uri -> clave
    uri_key = {}
    for uri, r in raw.items():
        if not r["concept"]:
            continue
        nt = r["notation"]
        if nt and HEADING_RE.match(nt):
            uri_key[uri] = heading_key(nt)
        elif nt:
            uri_key[uri] = nt
        elif uri.startswith(URI_PREFIX):
            uri_key[uri] = unquote(uri[len(URI_PREFIX):])
    nodes = {}
    for uri, key in uri_key.items():
        r = raw[uri]
        n = Node(key, None if key.startswith("heading-") else key)
        n.order = r["order"]
        n.node_type = r["type"] or ("heading" if n.notation is None else None)
        for tag, lang, text in r["lits"]:
            if tag == f"{{{SKOS}}}prefLabel":
                n.labels.setdefault(lang, text)
            elif tag == f"{{{SKOS}}}altLabel":
                add_unique(n.alt, lang, text)
            elif tag == f"{{{SKOS}}}hiddenLabel":
                add_unique(n.hidden, lang, text)
            elif tag == f"{{{SKOS}}}scopeNote":
                add_unique(n.scope, lang, text)
            elif tag in (f"{{{SKOS}}}note", f"{{{UDC}}}applicationNote"):
                add_unique(n.app, lang, text)
            elif tag == f"{{{UDC}}}includingNote":
                add_unique(n.including, lang, text)
            elif tag == f"{{{SKOS}}}example":
                add_unique(n.examples, lang, text)
        parents = [uri_key[b] for b in r["broader"] if b in uri_key]
        n.parent = parents[0] if parents else None
        n.related = [uri_key[x] for x in r["related"] if x in uri_key]
        nodes[key] = n
    stats = {"ignored_predicates": ignored, "dropped_literals_by_lang": dropped_lang}
    return nodes, scheme_meta, stats


# ---------------------------------------------------------------- lectura TXT
class TxtError(Exception):
    pass


def parse_line(s):
    """'notación etiqueta' -> (clave, notación|None, etiqueta)."""
    head, _, rest = s.partition(" ")
    if HEADING_RE.match(head):
        return heading_key(head), None, rest.strip()
    for nt in COMMA_NOTATIONS:
        if s == nt or s.startswith(nt + " "):
            return nt, nt, s[len(nt):].strip()
    if head.endswith(","):
        raise TxtError(f"notación con coma no reconocida: {head!r} (añádela a COMMA_NOTATIONS)")
    return head, head, rest.strip()


def read_txt(path):
    """Devuelve lista de entradas: (clave, notación, etiqueta, clave_padre, orden_entre_hermanos)."""
    text = Path(path).read_text(encoding="utf-8-sig")
    entries, stack, seen, child_count = [], [], set(), {}
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise TxtError(f"línea {i}: tabulador en la sangría (usar 4 espacios)")
        indent = len(line) - len(line.lstrip(" "))
        if indent % 4:
            raise TxtError(f"línea {i}: sangría de {indent} espacios (debe ser múltiplo de 4)")
        depth = indent // 4
        if depth > len(stack):
            raise TxtError(f"línea {i}: salto de nivel (profundidad {depth} tras {len(stack) - 1})")
        try:
            key, nt, label = parse_line(line.strip())
        except TxtError as e:
            raise TxtError(f"línea {i}: {e}") from None
        if key in seen:
            raise TxtError(f"línea {i}: notación duplicada {key!r}")
        seen.add(key)
        stack = stack[:depth]
        parent = stack[-1] if stack else None
        order = child_count.get(parent, 0)
        child_count[parent] = order + 1
        entries.append((key, nt, label, parent, order))
        stack.append(key)
    return entries


# ---------------------------------------------------------------- fusión
def merge_structure(nodes, entries, lang, prune, rep):
    in_txt = set()
    for key, nt, label, parent, order in entries:
        in_txt.add(key)
        n = nodes.get(key)
        if n is None:
            n = nodes[key] = Node(key, nt)
            if nt is None:
                n.node_type = "heading"
            rep["created"] += 1
        else:
            changed = False
            if n.parent != parent:
                rep["parent_changes"].append((key, n.parent, parent))
                changed = True
            old = n.labels.get(lang)
            if old is not None and old != label:
                rep["label_changes"].append((key, old, label))
                add_unique(n.hidden, lang, old)
                changed = True
            if n.order != order:
                changed = True
            if changed:
                rep["_changed"].add(key)
        n.parent, n.order = parent, order
        if label:
            n.labels[lang] = label
    # nodos del RDF que no están en el .txt
    missing = [k for k in nodes if k not in in_txt]
    if prune:
        for k in missing:
            del nodes[k]
        rep["removed"] = sorted(missing, key=natural_key)
    else:
        rep["kept_not_in_txt"] = sorted(missing, key=natural_key)
        for k in missing:
            nodes[k].order = None  # irán detrás de los hermanos del .txt


def merge_labels(nodes, entries, lang, rep):
    for key, nt, label, parent, order in entries:
        n = nodes.get(key)
        if n is None:
            rep["not_in_rdf"].append(key)
            continue
        if n.parent != parent:
            rep["hierarchy_mismatch"].append((key, n.parent, parent))
        old = n.labels.get(lang)
        if not label:
            continue
        if old is None:
            rep["labels_added"] += 1
        elif old != label:
            rep["labels_replaced"] += 1
            add_unique(n.hidden, lang, old)
        n.labels[lang] = label


NOTE_FIELDS = {"scopeNote": "scope", "applicationNote": "app", "includingNote": "including",
               "example": "examples"}


def apply_notes(nodes, notes, rep, source="extra_notes"):
    """Aplica un JSON de notas (extra_notes.json o udc_records.json; mismo formato).
    Cada campo presente y no vacío REEMPLAZA los valores de ese idioma; 'related' reemplaza la lista.
    Se aplica primero udc_records.json y después extra_notes.json, así lo manual siempre gana."""
    fields = NOTE_FIELDS
    for key, spec in notes.items():
        if key.startswith("_"):
            continue  # metadatos del archivo (p. ej. "_source")
        n = nodes.get(key)
        if n is None:
            rep["notes_unknown"].append(f"{key} ({source})")
            continue
        rep["notes_applied"][source] = rep["notes_applied"].get(source, 0) + 1
        if spec.get("related"):
            n.related = list(dict.fromkeys(spec["related"]))
        if "nodeType" in spec:
            n.node_type = spec["nodeType"] or None
        for lang, text in (spec.get("prefLabel") or {}).items():
            n.labels[lang] = text
        for jkey, attr in fields.items():
            for lang, val in (spec.get(jkey) or {}).items():
                vals = [val] if isinstance(val, str) else list(val)
                vals = [v.strip() for v in vals if v and v.strip()]
                if vals:
                    getattr(n, attr)[lang] = vals
                elif source == "extra_notes":  # en udc_records.json una lista vacía es normal
                    rep["notes_empty"].append(f"{key} {jkey}@{lang}")


# ---------------------------------------------------------------- escritura
def lang_sort(langs):
    return sorted(langs, key=lambda l: (l != "en", l))


def write_rdf(nodes, scheme_meta, out_path, rep):
    children = {}
    for n in nodes.values():
        if n.parent is not None and n.parent not in nodes:
            rep["orphans"].append(n.key)
            n.parent = None
        children.setdefault(n.parent, []).append(n)
    for kids in children.values():
        kids.sort(key=lambda n: (n.order is None, n.order or 0, natural_key(n.key)))
        for i, n in enumerate(kids):
            n.order = i
    ordered = []

    def walk(parent):  # recorrido en profundidad iterativo
        stack = list(reversed(children.get(parent, [])))
        while stack:
            n = stack.pop()
            ordered.append(n)
            stack.extend(reversed(children.get(n.key, [])))

    walk(None)
    roots = children.get(None, [])

    def lit(tag, lang, text):
        la = f' xml:lang="{lang}"' if lang else ""
        return f"    <{tag}{la}>{escape(text)}</{tag}>\n"

    def res(tag, key):
        return f"    <{tag} rdf:resource={quoteattr(key_to_uri(key))}/>\n"

    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    tag_prefix = {v: k for k, v in PREFIXES.items()}

    def qname(tag):
        ns, local = tag[1:].split("}")
        return f"{tag_prefix[ns]}:{local}"

    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<rdf:RDF')
        f.write("".join(f'\n   xmlns:{p}="{u}"' for p, u in PREFIXES.items()))
        f.write(">\n")
        # esquema
        f.write(f'  <skos:ConceptScheme rdf:about="{SCHEME_URI}">\n')
        for tag, lang, resource, text in scheme_meta:
            q = qname(tag)
            if resource is not None:
                f.write(f"    <{q} rdf:resource={quoteattr(resource)}/>\n")
            else:
                f.write(lit(q, lang, text))
        f.write(f'    <dct:modified rdf:datatype="http://www.w3.org/2001/XMLSchema#dateTime">{now}</dct:modified>\n')
        for n in roots:
            f.write(res("skos:hasTopConcept", n.key))
        f.write("  </skos:ConceptScheme>\n")
        # propiedades
        props = [(UDC + "applicationNote", "applicationNote", "Instructions for number building.", SKOS + "note"),
                 (UDC + "includingNote", "includingNote", "Concepts included in the class ('Including ...').", SKOS + "note"),
                 (UDCX + "order", "order", "Position of the concept among its siblings (0-based).", None),
                 (UDCX + "nodeType", "nodeType", "'heading' (grouping node without notation) or 'info' (informative node, not assignable).", None)]
        for uri, label, comment, sub in props:
            f.write(f'  <rdf:Property rdf:about="{uri}">\n    <rdfs:label>{label}</rdfs:label>\n'
                    f"    <rdfs:comment>{escape(comment)}</rdfs:comment>\n")
            if sub:
                f.write(f'    <rdfs:subPropertyOf rdf:resource="{sub}"/>\n')
            f.write("  </rdf:Property>\n")
        # conceptos
        for n in ordered:
            f.write(f"  <skos:Concept rdf:about={quoteattr(key_to_uri(n.key))}>\n")
            if n.parent is not None:
                f.write(res("skos:broader", n.parent))
            else:
                f.write(f'    <skos:topConceptOf rdf:resource="{SCHEME_URI}"/>\n')
            f.write(f'    <skos:inScheme rdf:resource="{SCHEME_URI}"/>\n')
            for c in children.get(n.key, []):
                f.write(res("skos:narrower", c.key))
            if n.notation is not None:
                f.write(f'    <skos:notation rdf:datatype="{NOTATION_DT}">{escape(n.notation)}</skos:notation>\n')
            for lang in lang_sort(n.labels):
                f.write(lit("skos:prefLabel", lang, n.labels[lang]))
            for tag, d in (("skos:altLabel", n.alt), ("skos:hiddenLabel", n.hidden),
                           ("skos:scopeNote", n.scope), ("udc:applicationNote", n.app),
                           ("udc:includingNote", n.including), ("skos:example", n.examples)):
                for lang in lang_sort(d):
                    for text in d[lang]:
                        f.write(lit(tag, lang, text))
            for r in n.related:
                if r in nodes:
                    f.write(res("skos:related", r))
                else:
                    rep["dangling_related"].append((n.key, r))
            if n.node_type:
                f.write(f"    <udcx:nodeType>{escape(n.node_type)}</udcx:nodeType>\n")
            f.write(f'    <udcx:order rdf:datatype="http://www.w3.org/2001/XMLSchema#integer">{n.order}</udcx:order>\n')
            f.write("  </skos:Concept>\n")
        f.write("</rdf:RDF>\n")
    return len(ordered)


# ---------------------------------------------------------------- informe
def write_report(path, rep, nodes, args, mode, total):
    lines = [f"UDC merge report - {dt.datetime.now():%Y-%m-%d %H:%M}",
             f"RDF de entrada: {args.rdf}", f"TXT: {args.txt}", f"Idioma: {args.lang}  Modo: {mode}"
             f"  Prune: {args.prune}", f"Salida: {args.out}", "",
             f"Conceptos escritos: {total}"]
    langs = {}
    for n in nodes.values():
        for l in n.labels:
            langs[l] = langs.get(l, 0) + 1
    lines.append("Etiquetas por idioma: " + ", ".join(f"{l}={c}" for l, c in sorted(langs.items())))
    no_label = [n.key for n in nodes.values() if args.lang not in n.labels]
    lines.append(f"Nodos sin etiqueta en '{args.lang}': {len(no_label)}")
    if mode == "structure":
        lines += [f"Creados: {rep['created']}",
                  f"Modificados (padre, orden o etiqueta): {len(rep['_changed'])}",
                  f"Cambios de padre: {len(rep['parent_changes'])}",
                  f"Cambios de etiqueta: {len(rep['label_changes'])}"]
        if args.prune:
            lines.append(f"Eliminados (no están en el .txt): {len(rep['removed'])}")
        else:
            lines.append(f"Conservados aunque no están en el .txt: {len(rep['kept_not_in_txt'])}")
    else:
        lines += [f"Etiquetas añadidas: {rep['labels_added']}",
                  f"Etiquetas reemplazadas: {rep['labels_replaced']}",
                  f"Notaciones del .txt que no existen en el RDF: {len(rep['not_in_rdf'])}",
                  f"Diferencias de jerarquía (no aplicadas): {len(rep['hierarchy_mismatch'])}"]
    lines += [f"Literales descartados por idioma: {rep['stats']['dropped_literals_by_lang']}",
              f"Predicados ignorados: {rep['stats']['ignored_predicates']}",
              f"related colgantes eliminados: {len(rep['dangling_related'])}",
              f"Huérfanos (padre inexistente, pasan a raíz): {len(rep['orphans'])}",
              f"Notas aplicadas por archivo: {rep['notes_applied']}",
              f"Notas con notación desconocida: {len(rep['notes_unknown'])}",
              f"extra_notes vacías: {rep['notes_empty']}"]
    for label, attr in (("scopeNote", "scope"), ("applicationNote", "app"), ("includingNote", "including"),
                        ("example", "examples")):
        with_f = [n for n in nodes.values() if getattr(n, attr)]
        total_v = sum(len(v) for n in with_f for v in getattr(n, attr).values())
        lines.append(f"Nodos con {label}: {len(with_f)} ({total_v} textos)")
    lines.append(f"Nodos con related: {sum(1 for n in nodes.values() if n.related)}")

    def section(title, items, fmt=str):
        if items:
            lines.extend(["", f"== {title} ({len(items)})"] + [fmt(x) for x in items])

    arrow = lambda t: f"{t[0]}: {t[1]!r} -> {t[2]!r}"
    section("Eliminados", rep.get("removed", []))
    section("Conservados sin estar en el .txt", rep.get("kept_not_in_txt", []))
    section("Cambios de padre", rep["parent_changes"], arrow)
    section("Cambios de etiqueta", rep["label_changes"], arrow)
    section("No existen en el RDF", rep["not_in_rdf"])
    section("Diferencias de jerarquía (RDF -> txt)", rep["hierarchy_mismatch"], arrow)
    section("related colgantes", rep["dangling_related"], lambda t: f"{t[0]} -> {t[1]}")
    section("Huérfanos", rep["orphans"])
    section("Notas con notación desconocida", rep["notes_unknown"])
    if mode == "labels":
        section(f"Sin etiqueta en '{args.lang}'", sorted(no_label, key=natural_key))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description="Fusiona un árbol UDC (.txt) en un SKOS RDF/XML.")
    ap.add_argument("--rdf", required=True, type=Path, help="RDF de entrada (se conserva su información)")
    ap.add_argument("--txt", required=True, type=Path, help="árbol UDC con sangría de 4 espacios")
    ap.add_argument("--lang", default="en", help="idioma de las etiquetas del .txt (por defecto en)")
    ap.add_argument("--mode", choices=["structure", "labels"],
                    help="structure: el .txt define la jerarquía; labels: solo añade etiquetas. "
                         "Por defecto structure si --lang en, labels en otro caso")
    ap.add_argument("--prune", action="store_true", help="(structure) elimina nodos que no están en el .txt")
    ap.add_argument("--keep-langs", help="conserva solo estos idiomas del RDF de entrada, p. ej. 'en'")
    ap.add_argument("--notes", type=Path, help="JSON de notas extra (por defecto extra_notes.json junto al script)")
    ap.add_argument("--records", type=Path,
                    help="fichas de UDC Online ya interpretadas (por defecto udc_records.json junto al script, "
                         "si existe). Se aplican antes que --notes")
    ap.add_argument("--out", type=Path, help="RDF de salida (por defecto sobrescribe --rdf con copia .bak)")
    ap.add_argument("--report", type=Path, help="informe (por defecto conversion_report.txt junto a la salida)")
    ap.add_argument("--dry-run", action="store_true", help="solo genera el informe")
    args = ap.parse_args(argv)

    mode = args.mode or ("structure" if args.lang == "en" else "labels")
    out = args.out or args.rdf
    args.out = out
    keep = set(x.strip() for x in args.keep_langs.split(",")) if args.keep_langs else None
    notes_path = args.notes or (Path(__file__).with_name("extra_notes.json"))
    records_path = args.records or (Path(__file__).with_name("udc_records.json"))
    if args.records and not records_path.exists():
        sys.exit(f"No existe {records_path}")

    nodes, scheme_meta, stats = read_rdf(args.rdf, keep)
    try:
        entries = read_txt(args.txt)
    except TxtError as e:
        sys.exit(f"Error en {args.txt}: {e}")

    rep = {"created": 0, "parent_changes": [], "label_changes": [], "_changed": set(),
           "not_in_rdf": [], "hierarchy_mismatch": [], "labels_added": 0,
           "labels_replaced": 0, "notes_unknown": [], "notes_empty": [], "notes_applied": {},
           "dangling_related": [],
           "orphans": [], "stats": stats}
    if mode == "structure":
        merge_structure(nodes, entries, args.lang, args.prune, rep)
    else:
        merge_labels(nodes, entries, args.lang, rep)
    if records_path.exists():
        apply_notes(nodes, json.loads(records_path.read_text(encoding="utf-8")), rep, "udc_records")
    if notes_path.exists():
        apply_notes(nodes, json.loads(notes_path.read_text(encoding="utf-8")), rep, "extra_notes")

    report_path = args.report or out.with_name("conversion_report.txt")
    if args.dry_run:
        tmp = out.with_name(out.name + ".dryrun.tmp")
        total = write_rdf(nodes, scheme_meta, tmp, rep)
        tmp.unlink()
    else:
        if out.exists() and out.resolve() == args.rdf.resolve():
            shutil.copy2(out, out.with_name(out.name + ".bak"))
        tmp = out.with_name(out.name + ".tmp")
        total = write_rdf(nodes, scheme_meta, tmp, rep)
        tmp.replace(out)
    lines = write_report(report_path, rep, nodes, args, mode, total)
    cut = next((i for i, l in enumerate(lines) if l.startswith("== ")), len(lines))
    print("\n".join(lines[:cut]).rstrip())
    print(f"Informe completo: {report_path}")


if __name__ == "__main__":
    main()
