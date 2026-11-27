"""Analyze button: the server's side of the classifier service (classifier.py), with the service faked."""
import hashlib
import time

import pytest

import classifier
import config
from tests.conftest import make_pdf


def record(udc="53", low=False):
    """A record as the service returns it (the PoC's results.json format)."""
    return {"file": "x.pdf", "sha1": "s1", "scanned": True, "ocr": True, "warnings": [],
            "item_type": {"value": "thesis", "confidence": 0.8},
            "fields": {"title": {"value": "Heat in metals", "source": "layout", "confidence": 0.7},
                       "date": {"value": "1999", "source": "regex:copyright", "confidence": 0.8},
                       "university": {"value": "UNAM", "source": "layout", "confidence": 0.6},
                       "creators": {"value": [{"creatorType": "author", "firstName": "Ann", "lastName": "Smith"}],
                                    "source": "layout", "confidence": 0.7},
                       "tags": {"value": ["heat"], "source": "regex", "confidence": 0.5}},
            "classification": {"low_confidence": low, "note": "check it", "suggestions": [
                {"rank": 1, "udc": udc, "confidence": 0.6, "main": [{"label": "Physics"}],
                 "aux": {"form": {"code": "(043)", "label": "Theses", "source": "rules"}},
                 "explain": {"retroceder_a": ["5 Science"]}},
                {"rank": 2, "udc": "61", "confidence": 0.2, "main": [{"label": "Medicine"}]}]}}


@pytest.fixture
def fake(monkeypatch):
    """A fake service: records the calls; jobs finish at once with `state['record']`."""
    state = {"calls": [], "record": record(), "status": "done", "jobs": {}}

    def call(method, path, body=None, timeout=5.0):
        state["calls"].append((method, path, body))
        if path == "/health":
            return {"ready": True, "error": None, "queue": 0}
        if path == "/jobs":
            jid = f"{len(state['jobs']):016x}"
            state["jobs"][jid] = body
            return {"job": jid}
        if path.startswith("/jobs/"):
            jid = path.rsplit("/", 1)[1]
            if jid not in state["jobs"]:
                raise classifier.UnknownJob()
            out = {"status": state["status"], "position": 0, "meta": state["jobs"][jid]["meta"]}
            if state["status"] == "done":
                out["result"] = state["record"]
            if state["status"] == "error":
                out["error"] = "boom"
            return out
        if path == "/learn":
            return {"job": "learn"}
        raise AssertionError(path)

    monkeypatch.setattr(config, "CLASSIFIER_URL", "http://fake")
    monkeypatch.setattr(classifier, "_call", call)
    classifier._health.update(t=0.0, value=None)
    return state


def test_unavailable_without_service(client):
    classifier._health.update(t=0.0, value=None)
    assert client.get("/api/classifier").json()["available"] is False
    up = client.post("/api/uploads", files={"file": ("a.pdf", make_pdf("unavail"), "application/pdf")}).json()
    r = client.post(f"/api/uploads/{up['temp_id']}/analyze", json={})
    assert r.status_code == 503


def test_analyze_upload(client, fake):
    assert client.get("/api/classifier").json()["available"] is True
    up = client.post("/api/uploads", files={"file": ("Smith - Heat.pdf", make_pdf("an"), "application/pdf")}).json()
    r = client.post(f"/api/uploads/{up['temp_id']}/analyze", json={})
    assert r.status_code == 202
    sent = fake["jobs"][r.json()["job"]]
    assert sent["name"] == "Smith - Heat.pdf" and sent["path"].endswith(f"{up['temp_id']}.pdf")
    res = client.get(f"/api/analyze/{r.json()['job']}").json()
    assert res["status"] == "done" and res["item_type"] == "thesis"
    assert res["fields"]["title"] == {"value": "Heat in metals", "source": "layout", "confidence": 0.7}
    assert res["fields"]["university"]["value"] == "UNAM"
    assert res["fields"]["date"]["source"] == "regex"
    assert res["creators"][0]["last_name"] == "Smith" and res["creators"][0]["source"] == "layout"
    assert [u["notation"] for u in res["udc"]] == ["53", "61"]
    assert res["udc"][0]["label"] == "Physics" and res["udc"][0]["broader"] == ["5 Science"]
    assert res["udc"][0]["aux"][0]["code"] == "(043)"
    assert res["tags"] == [{"name": "heat", "source": "regex"}]
    assert res["scanned"] and res["ocr"] and res["note"] == "check it"


def test_analyze_fits_the_requested_type(client, fake):
    up = client.post("/api/uploads", files={"file": ("a.pdf", make_pdf("fit"), "application/pdf")}).json()
    job = client.post(f"/api/uploads/{up['temp_id']}/analyze", json={"item_type": "book"}).json()["job"]
    res = client.get(f"/api/analyze/{job}").json()
    assert res["item_type"] == "book" and res["detected_type"]["value"] == "thesis"
    assert res["fields"]["publisher"]["value"] == "UNAM"          # university -> publisher (same base field)


def test_analyze_states_and_errors(client, fake):
    up = client.post("/api/uploads", files={"file": ("a.pdf", make_pdf("st"), "application/pdf")}).json()
    job = client.post(f"/api/uploads/{up['temp_id']}/analyze", json={}).json()["job"]
    fake["status"] = "running"
    assert client.get(f"/api/analyze/{job}").json() == {"status": "running", "position": 0}
    fake["status"] = "error"
    assert client.get(f"/api/analyze/{job}").json()["error"] == "boom"
    assert client.get("/api/analyze/ffffffffffffffff").status_code == 404
    assert client.get("/api/analyze/not-a-job").status_code == 404
    assert client.post("/api/uploads/deadbeef/analyze", json={}).status_code in (400, 404)


def test_analyze_stored_item(client, add_item, fake):
    it = add_item({"item_type": "book", "fields": {"title": "Old"}}).json()
    job = client.post(f"/api/items/{it['id']}/analyze", json={}).json()["job"]
    sent = fake["jobs"][job]
    assert sent["meta"]["item_type"] == "book" and sent["name"] == it["citekey"] + ".pdf"
    assert client.get(f"/api/analyze/{job}").json()["item_type"] == "book"


def test_learn_on_save(client, fake):
    data = make_pdf("learn")
    up = client.post("/api/uploads", files={"file": ("a.pdf", data, "application/pdf")}).json()
    it = client.post("/api/items", json={"temp_id": up["temp_id"], "item": {
        "item_type": "book", "fields": {"title": "Heat"},
        "udc": [{"notation": "53", "source": "classifier", "confidence": 0.6}]}}).json()

    def learned():
        for _ in range(50):
            sent = [b for m, p, b in fake["calls"] if p == "/learn"]
            if sent:
                return sent
            time.sleep(0.02)
        return []

    sent = learned()   # saved by a person -> confirmed -> sent in the background
    assert sent == [{"sha256": hashlib.sha256(data).hexdigest(), "notation": "53",
                     "file": it["citekey"] + ".pdf", "title": "Heat"}]
    fake["calls"].clear()
    client.put(f"/api/items/{it['id']}", json={"item_type": "book", "fields": {"title": "Heat"}, "udc": []})
    time.sleep(0.1)
    assert not [p for _, p, _ in fake["calls"] if p == "/learn"]   # no UDC: nothing to learn
