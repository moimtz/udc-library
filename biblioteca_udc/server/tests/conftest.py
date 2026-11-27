"""Test fixtures: every test gets an empty data folder, a fresh database and a signed-in editor.

Run from biblioteca_udc/server:  python -m pytest tests
"""
import functools
import json
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

import config  # noqa: E402


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    for name, sub in (("LIBRARY_DIR", "library"), ("COVERS_DIR", "covers"), ("TRASH_DIR", "trash"),
                      ("TMP_DIR", "tmp"), ("BACKUP_DIR", "backups")):
        monkeypatch.setattr(config, name, tmp_path / sub)
    monkeypatch.setattr(config, "JSON_BACKUP_DIR", tmp_path / "backups" / "json")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "biblioteca.db")
    monkeypatch.setattr(config, "CLASSIFIER_URL", "")   # never the real classifier service (test_classifier fakes it)
    return tmp_path


@pytest.fixture
def conn(data_dir):
    import db
    db.init_db()
    c = db.connect()
    # a few real UDC classes (the seed has only the ten main classes)
    for code, parent in (("00", "0"), ("004", "00"), ("004.8", "004"), ("53", "5"), ("53.08", "53"),
                         ("61", "6"), ("62", "6"), ("62-1", "62"), ("(4)", None), ("(46)", "(4)"),
                         ("(460)", "(46)"), ('"18"', None), ("=1", None), ("=13", "=1"), ("=134", "=13")):
        c.execute("INSERT OR IGNORE INTO udc_nodes(code, parent, labels, ord) VALUES (?,?,?,0)",
                  (code, parent, json.dumps({"en": code})))
    c.commit()
    yield c
    c.close()


@pytest.fixture
def client(conn):
    from fastapi.testclient import TestClient

    import security
    from db import now
    from main import app

    uid = conn.execute("INSERT INTO users(username, pw_hash, role, created_at) VALUES ('ed', 'x', 'editor', ?)",
                       (now(),)).lastrowid
    conn.commit()
    token = security.create_session(conn, uid)
    c = TestClient(app)   # no `with`: the lifespan (init_db + maintenance) is not needed
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@functools.lru_cache(maxsize=None)   # same arguments -> same bytes (PyMuPDF adds a new file ID each time)
def make_pdf(text: str = "Hello", pages: int = 2, title: str = "", author: str = "") -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"{text} - page {i + 1}")
    if title or author:
        doc.set_metadata({"title": title, "author": author})
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def upload(client):
    def _upload(text="Hello", **kw):
        r = client.post("/api/uploads", files={"file": ("doc.pdf", make_pdf(text, **kw), "application/pdf")})
        assert r.status_code == 200, r.text
        return r.json()
    return _upload


@pytest.fixture
def add_item(client, upload):
    def _add(item: dict, text: str | None = None, **kw):
        up = upload(text or json.dumps(item, sort_keys=True))
        r = client.post("/api/items", json={"temp_id": up["temp_id"], "item": item, **kw})
        return r
    return _add
