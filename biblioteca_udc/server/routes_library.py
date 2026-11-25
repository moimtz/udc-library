"""Library API: schema, UDC tree, uploads, items, attachments, notes, trash, autofill, stats."""
import gzip
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import catalog
import config
import library as lib
import lookup
import pdfutil
import security
import udc
from db import SOURCES, get_conn, now

router = APIRouter(prefix="/api")

TEMP_RE = re.compile(r"^[0-9a-f]{32}$")
SUPP_RE = re.compile(r"_s(\d+)\.pdf$")
LOOKUP_CONFIDENCE = 0.9      # values from Crossref / Open Library / arXiv
PDFMETA_CONFIDENCE = 0.3     # title/author from the PDF's info dictionary


# --------------------------------------------------------------------------- models
class ItemIn(BaseModel):
    """fields: {code: "text" | {value, source, confidence}}; creators: [{creator_type, last_name, first_name,
    field_mode, source?, confidence?}]; tags: ["name" | {name, source}]; udc: ["notation" | {notation, source}]."""
    item_type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    creators: list[dict[str, Any]] = Field(default_factory=list)
    tags: list[Any] = Field(default_factory=list)
    udc: list[Any] = Field(default_factory=list)


class CreateItem(BaseModel):
    temp_id: str
    item: ItemIn
    cover_page: int = 1
    duplicate_action: str = "check"  # check | keep_both | replace
    replace_id: int | None = None


class UpdateItem(ItemIn):
    cover_page: int | None = None
    regen_citekey: bool = False


class AutofillIn(BaseModel):
    temp_id: str | None = None
    doi: str | None = None
    isbn: str | None = None
    arxiv: str | None = None
    item_type: str | None = None   # the form's current type, used when the lookup's type is not available


class ConvertIn(BaseModel):
    from_type: str
    to_type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    creators: list[dict[str, Any]] = Field(default_factory=list)


class TypeChangeIn(BaseModel):
    item_type: str
    dry_run: bool = False


class AttachmentIn(BaseModel):
    temp_id: str
    label: str


class AttachmentPatch(BaseModel):
    label: str | None = None


class OrderIn(BaseModel):
    ids: list[int]


class NoteIn(BaseModel):
    body: str


class AutoValuesIn(BaseModel):
    """Values from an automatic source for a stored item: {code: {value, source, confidence}}."""
    fields: dict[str, dict[str, Any]] = Field(default_factory=dict)
    udc: dict[str, Any] | None = None   # {notation, source, confidence}


# --------------------------------------------------------------------------- helpers
def _item_row(conn, item_id: int, include_deleted: bool = False):
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row or (row["deleted_at"] and not include_deleted):
        raise HTTPException(404, "Item not found.")
    return row


def _item(conn, item_id: int) -> dict:
    return lib.load_item(conn, item_id)


def _att_path(att, item_deleted) -> Path:
    in_trash = bool(att["deleted_at"]) or bool(item_deleted)
    return (config.TRASH_DIR if in_trash else config.LIBRARY_DIR) / att["filename"]


def _main_att(conn, item_id: int):
    att = conn.execute("SELECT * FROM attachments WHERE item_id=? AND role='main'", (item_id,)).fetchone()
    if att is None:
        raise HTTPException(404, "This item has no main file.")
    return att


def _cover_path(item_id: int) -> Path:
    return config.COVERS_DIR / f"{item_id}.jpg"


def _tmp_pdf(temp_id: str) -> Path:
    if not TEMP_RE.match(temp_id or ""):
        raise HTTPException(400, "Invalid upload id.")
    return config.TMP_DIR / f"{temp_id}.pdf"


def _sidecar(temp_id: str) -> Path:
    return config.TMP_DIR / f"{temp_id}.json"


def _read_sidecar(temp_id: str) -> dict:
    p = _sidecar(temp_id)
    if not _tmp_pdf(temp_id).exists() or not p.exists():
        raise HTTPException(404, "The upload expired. Select the file again.")
    return json.loads(p.read_text(encoding="utf-8"))


def _used_bytes(conn) -> int:
    return conn.execute("SELECT COALESCE(SUM(size),0) FROM attachments").fetchone()[0]


def _item_error(e: lib.ItemError):
    return HTTPException(422, str(e))


def _first_creator(item: ItemIn) -> str:
    for c in item.creators:
        if (c.get("last_name") or c.get("first_name") or "").strip():
            return (c.get("last_name") or c.get("first_name")).strip()
    return ""


