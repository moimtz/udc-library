"""Bulk import (bulk_import.py) and type <-> UDC form coherence (coherence.py)."""
import hashlib
import json

import pytest

import bulk_import
import coherence
import config
import library as lib
from db import now
from tests.conftest import make_pdf


# --------------------------------------------------------------------------- coherence
def test_form_coherence(conn):
    def kinds(t, udc, extra=""):
        return [w["kind"] for w in coherence.check(conn, t, udc, extra)]

    assert kinds("thesis", ["53(043.2)=134"]) == []                  # (043) covers (043.2)
    assert kinds("thesis", ["53=134"]) == ["missing_form"]
    assert kinds("thesis", ["53(04)"]) == ["missing_form"]           # (04) is broader than (043)
    assert kinds("book", ["53(043)"]) == ["unexpected_form"]          # (043) implies a thesis
    assert kinds("book", ["53(075.8)"]) == []                         # books have no expected form
    assert kinds("standard", ["004(083.742)"]) == []
    assert kinds("journalArticle", ["53(083.74)"]) == ["missing_form", "unexpected_form"]
    assert kinds("statute", ["34(460)"]) == ["missing_form"]          # (460) is a place, not a form
    assert kinds("book", ["53"], "Type: musical_score") == ["score_not_78"]
    assert kinds("book", ["780.8:78.083.2"], "Type: musical_score") == []
    assert kinds("thesis", []) == []                                  # no UDC yet: nothing to compare


def test_udc_check_and_item_warnings(client, add_item):
    r = client.get("/api/udc/check", params={"udc": "53", "item_type": "thesis"})
    assert [w["kind"] for w in r.json()["form"]] == ["missing_form"]
    assert client.get("/api/udc/check", params={"udc": "53"}).json()["form"] == []
    it = add_item({"item_type": "patent", "fields": {"title": "Lamp"}, "udc": ["62"]}).json()
    assert [w["kind"] for w in it["warnings"]] == ["missing_form"]


def test_save_item_unconfirmed(conn):
    iid = lib.save_item(conn, None, {
        "item_type": "book",
        "fields": {"title": {"value": "T", "source": "layout", "confidence": 0.5}, "date": "2001"},
        "creators": [{"creator_type": "author", "last_name": "A", "source": "ner", "confidence": 0.4}],
        "udc": [{"notation": "53", "source": "classifier", "confidence": 0.3}]}, confirm=False)
    it = lib.load_item(conn, iid)
    assert not it["fields"]["title"]["confirmed"] and it["fields"]["date"]["confirmed"]   # manual stays confirmed
    assert not it["creators"][0]["confirmed"] and not it["udc"][0]["confirmed"]


# --------------------------------------------------------------------------- bulk import
@pytest.fixture
def batch(tmp_path, conn):
    """A folder with 3 PDFs (one an exact copy), the classifier's results for two of them and an editor."""
    folder = tmp_path / "pdfs"
    (folder / "sub").mkdir(parents=True)
    a, b = make_pdf("Alpha physics", pages=3), make_pdf("Beta thesis", pages=2)
    (folder / "alpha.pdf").write_bytes(a)
    (folder / "sub" / "beta.pdf").write_bytes(b)
    (folder / "copy of alpha.pdf").write_bytes(a)
    (folder / "lonely.pdf").write_bytes(make_pdf("Not analysed"))

    def rec(data, name, itype, fields, udc, pages_used, low=False):
        return {"file": f"C:\\laptop\\books\\{name}", "sha1": hashlib.sha1(data).hexdigest(),
                "item_type": {"value": itype, "confidence": 0.8}, "fields": fields, "pages_used": pages_used,
                "classification": {"low_confidence": low, "note": "", "suggestions": [
                    {"rank": 1, "udc": udc, "confidence": 0.6, "main": [{"label": "Physics"}],
                     "explain": {"retroceder_a": ["5 Science"]}},
                    {"rank": 2, "udc": "61", "confidence": 0.2, "main": [{"label": "Medicine"}]}]}}

    results = tmp_path / "results.json"
    results.write_text(json.dumps([
        rec(a, "alpha.pdf", "book", {
            "title": {"value": "Alpha Physics", "source": "layout+openlibrary", "confidence": 0.9},
            "date": {"value": "1999", "source": "regex:copyright", "confidence": 0.8},
            "language": {"value": "en", "source": "py3langid", "confidence": 1.0},
            "numPages": {"value": 3, "source": "pdf", "confidence": 1.0},
            "creators": {"value": [{"creatorType": "author", "firstName": "Ann", "lastName": "Smith"}],
                         "source": "openlibrary", "confidence": 0.9},
            "tags": {"value": ["Physics"], "source": "openlibrary", "confidence": 0.9}}, "53", [2, 3]),
        rec(b, "beta.pdf", "book", {
            "title": {"value": "Beta", "source": "layout", "confidence": 0.3}}, "53", [], low=True),
    ]), encoding="utf-8")
    gold = tmp_path / "gold.csv"
    gold.write_text("file,udc,nota\nbeta.pdf,53(043.2),checked by hand\n", encoding="utf-8")
    uid = conn.execute("INSERT INTO users(username, pw_hash, role, created_at) VALUES ('ed','x','editor',?)",
                       (now(),)).lastrowid
    conn.commit()
    return {"folder": folder, "results": results, "gold": gold, "uid": uid, "plan": folder / "import_plan.xlsx"}


