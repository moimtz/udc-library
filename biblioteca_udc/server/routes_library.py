"""Library API: schema, UDC tree, uploads, items, trash, autofill, stats."""
import gzip
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import config
import library as lib
import lookup
import pdfutil
import security
import udc
from db import CREATOR_ROLES, get_conn, now
from textutil import make_citekey, unique_key

router = APIRouter(prefix="/api")

TEMP_RE = re.compile(r"^[0-9a-f]{32}$")


# --------------------------------------------------------------------------- models
class CreatorIn(BaseModel):
    role: str = "author"
    first: str = ""
    last: str = ""


class ItemIn(BaseModel):
    item_type: str
    title: str
    year: int | None = None
    language: str | None = None
    udc: str = ""
    creators: list[CreatorIn] = Field(default_factory=list)
    data: dict[str, str] = Field(default_factory=dict)


class CreateItem(BaseModel):
    temp_id: str
    fields: ItemIn
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


class TypeIn(BaseModel):
    code: str
    label: str
    fields: list[str]


class FieldIn(BaseModel):
    key: str
    label: str
    kind: str = "text"


# --------------------------------------------------------------------------- helpers
def _row(conn, item_id: int, include_deleted: bool = False):
    row = conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row or (row["deleted_at"] and not include_deleted):
        raise HTTPException(404, "Item not found.")
    return row


def _file_path(row) -> Path:
    return (config.TRASH_DIR if row["deleted_at"] else config.LIBRARY_DIR) / row["filename"]


def _cover_path(item_id: int) -> Path:
    return config.COVERS_DIR / f"{item_id}.jpg"


def _tmp_pdf(temp_id: str) -> Path:
    if not TEMP_RE.match(temp_id):
        raise HTTPException(400, "Invalid upload id.")
    return config.TMP_DIR / f"{temp_id}.pdf"


def _sidecar(temp_id: str) -> Path:
    return config.TMP_DIR / f"{temp_id}.json"


def _read_sidecar(temp_id: str) -> dict:
    p = _sidecar(temp_id)
    if not _tmp_pdf(temp_id).exists() or not p.exists():
        raise HTTPException(404, "The upload expired. Select the file again.")
    return json.loads(p.read_text(encoding="utf-8"))


def _type_labels(conn) -> dict[str, str]:
    return {r["code"]: r["label"] for r in conn.execute("SELECT code, label FROM item_types")}


def _used_bytes(conn) -> int:
    return conn.execute("SELECT COALESCE(SUM(size),0) FROM items").fetchone()[0]


def _validate(conn, f: ItemIn) -> dict:
    if not conn.execute("SELECT 1 FROM item_types WHERE code=?", (f.item_type,)).fetchone():
        raise HTTPException(422, f"Unknown resource type '{f.item_type}'.")
    if not f.title.strip():
        raise HTTPException(422, "Title is required.")
    if f.year is not None and not (0 < f.year < 3000):
        raise HTTPException(422, "Year is not valid.")
    keys = {r["key"] for r in conn.execute("SELECT key FROM field_defs")}
    data = {k: v.strip() for k, v in f.data.items() if k in keys and v.strip()}
    creators = [c.model_dump() for c in f.creators if c.first.strip() or c.last.strip()]
    for c in creators:
        c["first"], c["last"] = c["first"].strip(), c["last"].strip()
        if c["role"] not in CREATOR_ROLES:
            c["role"] = "author"
    return {"title": f.title.strip(), "creators": creators, "data": data,
            "language": (f.language or "").strip().lower() or None}


def _key_taken(conn, exclude_id: int | None = None):
    def taken(k: str) -> bool:
        row = conn.execute("SELECT id FROM items WHERE citekey=?", (k,)).fetchone()
        return bool(row) and row["id"] != exclude_id
    return taken


def _new_citekey(conn, creators, title, year, exclude_id=None) -> str:
    return unique_key(make_citekey(creators, title, year), _key_taken(conn, exclude_id))


