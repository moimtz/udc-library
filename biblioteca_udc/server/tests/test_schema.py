"""Catalog sync and database integrity."""
import json
import sqlite3

import pytest

import catalog


def count(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_catalog_counts(conn):
    assert count(conn, "SELECT COUNT(*) FROM item_types") == 37
    assert count(conn, "SELECT COUNT(*) FROM item_types WHERE enabled=1") == 20
    assert count(conn, "SELECT COUNT(*) FROM fields") == 123
    assert count(conn, "SELECT COUNT(*) FROM item_type_fields") == 767
    assert count(conn, "SELECT COUNT(*) FROM creator_types") == 37
    assert count(conn, "SELECT COUNT(*) FROM item_type_creators") == 170
    assert not conn.execute("SELECT 1 FROM item_types WHERE code IN ('attachment','note','annotation')").fetchone()


def test_catalog_details(conn):
    cat = catalog.get(conn)
    assert cat.types["dictionaryEntry"]["enabled"] and not cat.types["film"]["enabled"]
    assert cat.label("type", "book", "es-ES") == "Libro"
    assert cat.field_kind("date") == "date" and cat.field_kind("dateDecided") == "date"
    assert cat.field_kind("filingDate") == "date" and cat.field_kind("accessDate") == "date"
    assert cat.field_kind("abstractNote") == "longtext" and cat.field_kind("url") == "url"
    assert cat.field_kind("publisher") == "text"
    assert cat.fields["citationKey"]["hidden"]
    assert cat.base_of("thesis", "university") == "publisher"
    assert cat.field_for_base("thesis", "publisher") == "university"
    assert cat.field_for_base("report", "publisher") == "institution"
    assert cat.field_for_base("case", "title") == "caseName"
    assert {"university", "institution", "label", "publisher"} <= cat.variants("publisher")
    assert cat.primary_creator("patent") == "inventor"
    assert cat.primary_creator("book") == "author"
    # type-specific help from the overlay
    pres = {f["code"]: f for f in cat.payload()["types"][[t["code"] for t in cat.payload()["types"]].index(
        "presentation")]["fields"]}
    assert pres["place"]["help"] != cat.fields["place"]["help"]


def test_sync_is_idempotent(conn):
    assert catalog.sync(conn) is False
    assert catalog.sync(conn, force=True) is True
    assert count(conn, "SELECT COUNT(*) FROM item_type_fields") == 767


def test_sync_marks_dropped_field_obsolete_and_keeps_used_pairs(conn, monkeypatch):
    item = conn.execute("INSERT INTO items(citekey, item_type, added_at, modified_at) VALUES ('k','book','t','t')"
                        ).lastrowid
    conn.execute("INSERT INTO item_fields(item_id, field, value, source, updated_at) VALUES (?,?,?,?,?)",
                 (item, "numPages", "300", "manual", "t"))
    conn.commit()
    schema = json.loads(catalog.SCHEMA_PATH.read_text(encoding="utf-8"))
    for t in schema["itemTypes"]:
        t["fields"] = [f for f in t["fields"] if f["field"] != "numPages"]
    schema["version"] = 9999
    orig = catalog._load

    def fake_load():
        _, overlay, h = orig()
        return schema, overlay, h
    monkeypatch.setattr(catalog, "_load", fake_load)
    assert catalog.sync(conn)
    assert count(conn, "SELECT obsolete FROM fields WHERE code='numPages'") == 1
    # book still holds numPages (an item uses it); other types lost it
    assert count(conn, "SELECT COUNT(*) FROM item_type_fields WHERE field='numPages'") == 1


def test_triggers_block_fields_and_creators_outside_the_type(conn):
    item = conn.execute("INSERT INTO items(citekey, item_type, added_at, modified_at) VALUES ('k','thesis','t','t')"
                        ).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="field not allowed"):
        conn.execute("INSERT INTO item_fields(item_id, field, value, source, updated_at) VALUES (?,?,?,?,?)",
                     (item, "publisher", "X", "manual", "t"))
    with pytest.raises(sqlite3.IntegrityError, match="creator type not allowed"):
        conn.execute("INSERT INTO item_creators(item_id, position, creator_type, source) VALUES (?,0,'editor','manual')",
                     (item,))
    conn.execute("INSERT INTO item_fields(item_id, field, value, source, updated_at) VALUES (?,?,?,?,?)",
                 (item, "university", "UNAM", "manual", "t"))
    with pytest.raises(sqlite3.IntegrityError, match="convert fields"):
        conn.execute("UPDATE items SET item_type='book' WHERE id=?", (item,))
    with pytest.raises(sqlite3.IntegrityError, match="field not allowed"):
        conn.execute("UPDATE item_fields SET field='publisher' WHERE item_id=?", (item,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO items(citekey, item_type, added_at, modified_at) VALUES ('k2','nope','t','t')")


def test_attachment_rules(conn):
    item = conn.execute("INSERT INTO items(citekey, item_type, added_at, modified_at) VALUES ('k','book','t','t')"
                        ).lastrowid
    ins = ("INSERT INTO attachments(item_id, role, label, filename, sha256, size, mime, added_at) "
           "VALUES (?,?,?,?,'s',1,'application/pdf','t')")
    conn.execute(ins, (item, "main", "", "k.pdf"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (item, "main", "", "k2.pdf"))           # one main file per item
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(ins, (item, "supplementary", "", "k_s1.pdf"))  # supplementary needs a label
    conn.execute(ins, (item, "supplementary", "Errata", "k_s1.pdf"))
