"""Items on the Zotero model: reading, saving with provenance, automatic values, derived columns,
duplicates and search. No web framework code here (routes_library.py calls this)."""
import difflib
import re

import catalog
import udc
from db import SOURCES, now
from textutil import fold, make_citekey, unique_key


class ItemError(ValueError):
    """Invalid item data; the message is shown to the user."""


class SearchError(ValueError):
    pass


# --------------------------------------------------------------------------- normalisation
MONTHS = {
    "jan": 1, "ene": 1, "janv": 1, "gen": 1, "feb": 2, "fev": 2, "fevr": 2, "mar": 3, "mär": 3, "apr": 4,
    "abr": 4, "avr": 4, "may": 5, "mai": 5, "mag": 5, "mayo": 5, "jun": 6, "juin": 6, "giu": 6, "jul": 7,
    "juil": 7, "lug": 7, "aug": 8, "ago": 8, "aou": 8, "sep": 9, "set": 9, "sept": 9, "oct": 10, "okt": 10,
    "out": 10, "ott": 10, "nov": 11, "dec": 12, "dic": 12, "dez": 12,
}
_MONTH_RE = re.compile(r"[^\W\d_]{3,}", re.U)


def parse_date(s: str) -> str | None:
    """Free-text date -> 'YYYY-MM-DD' with 00 for unknown parts (as Zotero's multipart dates).

    '2004' -> 2004-00-00; 'March 2004' / 'marzo de 2004' -> 2004-03-00; '2004-03-12', '12 March 2004',
    'March 12, 2004' -> 2004-03-12; 'a/b/yyyy' is read month-first unless a > 12 (the UI is en-US).
    """
    s = (s or "").strip()
    if not s:
        return None
    y = m = d = 0
    if mt := re.search(r"\b(\d{4})[-/.](\d{1,2})(?:[-/.](\d{1,2}))?\b", s):
        y, m, d = int(mt[1]), int(mt[2]), int(mt[3] or 0)
    elif mt := re.search(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b", s):
        a, b, y = int(mt[1]), int(mt[2]), int(mt[3])
        m, d = (b, a) if a > 12 else (a, b)
    else:
        yt = re.search(r"\b(\d{4})\b", s)
        if not yt:
            return None
        y = int(yt[1])
        for w in _MONTH_RE.findall(fold(s)):
            for k in (w[:4], w[:3]):
                if k in MONTHS:
                    m = MONTHS[k]
                    break
            if m:
                break
        if m:
            rest = s[:yt.start()] + " " + s[yt.end():]
            dt = re.search(r"\b(\d{1,2})(?:st|nd|rd|th|º|°)?\b", rest)
            d = int(dt[1]) if dt else 0
    if not (0 < y < 3000) or not (0 <= m <= 12) or not (0 <= d <= 31):
        return None
    if m == 0:
        d = 0
    return f"{y:04d}-{m:02d}-{d:02d}"


LANGUAGES = {
    "english": "en", "ingles": "en", "spanish": "es", "espanol": "es", "castellano": "es", "french": "fr",
    "frances": "fr", "francais": "fr", "german": "de", "aleman": "de", "deutsch": "de", "italian": "it",
    "italiano": "it", "portuguese": "pt", "portugues": "pt", "russian": "ru", "ruso": "ru", "chinese": "zh",
    "chino": "zh", "japanese": "ja", "japones": "ja", "latin": "la", "latin.": "la", "catalan": "ca",
    "catala": "ca", "dutch": "nl", "polish": "pl", "greek": "el", "arabic": "ar", "korean": "ko",
}


def norm_language(s: str) -> str | None:
    """'en', 'en-US', 'English', 'Español' -> ISO 639-1 code (None if unknown)."""
    s = (s or "").strip()
    if m := re.fullmatch(r"([A-Za-z]{2,3})(?:[-_][A-Za-z]{2,4})?", s):
        code = m[1].lower()
        if len(code) == 2 or code not in LANGUAGES:
            return code
    return LANGUAGES.get(fold(s).split(" ")[0])


def norm_doi(s: str) -> str:
    s = re.sub(r"(?i)^\s*(https?://(dx\.)?doi\.org/|doi:\s*)", "", s or "").strip()
    return s.lower()


def isbn_digits(s: str) -> list[str]:
    """Every ISBN in a field (Zotero allows several separated by spaces), as ISBN-13 digits."""
    out = []
    for raw in re.findall(r"[0-9Xx][0-9Xx\-\s]{8,16}[0-9Xx]", s or ""):
        d = re.sub(r"[^0-9Xx]", "", raw).upper()
        if len(d) == 10:
            core = "978" + d[:9]
            total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(core))
            d = core + str((10 - total % 10) % 10)
        if len(d) == 13 and d not in out:
            out.append(d)
    return out