def _dups_for(conn, sha, v: dict, f: ItemIn, exclude_id=None):
    first = v["creators"][0]["last"] if v["creators"] else ""
    return lib.find_duplicates(conn, sha256=sha, doi=v["data"].get("doi"), isbn=v["data"].get("isbn"),
                               title=v["title"], year=f.year, first_author=first, exclude_id=exclude_id)


# --------------------------------------------------------------------------- schema / stats
@router.get("/schema")
def schema(user=Depends(security.current_user), conn=Depends(get_conn)):
    types = [{"code": r["code"], "label": r["label"], "fields": json.loads(r["fields"])}
             for r in conn.execute("SELECT * FROM item_types ORDER BY position, label")]
    fields = {r["key"]: {"label": r["label"], "kind": r["kind"]}
              for r in conn.execute("SELECT * FROM field_defs ORDER BY position")}
    return {"types": types, "fields": fields, "roles": CREATOR_ROLES}


@router.post("/fields", status_code=201)
def add_field(body: FieldIn, admin=Depends(security.require_admin), conn=Depends(get_conn)):
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", body.key):
        raise HTTPException(422, "Field key: lowercase letters, digits and underscore (2-31 chars).")
    if body.kind not in ("text", "area"):
        raise HTTPException(422, "Field kind must be text or area.")
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM field_defs").fetchone()[0]
    conn.execute("INSERT OR REPLACE INTO field_defs(key,label,kind,position) VALUES (?,?,?,?)",
                 (body.key, body.label.strip() or body.key, body.kind, pos))
    conn.commit()
    return {"ok": True}


@router.post("/types", status_code=201)
def add_type(body: TypeIn, admin=Depends(security.require_admin), conn=Depends(get_conn)):
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,30}", body.code):
        raise HTTPException(422, "Type code: lowercase letters, digits and underscore (2-31 chars).")
    known = {r["key"] for r in conn.execute("SELECT key FROM field_defs")}
    unknown = [f for f in body.fields if f not in known]
    if unknown:
        raise HTTPException(422, f"Unknown fields: {', '.join(unknown)}")
    pos = conn.execute("SELECT COALESCE(MAX(position),0)+1 FROM item_types").fetchone()[0]
    conn.execute("INSERT OR REPLACE INTO item_types(code,label,fields,position) VALUES (?,?,?,?)",
                 (body.code, body.label.strip() or body.code, json.dumps(body.fields), pos))
    conn.commit()
    return {"ok": True}


@router.delete("/types/{code}")
def delete_type(code: str, admin=Depends(security.require_admin), conn=Depends(get_conn)):
    if code == "other":
        raise HTTPException(422, "The 'other' type cannot be removed.")
    if conn.execute("SELECT 1 FROM items WHERE item_type=?", (code,)).fetchone():
        raise HTTPException(409, "Items still use this type. Change their type first.")
    conn.execute("DELETE FROM item_types WHERE code=?", (code,))
    conn.commit()
    return {"ok": True}


@router.get("/stats")
def stats(user=Depends(security.current_user), conn=Depends(get_conn)):
    return {"used_bytes": _used_bytes(conn), "max_bytes": config.MAX_BYTES,
            "items": conn.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NULL").fetchone()[0],
            "trash_items": conn.execute("SELECT COUNT(*) FROM items WHERE deleted_at IS NOT NULL").fetchone()[0],
            "trash_days": config.TRASH_DAYS,
            "udc_source": (conn.execute("SELECT value FROM meta WHERE key='udc_source'").fetchone() or [None])[0]}


