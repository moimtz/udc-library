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
]

# skos:example por notación (formato de udc_merge.py: "notación    texto"). Caso de validación real: UDC Online.
EXAMPLES = {"330.322": ["330.322.01    Investment theory", "330.322.011    Investment criteria",
                        "330.322.014    Volume of investment", "330.322.014.3    Net investment",
                        "330.322.014.4    Gross investment", "330.322.014.6    Investment quota",
                        "330.322:94    History of investments"]}   # combinación: no se vuelve nodo


def rdf_xml() -> str:
    uri = lambda n: "http://udcdata.info/" + "".join(c if c.isalnum() else "_%02x" % ord(c) for c in n)
    out = ['<?xml version="1.0"?>', '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
           'xmlns:skos="http://www.w3.org/2004/02/skos/core#" xmlns:xml="http://www.w3.org/XML/1998/namespace">']
    for nt, lbl, parent in CONCEPTS:
        if nt == "1/9-range":
            continue
        out.append(f'<skos:Concept rdf:about="{uri(nt)}"><skos:notation>{escape(nt)}</skos:notation>'
                   f'<skos:prefLabel xml:lang="en">{escape(lbl)}</skos:prefLabel>'
                   f'<skos:prefLabel xml:lang="fi">{escape(lbl)}fi</skos:prefLabel>')
        if parent:
            out.append(f'<skos:broader rdf:resource="{uri(parent)}"/>')
        for ex in EXAMPLES.get(nt, []):
            out.append(f'<skos:example xml:lang="en">{escape(ex)}</skos:example>')
        out.append("</skos:Concept>")
    out.append("</rdf:RDF>")
    return "\n".join(out)