def norm_value(cat, field: str, value: str) -> str | None:
    if cat.field_kind(field) == "date":
        return parse_date(value)
    if field == "DOI":
        return norm_doi(value) or None
    if field == "ISBN":
        return " ".join(isbn_digits(value)) or None
    if field == "ISSN":
        return " ".join(re.sub(r"[^0-9Xx]", "", x).upper() for x in re.findall(r"\d{4}-?\d{3}[\dXx]", value)) or None
    if field == "language":
        return norm_language(value)
    return None


def extra_vars(extra: str) -> dict[str, str]:
    """'Type: musical_score\\nDOI: 10.1/x' -> {'type': 'musical_score', 'doi': '10.1/x'} (keys folded, no spaces)."""
    out = {}
    for line in (extra or "").splitlines():
        if m := re.match(r"\s*([A-Za-z][A-Za-z \-]*?)\s*:\s*(.+)$", line):
            out.setdefault(re.sub(r"[\s\-]", "", m[1]).lower(), m[2].strip())
    return out


# Leading articles ignored when sorting by title, by item language ("de" is an article in Dutch but a
# preposition in Spanish). Unknown language: only words that are articles wherever they appear.
ARTICLES_BY_LANG = {
    "en": ("the ", "a ", "an "),
    "es": ("el ", "la ", "los ", "las ", "lo ", "un ", "una ", "unos ", "unas "),
    "pt": ("o ", "a ", "os ", "as ", "um ", "uma "),
    "ca": ("el ", "la ", "els ", "les ", "l'", "l’", "un ", "una "),
    "fr": ("le ", "la ", "les ", "l'", "l’", "un ", "une "),
    "it": ("il ", "lo ", "la ", "i ", "gli ", "le ", "l'", "l’", "un ", "uno ", "una "),
    "de": ("der ", "die ", "das ", "ein ", "eine "),
    "nl": ("de ", "het ", "een "),
}
ARTICLES = ("the ", "an ", "el ", "los ", "las ", "les ", "l'", "l’", "der ", "die ", "das ", "il ", "gli ")


def sort_title(title: str, lang: str | None = None) -> str:
    t = fold((title or "").strip())
    for a in ARTICLES_BY_LANG.get((lang or "").split("-")[0], ARTICLES):
        if t.startswith(a) and len(t) > len(a):
            return t[len(a):].lstrip()
    return t


# --------------------------------------------------------------------------- input cleaning
def _value_obj(v) -> dict:
    """A field value as sent by a client: a string, or {value, source, confidence}."""
    if isinstance(v, dict):
        src = v.get("source") or "manual"
        if src not in SOURCES:
            raise ItemError(f"Unknown value source '{src}'.")
        conf = v.get("confidence")
        return {"value": str(v.get("value") or "").strip(), "source": src,
                "confidence": None if src == "manual" or conf is None else float(conf)}
    return {"value": str(v or "").strip(), "source": "manual", "confidence": None}


def clean_fields(cat, item_type: str, raw: dict) -> dict[str, dict]:
    out, bad = {}, []
    for code, v in (raw or {}).items():
        val = _value_obj(v)
        if not val["value"]:
            continue
        fd = cat.fields.get(code)
        if fd and fd["hidden"]:
            continue   # citationKey lives in items.citekey
        if not cat.allows_field(item_type, code):
            bad.append(code)
            continue
        out[code] = val
    if bad:
        raise ItemError(f"These fields do not belong to the type {cat.label('type', item_type)}: {', '.join(bad)}.")
    return out


