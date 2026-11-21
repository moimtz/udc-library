"""Exporta el RDF a un .txt con el mismo formato que la entrada (sangría de 4 espacios).

    python udc_export_txt.py --rdf udcs-skos.rdf --out arbol_en.txt [--lang en]

Si un nodo no tiene etiqueta en --lang, usa la inglesa. Sirve para comprobar
que el RDF reproduce el .txt original y para revisar las traducciones.
"""
import argparse
from pathlib import Path

from udc_merge import natural_key, read_rdf


def export(rdf, out, lang="en"):
    nodes, _, _ = read_rdf(rdf)
    children = {}
    for n in nodes.values():
        children.setdefault(n.parent, []).append(n)
    for kids in children.values():
        kids.sort(key=lambda n: (n.order is None, n.order or 0, natural_key(n.key)))
    lines, stack = [], [(n, 0) for n in reversed(children.get(None, []))]
    while stack:
        n, depth = stack.pop()
        if n.notation is None:  # encabezado: 'heading-N' -> N guiones
            code = "-" * int(n.key.split("-")[1])
        else:
            code = n.notation
        label = n.labels.get(lang) or n.labels.get("en", "")
        lines.append("    " * depth + (f"{code} {label}" if label else code))
        stack.extend((c, depth + 1) for c in reversed(children.get(n.key, [])))
    Path(out).write_text("\n".join(lines), encoding="utf-8", newline="\n")  # LF, como el original
    return len(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rdf", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--lang", default="en")
    a = ap.parse_args()
    print(f"{export(a.rdf, a.out, a.lang)} líneas escritas en {a.out}")
