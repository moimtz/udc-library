"""Lectura del UDC Summary (SKOS/RDF) y construcción del árbol jerárquico.

Se construye la jerarquía con skos:broader / skos:narrower y, si faltan, se infiere por prefijo de
notación. Es independiente de la lógica del servidor (que según comentas tiene la jerarquía mal).
"""
from __future__ import annotations
import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SKOS = "http://www.w3.org/2004/02/skos/core#"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
UDC = "http://udcdata.info/udc-schema#"   # udc:applicationNote, udc:informationNote, udc:includingNote
UDCX = "urn:udc:ext#"                     # udcx:nodeType, udcx:order, udcx:auxType (udc_merge.py)

KINDS = ("main", "lang", "form", "place", "ethnic", "time", "common", "special", "viewpoint", "other")

# Nodos estructurales del RDF ("-" AUXILIARY TABLES, "----" MAIN TABLES...): no son clases, se descartan.
_STRUCT = re.compile(r"^-+$")
# Encabezados de tabla ('=...', '(0...)', '-0...', '"..."'): agrupan, no se asignan; se tratan como rangos.
_HEADING = re.compile(r'\.\.\.\)?"?$')
# skos:example = "notación    texto" (4 espacios, ver udc_to_rdf_conversion/README.md)
_EX_SPLIT = re.compile(r"\s{2,}|\t")
# sufijo de un ejemplo que solo alarga la notación del nodo (330.322 -> 330.322.014.3); sin : + / ( = "
_EX_SUFFIX = re.compile(r"^[0-9.\-']+$")
MAX_EXAMPLES_IN_TEXT = 8