def _rows(plan):
    return {r["file"]: r for r in bulk_import.read_xlsx(plan)}


def _edit(plan, file, **cols):
    from openpyxl import load_workbook
    wb = load_workbook(plan)
    ws = wb.active
    head = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        if row[head.index("file")].value == file:
            for k, v in cols.items():
                row[head.index(k)].value = v
    wb.save(plan)


def test_source_mapping():
    m = bulk_import.map_source
    assert m("filename+openlibrary") == "openlibrary" and m("regex:año_más_frecuente") == "regex"
    assert m("py3langid") == "langid" and m("pdf") == "pdfmeta" and m("pdfmeta:creationDate") == "pdfmeta"
    assert m("layout+filename") == "layout" and m("rules") == "import" and m("manual") == "import"


def test_plan_writes_nothing(batch, conn):
    bulk_import.main(["plan", str(batch["results"]), str(batch["folder"]), "--gold", str(batch["gold"])])
    assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 0
    rows = _rows(batch["plan"])
    assert set(rows) == {"alpha.pdf", "sub/beta.pdf", "copy of alpha.pdf", "lonely.pdf"}
    assert rows["alpha.pdf"]["to_review"] == ""
    assert rows["alpha.pdf"]["action"] == "load" and rows["alpha.pdf"]["cover_page"] == "2"
    assert rows["alpha.pdf"]["citekey"] == "smithAlphaPhysics1999"
    assert rows["copy of alpha.pdf"]["action"] == "skip" and "alpha.pdf" in rows["copy of alpha.pdf"]["duplicate_of"]
    assert rows["lonely.pdf"]["action"] == "skip" and "not analysed" in rows["lonely.pdf"]["to_review"]
    beta = rows["sub/beta.pdf"]
    assert beta["udc"] == "53(043.2)" and beta["udc_source"] == "gold"
    assert "UDC form does not fit the type" in beta["to_review"] and "Thesis" in beta["warnings"]