def clean_creators(cat, item_type: str, raw: list) -> list[dict]:
    out, bad = [], []
    for c in raw or []:
        c = dict(c)
        last, first = (c.get("last_name") or "").strip(), (c.get("first_name") or "").strip()
        if not last and not first:
            continue
        mode = 1 if int(c.get("field_mode") or 0) else 0
        if mode == 1:   # one-field name (institutions): Zotero keeps it in lastName
            last, first = last or first, ""
        ct = c.get("creator_type") or cat.primary_creator(item_type)
        if not cat.allows_creator(item_type, ct):
            bad.append(ct)
            continue
        src = c.get("source") or "manual"
        if src not in SOURCES:
            raise ItemError(f"Unknown value source '{src}'.")
        conf = c.get("confidence")
        out.append({"creator_type": ct, "last_name": last, "first_name": first, "field_mode": mode, "source": src,
                    "confidence": None if src == "manual" or conf is None else float(conf)})
    if bad:
        raise ItemError(f"The type {cat.label('type', item_type)} has no creator role: {', '.join(sorted(set(bad)))}.")
    return out


def clean_list(raw: list, key: str) -> list[dict]:
    """Tags ({name}) or UDC notations ({notation}): strings or objects, blanks and repeats removed."""
    out, seen = [], set()
    for x in raw or []:
        obj = dict(x) if isinstance(x, dict) else {key: x}
        text = " ".join(str(obj.get(key) or "").split())
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        src = obj.get("source") or "manual"
        if src not in SOURCES:
            raise ItemError(f"Unknown value source '{src}'.")
        conf = obj.get("confidence")
        out.append({key: text, "source": src, "confidence": None if src == "manual" or conf is None else float(conf)})
    return out


def title_field(cat, item_type: str) -> str:
    return cat.field_for_base(item_type, "title") or "title"


# --------------------------------------------------------------------------- reading
def _chunks(ids, n=900):
    ids = list(ids)
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def creators_text(creators: list[dict]) -> str:
    parts = []
    for c in creators:
        last, first = c.get("last_name", ""), c.get("first_name", "")
        parts.append(f"{last}, {first}" if last and first else (last or first))
    return "; ".join(p for p in parts if p)


def load_items(conn, ids, *, light: bool = False) -> list[dict]:
    """Full items in the order of `ids`. light=True leaves out notes (list views)."""
    cat = catalog.get(conn)
    ids = list(ids)
    if not ids:
        return []
    items: dict[int, dict] = {}
    for chunk in _chunks(ids):
        q = ",".join("?" * len(chunk))
        for r in conn.execute(f"SELECT * FROM items WHERE id IN ({q})", chunk):
            items[r["id"]] = {
                "id": r["id"], "citekey": r["citekey"], "item_type": r["item_type"], "fields": {}, "creators": [],
                "tags": [], "udc": [], "attachments": [], "year": r["year"], "language": r["language"],
                "date_sort": r["date_sort"], "added_at": r["added_at"], "modified_at": r["modified_at"],
                "deleted_at": r["deleted_at"]}
        for r in conn.execute(f"SELECT * FROM item_fields WHERE item_id IN ({q})", chunk):
            items[r["item_id"]]["fields"][r["field"]] = {
                "value": r["value"], "source": r["source"], "confidence": r["confidence"],
                "confirmed": bool(r["confirmed"])}
        for r in conn.execute(f"SELECT * FROM item_creators WHERE item_id IN ({q}) ORDER BY item_id, position", chunk):
            items[r["item_id"]]["creators"].append({
                "creator_type": r["creator_type"], "last_name": r["last_name"], "first_name": r["first_name"],
                "field_mode": r["field_mode"], "source": r["source"], "confidence": r["confidence"],
                "confirmed": bool(r["confirmed"])})
        for r in conn.execute(f"SELECT it.item_id, t.name, it.source FROM item_tags it JOIN tags t ON t.id=it.tag_id "
                              f"WHERE it.item_id IN ({q}) ORDER BY t.name COLLATE NOCASE", chunk):
            items[r["item_id"]]["tags"].append({"name": r["name"], "source": r["source"]})
        for r in conn.execute(f"SELECT * FROM item_udc WHERE item_id IN ({q}) ORDER BY item_id, position", chunk):
            items[r["item_id"]]["udc"].append({"notation": r["notation"], "source": r["source"],
                                               "confidence": r["confidence"], "confirmed": bool(r["confirmed"])})
        for r in conn.execute(f"SELECT * FROM attachments WHERE item_id IN ({q}) "
                              f"ORDER BY item_id, role, position, id", chunk):
            items[r["item_id"]]["attachments"].append({
                "id": r["id"], "role": r["role"], "label": r["label"], "position": r["position"],
                "filename": r["filename"], "sha256": r["sha256"], "size": r["size"], "mime": r["mime"],
                "pages": r["pages"], "cover_page": r["cover_page"], "added_at": r["added_at"],
                "deleted_at": r["deleted_at"]})
        if not light:
            for it in (items[i] for i in chunk if i in items):
                it["notes"] = []
            for r in conn.execute(f"SELECT * FROM item_notes WHERE item_id IN ({q}) ORDER BY item_id, id", chunk):
                items[r["item_id"]]["notes"].append({"id": r["id"], "body": r["body"], "created_at": r["created_at"],
                                                     "modified_at": r["modified_at"]})
    out = []
    for i in ids:
        it = items.get(i)
        if it is None:
            continue
        tf = title_field(cat, it["item_type"])
        it["title"] = it["fields"].get(tf, {}).get("value", "")
        it["creators_text"] = creators_text(it["creators"])
        it["udc_text"] = " ; ".join(u["notation"] for u in it["udc"])
        it["main"] = next((a for a in it["attachments"] if a["role"] == "main"), None)
        if not light:
            import coherence   # here: coherence imports this module
            it["warnings"] = coherence.check(conn, it["item_type"], [u["notation"] for u in it["udc"]],
                                             it["fields"].get("extra", {}).get("value", ""))
        out.append(it)
    return out