def parse_example(text: str):
    """'330.322.014.3    Net investment' -> ('330.322.014.3', 'Net investment'); None si no tiene ese formato."""
    parts = _EX_SPLIT.split(text.strip(), maxsplit=1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()
_SPECIAL_LBL = re.compile(r"special auxiliar", re.I)


@dataclass
class Node:
    uri: str
    notation: str
    labels: dict = field(default_factory=dict)
    alt: list = field(default_factory=list)
    note: str = ""
    including: str = ""                           # udc:includingNote ("Including ...")
    examples: list = field(default_factory=list)  # [(notación, texto)] de skos:example
    origin: str = ""                              # "" = clase del RDF; "example" = creado a partir de un ejemplo
    host: str | None = None                       # (origin=example) uri del nodo que trae el ejemplo
    aux_type: str | None = None                   # udcx:auxType de UDC Online: "common", "special" o None
    related: list = field(default_factory=list)   # uris de skos:related ("See also"), en ambos sentidos
    parent: str | None = None
    children: list = field(default_factory=list)
    kind: str = "main"
    is_range: bool = False
    depth: int = 0

    def label(self, langs=("en",)) -> str:
        for lg in langs:
            if self.labels.get(lg):
                return self.labels[lg]
        return next(iter(self.labels.values()), self.notation)


def classify_notation(n: str) -> str:
    """Clasifica una notación según su símbolo inicial (tabla a la que pertenece)."""
    if n.startswith("(="):
        return "ethnic"
    if n.startswith("(0"):
        return "form"
    if n.startswith("("):
        return "place"
    if n.startswith("="):
        return "lang"
    if n.startswith('"'):
        return "time"
    if n.startswith(".00"):
        return "viewpoint"
    if n.startswith("-0"):
        return "common"
    if n.startswith(("-", ".0", "'")):
        return "special"
    if re.match(r"^\d", n):
        return "main"
    return "other"


# ------------------------------------------------------------------ lectura de tripletas
def _triples_rdflib(path):
    """Cualquier sintaxis RDF. El orden de un grafo de rdflib cambia en cada ejecución (hash aleatorio de
    Python), así que se ordenan las tripletas: el árbol y su huella deben salir idénticos siempre."""
    import rdflib
    g = rdflib.Graph()
    try:
        g.parse(str(path), format="xml")
    except Exception:
        g.parse(str(path))
    out = []
    for s, p, o in g:
        lang = (o.language or "") if isinstance(o, rdflib.Literal) else None
        out.append((str(s), str(p), str(o), lang))
    out.sort(key=lambda t: (t[0], t[1], t[3] or "", t[2]))
    yield from out


def _triples_et(path):
    """RDF/XML plano (como el de udc_to_rdf_conversion): tripletas en el ORDEN DEL DOCUMENTO, que es
    determinista y conserva el orden de notas y ejemplos. Sin duplicados (como haría rdflib)."""
    import xml.etree.ElementTree as ET
    root = ET.parse(str(path)).getroot()
    for el in root:
        about = el.get(f"{{{RDF}}}about")
        if about is None:
            continue
        seen = set()
        for ch in el:
            if not ch.tag.startswith("{"):
                continue
            ns, local = ch.tag[1:].split("}")
            res = ch.get(f"{{{RDF}}}resource")
            t = (about, ns + local, res, None) if res is not None else \
                (about, ns + local, (ch.text or "").strip(), ch.get(XML_LANG, ""))
            if t not in seen:
                seen.add(t)
                yield t


def iter_triples(path):
    """RDF/XML: lector XML en orden del documento (determinista y rápido). Otras sintaxis: rdflib ordenado."""
    if str(path).lower().endswith((".rdf", ".xml", ".owl")):
        try:
            import xml.etree.ElementTree as ET
            for _ in ET.iterparse(str(path), events=("start",)):     # ¿es XML? (solo mira el inicio)
                break
            return _triples_et(path)
        except ET.ParseError:
            pass
    return _triples_rdflib(path)


# ------------------------------------------------------------------------------ árbol
class Tree:
    def __init__(self, nodes: dict[str, Node], label_langs=("en", "sv", "fi")):
        self.nodes = nodes
        self.official_aux = False  # True si el RDF trae udcx:auxType
        self.cancelled: dict[str, list[dict]] = {}   # notación cancelada -> [{year, ec, label, replaced_by}]
        self.label_langs = tuple(label_langs)
        self.by_notation: dict[str, Node] = {}
        for n in nodes.values():
            self.by_notation.setdefault(n.notation, n)

    # ---- carga
    @classmethod
    def load(cls, path, label_langs=("en", "sv", "fi")) -> "Tree":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"No encuentro el RDF del UDC en {path}. Cópialo ahí (ver README).")
        notation, labels, alts, notes, including, examples = {}, {}, {}, {}, {}, {}
        broader, narrower, related = {}, {}, {}
        info = set()  # nodos informativos (udcx:nodeType "info"): no son clases asignables
        aux = {}      # udcx:auxType (marca oficial de auxiliar común/especial)
        canc = {}     # udcx:CancelledClass: uri -> {notation, year, ec, label, replaced_by}
        rdfs_label = {}
        for s, p, o, lang in iter_triples(path):
            if p.startswith(UDCX) and p[len(UDCX):] in ("cancelledNotation", "cancelledYear", "cancelledIn",
                                                         "replacedByNotation"):
                c = canc.setdefault(s, {"notation": "", "year": None, "ec": "", "label": "", "replaced_by": []})
                k = p[len(UDCX):]
                if k == "cancelledNotation":
                    c["notation"] = o.strip()
                elif k == "cancelledYear":
                    c["year"] = int(o) if o.strip().isdigit() else None
                elif k == "cancelledIn":
                    c["ec"] = o.strip()
                else:
                    c["replaced_by"].append(o.strip())
            elif p == RDFS + "label":
                rdfs_label[s] = o.strip()
            elif p == UDCX + "auxType":
                aux[s] = o.strip() or None
            elif p == UDCX + "nodeType":
                if o.strip() == "info":
                    info.add(s)
            elif p == SKOS + "notation":
                notation.setdefault(s, o.strip())
            elif p == SKOS + "prefLabel":
                labels.setdefault(s, {})[(lang or "en")] = o.strip()
            elif p == SKOS + "altLabel":
                if lang in ("en", "", None):  # en el Summary solo hay altLabel en finés: no aportan
                    alts.setdefault(s, []).append(o.strip())
            elif p in (SKOS + "scopeNote", SKOS + "definition", SKOS + "note", UDC + "applicationNote",
                       UDC + "informationNote"):
                if lang in ("en", "", None):
                    notes[s] = (notes.get(s, "") + " " + o.strip()).strip()
            elif p == UDC + "includingNote":
                if lang in ("en", "", None):
                    including[s] = (including.get(s, "") + " " + o.strip()).strip()
            elif p == SKOS + "example":
                ex = parse_example(o) if lang in ("en", "", None) else None
                if ex and ex not in examples.get(s, []):
                    examples.setdefault(s, []).append(ex)
            elif p == SKOS + "related":
                related.setdefault(s, []).append(o)
            elif p == SKOS + "broader":
                broader.setdefault(s, []).append(o)
            elif p == SKOS + "narrower":
                narrower.setdefault(s, []).append(o)
        # encabezados sin notación (udc_merge.py) también son estructurales
        struct = {b for lst in broader.values() for b in lst if b not in notation} | info
        nodes = {}
        for uri, nt in notation.items():
            if not nt:
                continue
            if _STRUCT.match(nt) or uri in info:
                struct.add(uri)
                continue
            nodes[uri] = Node(uri=uri, notation=nt, labels=labels.get(uri, {}), alt=alts.get(uri, []),
                              note=notes.get(uri, ""), including=including.get(uri, ""),
                              examples=examples.get(uri, []), aux_type=aux.get(uri))
        # "See also": UDC Online a veces lo pone en un solo sentido; aquí vale en los dos
        for s, lst in related.items():
            for o in lst:
                if s in nodes and o in nodes and s != o:
                    for a, b in ((s, o), (o, s)):
                        if b not in nodes[a].related:
                            nodes[a].related.append(b)
        t = cls(nodes, label_langs)
        t.official_aux = bool(aux)
        # clases canceladas: fuera del árbol (no son nodos); notación -> [cancelaciones]
        for uri, c in canc.items():
            if c["notation"]:
                c["label"] = rdfs_label.get(uri, "")
                t.cancelled.setdefault(c.pop("notation"), []).append(c)
        t._link(broader, narrower, struct)
        t._assign_kinds()
        t._add_example_nodes()
        return t

    def _add_example_nodes(self):
        """Los ejemplos que solo alargan la notación del nodo (330.322 -> 330.322.014.3) se vuelven nodos hijos
        (origin='example'): se embeben, el haz puede llegar a ellos y el validador los reconoce. Se anidan por
        prefijo decimal: 330.322.014.3 cuelga de 330.322.014 si ese ejemplo existe. Las combinaciones con
        : + ( = " no se crean como nodos; solo enriquecen el texto del nodo (node_text)."""
        for host in list(self.nodes.values()):
            if not host.examples or host.is_range or host.origin:
                continue
            made = []
            for nt, lbl in sorted(host.examples, key=lambda e: len(e[0])):
                suffix = nt[len(host.notation):] if nt.startswith(host.notation) else ""
                if not suffix or not _EX_SUFFIX.match(suffix) or nt in self.by_notation:
                    continue
                parent = max((m for m in made if nt.startswith(m.notation)),
                             key=lambda m: len(m.notation), default=host)
                n = Node(uri=f"{host.uri}#ex={nt}", notation=nt, labels={"en": lbl}, parent=parent.uri,
                         kind=host.kind, depth=parent.depth + 1, origin="example", host=host.uri)
                self.nodes[n.uri] = n
                self.by_notation[nt] = n
                parent.children.append(n.uri)
                made.append(n)
            for m in [host] + made:
                m.children.sort(key=lambda u: self._sort_key(self.nodes[u].notation))

    def _link(self, broader, narrower, struct=frozenset()):
        nodes = self.nodes
        # inversa de narrower
        for parent, kids in narrower.items():
            for k in kids:
                if k in nodes and parent in nodes:
                    broader.setdefault(k, [])
                    if parent not in broader[k]:
                        broader[k].append(parent)
        for uri, n in nodes.items():
            cands = [b for b in broader.get(uri, []) if b in nodes and b != uri]
            if cands:
                # preferir el padre cuya notación sea prefijo más largo
                cands.sort(key=lambda b: (-len(self._common_prefix(nodes[b].notation, n.notation)),))
                n.parent = cands[0]
        # inferencia por prefijo para los que quedaron sin padre
        by_nt = {n.notation: n for n in nodes.values()}
        for n in nodes.values():
            # hijos de un nodo estructural descartado: son raíces de su tabla, no se infiere padre
            if n.parent is None and not any(b in struct for b in broader.get(n.uri, [])):
                p = self._infer_parent(n.notation, by_nt)
                if p is not None and p.uri != n.uri:
                    n.parent = p.uri
        # evitar ciclos
        for n in nodes.values():
            seen, cur = {n.uri}, n.parent
            while cur:
                if cur in seen:
                    n.parent = None
                    break
                seen.add(cur)
                cur = nodes[cur].parent
        for n in nodes.values():
            n.children = []
        for n in nodes.values():
            if n.parent:
                nodes[n.parent].children.append(n.uri)
        for n in nodes.values():
            n.children.sort(key=lambda u: self._sort_key(nodes[u].notation))
        for n in nodes.values():
            d, cur = 0, n.parent
            while cur:
                d += 1
                cur = nodes[cur].parent
            n.depth = d

    @staticmethod
    def _common_prefix(a: str, b: str) -> str:
        i = 0
        while i < min(len(a), len(b)) and a[i] == b[i]:
            i += 1
        return a[:i]

    @staticmethod
    def _infer_parent(nt: str, by_nt: dict):
        s = nt.rstrip(".")
        while len(s) > 1:
            s = s[:-1].rstrip(".")
            if s in by_nt and s != nt:
                return by_nt[s]
        return None

    @staticmethod
    def _sort_key(nt: str):
        return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"(\d+)", nt) if x]

    def _assign_kinds(self):
        order = sorted(self.nodes.values(), key=lambda n: n.depth)
        for n in order:
            k = classify_notation(n.notation)
            if k == "other" and n.parent:
                k = self.nodes[n.parent].kind
            # auxiliares especiales dentro de la tabla principal (2-1/-9, 53.01/.09, ...): el RDF las agrupa
            # bajo un rango "Special auxiliary subdivision/table for ..."; sus hijos lo heredan abajo.
            if k == "main" and _SPECIAL_LBL.match(n.label(self.label_langs)):
                k = "special"
            # sin ese rango: notación = la del padre + "-x" o ".0x" (p. ej. 364-1, 78.01)
            elif k == "main" and n.parent:
                pn = self.nodes[n.parent].notation
                rest = n.notation[len(pn):] if n.notation.startswith(pn) else ""
                if re.match(r"^(-\d|\.0\d$)", rest):
                    k = "special"
            n.kind = k
            n.is_range = "/" in n.notation or bool(_HEADING.search(n.notation))
        # hijos de tablas auxiliares con notación "pelada" heredan el tipo del padre
        for n in order:
            if n.kind == "main" and n.parent and self.nodes[n.parent].kind not in ("main", "other"):
                n.kind = self.nodes[n.parent].kind
        # Si el RDF trae la marca oficial de UDC Online (udcx:auxType), decide entre principal y especial.
        # Corrige ~1 100 auxiliares especiales que la notación no delata (661.187.047, 661.8`044.3) y ~170
        # clases principales tomadas por especiales (621.039.5...). Dentro de las tablas auxiliares comunes
        # se conserva el tipo fino (place, lang, time...), que es el que elige la tabla.
        if getattr(self, "official_aux", False):
            for n in order:
                if n.kind == "main" and n.aux_type == "special":
                    n.kind = "special"
                elif n.kind == "special" and n.aux_type is None:
                    n.kind = "main"

    # ---- consultas
    def get(self, notation: str) -> Node | None:
        return self.by_notation.get(notation)

    def parent_of(self, n: Node) -> Node | None:
        return self.nodes.get(n.parent) if n.parent else None

    def ancestors(self, n: Node) -> list[Node]:
        out, cur = [], n.parent
        while cur:
            out.append(self.nodes[cur])
            cur = self.nodes[cur].parent
        return out[::-1]

    def path(self, n: Node, skip_ranges=True) -> list[Node]:
        p = self.ancestors(n) + [n]
        return [x for x in p if not (skip_ranges and x.is_range)]

    def real_children(self, n: Node, kind: str | None = None) -> list[Node]:
        """Hijos directos, atravesando nodos de rango (p. ej. '(1/9)')."""
        out = []
        for u in n.children:
            c = self.nodes[u]
            if c.is_range:
                out.extend(self.real_children(c, kind))
            elif kind is None or c.kind == kind:
                out.append(c)
        return out

    def descendants(self, n: Node):
        stack = list(n.children)
        while stack:
            c = self.nodes[stack.pop()]
            yield c
            stack.extend(c.children)

    def special_suffix(self, n: Node) -> str:
        """Parte anexable de una auxiliar especial: '2-55' -> '-55', '53.08' -> '.08'."""
        base = next((a for a in reversed(self.ancestors(n)) if a.kind == "main" and not a.is_range), None)
        if base and n.notation.startswith(base.notation):
            return n.notation[len(base.notation):]
        return n.notation

    def cancellation(self, notation: str) -> dict | None:
        """La cancelación más reciente de una notación que ya NO existe en el árbol (las reutilizadas no cuentan)."""
        if notation in self.by_notation or notation not in self.cancelled:
            return None
        return max(self.cancelled[notation], key=lambda c: c["year"] or 0)

    def see_also(self, n: Node) -> list[Node]:
        """Clases enlazadas por "See also" (skos:related), en ambos sentidos."""
        return [self.nodes[u] for u in n.related if u in self.nodes]

    def is_related(self, a: Node, b: Node) -> bool:
        """True si a y b son iguales, o uno es ancestro del otro."""
        if a.uri == b.uri:
            return True
        return a.uri in {x.uri for x in self.ancestors(b)} or b.uri in {x.uri for x in self.ancestors(a)}

    def roots(self, kind="main") -> list[Node]:
        return sorted([n for n in self.nodes.values() if n.parent is None and n.kind == kind and not n.is_range],
                      key=lambda n: self._sort_key(n.notation))

    def of_kind(self, kind: str, include_ranges=False) -> list[Node]:
        return [n for n in self.nodes.values() if n.kind == kind and (include_ranges or not n.is_range)]

    def indexable(self) -> list[Node]:
        """Nodos que se embeben: sin rangos/encabezados, sin signos (kind 'other') y con etiqueta
        (los nodos sin etiqueta parecen clases canceladas)."""
        return sorted([n for n in self.nodes.values() if not n.is_range and n.kind != "other" and n.labels],
                      key=lambda n: n.uri)

    def node_text(self, n: Node) -> str:
        """Texto que se embebe: ruta jerárquica | sinónimos | Including | ejemplos | nota."""
        lbl = lambda x: x.label(self.label_langs)
        path = " > ".join(lbl(x) for x in self.path(n))
        extra = "; ".join(n.alt[:6])
        inc = f"Including: {n.including[:200]}" if n.including else ""
        # solo los ejemplos que NO se volvieron nodo (combinaciones con : + ...): si el anfitrión llevara
        # también "Net investment", competiría contra su propio nodo de ejemplo y lo taparía
        own = [t for nt, t in n.examples if not (self.get(nt) and self.get(nt).origin == "example")]
        exs = "; ".join(own[:MAX_EXAMPLES_IN_TEXT])
        exs = f"e.g. {exs}" if exs else ""
        note = n.note[:200]
        return " | ".join(s for s in (path, extra, inc, exs, note) if s)

    def fingerprint(self) -> str:
        # incluye el texto embebido: si cambian notas o ejemplos, el índice se regenera
        h = hashlib.sha1()
        for n in sorted(self.nodes.values(), key=lambda n: n.uri):
            h.update(f"{n.uri}|{n.notation}|{n.parent}|{self.node_text(n)}".encode("utf-8"))
        return h.hexdigest()

    def stats(self) -> dict:
        c = Counter(n.kind for n in self.nodes.values())
        main = [n for n in self.nodes.values() if n.kind == "main" and not n.is_range]
        depth = Counter(n.depth for n in main)
        return {"nodos": len(self.nodes), "por_tabla": dict(c),
                "rangos": sum(n.is_range for n in self.nodes.values()),
                "raices_main": [n.notation for n in self.roots("main")],
                "sin_padre": sum(1 for n in self.nodes.values() if n.parent is None),
                "main_por_profundidad": dict(sorted(depth.items())),
                "con_ejemplos": sum(1 for n in self.nodes.values() if n.examples),
                "nodos_de_ejemplo": sum(1 for n in self.nodes.values() if n.origin == "example"),
                "con_including": sum(1 for n in self.nodes.values() if n.including),
                "marca_auxiliar_oficial": self.official_aux,
                "con_see_also": sum(1 for n in self.nodes.values() if n.related),
                "notaciones_canceladas": len(self.cancelled),
                "sin_etiqueta_en": sum(1 for n in self.nodes.values() if "en" not in n.labels)}