def test_load(batch, conn):
    bulk_import.main(["plan", str(batch["results"]), str(batch["folder"]), "--gold", str(batch["gold"])])
    _edit(batch["plan"], "sub/beta.pdf", type="thesis", title="Beta: a thesis", to_review="")
    _edit(batch["plan"], "alpha.pdf", cover_page="3")
    bulk_import.main(["load", str(batch["plan"]), "--user", "ed", "--yes", "--tag", "batch 1"])
    items = {it["title"]: it for it in lib.load_items(conn, [r[0] for r in conn.execute("SELECT id FROM items")])}
    assert set(items) == {"Alpha Physics", "Beta: a thesis"}
    a = items["Alpha Physics"]
    assert a["fields"]["title"] == {"value": "Alpha Physics", "source": "openlibrary", "confidence": 0.9,
                                    "confirmed": False}
    assert a["fields"]["language"]["source"] == "langid" and a["fields"]["numPages"]["value"] == "3"
    assert a["udc"] == [{"notation": "53", "source": "classifier", "confidence": 0.6, "confirmed": False}]
    assert {t["name"] for t in a["tags"]} == {"batch 1", "Physics"}                  # nothing to review
    assert a["main"]["cover_page"] == 3 and a["main"]["filename"] == "smithAlphaPhysics1999.pdf"
    assert (config.LIBRARY_DIR / a["main"]["filename"]).exists() and (batch["folder"] / "alpha.pdf").exists()
    assert "2. 61" in a["notes"][0]["body"]
    b = items["Beta: a thesis"]
    assert b["item_type"] == "thesis" and b["fields"]["title"]["confirmed"]          # edited -> manual
    assert b["udc"][0]["source"] == "manual" and b["udc"][0]["confirmed"]            # from the gold file
    assert {t["name"] for t in b["tags"]} == {"batch 1"}                             # to_review cleared
    assert b["warnings"] == [] and "checked by hand" in b["notes"][0]["body"]
    # running it again adds nothing
    bulk_import.main(["load", str(batch["plan"]), "--user", "ed", "--yes"])
    assert conn.execute("SELECT count(*) FROM items").fetchone()[0] == 2


def test_reference(batch, conn, tmp_path):
    """The PoC's referencia.csv: matched by SHA-256 (renamed file), its values win; 'verificado' rows are
    confirmed, 'propuesto' ones are not; a PDF the classifier did not analyse is loaded anyway."""
    import csv

    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    ref = tmp_path / "referencia.csv"
    cols = ["sha256", "archivo", "type", "title", "creators", "contributors", "date", "publisher", "ISBN",
            "udc", "udc_alternativas", "fuente_udc", "nota_udc", "cover_page", "estado", "observaciones"]
    with ref.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerow({"sha256": sha(batch["folder"] / "alpha.pdf"), "archivo": "old name.pdf", "type": "book",
                    "title": "Alpha Physics: An Introduction", "creators": "Smith, Ann; Jones, Bob",
                    "contributors": "Pérez, Ana (translator)", "date": "2001", "publisher": "Wiley",
                    "ISBN": "978-0-470-39818-0", "udc": "53(075.8)=111", "udc_alternativas": "530(075.8)=111",
                    "fuente_udc": "claude-opus-5-5", "cover_page": "1", "estado": "propuesto"})
        w.writerow({"sha256": sha(batch["folder"] / "lonely.pdf"), "archivo": "lonely.pdf", "type": "thesis",
                    "title": "Lonely thesis", "creators": "Doe, Jane", "date": "2010", "udc": "53(043.2)",
                    "estado": "verificado", "cover_page": "1"})
    bulk_import.main(["plan", str(batch["results"]), str(batch["folder"]), "--gold", str(ref)])
    rows = _rows(batch["plan"])
    a, lone = rows["alpha.pdf"], rows["lonely.pdf"]
    assert a["udc"] == "53(075.8)=111" and a["udc_source"] == "reference" and a["cover_page"] == "1"
    assert a["title"] == "Alpha Physics: An Introduction" and a["date"] == "2001"
    assert lone["action"] == "load" and lone["type"] == "thesis" and lone["to_review"] == ""
    bulk_import.main(["load", str(batch["plan"]), "--user", "ed", "--yes"])
    items = {it["title"]: it for it in lib.load_items(conn, [r[0] for r in conn.execute("SELECT id FROM items")])}
    ia, il = items["Alpha Physics: An Introduction"], items["Lonely thesis"]
    assert ia["udc"][0]["source"] == "import" and not ia["udc"][0]["confirmed"]
    assert ia["fields"]["publisher"]["value"] == "Wiley" and ia["fields"]["ISBN"]["source"] == "import"
    assert [c["creator_type"] for c in ia["creators"]] == ["author", "author", "translator"]
    assert "Also accepted: 530(075.8)=111" in ia["notes"][0]["body"]
    assert il["udc"][0]["confirmed"] and il["fields"]["title"]["confirmed"] and il["item_type"] == "thesis"


def test_load_needs_an_editor(batch, conn):
    bulk_import.main(["plan", str(batch["results"]), str(batch["folder"])])
    with pytest.raises(SystemExit, match="not an active editor"):
        bulk_import.main(["load", str(batch["plan"]), "--user", "nobody", "--yes"])