def _title_of(conn, item: ItemIn) -> str:
    cat = catalog.get(conn)
    v = item.fields.get(lib.title_field(cat, item.item_type)) if item.item_type in cat.types else None
    return (v.get("value") if isinstance(v, dict) else v) or ""


def _value(item: ItemIn, code: str) -> str:
    v = item.fields.get(code)
    return ((v.get("value") if isinstance(v, dict) else v) or "").strip()


def _dups_for(conn, sha, item: ItemIn, exclude_id=None):
    year = None
    if d := lib.parse_date(_value(item, "date")):
        year = int(d[:4]) or None
    doi = _value(item, "DOI") or lib.extra_vars(_value(item, "extra")).get("doi")
    return lib.find_duplicates(conn, sha256=sha, doi=doi, isbn=_value(item, "ISBN"), title=_title_of(conn, item),
                               year=year, first_creator=_first_creator(item), exclude_id=exclude_id)


def _store_upload(file: UploadFile, conn) -> tuple[str, Path, str, int]:
    """Save an uploaded PDF to tmp; returns (temp_id, path, sha256, size)."""
    temp_id = uuid.uuid4().hex
    dest = _tmp_pdf(temp_id)
    sha, size = hashlib.sha256(), 0
    try:
        with dest.open("wb") as out:
            head = file.file.read(5)
            if not head.startswith(b"%PDF"):
                raise HTTPException(422, "Only PDF files can be added.")
            out.write(head)
            sha.update(head)
            size = len(head)
            while chunk := file.file.read(1024 * 1024):
                out.write(chunk)
                sha.update(chunk)
                size += len(chunk)
        if _used_bytes(conn) + size > config.MAX_BYTES:
            gb = config.MAX_STORAGE_GB
            raise HTTPException(507, f"Storage limit reached ({gb:g} GB). Delete items or raise BUDC_MAX_STORAGE_GB.")
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    return temp_id, dest, sha.hexdigest(), size


def _rename_files(conn, item_id: int, citekey: str, item_deleted) -> None:
    """Attachment files follow the citekey: citekey.pdf, citekey_s1.pdf, ..."""
    for att in conn.execute("SELECT * FROM attachments WHERE item_id=?", (item_id,)).fetchall():
        if att["role"] == "main":
            new = f"{citekey}.pdf"
        else:
            m = SUPP_RE.search(att["filename"])
            new = f"{citekey}_s{m.group(1) if m else att['id']}.pdf"
        if new == att["filename"]:
            continue
        src = _att_path(att, item_deleted)
        dst = src.with_name(new)
        if src.exists():
            src.rename(dst)
        conn.execute("UPDATE attachments SET filename=? WHERE id=?", (new, att["id"]))


def _auto_fields(values: dict[str, str], source: str, confidence: float) -> dict[str, dict]:
    return {k: {"value": v, "source": source, "confidence": confidence} for k, v in values.items() if v}


# --------------------------------------------------------------------------- schema / stats
@router.get("/schema")
def schema(lang: str = catalog.DEFAULT_LANG, user=Depends(security.current_user), conn=Depends(get_conn)):
    """Item types (enabled = can be chosen for new items) with their fields in Zotero's order and their
    creator roles, labelled in `lang` (any of the 48 Zotero locales; en-US if missing)."""
    out = catalog.get(conn).payload(lang)
    out["sources"] = sorted(SOURCES)
    out["zotero_schema_version"] = (conn.execute(
        "SELECT value FROM meta WHERE key='zotero_schema_version'").fetchone() or [None])[0]
    return out


@router.get("/stats")
def stats(user=Depends(security.current_user), conn=Depends(get_conn)):
    return {"used_bytes": _used_bytes(conn), "max_bytes": config.MAX_BYTES,
            "items": conn.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NULL").fetchone()[0],
            "trash_items": conn.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NOT NULL").fetchone()[0],
            "trash_days": config.TRASH_DAYS,
            "udc_source": (conn.execute("SELECT value FROM meta WHERE key='udc_source'").fetchone() or [None])[0]}


# --------------------------------------------------------------------------- UDC tree
def _gzip_json(request: Request, payload) -> Response:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # The full tree is ~10 MB of JSON; gzip cuts it ~10x (Dart's HttpClient decompresses it).
    # Only here: compressing PDFs would hide Content-Length (download progress).
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gzip.compress(body, 6), media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(body, media_type="application/json")