@router.get("/udc/tree")
def udc_tree(request: Request, user=Depends(security.current_user), conn=Depends(get_conn)):
    unclassified = conn.execute(
        "SELECT COUNT(*) FROM items WHERE deleted_at IS NULL AND id NOT IN "
        "(SELECT item_id FROM item_udc WHERE node_code IS NOT NULL)").fetchone()[0]
    body = json.dumps({"nodes": udc.tree_payload(conn), "unclassified": unclassified},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # The full tree is ~10 MB of JSON; gzip cuts it ~10x (Dart's HttpClient decompresses it).
    # Only here: compressing PDFs would hide Content-Length (download progress).
    if "gzip" in request.headers.get("accept-encoding", ""):
        return Response(gzip.compress(body, 6), media_type="application/json",
                        headers={"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
    return Response(body, media_type="application/json")


@router.get("/udc/node")
def udc_node(code: str = Query(..., min_length=1), user=Depends(security.current_user), conn=Depends(get_conn)):
    """Notes of one class for the information window. The code goes in the query string
    because notations may contain '/' (e.g. 62-1/-9)."""
    d = udc.node_detail(conn, code)
    if d is None:
        raise HTTPException(404, "Unknown UDC class")
    return d


# --------------------------------------------------------------------------- uploads
@router.post("/uploads")
def upload(file: UploadFile = File(...), user=Depends(security.require_editor), conn=Depends(get_conn)):
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
        try:
            pages = pdfutil.page_count(dest)
            guess = pdfutil.embedded_metadata(dest)
            ids = pdfutil.find_identifiers(pdfutil.extract_text(dest))
        except pdfutil.PdfError as e:
            raise HTTPException(422, str(e))
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    digest = sha.hexdigest()
    first = guess["creators"][0]["last"] if guess["creators"] else ""
    dups = lib.find_duplicates(conn, sha256=digest, doi=(ids["doi"] or [None])[0],
                               isbn=(ids["isbn"] or [None])[0], title=guess["title"], first_author=first)
    _sidecar(temp_id).write_text(json.dumps(
        {"sha256": digest, "size": size, "pages": pages, "name": file.filename, "identifiers": ids}), encoding="utf-8")
    return {"temp_id": temp_id, "filename": file.filename, "size": size, "sha256": digest, "pages": pages,
            "guess": guess, "identifiers": ids, "duplicates": dups}


@router.get("/uploads/{temp_id}/page/{page}")
def upload_page(temp_id: str, page: int, w: int = 420, user=Depends(security.current_user)):
    path = _tmp_pdf(temp_id)
    if not path.exists():
        raise HTTPException(404, "The upload expired.")
    return Response(pdfutil.render_page_jpeg(path, page, min(max(w, 100), 1200)), media_type="image/jpeg")


@router.post("/autofill")
def autofill(body: AutofillIn, user=Depends(security.require_editor)):
    cands: list[tuple[str, str]] = []
    for kind, val in (("doi", body.doi), ("isbn", body.isbn), ("arxiv", body.arxiv)):
        if val and val.strip():
            cands.append((kind, val.strip()))
    if not cands and body.temp_id:
        ids = _read_sidecar(body.temp_id)["identifiers"]
        cands = [("doi", v) for v in ids["doi"]] + [("isbn", v) for v in ids["isbn"]] + [("arxiv", v) for v in ids["arxiv"]]
    if not cands:
        raise HTTPException(404, "No DOI, ISBN or arXiv ID found in the PDF. Type one in the form and try again.")
    last_error = None
    for kind, value in cands:
        try:
            if kind == "doi":
                found = lookup.lookup_doi(re.sub(r"(?i)^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value))
            elif kind == "isbn":
                digits = re.sub(r"[^0-9Xx]", "", value).upper()
                if not pdfutil.isbn_valid(digits):
                    continue
                found = lookup.lookup_isbn(pdfutil.isbn10_to_13(digits) if len(digits) == 10 else digits)
            else:
                found = lookup.lookup_arxiv(re.sub(r"(?i)^arxiv:\s*", "", value))
        except lookup.LookupFailed as e:
            last_error = str(e)
            continue
        if found:
            return {"identifier": {"type": kind, "value": value}, "fields": found}
    if last_error:
        raise HTTPException(502, last_error)
    raise HTTPException(404, "The identifiers found are not in Crossref, Open Library or arXiv.")


# --------------------------------------------------------------------------- items
@router.get("/items")
def list_items(q: str = "", field: str = "all", regex: bool = False, case: bool = False, whole: bool = False,
               udc_code: str | None = Query(None, alias="udc"), include_desc: bool = True,
               type: str | None = None, year_from: int | None = None, year_to: int | None = None,
               language: str | None = None, sort: str = "title", order: str = "asc", limit: int = 2000,
               user=Depends(security.current_user), conn=Depends(get_conn)):
    sql, args = ["SELECT * FROM items WHERE deleted_at IS NULL"], []
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
        args.append(language.lower())
    if udc_code == "none":
        sql.append("AND id NOT IN (SELECT item_id FROM item_udc WHERE node_code IS NOT NULL)")
    elif udc_code:
        nodes = udc.descendants(conn, udc_code) if include_desc else {udc_code}
        sql.append(f"AND id IN (SELECT item_id FROM item_udc WHERE node_code IN ({','.join('?' * len(nodes))}))")
        args.extend(sorted(nodes))
    items = [lib.row_to_item(r) for r in conn.execute(" ".join(sql), args)]
    if q.strip():
        try:
            matcher = lib.build_matcher(q, regex=regex, case=case, whole=whole)
        except lib.SearchError as e:
            raise HTTPException(400, str(e))
        items = lib.run_search(items, matcher, field, _type_labels(conn))
    lib.sort_items(items, sort, order != "desc")
    return {"total": len(items), "items": items[:limit]}


@router.get("/items/{item_id}")
def get_item(item_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    return lib.row_to_item(_row(conn, item_id))


@router.post("/items", status_code=201)
def create_item(body: CreateItem, user=Depends(security.require_editor), conn=Depends(get_conn)):
    tmp = _tmp_pdf(body.temp_id)
    side = _read_sidecar(body.temp_id)
    v = _validate(conn, body.fields)
    f = body.fields
    dups = _dups_for(conn, side["sha256"], v, f)
    if body.duplicate_action == "check" and dups:
        raise HTTPException(409, {"message": "This looks like a duplicate.", "duplicates": dups})

    if body.duplicate_action == "replace":
        if body.replace_id is None:
            raise HTTPException(422, "Choose which item to replace.")
        old = _row(conn, body.replace_id, include_deleted=True)
        _file_path(old).unlink(missing_ok=True)
        dest = config.LIBRARY_DIR / old["filename"]
        shutil.move(str(tmp), dest)
        conn.execute(
            "UPDATE items SET item_type=?, title=?, year=?, language=?, udc=?, creators=?, data=?, sha256=?, size=?, "
            "pages=?, cover_page=?, modified_at=?, deleted_at=NULL WHERE id=?",
            (f.item_type, v["title"], f.year, v["language"], f.udc.strip(), json.dumps(v["creators"]),
             json.dumps(v["data"]), side["sha256"], side["size"], side["pages"], body.cover_page, now(), old["id"]))
        udc.set_item_udc(conn, old["id"], f.udc)
        pdfutil.save_cover(dest, _cover_path(old["id"]), body.cover_page)
        conn.commit()
        _sidecar(body.temp_id).unlink(missing_ok=True)
        return lib.row_to_item(_row(conn, old["id"]))

    citekey = _new_citekey(conn, v["creators"], v["title"], f.year)
    dest = config.LIBRARY_DIR / f"{citekey}.pdf"
    shutil.move(str(tmp), dest)
    try:
        cur = conn.execute(
            "INSERT INTO items(citekey,item_type,title,year,language,udc,creators,data,filename,sha256,size,pages,"
            "cover_page,added_at,modified_at,added_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (citekey, f.item_type, v["title"], f.year, v["language"], f.udc.strip(), json.dumps(v["creators"]),
             json.dumps(v["data"]), dest.name, side["sha256"], side["size"], side["pages"], body.cover_page,
             now(), now(), user["id"]))
        item_id = cur.lastrowid
        udc.set_item_udc(conn, item_id, f.udc)
        pdfutil.save_cover(dest, _cover_path(item_id), body.cover_page)
        conn.commit()
    except Exception:
        conn.rollback()
        dest.unlink(missing_ok=True)
        raise
    _sidecar(body.temp_id).unlink(missing_ok=True)
    return lib.row_to_item(_row(conn, item_id))


@router.put("/items/{item_id}")
def update_item(item_id: int, body: UpdateItem, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _row(conn, item_id)
    v = _validate(conn, body)
    filename, citekey = row["filename"], row["citekey"]
    if body.regen_citekey:
        citekey = _new_citekey(conn, v["creators"], v["title"], body.year, exclude_id=item_id)
        if citekey != row["citekey"]:
            new_name = f"{citekey}.pdf"
            _file_path(row).rename(config.LIBRARY_DIR / new_name)
            filename = new_name
    cover = body.cover_page or row["cover_page"]
    conn.execute(
        "UPDATE items SET citekey=?, filename=?, item_type=?, title=?, year=?, language=?, udc=?, creators=?, data=?, "
        "cover_page=?, modified_at=? WHERE id=?",
        (citekey, filename, body.item_type, v["title"], body.year, v["language"], body.udc.strip(),
         json.dumps(v["creators"]), json.dumps(v["data"]), cover, now(), item_id))
    udc.set_item_udc(conn, item_id, body.udc)
    conn.commit()
    if body.cover_page and body.cover_page != row["cover_page"]:
        pdfutil.save_cover(config.LIBRARY_DIR / filename, _cover_path(item_id), body.cover_page)
    return lib.row_to_item(_row(conn, item_id))


@router.get("/items/{item_id}/file")
def item_file(item_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    row = _row(conn, item_id)
    path = _file_path(row)
    if not path.exists():
        raise HTTPException(404, "The PDF is missing on the server.")
    return FileResponse(path, media_type="application/pdf", filename=row["filename"])


@router.get("/items/{item_id}/cover")
def item_cover(item_id: int, user=Depends(security.current_user), conn=Depends(get_conn)):
    row = _row(conn, item_id, include_deleted=True)
    cover = _cover_path(item_id)
    if not cover.exists():
        pdfutil.save_cover(_file_path(row), cover, row["cover_page"])
    return FileResponse(cover, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/items/{item_id}/page/{page}")
def item_page(item_id: int, page: int, w: int = 420, user=Depends(security.current_user), conn=Depends(get_conn)):
    row = _row(conn, item_id)
    return Response(pdfutil.render_page_jpeg(_file_path(row), page, min(max(w, 100), 1200)), media_type="image/jpeg")


# --------------------------------------------------------------------------- trash
@router.delete("/items/{item_id}")
def trash_item(item_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _row(conn, item_id)
    src = _file_path(row)
    if src.exists():
        shutil.move(str(src), config.TRASH_DIR / row["filename"])
    conn.execute("UPDATE items SET deleted_at=? WHERE id=?", (now(), item_id))
    conn.commit()
    return {"ok": True}


@router.get("/trash")
def list_trash(user=Depends(security.require_editor), conn=Depends(get_conn)):
    rows = conn.execute("SELECT * FROM items WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
    return {"items": [lib.row_to_item(r) for r in rows]}


@router.post("/trash/{item_id}/restore")
def restore_item(item_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _row(conn, item_id, include_deleted=True)
    if not row["deleted_at"]:
        return {"ok": True}
    src = config.TRASH_DIR / row["filename"]
    if src.exists():
        shutil.move(str(src), config.LIBRARY_DIR / row["filename"])
    conn.execute("UPDATE items SET deleted_at=NULL WHERE id=?", (item_id,))
    conn.commit()
    return {"ok": True}


def purge_item(conn, row) -> None:
    _file_path(row).unlink(missing_ok=True)
    _cover_path(row["id"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM items WHERE id=?", (row["id"],))


@router.delete("/trash/{item_id}")
def delete_forever(item_id: int, user=Depends(security.require_editor), conn=Depends(get_conn)):
    row = _row(conn, item_id, include_deleted=True)
    if not row["deleted_at"]:
        raise HTTPException(409, "Move the item to the trash first.")
    purge_item(conn, row)
    conn.commit()
    return {"ok": True}