def load_item(conn, item_id: int) -> dict | None:
    got = load_items(conn, [item_id])
    return got[0] if got else None


# --------------------------------------------------------------------------- derived columns, citekey
def refresh_derived(conn, item_id: int) -> None:
    cat = catalog.get(conn)
    itype = conn.execute("SELECT item_type FROM items WHERE id=?", (item_id,)).fetchone()[0]
    vals = {r["field"]: (r["value"], r["norm"]) for r in
            conn.execute("SELECT field, value, norm FROM item_fields WHERE item_id=?", (item_id,))}
    title = vals.get(title_field(cat, itype), ("", None))[0]
    date_f = cat.field_for_base(itype, "date")
    date_sort = vals.get(date_f, (None, None))[1] if date_f else None
    year = int(date_sort[:4]) if date_sort and date_sort[:4] != "0000" else None
    primary = cat.primary_creator(itype)
    rows = conn.execute("SELECT creator_type, last_name, first_name FROM item_creators WHERE item_id=? "
                        "ORDER BY creator_type<>?, position", (item_id, primary)).fetchall()
    first = (rows[0]["last_name"] or rows[0]["first_name"]) if rows else ""
    conn.execute("UPDATE items SET sort_title=?, sort_creator=?, date_sort=?, year=?, language=? WHERE id=?",
                 (sort_title(title, vals.get("language", (None, None))[1]), fold(first), date_sort, year,
                  vals.get("language", (None, None))[1], item_id))


def citekey_for(conn, item_id: int) -> str:
    row = conn.execute("SELECT sort_title, year, item_type FROM items WHERE id=?", (item_id,)).fetchone()
    cat = catalog.get(conn)
    title = (conn.execute("SELECT value FROM item_fields WHERE item_id=? AND field=?",
                          (item_id, title_field(cat, row["item_type"]))).fetchone() or [""])[0]
    first = conn.execute("SELECT last_name, first_name FROM item_creators WHERE item_id=? "
                         "ORDER BY creator_type<>?, position LIMIT 1",
                         (item_id, cat.primary_creator(row["item_type"]))).fetchone()
    name = (first["last_name"] or first["first_name"]) if first else ""

    def taken(k):
        r = conn.execute("SELECT id FROM items WHERE citekey=?", (k,)).fetchone()
        return bool(r) and r[0] != item_id

    return unique_key(make_citekey(name, title, row["year"]), taken)


# --------------------------------------------------------------------------- writing (people)
def _confirmed(confirm: bool, source: str) -> int:
    """Saved by a person: everything is confirmed. Saved by a program (bulk import): only manual values."""
    return 1 if confirm or source == "manual" else 0


