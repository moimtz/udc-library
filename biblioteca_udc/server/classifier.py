"""Client of the classifier service (udc_poc: run_classifier.bat -> python -m udcpoc serve, same PC).

The library works without it: /api/classifier says whether it is running and the app enables Analyze only
then. An analysis is a job in the service's queue (one PDF at a time, ~30 s; more with OCR):

    submit(path, name, meta) -> job id;  job(id) -> {status, position, result | error, meta}

to_form() turns the service's record into form values for the item type, with the same conversion as the
bulk import (bulk_import.item_from_record). learn() sends the UDC a person saved, so the classifier learns
from it (only PDFs it analysed; the rest is ignored by the service).
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import httpx

import catalog
import config
import library as lib
from bulk_import import item_from_record

JOB_RE = re.compile(r"^[0-9a-f]{16}$")
_health = {"t": 0.0, "value": None}


class Unavailable(Exception):
    pass


class UnknownJob(Exception):
    pass


def _call(method: str, path: str, body: dict | None = None, timeout: float = 5.0) -> dict:
    if not config.CLASSIFIER_URL:
        raise Unavailable("No classifier is configured on the server.")
    try:
        r = httpx.request(method, config.CLASSIFIER_URL + path, json=body, timeout=timeout)
    except httpx.HTTPError as e:
        raise Unavailable("The classifier is not running on the server.") from e
    try:
        data = r.json()
    except ValueError:
        raise Unavailable(f"The classifier answered with error {r.status_code}.")
    if r.status_code == 404 and path.startswith("/jobs/"):
        raise UnknownJob()
    if r.status_code >= 400:
        raise Unavailable(f"The classifier refused the request: {data.get('error', r.status_code)}")
    return data


def status() -> dict:
    """{available, loading, queue}. Cached a few seconds (the app asks when a form opens)."""
    if _health["value"] is not None and time.time() - _health["t"] < 5:
        return _health["value"]
    try:
        h = _call("GET", "/health", timeout=1.5)
        v = {"available": bool(h.get("ready")), "loading": not h.get("ready") and not h.get("error"),
             "queue": int(h.get("queue") or 0), "error": h.get("error")}
    except Unavailable:
        v = {"available": False, "loading": False, "queue": 0, "error": None}
    _health.update(t=time.time(), value=v)
    return v


def submit(path: Path, name: str, meta: dict) -> str:
    return _call("POST", "/jobs", {"path": str(Path(path).resolve()), "name": name, "meta": meta})["job"]


def job(job_id: str) -> dict:
    if not JOB_RE.match(job_id or ""):
        raise UnknownJob()
    return _call("GET", f"/jobs/{job_id}", timeout=15.0)   # holgura si el servicio está ocupado


# --------------------------------------------------------------------------- record -> form
def _suggestion(s: dict) -> dict:
    main = s.get("main") or []
    return {
        "rank": s.get("rank"),
        "notation": s["udc"],
        "confidence": s.get("confidence"),
        "label": " : ".join(m.get("label", "") for m in main if m.get("label")),
        "aux": [{"kind": k, "code": v.get("code"), "label": v.get("label"), "source": v.get("source")}
                for k, v in (s.get("aux") or {}).items() if isinstance(v, dict)],
        "broader": ((s.get("explain") or {}).get("retroceder_a") or [])[:3],
    }


def to_form(cat, rec: dict, filename: str | None, item_type: str | None = None) -> dict:
    """Form values for item_type (None = the type the classifier detected), each with source and
    confidence, plus the UDC suggestions and the reasons to check the result."""
    pdf = Path(filename or "document.pdf")
    item, _note, review = item_from_record(cat, rec, pdf, None)
    detected = item["item_type"]
    fields, creators, itype = item["fields"], item["creators"], detected
    if item_type and item_type != detected and item_type in cat.types:
        conv = catalog.convert(cat, detected, item_type, {k: {**v, "confirmed": 0} for k, v in fields.items()},
                               creators)
        fields = {k: {kk: vv for kk, vv in v.items() if kk != "confirmed"} for k, v in conv["fields"].items()}
        creators, itype = conv["creators"], item_type
    for v in [*fields.values(), *creators]:
        if v.get("source") == "import":          # the bulk import's catch-all source
            v["source"] = "classifier"
    tfield = lib.title_field(cat, itype)
    if fields.get(tfield, {}).get("source") == "filename" and fields[tfield]["value"] == pdf.stem:
        del fields[tfield]                       # the form already has its own guess
        review = [r for r in review if not r.startswith("no title found")]
    cls = rec.get("classification") or {}
    return {
        "item_type": itype,
        "detected_type": {"value": detected, "confidence": (rec.get("item_type") or {}).get("confidence")},
        "fields": fields,
        "creators": creators,
        "tags": [{"name": t["name"], "source": "classifier" if t["source"] == "import" else t["source"]}
                 for t in item["tags"]],
        "udc": [_suggestion(s) for s in (cls.get("suggestions") or [])[:3]],
        "low_confidence": bool(cls.get("low_confidence")),
        "note": cls.get("note") or "",
        "review": review,
        "scanned": bool(rec.get("scanned")),
        "ocr": bool(rec.get("ocr")),
        "warnings": rec.get("warnings") or [],
    }


# --------------------------------------------------------------------------- learning
def learn(conn, item_id: int) -> None:
    """After a person saves an item: its main UDC goes to the classifier as an example, in the background
    (saving never waits for it nor fails because of it)."""
    if not config.CLASSIFIER_URL:
        return
    row = conn.execute(
        "SELECT a.sha256, a.filename, u.notation, i.item_type FROM items i "
        "JOIN attachments a ON a.item_id=i.id AND a.role='main' AND a.deleted_at IS NULL "
        "JOIN item_udc u ON u.item_id=i.id AND u.position=0 AND u.confirmed=1 WHERE i.id=?", (item_id,)).fetchone()
    if row is None:
        return
    tfield = lib.title_field(catalog.get(conn), row["item_type"])
    t = conn.execute("SELECT value FROM item_fields WHERE item_id=? AND field=?", (item_id, tfield)).fetchone()
    body = {"sha256": row["sha256"], "notation": row["notation"], "file": row["filename"],
            "title": t[0] if t else ""}

    def send():
        try:
            _call("POST", "/learn", body, timeout=3)
        except Unavailable:
            pass

    threading.Thread(target=send, daemon=True).start()