@router.get("/udc/tree")
def udc_tree(request: Request, user=Depends(security.current_user), conn=Depends(get_conn)):
    unclassified = conn.execute(
        "SELECT COUNT(*) FROM items WHERE deleted_at IS NULL AND id NOT IN (SELECT item_id FROM item_udc_nodes)"
    ).fetchone()[0]
    return _gzip_json(request, {"nodes": udc.tree_payload(conn), "unclassified": unclassified})


@router.get("/udc/node")
def udc_node(code: str = Query(..., min_length=1), user=Depends(security.current_user), conn=Depends(get_conn)):
    """Notes of one class for the information window. The code goes in the query string
    because notations may contain '/' (e.g. 62-1/-9)."""
    d = udc.node_detail(conn, code)
    if d is None:
        raise HTTPException(404, "Unknown UDC class")
    return d


@router.get("/udc/cancelled")
def udc_cancelled(code: str = Query(..., min_length=1), user=Depends(security.current_user), conn=Depends(get_conn)):
    """A cancelled notation: year, E&C issue, old label and the classes that replace it."""
    d = udc.cancelled_detail(conn, code)
    if not d:
        raise HTTPException(404, "Not a cancelled UDC notation")
    return {"code": code, "cancellations": d, "exists": conn.execute(
        "SELECT 1 FROM udc_nodes WHERE code=?", (code,)).fetchone() is not None}


@router.get("/udc/cancelled-index")
def udc_cancelled_index(request: Request, user=Depends(security.current_user), conn=Depends(get_conn)):
    """Cancelled notations that are not in the current tree, for the tree filter (loaded once by the app)."""
    return _gzip_json(request, {"cancelled": udc.cancelled_index(conn)})


@router.get("/udc/check")
def udc_check(udc_text: str = Query(..., alias="udc"), user=Depends(security.current_user), conn=Depends(get_conn)):
    """Warnings for a UDC string before saving: components that are cancelled notations."""
    return {"cancelled": udc.find_cancelled(conn, udc_text)}


# --------------------------------------------------------------------------- uploads, autofill, type conversion
@router.post("/uploads")
def upload(file: UploadFile = File(...), user=Depends(security.require_editor), conn=Depends(get_conn)):
    temp_id, dest, digest, size = _store_upload(file, conn)
    try:
        pages = pdfutil.page_count(dest)
        guess = pdfutil.embedded_metadata(dest)
        ids = pdfutil.find_identifiers(pdfutil.extract_text(dest))
    except pdfutil.PdfError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(422, str(e))
    first = guess["creators"][0]["last_name"] if guess["creators"] else ""
    dups = lib.find_duplicates(conn, sha256=digest, doi=(ids["doi"] or [None])[0],
                               isbn=(ids["isbn"] or [None])[0], title=guess["title"], first_creator=first)
    _sidecar(temp_id).write_text(json.dumps(
        {"sha256": digest, "size": size, "pages": pages, "name": file.filename, "identifiers": ids}), encoding="utf-8")
    fields = _auto_fields({"title": guess["title"]}, "pdfmeta", PDFMETA_CONFIDENCE)
    creators = [{**c, "source": "pdfmeta", "confidence": PDFMETA_CONFIDENCE} for c in guess["creators"]]
    return {"temp_id": temp_id, "filename": file.filename, "size": size, "sha256": digest, "pages": pages,
            "guess": {"fields": fields, "creators": creators}, "identifiers": ids, "duplicates": dups}


@router.get("/uploads/{temp_id}/page/{page}")
def upload_page(temp_id: str, page: int, w: int = 420, user=Depends(security.current_user)):
    path = _tmp_pdf(temp_id)
    if not path.exists():
        raise HTTPException(404, "The upload expired.")
    return Response(pdfutil.render_page_jpeg(path, page, min(max(w, 100), 1200)), media_type="image/jpeg")


def _lookup(cands: list[tuple[str, str]]) -> tuple[dict, str, str]:
    last_error = None
    for kind, value in cands:
        try:
            if kind == "doi":
                found = lookup.lookup_doi(lib.norm_doi(value))
                source = "crossref"
            elif kind == "isbn":
                digits = re.sub(r"[^0-9Xx]", "", value).upper()
                if not pdfutil.isbn_valid(digits):
                    continue
                found = lookup.lookup_isbn(pdfutil.isbn10_to_13(digits) if len(digits) == 10 else digits)
                source = "openlibrary"
            else:
                found = lookup.lookup_arxiv(re.sub(r"(?i)^arxiv:\s*", "", value))
                source = "arxiv"
        except lookup.LookupFailed as e:
            last_error = str(e)
            continue
        if found:
            return found, source, f"{kind}:{value}"
    if last_error:
        raise HTTPException(502, last_error)
    raise HTTPException(404, "The identifiers found are not in Crossref, Open Library or arXiv.")