def _write_fields(conn, cat, item_id: int, fields: dict[str, dict], user_id, confirm: bool = True) -> None:
    """Replace the item's fields with `fields`, as saved by a person: every value ends up confirmed
    (confirm=False: only manual values). A value left as it was keeps its source (so automatic sources
    can be measured)."""
    old = {r["field"]: r for r in conn.execute("SELECT * FROM item_fields WHERE item_id=?", (item_id,))}
    ts = now()
    for code, r in old.items():
        if code not in fields and not cat.fields.get(code, {}).get("obsolete"):
            conn.execute("DELETE FROM item_fields WHERE item_id=? AND field=?", (item_id, code))
    for code, v in fields.items():
        prev = old.get(code)
        if prev is not None and prev["value"] == v["value"]:
            if not prev["confirmed"] and confirm:
                conn.execute("UPDATE item_fields SET confirmed=1, updated_at=?, updated_by=? "
                             "WHERE item_id=? AND field=?", (ts, user_id, item_id, code))
            continue
        conn.execute(
            "INSERT INTO item_fields(item_id, field, value, norm, source, confidence, confirmed, updated_at, updated_by) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(item_id, field) DO UPDATE SET value=excluded.value, "
            "norm=excluded.norm, source=excluded.source, confidence=excluded.confidence, "
            "confirmed=excluded.confirmed, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (item_id, code, v["value"], norm_value(cat, code, v["value"]), v["source"], v["confidence"],
             _confirmed(confirm, v["source"]), ts, user_id))


def _write_creators(conn, item_id: int, creators: list[dict], confirm: bool = True) -> None:
    old = {(r["creator_type"], r["last_name"], r["first_name"]): r
           for r in conn.execute("SELECT * FROM item_creators WHERE item_id=?", (item_id,))}
    conn.execute("DELETE FROM item_creators WHERE item_id=?", (item_id,))
    for pos, c in enumerate(creators):
        prev = old.get((c["creator_type"], c["last_name"], c["first_name"]))
        src, conf = (prev["source"], prev["confidence"]) if prev else (c["source"], c["confidence"])
        conn.execute("INSERT INTO item_creators(item_id, position, creator_type, last_name, first_name, field_mode, "
                     "source, confidence, confirmed) VALUES (?,?,?,?,?,?,?,?,?)",
                     (item_id, pos, c["creator_type"], c["last_name"], c["first_name"], c["field_mode"], src, conf,
                      _confirmed(confirm, src)))


def _write_tags(conn, item_id: int, tags: list[dict]) -> None:
    old = {r["name"].lower(): r["source"] for r in conn.execute(
        "SELECT t.name, it.source FROM item_tags it JOIN tags t ON t.id=it.tag_id WHERE it.item_id=?", (item_id,))}
    conn.execute("DELETE FROM item_tags WHERE item_id=?", (item_id,))
    for t in tags:
        conn.execute("INSERT OR IGNORE INTO tags(name) VALUES (?)", (t["name"],))
        tag_id = conn.execute("SELECT id FROM tags WHERE name=?", (t["name"],)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO item_tags(item_id, tag_id, source) VALUES (?,?,?)",
                     (item_id, tag_id, old.get(t["name"].lower(), t["source"])))
    conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM item_tags)")


def _write_udc(conn, item_id: int, entries: list[dict], confirm: bool = True) -> None:
    old = {r["notation"]: r for r in conn.execute("SELECT * FROM item_udc WHERE item_id=?", (item_id,))}
    conn.execute("DELETE FROM item_udc WHERE item_id=?", (item_id,))
    for pos, u in enumerate(entries):
        prev = old.get(u["notation"])
        src, conf = (prev["source"], prev["confidence"]) if prev else (u["source"], u["confidence"])
        conn.execute("INSERT INTO item_udc(item_id, position, notation, source, confidence, confirmed) "
                     "VALUES (?,?,?,?,?,?)", (item_id, pos, u["notation"], src, conf, _confirmed(confirm, src)))
    udc.refresh_item_nodes(conn, item_id)


