"""Normalisation helpers, type conversion and UDC node resolution (no HTTP)."""
import catalog
import library as lib
import notation


def test_parse_date():
    assert lib.parse_date("2004") == "2004-00-00"
    assert lib.parse_date("March 2004") == "2004-03-00"
    assert lib.parse_date("marzo de 2004") == "2004-03-00"
    assert lib.parse_date("12 March 2004") == "2004-03-12"
    assert lib.parse_date("March 12, 2004") == "2004-03-12"
    assert lib.parse_date("2004-03-12") == "2004-03-12"
    assert lib.parse_date("2004-3") == "2004-03-00"
    assert lib.parse_date("25/12/1998") == "1998-12-25"
    assert lib.parse_date("3/4/1998") == "1998-03-04"      # month first (en-US)
    assert lib.parse_date("c. 1850") == "1850-00-00"
    assert lib.parse_date("no date") is None and lib.parse_date("") is None


def test_norms():
    assert lib.norm_language("English") == "en" and lib.norm_language("Español") == "es"
    assert lib.norm_language("en-US") == "en" and lib.norm_language("spa") == "spa"
    assert lib.norm_doi("https://doi.org/10.1000/ABC") == "10.1000/abc"
    assert lib.isbn_digits("0-306-40615-2") == ["9780306406157"]
    assert lib.isbn_digits("978-0-306-40615-7 0306406152") == ["9780306406157"]
    assert lib.extra_vars("Type: musical_score\nOriginal Title: X\nfree text") == \
        {"type": "musical_score", "originaltitle": "X"}
    assert lib.sort_title("The Art of Fugue") == "art of fugue"
    assert lib.sort_title("El Álgebra") == "algebra"
    assert lib.sort_title("De Nachtwacht", "nl") == "nachtwacht"
    assert lib.sort_title("De la naturaleza", "es") == "de la naturaleza"    # preposition in Spanish
    assert lib.sort_title("L'Étranger", "fr") == "etranger"
    assert lib.sort_title("A Arte da Fuga", "pt") == "arte da fuga"


def test_citekey_any_script():
    from textutil import make_citekey
    assert make_citekey("Достоевский", "Преступление и наказание", 1866) == "dostoevskiyPrestuplenieNakazanie1866"
    assert make_citekey("Müller", "Die Geschichte der Chemie", 1990) == "mullerGeschichteChemie1990"


def test_nodes_for():
    known = {"004", "004.8", "61", "53.08", "62", "62-1", "(46)", "(460)", "\"18\"", "=134", "(0.034)"}
    assert notation.nodes_for("004.8:61", known) == ["004.8", "61"]
    assert notation.nodes_for("004.89", known) == ["004.8"]                 # deeper than the tree
    assert notation.nodes_for("94(460.1)\"1850\"", known) == ["(460)", "\"18\""]
    assert notation.nodes_for("62-1", known) == ["62", "62-1"]
    assert notation.nodes_for("811.134.2=134.2", known) == ["=134"]
    assert notation.nodes_for("53.08", known) == ["53.08"]


def v(value, source="manual", confidence=None, confirmed=True):
    return {"value": value, "source": source, "confidence": confidence, "confirmed": confirmed}


def test_convert_thesis_report_book(conn):
    cat = catalog.get(conn)
    res = catalog.convert(cat, "thesis", "report", {"title": v("T"), "university": v("UNAM", "crossref", 0.9),
                                                    "thesisType": v("PhD")}, [])
    assert res["fields"]["institution"]["value"] == "UNAM"
    assert res["fields"]["institution"]["source"] == "crossref"    # provenance travels with the value
    assert res["fields"]["reportType"]["value"] == "PhD"           # thesisType -> type -> reportType
    assert res["report"]["moved"] == [{"from": "university", "to": "institution"},
                                      {"from": "thesisType", "to": "reportType"}]

    res = catalog.convert(cat, "book", "thesis",
                          {"title": v("T"), "publisher": v("Springer"), "edition": v("2"),
                           "extra": v("Type: musical_score")},
                          [{"creator_type": "author", "last_name": "A"}, {"creator_type": "editor", "last_name": "E"}])
    assert res["fields"]["university"]["value"] == "Springer"
    assert res["fields"]["extra"]["value"] == "Type: musical_score\nEdition: 2"
    assert res["report"]["to_extra"] == [{"field": "edition", "label": "Edition", "value": "2"}]
    assert [c["creator_type"] for c in res["creators"]] == ["author", "contributor"]

    res = catalog.convert(cat, "book", "patent", {"title": v("T")}, [{"creator_type": "author", "last_name": "A"}])
    assert res["creators"][0]["creator_type"] == "inventor"        # primary role -> primary role

    res = catalog.convert(cat, "book", "case", {"title": v("Roe v. Wade")}, [])
    assert res["fields"]["caseName"]["value"] == "Roe v. Wade"


def test_fit_to_type(conn):
    cat = catalog.get(conn)
    fields, extra = lib.fit_to_type(cat, "bookSection", {"publicationTitle": "Handbook", "archiveID": "arXiv:1"})
    assert fields == {"bookTitle": "Handbook"}
    assert extra == ["Archive ID: arXiv:1"]
    fields, _ = lib.fit_to_type(cat, "conferencePaper", {"bookTitle": "Proc."})
    assert fields == {"proceedingsTitle": "Proc."}
