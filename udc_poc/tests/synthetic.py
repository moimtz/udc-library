"""RDF sintético mínimo (formato SKOS/RDF-XML) para probar sin el archivo real."""
from xml.sax.saxutils import escape

CONCEPTS = [  # (notación, etiqueta en, notación del padre o None)
    ("0", "Science and knowledge. Organization. Computer science", None),
    ("004", "Computer science and technology. Computing. Data processing", "0"),
    ("3", "Social sciences", None), ("34", "Law. Jurisprudence", "3"),
    ("33", "Economics. Economic science", "3"), ("330.322", "Investments. Capital formation", "33"),
    ("5", "Mathematics. Natural sciences", None), ("51", "Mathematics", "5"), ("53", "Physics", "5"),
    ("6", "Applied sciences. Medicine. Technology", None), ("61", "Medical sciences. Medicine", "6"),
    ("62", "Engineering. Technology in general", "6"),
    ("7", "The arts. Recreation. Entertainment. Sport", None), ("78", "Music", "7"),
    ("8", "Language. Linguistics. Literature", None), ("82", "Literature", "8"),
    ("821", "Literatures of individual languages and language families", None),   # padre inferido por prefijo
    ("9", "Geography. Biography. History", None), ("94", "History", "9"),
    ("1/9-range", "x", None),
    ("=111", "English", None), ("=134.2", "Spanish", None),
    ("(0)", "Common auxiliaries of form", None), ("(02)", "Books in general", "(0)"),
    ("(03)", "Reference works", "(0)"), ("(043.2)", "Dissertations, theses", "(0)"),
    ("(075)", "Educational texts. Schoolbooks", "(0)"), ("(035)", "Handbooks. Manuals", "(0)"),
    ("(083.1)", "Patent specifications", "(0)"),
    ("(4)", "Europe", None), ("(460)", "Spain", "(4)"), ("(72)", "Mexico", None),
    ('"18"', "19th century", None), ('"19"', "20th century", None),
    ("-05", "Persons as agents", None),
    # "See also": par real de UDC Online (903.26 -> 2-533, auxiliar especial) y uno entre clases principales
    ("2", "Religion. Theology", None), ("2-533", "Object of worship", "2"),
    ("90", "Archaeology. Prehistory", "9"), ("903", "Prehistory. Prehistoric remains, artefacts, antiquities", "90"),
    ("903.26", "Objects of worship. Religious, cult objects", "903"),
    ("681.3", "Computer hardware. Computing machines", "62"),
]

# skos:related ("See also"), escrito en UN solo sentido como a veces en UDC Online: el PoC lo usa en los dos.
RELATED = {"903.26": ["2-533"], "004": ["681.3"]}

# Clases canceladas (udcx:CancelledClass de udc_merge.py): (notación, año, E&C, etiqueta, reemplazos).
# "94" está cancelada pero hoy existe (notación reutilizada): no debe contar como cancelada.
CANCELLED = [("568.1", 2011, "E&C33", "Reptilia. Fossil reptiles", ["53"]),
             ("(1-73)", 2002, "", "Federative spheres of activity", ["94", "34"]),
             ("94", 1994, "E&C16", "Mediaeval and modern history (in general)", ["94(4/9)"])]

# skos:example por notación (formato de udc_merge.py: "notación    texto"). Caso de validación real: UDC Online.
EXAMPLES = {"330.322": ["330.322.01    Investment theory", "330.322.011    Investment criteria",
                        "330.322.014    Volume of investment", "330.322.014.3    Net investment",
                        "330.322.014.4    Gross investment", "330.322.014.6    Investment quota",
                        "330.322:94    History of investments"]}   # combinación: no se vuelve nodo


def rdf_xml(extra=(), aux=None) -> str:
    """extra: conceptos adicionales (mismo formato que CONCEPTS); aux: {notación: "common"|"special"} -> udcx:auxType."""
    uri = lambda n: "http://udcdata.info/" + "".join(c if c.isalnum() else "_%02x" % ord(c) for c in n)
    out = ['<?xml version="1.0"?>', '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
           'xmlns:skos="http://www.w3.org/2004/02/skos/core#" xmlns:xml="http://www.w3.org/XML/1998/namespace">']
    for nt, lbl, parent in [*CONCEPTS, *extra]:
        if nt == "1/9-range":
            continue
        out.append(f'<skos:Concept rdf:about="{uri(nt)}"><skos:notation>{escape(nt)}</skos:notation>'
                   f'<skos:prefLabel xml:lang="en">{escape(lbl)}</skos:prefLabel>'
                   f'<skos:prefLabel xml:lang="fi">{escape(lbl)}fi</skos:prefLabel>')
        if parent:
            out.append(f'<skos:broader rdf:resource="{uri(parent)}"/>')
        if aux and aux.get(nt):
            out.append(f'<udcx:auxType xmlns:udcx="urn:udc:ext#">{aux[nt]}</udcx:auxType>')
        for r in RELATED.get(nt, []):
            out.append(f'<skos:related rdf:resource="{uri(r)}"/>')
        for ex in EXAMPLES.get(nt, []):
            out.append(f'<skos:example xml:lang="en">{escape(ex)}</skos:example>')
        out.append("</skos:Concept>")
    for nt, year, ec, label, repl in CANCELLED:
        out.append(f'<udcx:CancelledClass xmlns:udcx="urn:udc:ext#" xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
                   f'rdf:about="urn:udc:cancelled:{uri(nt)[len("http://udcdata.info/"):]}%40{year}">'
                   f'<udcx:cancelledNotation>{escape(nt)}</udcx:cancelledNotation>'
                   f'<rdfs:label xml:lang="en">{escape(label)}</rdfs:label>'
                   f'<udcx:cancelledYear>{year}</udcx:cancelledYear>'
                   + (f'<udcx:cancelledIn>{escape(ec)}</udcx:cancelledIn>' if ec else "")
                   + "".join(f'<udcx:replacedByNotation>{escape(r)}</udcx:replacedByNotation>' for r in repl)
                   + "</udcx:CancelledClass>")
    out.append("</rdf:RDF>")
    return "\n".join(out)