def save_item(conn, user_id, data: dict, item_id: int | None = None, *, confirm: bool = True) -> int:
    """Create (item_id None) or replace an item's bibliographic data as saved by a person.
    confirm=False (bulk import): values keep confirmed=0 unless their source is 'manual'.

    data: {item_type, fields: {code: str | {value, source, confidence}}, creators: [...], tags: [...],
    udc: [...]}. Runs inside the caller's transaction; the caller commits. Returns the item id.
    Changing the type of an existing item: the client sends the values already converted (see /convert-type).
    """
    cat = catalog.get(conn)
    itype = data.get("item_type") or ""
    t = cat.types.get(itype)
    if t is None:
        raise ItemError(f"Unknown item type '{itype}'.")
    if item_id is None and not t["enabled"]:
        raise ItemError(f"The type {cat.label('type', itype)} is not available yet.")
    fields = clean_fields(cat, itype, data.get("fields"))
    if not fields.get(title_field(cat, itype), {}).get("value"):
        raise ItemError(f"{cat.label('field', title_field(cat, itype))} is required.")
    creators = clean_creators(cat, itype, data.get("creators"))
    tags = clean_list(data.get("tags"), "name")
    notations = clean_list(data.get("udc"), "notation")
    ts = now()
    new = item_id is None
    if new:
        tmp_key = f"tmp-{ts}-{id(data)}"
        item_id = conn.execute(
            "INSERT INTO items(citekey, item_type, added_at, added_by, modified_at, modified_by) VALUES (?,?,?,?,?,?)",
            (tmp_key, itype, ts, user_id, ts, user_id)).lastrowid
    else:
        old_type = conn.execute("SELECT item_type FROM items WHERE id=?", (item_id,)).fetchone()[0]
        if old_type != itype:
            # drop what the new type cannot hold (the client already moved it), then switch the type
            conn.execute("DELETE FROM item_fields WHERE item_id=? AND field NOT IN "
                         "(SELECT field FROM item_type_fields WHERE item_type=?)", (item_id, itype))
            conn.execute("DELETE FROM item_creators WHERE item_id=? AND creator_type NOT IN "
                         "(SELECT creator_type FROM item_type_creators WHERE item_type=?)", (item_id, itype))
            conn.execute("UPDATE items SET item_type=? WHERE id=?", (itype, item_id))
        conn.execute("UPDATE items SET modified_at=?, modified_by=? WHERE id=?", (ts, user_id, item_id))
    _write_fields(conn, cat, item_id, fields, user_id, confirm)
    _write_creators(conn, item_id, creators, confirm)
    _write_tags(conn, item_id, tags)
    _write_udc(conn, item_id, notations, confirm)
    refresh_derived(conn, item_id)
    if new:
        conn.execute("UPDATE items SET citekey=? WHERE id=?", (citekey_for(conn, item_id), item_id))
    return item_id


def change_type(conn, user_id, item_id: int, new_type: str, *, dry_run: bool = False) -> dict:
    """Server-side type change of a stored item (same rules as catalog.convert). Returns the report."""
    cat = catalog.get(conn)
    if new_type not in cat.types:
        raise ItemError(f"Unknown item type '{new_type}'.")
    it = load_item(conn, item_id)
    res = catalog.convert(cat, it["item_type"], new_type, it["fields"], it["creators"])
    if dry_run or new_type == it["item_type"]:
        return res["report"]
    ts = now()
    conn.execute("DELETE FROM item_fields WHERE item_id=?", (item_id,))
    conn.execute("DELETE FROM item_creators WHERE item_id=?", (item_id,))
    conn.execute("UPDATE items SET item_type=?, modified_at=?, modified_by=? WHERE id=?",
                 (new_type, ts, user_id, item_id))
    for code, v in res["fields"].items():
        conn.execute("INSERT INTO item_fields(item_id, field, value, norm, source, confidence, confirmed, updated_at, "
                     "updated_by) VALUES (?,?,?,?,?,?,?,?,?)",
                     (item_id, code, v["value"], norm_value(cat, code, v["value"]), v.get("source", "manual"),
                      v.get("confidence"), int(bool(v.get("confirmed"))), ts, user_id))
    for pos, c in enumerate(res["creators"]):
        conn.execute("INSERT INTO item_creators(item_id, position, creator_type, last_name, first_name, field_mode, "
                     "source, confidence, confirmed) VALUES (?,?,?,?,?,?,?,?,?)",
                     (item_id, pos, c["creator_type"], c["last_name"], c["first_name"], c["field_mode"],
                      c["source"], c["confidence"], int(bool(c["confirmed"]))))
    refresh_derived(conn, item_id)
    return res["report"]