def _candidates(doi=None, isbn=None, arxiv=None, temp_id=None) -> list[tuple[str, str]]:
    cands = [(k, v.strip()) for k, v in (("doi", doi), ("isbn", isbn), ("arxiv", arxiv)) if v and v.strip()]
    if not cands and temp_id:
        ids = _read_sidecar(temp_id)["identifiers"]
        cands = [("doi", v) for v in ids["doi"]] + [("isbn", v) for v in ids["isbn"]] + \
                [("arxiv", v) for v in ids["arxiv"]]
    if not cands:
        raise HTTPException(404, "No DOI, ISBN or arXiv ID found in the PDF. Type one in the form and try again.")
    return cands


def _fit(cat, item_type: str, found: dict, source: str) -> dict:
    fields, extra = lib.fit_to_type(cat, item_type, found["fields"])
    out = _auto_fields(fields, source, LOOKUP_CONFIDENCE)
    if extra:
        out["extra"] = {"value": "\n".join(extra), "source": source, "confidence": LOOKUP_CONFIDENCE}
    creators = []
    for c in found["creators"]:
        ct = c["creator_type"]
        if not cat.allows_creator(item_type, ct):
            ct = "contributor" if cat.allows_creator(item_type, "contributor") else cat.primary_creator(item_type)
        creators.append({**c, "creator_type": ct, "source": source, "confidence": LOOKUP_CONFIDENCE})
    return {"fields": out, "creators": creators,
            "tags": [{"name": t, "source": source} for t in found.get("tags", []) if t]}


