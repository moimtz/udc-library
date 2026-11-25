"""HTTP API on the Zotero model: items, provenance, type change, attachments, duplicates, search, trash."""
import config
import library as lib

BOOK = {
    "item_type": "book",
    "fields": {"title": "Introducción a la teoría de conjuntos", "date": "March 1998", "publisher": "Springer",
               "edition": "2", "ISBN": "0-306-40615-2", "language": "Español", "citationKey": "ignored"},
    "creators": [{"creator_type": "author", "last_name": "García", "first_name": "Ana"},
                 {"creator_type": "editor", "last_name": "Pérez", "first_name": "Luis"}],
    "tags": ["sets", "logic", "Sets"],
    "udc": ["510.22", "004.8:61"],
}


def test_schema_endpoint(client):
    r = client.get("/api/schema", params={"lang": "es-ES"})
    assert r.status_code == 200
    s = r.json()
    book = next(t for t in s["types"] if t["code"] == "book")
    assert book["label"] == "Libro" and book["enabled"]
    assert [f["code"] for f in book["fields"]][:3] == ["title", "abstractNote", "series"]
    assert next(f for f in book["fields"] if f["code"] == "citationKey")["hidden"]
    assert book["creator_types"][0] == {**book["creator_types"][0], "code": "author", "primary": True}
    assert "es-ES" in s["languages"] and s["zotero_schema_version"] == "45"


def test_create_and_read_item(client, add_item, conn):
    r = add_item(BOOK)
    assert r.status_code == 201, r.text
    it = r.json()
    assert it["citekey"] == "garciaIntroduccionTeoriaConjuntos1998"
    assert it["title"] == BOOK["fields"]["title"] and it["year"] == 1998 and it["language"] == "es"
    assert it["date_sort"] == "1998-03-00"
    assert "citationKey" not in it["fields"]
    assert it["fields"]["publisher"] == {"value": "Springer", "source": "manual", "confidence": None,
                                         "confirmed": True}
    assert [t["name"] for t in it["tags"]] == ["logic", "sets"]
    assert [u["notation"] for u in it["udc"]] == ["510.22", "004.8:61"]
    assert it["main"]["filename"] == "garciaIntroduccionTeoriaConjuntos1998.pdf"
    assert (config.LIBRARY_DIR / it["main"]["filename"]).exists()
    nodes = {r[0] for r in conn.execute("SELECT node_code FROM item_udc_nodes WHERE item_id=?", (it["id"],))}
    assert nodes == {"5", "004.8", "61"}     # 510.22 falls back to the seed class 5
    row = conn.execute("SELECT norm FROM item_fields WHERE item_id=? AND field='ISBN'", (it["id"],)).fetchone()
    assert row[0] == "9780306406157"
    assert client.get(f"/api/items/{it['id']}/file").status_code == 200
    assert client.get(f"/api/items/{it['id']}/cover").status_code == 200


def test_validation(client, add_item):
    r = add_item({"item_type": "thesis", "fields": {"title": "T", "publisher": "X"}})
    assert r.status_code == 422 and "publisher" in r.json()["detail"]
    r = add_item({"item_type": "film", "fields": {"title": "T"}})
    assert r.status_code == 422 and "not available" in r.json()["detail"]
    r = add_item({"item_type": "thesis", "fields": {"title": "T"}, "creators": [{"creator_type": "editor",
                                                                                 "last_name": "E"}]})
    assert r.status_code == 422
    r = add_item({"item_type": "case", "fields": {"caseName": ""}})
    assert r.status_code == 422 and "Case Name" in r.json()["detail"]
    r = add_item({"item_type": "book", "fields": {"title": {"value": "T", "source": "guess"}}})
    assert r.status_code == 422


def test_provenance_on_save(client, add_item):
    item = {"item_type": "journalArticle",
            "fields": {"title": {"value": "Deep nets", "source": "crossref", "confidence": 0.9},
                       "publicationTitle": {"value": "Nature", "source": "crossref", "confidence": 0.9},
                       "volume": {"value": "5", "source": "crossref", "confidence": 0.9}},
            "creators": [{"creator_type": "author", "last_name": "Li", "source": "crossref", "confidence": 0.9}]}
    it = add_item(item).json()
    assert it["fields"]["title"] == {"value": "Deep nets", "source": "crossref", "confidence": 0.9,
                                     "confirmed": True}
    assert it["creators"][0]["source"] == "crossref" and it["creators"][0]["confirmed"]
    # a person edits the volume; the other values stay as accepted
    upd = {**item, "fields": {**it["fields"], "volume": "6"}}
    upd["fields"] = {k: (v["value"] if isinstance(v, dict) else v) for k, v in upd["fields"].items()}
    it2 = client.put(f"/api/items/{it['id']}", json=upd).json()
    assert it2["fields"]["title"]["source"] == "crossref"      # unchanged value keeps its source
    assert it2["fields"]["volume"] == {"value": "6", "source": "manual", "confidence": None, "confirmed": True}