# --------------------------------------------------------------------------- writing (automatic sources)
def fit_to_type(cat, item_type: str, values: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Values keyed by Zotero field or base field (as lookups produce them) -> the type's own fields.
    Values with no place become 'Label: value' lines for Extra."""
    out, extra = {}, []
    for code, value in values.items():
        if not value:
            continue
        target = code if cat.allows_field(item_type, code) else cat.field_for_base(item_type, cat.base_any(code))
        if target and target not in out:
            out[target] = value
        else:
            extra.append(f"{cat.label('field', code)}: {value}")
    return out, extra


def apply_auto(conn, item_id: int, values: dict[str, dict]) -> list[dict]:
    """Write values from an automatic source ({field: {value, source, confidence}}).

    A confirmed value is never overwritten: if it differs, the new value comes back as a suggestion.
    An unconfirmed value is replaced only by a more confident one. Returns the suggestions.
    """
    cat = catalog.get(conn)
    itype = conn.execute("SELECT item_type FROM items WHERE id=?", (item_id,)).fetchone()[0]
    suggestions, ts = [], now()
    for code, v in values.items():
        v = _value_obj(v)
        if not v["value"]:
            continue
        if v["source"] == "manual":
            raise ItemError("Automatic values need their source.")
        if not cat.allows_field(itype, code):
            suggestions.append({"field": code, "value": v["value"], "source": v["source"],
                                "confidence": v["confidence"], "reason": "no such field for this type"})
            continue
        cur = conn.execute("SELECT * FROM item_fields WHERE item_id=? AND field=?", (item_id, code)).fetchone()
        if cur is not None and cur["value"] == v["value"]:
            continue
        if cur is not None and (cur["confirmed"] or (cur["confidence"] or 0) >= (v["confidence"] or 0)):
            suggestions.append({"field": code, "value": v["value"], "source": v["source"],
                                "confidence": v["confidence"], "current": cur["value"],
                                "reason": "confirmed" if cur["confirmed"] else "less confident"})
            continue
        conn.execute(
            "INSERT INTO item_fields(item_id, field, value, norm, source, confidence, confirmed, updated_at) "
            "VALUES (?,?,?,?,?,?,0,?) ON CONFLICT(item_id, field) DO UPDATE SET value=excluded.value, "
            "norm=excluded.norm, source=excluded.source, confidence=excluded.confidence, confirmed=0, "
            "updated_at=excluded.updated_at, updated_by=NULL",
            (item_id, code, v["value"], norm_value(cat, code, v["value"]), v["source"], v["confidence"], ts))
    refresh_derived(conn, item_id)
    return suggestions


def set_udc_auto(conn, item_id: int, notation: str, source: str, confidence: float | None) -> dict | None:
    """Classifier suggestion: becomes the main notation unless a person confirmed one (then it is returned)."""
    if source not in SOURCES or source == "manual":
        raise ItemError("Automatic values need their source.")
    cur = conn.execute("SELECT * FROM item_udc WHERE item_id=? AND position=0", (item_id,)).fetchone()
    if cur is not None and (cur["confirmed"] or (cur["confidence"] or 0) >= (confidence or 0)):
        if cur["notation"] == notation:
            return None
        return {"notation": notation, "source": source, "confidence": confidence, "current": cur["notation"]}
    conn.execute("INSERT OR REPLACE INTO item_udc(item_id, position, notation, source, confidence, confirmed) "
                 "VALUES (?,0,?,?,?,0)", (item_id, notation, source, confidence))
    udc.refresh_item_nodes(conn, item_id)
    return None


# --------------------------------------------------------------------------- duplicates
def find_duplicates(conn, *, sha256=None, doi=None, isbn=None, title=None, year=None,
                    first_creator=None, exclude_id=None) -> list[dict]:
    """Possible duplicates, in this order: same file (any attachment, also in the trash), same DOI (field or
    'DOI:' in Extra) or ISBN, then a very similar title with matching first creator and year."""
    reasons: dict[int, str] = {}

    def add(item_id, reason):
        if item_id != exclude_id and item_id not in reasons:
            reasons[item_id] = reason

    if sha256:
        for r in conn.execute("SELECT DISTINCT item_id FROM attachments WHERE sha256=?", (sha256,)):
            add(r[0], "Identical file")
    if doi and (d := norm_doi(doi)):
        for r in conn.execute("SELECT item_id FROM item_fields WHERE field='DOI' AND norm=?", (d,)):
            add(r[0], "Same DOI")
        for r in conn.execute("SELECT item_id, value FROM item_fields WHERE field='extra' AND value LIKE '%DOI:%'"):
            if norm_doi(extra_vars(r["value"]).get("doi", "")) == d:
                add(r["item_id"], "Same DOI")
    wanted = set(isbn_digits(isbn or ""))
    if wanted:
        for r in conn.execute("SELECT item_id, norm FROM item_fields WHERE field='ISBN' AND norm IS NOT NULL"):
            if wanted & set(r["norm"].split()):
                add(r["item_id"], "Same ISBN")
    st = sort_title(title or "")
    if len(st) > 8:
        author = fold(first_creator or "")
        for r in conn.execute("SELECT id, sort_title, sort_creator, year FROM items"):
            if r["id"] in reasons or not r["sort_title"]:
                continue
            if difflib.SequenceMatcher(None, st, r["sort_title"]).ratio() >= 0.9:
                year_ok = year is None or r["year"] is None or year == r["year"]
                author_ok = not author or not r["sort_creator"] or author == r["sort_creator"]
                if year_ok and author_ok:
                    add(r["id"], "Very similar title, creator and year")
    out = []
    for it in load_items(conn, list(reasons), light=True):
        out.append({"reason": reasons[it["id"]], "id": it["id"], "title": it["title"], "citekey": it["citekey"],
                    "year": it["year"], "creators_text": it["creators_text"], "in_trash": it["deleted_at"] is not None})
    return out


# --------------------------------------------------------------------------- search and sort
def build_matcher(query: str, *, regex: bool = False, case: bool = False, whole: bool = False):
    """Return find(text) -> [[start, end], ...] (offsets refer to the original text)."""
    if not query:
        return None
    pattern = query if regex else re.escape(query if case else fold(query))
    if whole:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    try:
        rx = re.compile(pattern, 0 if case else re.IGNORECASE)
    except re.error as e:
        raise SearchError(f"Invalid regular expression: {e}")
    fold_text = (not case) and (not regex)

    def find(text: str) -> list[list[int]]:
        hay = fold(text) if fold_text else text
        spans: list[list[int]] = []
        for m in rx.finditer(hay):
            if m.end() > m.start():
                spans.append([m.start(), m.end()])
                if len(spans) >= 100:
                    break
        return spans

    return find


# pseudo-fields that are not Zotero fields
SEARCH_EXTRA = ("creators", "year", "type", "udc", "citekey", "tags")


def searchable(cat, item: dict) -> dict[str, str]:
    f = {code: v["value"] for code, v in item["fields"].items()}
    f.update({"creators": item["creators_text"], "year": str(item["year"] or ""),
              "type": cat.label("type", item["item_type"]), "udc": item["udc_text"], "citekey": item["citekey"],
              "tags": "; ".join(t["name"] for t in item["tags"])})
    return f


def run_search(conn, items: list[dict], matcher, field: str) -> list[dict]:
    """field: 'all', a pseudo-field, or a Zotero field. A base field also searches its variants
    ('publisher' finds university, label, institution...)."""
    cat = catalog.get(conn)
    wanted = None if field == "all" else (cat.variants(field) if field in cat.fields else {field})
    out = []
    for it in items:
        hits = {}
        for k, t in searchable(cat, it).items():
            if t and (wanted is None or k in wanted):
                spans = matcher(t)
                if spans:
                    hits[k] = spans
        if hits:
            it["matches"] = hits
            out.append(it)
    return out


SORT_SQL = {"title": "sort_title", "author": "sort_creator", "date": "date_sort", "year": "date_sort",
            "added": "added_at"}


def sort_items(items: list[dict], key: str, ascending: bool) -> None:
    if key in ("year", "date"):
        have = [i for i in items if i["date_sort"]]
        miss = [i for i in items if not i["date_sort"]]   # unknown dates always last
        have.sort(key=lambda it: it["date_sort"], reverse=not ascending)
        items[:] = have + miss
        return
    keyfun = {"author": lambda it: (fold(it["creators"][0]["last_name"]) if it["creators"] else "￿"),
              "added": lambda it: it["added_at"]}.get(key, lambda it: sort_title(it["title"]))
    items.sort(key=keyfun, reverse=not ascending)