@router.post("/autofill")
def autofill(body: AutofillIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    """Look up a DOI / ISBN / arXiv ID (given, or found in the uploaded PDF) for the add form. Values come back
    fitted to the item type, each with its source; the person accepts them by saving the form."""
    cat = catalog.get(conn)
    found, source, ident = _lookup(_candidates(body.doi, body.isbn, body.arxiv, body.temp_id))
    t = found.get("item_type")
    item_type = t if t in cat.types and cat.types[t]["enabled"] else (body.item_type or "book")
    if item_type not in cat.types:
        raise HTTPException(422, f"Unknown item type '{item_type}'.")
    kind, _, value = ident.partition(":")
    return {"identifier": {"type": kind, "value": value}, "source": source, "item_type": item_type,
            "suggested_type": t, **_fit(cat, item_type, found, source)}


@router.post("/convert-type")
def convert_type(body: ConvertIn, user=Depends(security.current_user), conn=Depends(get_conn)):
    """Move a form's values to another item type (nothing is saved). report says what moved and what went
    to Extra, so the app can warn before the person saves."""
    cat = catalog.get(conn)
    for t in (body.from_type, body.to_type):
        if t not in cat.types:
            raise HTTPException(422, f"Unknown item type '{t}'.")
    fields = {}
    for code, v in body.fields.items():
        obj = dict(v) if isinstance(v, dict) else {"value": v, "source": "manual", "confidence": None}
        if str(obj.get("value") or "").strip():
            fields[code] = obj
    creators = [{"last_name": "", "first_name": "", "field_mode": 0, "source": "manual", "confidence": None,
                 **c} for c in body.creators]
    return catalog.convert(cat, body.from_type, body.to_type, fields, creators)


# --------------------------------------------------------------------------- items
@router.get("/items")
def list_items(q: str = "", field: str = "all", regex: bool = False, case: bool = False, whole: bool = False,
               udc_code: str | None = Query(None, alias="udc"), include_desc: bool = True,
               type: str | None = None, year_from: int | None = None, year_to: int | None = None,
               language: str | None = None, sort: str = "title", order: str = "asc", limit: int = 2000,
               user=Depends(security.current_user), conn=Depends(get_conn)):
    sql, args = ["SELECT id FROM items WHERE deleted_at IS NULL"], []
    if type:
        sql.append("AND item_type=?")
        args.append(type)
    if year_from is not None:
        sql.append("AND year>=?")
        args.append(year_from)
    if year_to is not None:
        sql.append("AND year<=?")
        args.append(year_to)
    if language:
        sql.append("AND language=?")
        args.append(lib.norm_language(language) or language.lower())
    if udc_code == "none":
        sql.append("AND id NOT IN (SELECT item_id FROM item_udc_nodes)")
    elif udc_code:
        nodes = udc.descendants(conn, udc_code) if include_desc else {udc_code}
        sql.append("AND id IN (SELECT item_id FROM item_udc_nodes WHERE node_code IN "
                   f"({','.join('?' * len(nodes))}))")
        args.extend(sorted(nodes))
    ids = [r[0] for r in conn.execute(" ".join(sql), args)]
    items = lib.load_items(conn, ids, light=True)
    if q.strip():
        try:
            matcher = lib.build_matcher(q, regex=regex, case=case, whole=whole)
        except lib.SearchError as e:
            raise HTTPException(400, str(e))
        items = lib.run_search(conn, items, matcher, field)
    lib.sort_items(items, sort, order != "desc")
    return {"total": len(items), "items": items[:limit]}


@router.get("/items/{item_id}")
def get_item(item_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    _item_row(conn, item_id)
    return _item(conn, item_id)


@router.post("/items", status_code=201)
def create_item(body: CreateItem, user=Depends(security.require_editor), conn=Depends(get_conn)):
    tmp = _tmp_pdf(body.temp_id)
    side = _read_sidecar(body.temp_id)
    dups = _dups_for(conn, side["sha256"], body.item)
    if body.duplicate_action == "check" and dups:
        raise HTTPException(409, {"message": "This looks like a duplicate.", "duplicates": dups})
    data = body.item.model_dump()
    cover = min(max(body.cover_page, 1), side["pages"] or 1)

    if body.duplicate_action == "replace":
        if body.replace_id is None:
            raise HTTPException(422, "Choose which item to replace.")
        old = _item_row(conn, body.replace_id, include_deleted=True)
        try:
            item_id = lib.save_item(conn, user["id"], data, old["id"])
        except lib.ItemError as e:
            conn.rollback()
            raise _item_error(e)
        main = conn.execute("SELECT * FROM attachments WHERE item_id=? AND role='main'", (old["id"],)).fetchone()
        if old["deleted_at"]:   # bring the item (and its files) back from the trash
            for att in conn.execute("SELECT * FROM attachments WHERE item_id=? AND deleted_at IS NULL",
                                    (old["id"],)).fetchall():
                src = config.TRASH_DIR / att["filename"]
                if src.exists():
                    shutil.move(str(src), config.LIBRARY_DIR / att["filename"])
            conn.execute("UPDATE items SET deleted_at=NULL WHERE id=?", (old["id"],))
        name = main["filename"] if main else f"{old['citekey']}.pdf"
        dest = config.LIBRARY_DIR / name
        dest.unlink(missing_ok=True)
        shutil.move(str(tmp), dest)
        conn.execute("DELETE FROM attachments WHERE item_id=? AND role='main'", (old["id"],))
        conn.execute("INSERT INTO attachments(item_id, role, filename, sha256, size, mime, pages, cover_page, "
                     "added_at, added_by) VALUES (?,'main',?,?,?,'application/pdf',?,?,?,?)",
                     (old["id"], name, side["sha256"], side["size"], side["pages"], cover, now(), user["id"]))
        pdfutil.save_cover(dest, _cover_path(old["id"]), cover)
        conn.commit()
        _sidecar(body.temp_id).unlink(missing_ok=True)
        return _item(conn, old["id"])

    try:
        item_id = lib.save_item(conn, user["id"], data)
    except lib.ItemError as e:
        conn.rollback()
        raise _item_error(e)
    citekey = conn.execute("SELECT citekey FROM items WHERE id=?", (item_id,)).fetchone()[0]
    dest = config.LIBRARY_DIR / f"{citekey}.pdf"
    shutil.move(str(tmp), dest)
    try:
        conn.execute("INSERT INTO attachments(item_id, role, filename, sha256, size, mime, pages, cover_page, "
                     "added_at, added_by) VALUES (?,'main',?,?,?,'application/pdf',?,?,?,?)",
                     (item_id, dest.name, side["sha256"], side["size"], side["pages"], cover, now(), user["id"]))
        pdfutil.save_cover(dest, _cover_path(item_id), cover)
        conn.commit()
    except Exception:
        conn.rollback()
        shutil.move(str(dest), tmp)
        raise
    _sidecar(body.temp_id).unlink(missing_ok=True)
    return _item(conn, item_id)


@router.put("/items/{item_id}")
def update_item(item_id: int, body: UpdateItem, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _item_row(conn, item_id)
    data = body.model_dump(exclude={"cover_page", "regen_citekey"})
    try:
        lib.save_item(conn, user["id"], data, item_id)
    except lib.ItemError as e:
        conn.rollback()
        raise _item_error(e)
    if body.regen_citekey:
        key = lib.citekey_for(conn, item_id)
        if key != row["citekey"]:
            conn.execute("UPDATE items SET citekey=? WHERE id=?", (key, item_id))
            _rename_files(conn, item_id, key, row["deleted_at"])
    main = conn.execute("SELECT * FROM attachments WHERE item_id=? AND role='main'", (item_id,)).fetchone()
    new_cover = None
    if main and body.cover_page and body.cover_page != main["cover_page"]:
        new_cover = min(max(body.cover_page, 1), main["pages"] or 1)
        conn.execute("UPDATE attachments SET cover_page=? WHERE id=?", (new_cover, main["id"]))
    conn.commit()
    if new_cover:
        pdfutil.save_cover(_att_path(main, None), _cover_path(item_id), new_cover)
    return _item(conn, item_id)


@router.post("/items/{item_id}/type")
def change_item_type(item_id: int, body: TypeChangeIn, user=Depends(security.require_editor),
                     conn=Depends(get_conn)):
    """Convert a stored item to another type (dry_run: only report what would move or go to Extra)."""
    _item_row(conn, item_id)
    try:
        report = lib.change_type(conn, user["id"], item_id, body.item_type, dry_run=body.dry_run)
    except lib.ItemError as e:
        conn.rollback()
        raise _item_error(e)
    if body.dry_run:
        return {"report": report}
    conn.commit()
    return {"report": report, "item": _item(conn, item_id)}


@router.post("/items/{item_id}/autofill")
def autofill_item(item_id: int, body: AutofillIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    """Look up an identifier for a stored item. Confirmed values are never overwritten: differing values come
    back as suggestions."""
    row = _item_row(conn, item_id)
    item = _item(conn, item_id)

    def val(code):
        return item["fields"].get(code, {}).get("value")

    cands = _candidates(body.doi or val("DOI"), body.isbn or val("ISBN"), body.arxiv)
    found, source, _ = _lookup(cands)
    fitted = _fit(catalog.get(conn), row["item_type"], found, source)
    fitted["fields"].pop("extra", None)   # never rewrite Extra automatically
    try:
        suggestions = lib.apply_auto(conn, item_id, fitted["fields"])
    except lib.ItemError as e:
        conn.rollback()
        raise _item_error(e)
    conn.commit()
    return {"item": _item(conn, item_id), "suggestions": suggestions, "source": source}


@router.post("/items/{item_id}/auto")
def auto_values(item_id: int, body: AutoValuesIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    """Values from an automatic process (extraction, classifier). Same rules as autofill."""
    _item_row(conn, item_id)
    try:
        suggestions = lib.apply_auto(conn, item_id, body.fields)
        if body.udc:
            s = lib.set_udc_auto(conn, item_id, str(body.udc.get("notation") or "").strip(),
                                 body.udc.get("source") or "", body.udc.get("confidence"))
            if s:
                suggestions.append({"field": "udc", **s})
    except lib.ItemError as e:
        conn.rollback()
        raise _item_error(e)
    conn.commit()
    return {"item": _item(conn, item_id), "suggestions": suggestions}


@router.get("/items/{item_id}/file")
def item_file(item_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    row = _item_row(conn, item_id)
    att = _main_att(conn, item_id)
    path = _att_path(att, row["deleted_at"])
    if not path.exists():
        raise HTTPException(404, "The PDF is missing on the server.")
    return FileResponse(path, media_type=att["mime"], filename=att["filename"])


@router.get("/items/{item_id}/cover")
def item_cover(item_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    row = _item_row(conn, item_id, include_deleted=True)
    cover = _cover_path(item_id)
    if not cover.exists():
        att = _main_att(conn, item_id)
        pdfutil.save_cover(_att_path(att, row["deleted_at"]), cover, att["cover_page"] or 1)
    return FileResponse(cover, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/items/{item_id}/page/{page}")
def item_page(item_id: int, page: int, w: int = 420, user=Depends(security.current_user), conn=Depends(get_conn)):
    row = _item_row(conn, item_id)
    att = _main_att(conn, item_id)
    return Response(pdfutil.render_page_jpeg(_att_path(att, row["deleted_at"]), page, min(max(w, 100), 1200)),
                    media_type="image/jpeg")


# --------------------------------------------------------------------------- supplementary material
def _att_row(conn, att_id: int):
    att = conn.execute("SELECT a.*, i.deleted_at AS item_deleted FROM attachments a JOIN items i ON i.id=a.item_id "
                       "WHERE a.id=?", (att_id,)).fetchone()
    if att is None:
        raise HTTPException(404, "File not found.")
    return att


@router.post("/items/{item_id}/attachments", status_code=201)
def add_attachment(item_id: int, body: AttachmentIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    """Add an uploaded PDF (POST /uploads first) as supplementary material with a label ('Errata', 'Parts')."""
    row = _item_row(conn, item_id)
    label = " ".join(body.label.split())
    if not label:
        raise HTTPException(422, "Give the file a label (e.g. 'Errata', 'Solutions manual').")
    tmp = _tmp_pdf(body.temp_id)
    side = _read_sidecar(body.temp_id)
    same = conn.execute("SELECT item_id FROM attachments WHERE sha256=?", (side["sha256"],)).fetchone()
    if same:
        raise HTTPException(409, "This file is already in the library." if same[0] != item_id
                            else "This file is already attached to this item.")
    nums = [int(m.group(1)) for (fn,) in conn.execute("SELECT filename FROM attachments WHERE item_id=?", (item_id,))
            if (m := SUPP_RE.search(fn))]
    name = f"{row['citekey']}_s{max(nums, default=0) + 1}.pdf"
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM attachments WHERE item_id=? AND role='supplementary'",
                       (item_id,)).fetchone()[0]
    dest = config.LIBRARY_DIR / name
    shutil.move(str(tmp), dest)
    try:
        conn.execute("INSERT INTO attachments(item_id, role, label, position, filename, sha256, size, mime, pages, "
                     "added_at, added_by) VALUES (?,'supplementary',?,?,?,?,?,'application/pdf',?,?,?)",
                     (item_id, label, pos, name, side["sha256"], side["size"], side["pages"], now(), user["id"]))
        conn.execute("UPDATE items SET modified_at=?, modified_by=? WHERE id=?", (now(), user["id"], item_id))
        conn.commit()
    except Exception:
        conn.rollback()
        shutil.move(str(dest), tmp)
        raise
    _sidecar(body.temp_id).unlink(missing_ok=True)
    return _item(conn, item_id)


@router.patch("/attachments/{att_id}")
def edit_attachment(att_id: int, body: AttachmentPatch, user=Depends(security.require_editor),
                    conn=Depends(get_conn)):
    att = _att_row(conn, att_id)
    if body.label is not None:
        label = " ".join(body.label.split())
        if att["role"] == "supplementary" and not label:
            raise HTTPException(422, "Supplementary files need a label.")
        conn.execute("UPDATE attachments SET label=? WHERE id=?", (label, att_id))
    conn.commit()
    return _item(conn, att["item_id"])


@router.put("/items/{item_id}/attachments/order")
def order_attachments(item_id: int, body: OrderIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    _item_row(conn, item_id)
    have = {r[0] for r in conn.execute("SELECT id FROM attachments WHERE item_id=? AND role='supplementary'",
                                       (item_id,))}
    if set(body.ids) != have:
        raise HTTPException(422, "Send every supplementary file of the item, in the new order.")
    for pos, att_id in enumerate(body.ids, 1):
        conn.execute("UPDATE attachments SET position=? WHERE id=?", (pos, att_id))
    conn.commit()
    return _item(conn, item_id)


@router.get("/attachments/{att_id}/file")
def attachment_file(att_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    att = _att_row(conn, att_id)
    path = _att_path(att, att["item_deleted"])
    if not path.exists():
        raise HTTPException(404, "The file is missing on the server.")
    return FileResponse(path, media_type=att["mime"], filename=att["filename"])


@router.delete("/attachments/{att_id}")
def trash_attachment(att_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    """Move one supplementary file to the trash (the main file goes only with its item)."""
    att = _att_row(conn, att_id)
    if att["role"] == "main":
        raise HTTPException(409, "The main file cannot be removed on its own. Move the item to the trash instead.")
    if att["deleted_at"]:
        return {"ok": True}
    src = _att_path(att, att["item_deleted"])
    if src.exists() and not att["item_deleted"]:
        shutil.move(str(src), config.TRASH_DIR / att["filename"])
    conn.execute("UPDATE attachments SET deleted_at=? WHERE id=?", (now(), att_id))
    conn.commit()
    return {"ok": True}


@router.post("/attachments/{att_id}/restore")
def restore_attachment(att_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    att = _att_row(conn, att_id)
    if not att["deleted_at"]:
        return {"ok": True}
    src = config.TRASH_DIR / att["filename"]
    if src.exists() and not att["item_deleted"]:
        shutil.move(str(src), config.LIBRARY_DIR / att["filename"])
    conn.execute("UPDATE attachments SET deleted_at=NULL WHERE id=?", (att_id,))
    conn.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- notes
@router.post("/items/{item_id}/notes", status_code=201)
def add_note(item_id: int, body: NoteIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    _item_row(conn, item_id)
    if not body.body.strip():
        raise HTTPException(422, "The note is empty.")
    conn.execute("INSERT INTO item_notes(item_id, body, created_at, created_by, modified_at) VALUES (?,?,?,?,?)",
                 (item_id, body.body.strip(), now(), user["id"], now()))
    conn.commit()
    return _item(conn, item_id)


@router.put("/notes/{note_id}")
def edit_note(note_id: int, body: NoteIn, user=Depends(security.require_editor), conn=Depends(get_conn)):
    note = conn.execute("SELECT item_id FROM item_notes WHERE id=?", (note_id,)).fetchone()
    if note is None:
        raise HTTPException(404, "Note not found.")
    if not body.body.strip():
        raise HTTPException(422, "The note is empty.")
    conn.execute("UPDATE item_notes SET body=?, modified_at=? WHERE id=?", (body.body.strip(), now(), note_id))
    conn.commit()
    return _item(conn, note["item_id"])


@router.delete("/notes/{note_id}")
def delete_note(note_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    note = conn.execute("SELECT item_id FROM item_notes WHERE id=?", (note_id,)).fetchone()
    if note is None:
        raise HTTPException(404, "Note not found.")
    conn.execute("DELETE FROM item_notes WHERE id=?", (note_id,))
    conn.commit()
    return _item(conn, note["item_id"])


# --------------------------------------------------------------------------- trash
@router.delete("/items/{item_id}")
def trash_item(item_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    _item_row(conn, item_id)
    for att in conn.execute("SELECT * FROM attachments WHERE item_id=? AND deleted_at IS NULL", (item_id,)).fetchall():
        src = config.LIBRARY_DIR / att["filename"]
        if src.exists():
            shutil.move(str(src), config.TRASH_DIR / att["filename"])
    conn.execute("UPDATE items SET deleted_at=? WHERE id=?", (now(), item_id))
    conn.commit()
    return {"ok": True}


@router.get("/trash")
def list_trash(user=Depends(security.require_editor), conn=Depends(get_conn)):
    ids = [r[0] for r in conn.execute("SELECT id FROM items WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC")]
    return {"items": lib.load_items(conn, ids, light=True)}


@router.post("/trash/{item_id}/restore")
def restore_item(item_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _item_row(conn, item_id, include_deleted=True)
    if not row["deleted_at"]:
        return {"ok": True}
    for att in conn.execute("SELECT * FROM attachments WHERE item_id=? AND deleted_at IS NULL", (item_id,)).fetchall():
        src = config.TRASH_DIR / att["filename"]
        if src.exists():
            shutil.move(str(src), config.LIBRARY_DIR / att["filename"])
    conn.execute("UPDATE items SET deleted_at=NULL WHERE id=?", (item_id,))
    conn.commit()
    return {"ok": True}


def purge_item(conn, row) -> None:
    for att in conn.execute("SELECT filename FROM attachments WHERE item_id=?", (row["id"],)).fetchall():
        (config.TRASH_DIR / att["filename"]).unlink(missing_ok=True)
        (config.LIBRARY_DIR / att["filename"]).unlink(missing_ok=True)
    _cover_path(row["id"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM items WHERE id=?", (row["id"],))


def purge_attachment(conn, att) -> None:
    (config.TRASH_DIR / att["filename"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM attachments WHERE id=?", (att["id"],))


@router.delete("/trash/{item_id}")
def delete_forever(item_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _item_row(conn, item_id, include_deleted=True)
    if not row["deleted_at"]:
        raise HTTPException(409, "Move the item to the trash first.")
    purge_item(conn, row)
    conn.commit()
    return {"ok": True}