def test_automatic_values_respect_confirmed(client, add_item, conn):
    it = add_item({"item_type": "book", "fields": {"title": "T", "publisher": "Springer"}}).json()
    r = client.post(f"/api/items/{it['id']}/auto", json={"fields": {
        "publisher": {"value": "Wiley", "source": "llm", "confidence": 0.99},
        "place": {"value": "Berlin", "source": "llm", "confidence": 0.5},
        "university": {"value": "UNAM", "source": "llm", "confidence": 0.5}},
        "udc": {"notation": "53.08", "source": "classifier", "confidence": 0.7}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["item"]["fields"]["publisher"]["value"] == "Springer"
    assert out["item"]["fields"]["place"] == {"value": "Berlin", "source": "llm", "confidence": 0.5,
                                              "confirmed": False}
    reasons = {s["field"]: s["reason"] for s in out["suggestions"]}
    assert reasons == {"publisher": "confirmed", "university": "no such field for this type"}
    assert out["item"]["udc"] == [{"notation": "53.08", "source": "classifier", "confidence": 0.7,
                                   "confirmed": False}]
    # unconfirmed: a less confident value does not replace it, a more confident one does
    out = client.post(f"/api/items/{it['id']}/auto", json={"fields": {
        "place": {"value": "Bonn", "source": "ner", "confidence": 0.4}}}).json()
    assert out["item"]["fields"]["place"]["value"] == "Berlin" and out["suggestions"][0]["reason"] == "less confident"
    out = client.post(f"/api/items/{it['id']}/auto", json={"fields": {
        "place": {"value": "Bonn", "source": "ner", "confidence": 0.8}}}).json()
    assert out["item"]["fields"]["place"]["value"] == "Bonn"
    # the classifier does not replace a notation a person confirmed
    client.put(f"/api/items/{it['id']}", json={"item_type": "book", "fields": {"title": "T", "publisher": "Springer",
                                                                                "place": "Bonn"}, "udc": ["53.08"]})
    out = client.post(f"/api/items/{it['id']}/auto", json={"udc": {"notation": "62-1", "source": "classifier",
                                                                     "confidence": 0.99}}).json()
    assert out["item"]["udc"][0]["notation"] == "53.08" and out["item"]["udc"][0]["source"] == "classifier"
    assert out["suggestions"][0]["notation"] == "62-1"


def test_type_change(client, add_item):
    it = add_item({"item_type": "book", "fields": {"title": "T", "publisher": "UNAM", "edition": "2"},
                   "creators": [{"creator_type": "author", "last_name": "A"},
                                {"creator_type": "editor", "last_name": "E"}]}).json()
    r = client.post(f"/api/items/{it['id']}/type", json={"item_type": "thesis", "dry_run": True}).json()
    assert r["report"]["to_extra"][0]["field"] == "edition"
    assert client.get(f"/api/items/{it['id']}").json()["item_type"] == "book"
    r = client.post(f"/api/items/{it['id']}/type", json={"item_type": "thesis"}).json()
    t = r["item"]
    assert t["item_type"] == "thesis" and t["fields"]["university"]["value"] == "UNAM"
    assert t["fields"]["extra"]["value"] == "Edition: 2"
    assert [c["creator_type"] for c in t["creators"]] == ["author", "contributor"]

    # the app's way: convert the form, then save it with the new type
    conv = client.post("/api/convert-type", json={"from_type": "thesis", "to_type": "report",
                                                   "fields": {k: v["value"] for k, v in t["fields"].items()},
                                                   "creators": t["creators"]}).json()
    saved = client.put(f"/api/items/{it['id']}", json={"item_type": "report", "fields": conv["fields"],
                                                        "creators": conv["creators"]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["fields"]["institution"]["value"] == "UNAM"


def test_supplementary_material(client, add_item, upload):
    it = add_item(BOOK).json()
    up = upload("errata")
    assert client.post(f"/api/items/{it['id']}/attachments", json={"temp_id": up["temp_id"], "label": " "}
                       ).status_code == 422
    r = client.post(f"/api/items/{it['id']}/attachments", json={"temp_id": up["temp_id"], "label": "Errata"})
    assert r.status_code == 201, r.text
    sup = [a for a in r.json()["attachments"] if a["role"] == "supplementary"]
    assert sup[0]["filename"] == f"{it['citekey']}_s1.pdf" and sup[0]["label"] == "Errata"
    assert client.get(f"/api/attachments/{sup[0]['id']}/file").status_code == 200
    # the same file again: duplicate (also detected when uploading it as a new item)
    again = upload("errata")
    assert again["duplicates"][0]["reason"] == "Identical file"
    assert client.post(f"/api/items/{it['id']}/attachments", json={"temp_id": again["temp_id"],
                                                                     "label": "X"}).status_code == 409
    up2 = upload("solutions")
    it2 = client.post(f"/api/items/{it['id']}/attachments", json={"temp_id": up2["temp_id"],
                                                                   "label": "Solutions"}).json()
    ids = [a["id"] for a in it2["attachments"] if a["role"] == "supplementary"]
    it3 = client.put(f"/api/items/{it['id']}/attachments/order", json={"ids": ids[::-1]}).json()
    assert [a["label"] for a in it3["attachments"] if a["role"] == "supplementary"] == ["Solutions", "Errata"]
    main_id = it["main"]["id"]
    assert client.delete(f"/api/attachments/{main_id}").status_code == 409
    assert client.delete(f"/api/attachments/{ids[0]}").json() == {"ok": True}
    assert (config.TRASH_DIR / f"{it['citekey']}_s1.pdf").exists()
    client.post(f"/api/attachments/{ids[0]}/restore")
    assert (config.LIBRARY_DIR / f"{it['citekey']}_s1.pdf").exists()
    # regenerating the citekey renames every file
    upd = {"item_type": "book", "fields": {"title": "Otro título", "date": "2001"}, "regen_citekey": True}
    it4 = client.put(f"/api/items/{it['id']}", json=upd).json()
    assert it4["citekey"] == "anonOtroTitulo2001"
    assert sorted(a["filename"] for a in it4["attachments"]) == \
        ["anonOtroTitulo2001.pdf", "anonOtroTitulo2001_s1.pdf", "anonOtroTitulo2001_s2.pdf"]
    assert all((config.LIBRARY_DIR / a["filename"]).exists() for a in it4["attachments"])


def test_duplicates(client, add_item):
    add_item({"item_type": "journalArticle", "fields": {"title": "A study of things", "DOI": "10.1/ABC"}})
    add_item({"item_type": "book", "fields": {"title": "Old book", "extra": "DOI: 10.2/xyz"}})
    add_item({"item_type": "book", "fields": {"title": "Graph theory and its applications", "date": "2005",
                                              "ISBN": "9780306406157"},
              "creators": [{"creator_type": "author", "last_name": "Gross"}]})
    r = add_item({"item_type": "journalArticle", "fields": {"title": "Other", "DOI": "https://doi.org/10.1/abc"}})
    assert r.status_code == 409 and r.json()["detail"]["duplicates"][0]["reason"] == "Same DOI"
    r = add_item({"item_type": "journalArticle", "fields": {"title": "Other", "DOI": "10.2/XYZ"}})
    assert r.json()["detail"]["duplicates"][0]["reason"] == "Same DOI"
    r = add_item({"item_type": "book", "fields": {"title": "Other", "ISBN": "0-306-40615-2"}})
    assert r.json()["detail"]["duplicates"][0]["reason"] == "Same ISBN"
    r = add_item({"item_type": "book", "fields": {"title": "Graph Theory and its Applications.", "date": "2005"},
                  "creators": [{"creator_type": "author", "last_name": "Gross"}]})
    assert r.json()["detail"]["duplicates"][0]["reason"].startswith("Very similar title")
    assert add_item({"item_type": "book", "fields": {"title": "Graph Theory and its Applications.",
                                                     "date": "2005"}}, duplicate_action="keep_both").status_code == 201


def test_replace_duplicate(client, add_item, upload):
    it = add_item({"item_type": "book", "fields": {"title": "First"}}).json()
    up = upload("new scan")
    r = client.post("/api/items", json={"temp_id": up["temp_id"], "duplicate_action": "replace",
                                        "replace_id": it["id"], "item": {"item_type": "book",
                                                                         "fields": {"title": "First (2nd scan)"}}})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["id"] == it["id"] and out["main"]["sha256"] == up["sha256"]
    assert out["title"] == "First (2nd scan)"


def test_search_and_filters(client, add_item):
    add_item({"item_type": "thesis", "fields": {"title": "Redes neuronales", "university": "UNAM", "date": "2010"},
              "udc": ["004.8"]})
    add_item({"item_type": "book", "fields": {"title": "Física", "publisher": "Reverté", "date": "1990",
                                              "language": "es"}, "udc": ["53.08"]})
    r = client.get("/api/items", params={"q": "unam", "field": "publisher"}).json()
    assert r["total"] == 1 and r["items"][0]["matches"] == {"university": [[0, 4]]}
    assert client.get("/api/items", params={"q": "fisica"}).json()["total"] == 1       # accents folded
    assert client.get("/api/items", params={"udc": "00"}).json()["total"] == 1          # descendants
    assert client.get("/api/items", params={"udc": "none"}).json()["total"] == 0
    assert client.get("/api/items", params={"year_from": 2000}).json()["total"] == 1
    assert client.get("/api/items", params={"language": "Spanish"}).json()["total"] == 1
    r = client.get("/api/items", params={"sort": "year", "order": "desc"}).json()
    assert [i["year"] for i in r["items"]] == [2010, 1990]
    tree = client.get("/api/udc/tree").json()
    counts = {n["code"]: n["count"] for n in tree["nodes"]}
    assert counts["004.8"] == 1 and counts["0"] == 1 and counts["5"] == 1 and tree["unclassified"] == 0


def test_notes(client, add_item):
    it = add_item({"item_type": "book", "fields": {"title": "T"}}).json()
    it = client.post(f"/api/items/{it['id']}/notes", json={"body": "Check chapter 3"}).json()
    note = it["notes"][0]
    it = client.put(f"/api/notes/{note['id']}", json={"body": "Chapter 4"}).json()
    assert it["notes"][0]["body"] == "Chapter 4"
    assert client.delete(f"/api/notes/{note['id']}").json()["notes"] == []


def test_trash_cycle(client, add_item, conn):
    it = add_item({"item_type": "book", "fields": {"title": "T"}}).json()
    name = it["main"]["filename"]
    client.delete(f"/api/items/{it['id']}")
    assert (config.TRASH_DIR / name).exists() and not (config.LIBRARY_DIR / name).exists()
    assert client.get(f"/api/items/{it['id']}").status_code == 404
    assert client.get("/api/trash").json()["items"][0]["id"] == it["id"]
    client.post(f"/api/trash/{it['id']}/restore")
    assert (config.LIBRARY_DIR / name).exists()
    client.delete(f"/api/items/{it['id']}")
    assert client.delete(f"/api/trash/{it['id']}").json() == {"ok": True}
    assert not (config.TRASH_DIR / name).exists()
    assert conn.execute("SELECT COUNT(*) FROM item_fields").fetchone()[0] == 0     # cascade
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0


def test_upload_guess_and_stats(client, upload):
    up = upload("x", title="A Real Title", author="Smith, John")
    assert up["guess"]["fields"]["title"] == {"value": "A Real Title", "source": "pdfmeta", "confidence": 0.3}
    assert up["guess"]["creators"][0]["last_name"] == "Smith"
    assert client.get("/api/stats").json()["items"] == 0


def test_lookup_results_fit_the_type(monkeypatch, client, conn):
    import lookup
    msg = {"type": "book-chapter", "title": ["Chapter"], "container-title": ["Big Handbook"],
           "author": [{"family": "Doe", "given": "J."}], "issued": {"date-parts": [[2019, 5]]},
           "DOI": "10.5/x", "publisher": "CRC", "page": "1-20", "subject": ["Physics"]}
    monkeypatch.setattr(lookup, "lookup_doi", lambda doi: lookup.parse_crossref(msg))
    r = client.post("/api/autofill", json={"doi": "10.5/x"}).json()
    assert r["item_type"] == "bookSection" and r["source"] == "crossref"
    assert r["fields"]["bookTitle"]["value"] == "Big Handbook"
    assert r["fields"]["date"]["value"] == "2019-05"
    assert r["tags"] == [{"name": "Physics", "source": "crossref"}]
    assert lib.parse_date(r["fields"]["date"]["value"]) == "2019-05-00"
