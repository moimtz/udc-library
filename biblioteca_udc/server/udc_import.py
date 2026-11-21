"""Import the UDC tree (SKOS RDF/XML) into the database.

    python udc_import.py path\\to\\udcs-skos.rdf [--langs en,es]

Meant for the RDF produced by udc_to_rdf_conversion/udc_merge.py (full tree, sibling order,
headings, informative nodes and class notes). The original UDC Summary file also works:
without skos:broader the parent is inferred from the notation, and siblings are sorted naturally.

Per class it stores: code, parent, labels, global order, node type and the notes shown in the
class information window (scope note, application note, including, examples, see also).
"""
import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote

import udc
from db import connect, init_db

RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
UDC = "http://udcdata.info/udc-schema#"      # applicationNote, includingNote
UDCX = "urn:udc:ext#"                        # order, nodeType (udc_merge.py)
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
URI_PREFIX = "urn:udc:"

# literal property -> key in the notes JSON
NOTE_TAGS = {f"{{{SKOS}}}scopeNote": "scope", f"{{{UDC}}}applicationNote": "app",
             f"{{{SKOS}}}note": "app", f"{{{UDC}}}includingNote": "including"}


def infer_parent(code: str, known: set[str]) -> str | None:
    c = code[:-1].rstrip(".")
    while c:
        if c in known:
            return c
        c = c[:-1].rstrip(".")
    return None


def split_example(text: str) -> dict:
    """'330.322.014.3    Net investment' -> {'code': ..., 'label': ...} (format of udc_merge.py)."""
    code, sep, label = text.strip().partition("    ")
    return {"code": code.strip(), "label": label.strip()} if sep else {"code": "", "label": text.strip()}


def read_rdf(path: Path, langs: list[str]) -> dict[str, dict]:
    """uri -> concept dict. Reads skos:Concept and rdf:Description elements."""
    root = ET.parse(path).getroot()
    concepts: dict[str, dict] = {}
    for el in root:
        if el.tag not in (f"{{{SKOS}}}Concept", f"{{{RDF}}}Description"):
            continue
        about = el.get(f"{{{RDF}}}about")
        if not about:
            continue
        c = concepts.setdefault(about, {"notation": None, "labels": {}, "broader": [], "order": None,
                                        "type": None, "notes": {}, "examples": {}, "related": [],
                                        "concept": False})
        c["concept"] |= el.tag == f"{{{SKOS}}}Concept"
        for ch in el:
            tag, text = ch.tag, (ch.text or "").strip()
            lang = ch.get(XML_LANG) or "en"
            res = ch.get(f"{{{RDF}}}resource")
            if tag == f"{{{SKOS}}}notation":
                c["notation"] = text
            elif tag == f"{{{SKOS}}}prefLabel":
                if lang in langs and text:
                    c["labels"].setdefault(lang, text)
            elif tag == f"{{{SKOS}}}broader" and res:
                c["broader"].append(res)
            elif tag == f"{{{SKOS}}}related" and res:
                c["related"].append(res)
            elif tag == f"{{{UDCX}}}order" and text:
                c["order"] = int(text)
            elif tag == f"{{{UDCX}}}nodeType" and text:
                c["type"] = text
            elif tag in NOTE_TAGS and text and lang in langs:
                lst = c["notes"].setdefault(NOTE_TAGS[tag], {}).setdefault(lang, [])
                if text not in lst:
                    lst.append(text)
            elif tag == f"{{{SKOS}}}example" and text and lang in langs:
                c["examples"].setdefault(lang, []).append(split_example(text))
    return concepts


def code_of(uri: str, c: dict) -> str | None:
    """Notation, or 'heading-N' for grouping headings without notation."""
    if c["notation"]:
        return c["notation"]
    if c["type"] == "heading" and uri.startswith(URI_PREFIX):
        return unquote(uri[len(URI_PREFIX):])
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--langs", default="en,es", help="comma-separated language codes to keep")
    args = ap.parse_args()
    langs = [x.strip() for x in args.langs.split(",") if x.strip()]

    concepts = read_rdf(args.file, langs)
    codes = {uri: code_of(uri, c) for uri, c in concepts.items() if c["concept"]}
    codes = {uri: code for uri, code in codes.items() if code and concepts[uri]["labels"]}
    if not codes:
        raise SystemExit("No SKOS concepts with notation and the requested languages were found in that file.")
    known = set(codes.values())

    nodes = {}   # code -> dict
    for uri, code in codes.items():
        c = concepts[uri]
        parents = [codes[b] for b in c["broader"] if b in codes]
        parent = parents[0] if parents else None
        if parent is None and not c["broader"] and len(code) > 1 and c["type"] != "heading":
            parent = infer_parent(code, known)   # original Summary without skos:broader
        if parent == code:
            parent = None
        notes = dict(c["notes"])
        if c["examples"]:
            notes["examples"] = c["examples"]
        related = [codes[r] for r in c["related"] if r in codes]
        if related:
            notes["related"] = related
        nodes[code] = {"parent": parent, "labels": c["labels"], "order": c["order"], "type": c["type"],
                       "notes": notes}

    # global order = depth-first walk; siblings by udcx:order, then natural order of the notation
    children: dict[str | None, list[str]] = {}
    for code, n in nodes.items():
        if n["parent"] not in nodes:
            n["parent"] = None   # parent without label in the requested languages: becomes a root
        children.setdefault(n["parent"], []).append(code)
    for kids in children.values():
        kids.sort(key=lambda k: (nodes[k]["order"] is None, nodes[k]["order"] or 0, udc.natural_key(k)))
    ordered, stack = [], list(reversed(children.get(None, [])))
    while stack:
        code = stack.pop()
        ordered.append(code)
        stack.extend(reversed(children.get(code, [])))

    init_db()
    conn = connect()
    conn.execute("DELETE FROM udc_nodes")
    for i, code in enumerate(ordered):
        n = nodes[code]
        conn.execute("INSERT INTO udc_nodes(code,parent,labels,ord,node_type,notes) VALUES (?,?,?,?,?,?)",
                     (code, n["parent"], json.dumps(n["labels"], ensure_ascii=False), i, n["type"],
                      json.dumps(n["notes"], ensure_ascii=False) if n["notes"] else None))
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('udc_source', ?)", (args.file.name,))
    udc.rebuild_all_item_links(conn)
    conn.commit()
    conn.close()
    with_notes = sum(1 for n in nodes.values() if n["notes"])
    info = sum(1 for n in nodes.values() if n["type"] == "info")
    print(f"Imported {len(ordered)} UDC classes ({', '.join(langs)}); {with_notes} with notes, {info} informative. "
          "Existing items were re-linked to the tree.")
    if len(ordered) < len(nodes):
        print(f"Warning: {len(nodes) - len(ordered)} classes were not reachable from a root and were skipped.")


if __name__ == "__main__":
    main()
