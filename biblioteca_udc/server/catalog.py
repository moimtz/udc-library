"""Zotero item-type catalog: zotero/schema.json (official, never edited) + zotero/zotero_overlay.json (ours).

sync() copies both into the catalog tables (item_types, fields, item_type_fields, creator_types,
item_type_creators) when the schema version or the overlay changes. The rest of the server reads the
catalog from the database through Catalog, which is cached per catalog revision.
"""
import hashlib
import json
from pathlib import Path

ZOTERO_DIR = Path(__file__).resolve().parent / "zotero"
SCHEMA_PATH = ZOTERO_DIR / "schema.json"
OVERLAY_PATH = ZOTERO_DIR / "zotero_overlay.json"

# Zotero types whose job is done by our own tables (attachments, item_notes).
SKIPPED_TYPES = {"annotation", "attachment", "note"}
KINDS = ("text", "longtext", "date", "url")
DEFAULT_LANG = "en-US"


def _load():
    schema_bytes = SCHEMA_PATH.read_bytes()
    overlay_bytes = OVERLAY_PATH.read_bytes()
    return json.loads(schema_bytes), json.loads(overlay_bytes), hashlib.sha256(overlay_bytes).hexdigest()


def _meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _labels(locales: dict, section: str, code: str) -> str:
    out = {lang: loc[section][code] for lang, loc in locales.items() if code in loc.get(section, {})}
    return json.dumps(out, ensure_ascii=False, sort_keys=True)


def sync(conn, force: bool = False) -> bool:
    """Bring the catalog tables in line with schema.json + overlay. Returns True if it wrote anything.

    Rows still used by items are never deleted: a field Zotero dropped is marked obsolete, and a
    (type, field) or (type, creator) pair that items still use is kept.
    """
    schema, overlay, ohash = _load()
    version = str(schema["version"])
    if not force and _meta(conn, "zotero_schema_version") == version and _meta(conn, "zotero_overlay_hash") == ohash:
        return False

    locales = schema["locales"]
    types = [t for t in schema["itemTypes"] if t["itemType"] not in SKIPPED_TYPES]
    enabled = set(overlay.get("enabled_types", []))
    unknown = enabled - {t["itemType"] for t in types}
    if unknown:
        raise ValueError(f"zotero_overlay.json enables unknown item types: {sorted(unknown)}")
    date_fields = {f for f, m in schema.get("meta", {}).get("fields", {}).items() if m.get("type") == "date"}
    kinds = overlay.get("field_kind", {})
    hidden = set(overlay.get("hidden_fields", []))
    help_ = overlay.get("help", {})
    help_by_type = overlay.get("help_by_type", {})
    not_citable = set(overlay.get("creator_not_citable", []))
    creator_help = overlay.get("creator_help", {})
    type_help = overlay.get("type_help", {})

    # fields: every field used by a type, plus the base fields (authority, medium have no direct use)
    base_of: dict[tuple[str, str], str] = {}
    field_codes: list[str] = []
    for t in types:
        for f in t["fields"]:
            field_codes.append(f["field"])
            if "baseField" in f:
                base_of[(t["itemType"], f["field"])] = f["baseField"]
                field_codes.append(f["baseField"])
    field_codes = list(dict.fromkeys(field_codes))

    def kind_of(code: str) -> str:
        if code in kinds:
            k = kinds[code]
        elif code in date_fields or any(b in date_fields for (_, f), b in base_of.items() if f == code):
            k = "date"
        else:
            k = "text"
        if k not in KINDS:
            raise ValueError(f"zotero_overlay.json: field_kind of {code} must be one of {KINDS}")
        return k

    with conn:
        for pos, t in enumerate(types):
            code = t["itemType"]
            conn.execute(
                "INSERT INTO item_types(code, labels, help, enabled, position) VALUES (?,?,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET labels=excluded.labels, help=excluded.help, "
                "enabled=excluded.enabled, position=excluded.position",
                (code, _labels(locales, "itemTypes", code), type_help.get(code, ""), int(code in enabled), pos))
        # a type Zotero removed stays (items may use it) but can no longer be chosen
        live_types = [t["itemType"] for t in types]
        conn.execute(f"UPDATE item_types SET enabled=0 WHERE code NOT IN ({','.join('?' * len(live_types))})",
                     live_types)

        for code in field_codes:
            conn.execute(
                "INSERT INTO fields(code, labels, kind, help, hidden, obsolete) VALUES (?,?,?,?,?,0) "
                "ON CONFLICT(code) DO UPDATE SET labels=excluded.labels, kind=excluded.kind, help=excluded.help, "
                "hidden=excluded.hidden, obsolete=0",
                (code, _labels(locales, "fields", code), kind_of(code), help_.get(code, ""), int(code in hidden)))
        conn.execute(f"UPDATE fields SET obsolete=1 WHERE code NOT IN ({','.join('?' * len(field_codes))})",
                     field_codes)

        pairs = set()
        for t in types:
            for pos, f in enumerate(t["fields"]):
                key = (t["itemType"], f["field"])
                pairs.add(key)
                conn.execute(
                    "INSERT INTO item_type_fields(item_type, field, base_field, position, help) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(item_type, field) DO UPDATE SET base_field=excluded.base_field, "
                    "position=excluded.position, help=excluded.help",
                    (*key, base_of.get(key), pos, help_by_type.get(key[0], {}).get(key[1])))
        for r in conn.execute("SELECT item_type, field FROM item_type_fields").fetchall():
            if (r[0], r[1]) not in pairs and not conn.execute(
                    "SELECT 1 FROM item_fields f JOIN items i ON i.id=f.item_id WHERE i.item_type=? AND f.field=?",
                    (r[0], r[1])).fetchone():
                conn.execute("DELETE FROM item_type_fields WHERE item_type=? AND field=?", (r[0], r[1]))

        creator_codes = list(dict.fromkeys(c["creatorType"] for t in types for c in t["creatorTypes"]))
        for code in creator_codes:
            conn.execute(
                "INSERT INTO creator_types(code, labels, help, citable) VALUES (?,?,?,?) "
                "ON CONFLICT(code) DO UPDATE SET labels=excluded.labels, help=excluded.help, citable=excluded.citable",
                (code, _labels(locales, "creatorTypes", code), creator_help.get(code, ""),
                 int(code not in not_citable)))
        cpairs = set()
        for t in types:
            for pos, c in enumerate(t["creatorTypes"]):
                key = (t["itemType"], c["creatorType"])
                cpairs.add(key)
                conn.execute(
                    "INSERT INTO item_type_creators(item_type, creator_type, is_primary, position) VALUES (?,?,?,?) "
                    "ON CONFLICT(item_type, creator_type) DO UPDATE SET is_primary=excluded.is_primary, "
                    "position=excluded.position",
                    (*key, int(bool(c.get("primary"))), pos))
        for r in conn.execute("SELECT item_type, creator_type FROM item_type_creators").fetchall():
            if (r[0], r[1]) not in cpairs and not conn.execute(
                    "SELECT 1 FROM item_creators c JOIN items i ON i.id=c.item_id "
                    "WHERE i.item_type=? AND c.creator_type=?", (r[0], r[1])).fetchone():
                conn.execute("DELETE FROM item_type_creators WHERE item_type=? AND creator_type=?", (r[0], r[1]))

        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('zotero_schema_version', ?)", (version,))
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('zotero_overlay_hash', ?)", (ohash,))
    _CACHE.clear()
    return True


# --------------------------------------------------------------------------- read side
class Catalog:
    """In-memory view of the catalog tables (small: ~1,000 rows)."""

    def __init__(self, conn):
        self.types: dict[str, dict] = {}
        for r in conn.execute("SELECT * FROM item_types ORDER BY position"):
            self.types[r["code"]] = {"code": r["code"], "labels": json.loads(r["labels"]), "help": r["help"],
                                     "enabled": bool(r["enabled"]), "position": r["position"]}
        self.fields: dict[str, dict] = {}
        for r in conn.execute("SELECT * FROM fields"):
            self.fields[r["code"]] = {"code": r["code"], "labels": json.loads(r["labels"]), "kind": r["kind"],
                                      "help": r["help"], "hidden": bool(r["hidden"]), "obsolete": bool(r["obsolete"])}
        # type -> ordered [(field, base_field, help)]
        self.type_fields: dict[str, list[dict]] = {t: [] for t in self.types}
        for r in conn.execute("SELECT * FROM item_type_fields ORDER BY item_type, position"):
            self.type_fields.setdefault(r["item_type"], []).append(
                {"field": r["field"], "base": r["base_field"], "help": r["help"]})
        self.creator_types: dict[str, dict] = {}
        for r in conn.execute("SELECT * FROM creator_types"):
            self.creator_types[r["code"]] = {"code": r["code"], "labels": json.loads(r["labels"]),
                                             "help": r["help"], "citable": bool(r["citable"])}
        self.type_creators: dict[str, list[dict]] = {t: [] for t in self.types}
        for r in conn.execute("SELECT * FROM item_type_creators ORDER BY item_type, position"):
            self.type_creators.setdefault(r["item_type"], []).append(
                {"creator_type": r["creator_type"], "primary": bool(r["is_primary"])})
        self._allowed = {t: {f["field"] for f in fs} for t, fs in self.type_fields.items()}
        self._base = {(t, f["field"]): f["base"] for t, fs in self.type_fields.items() for f in fs}
        self._base_any = {f: b for (_, f), b in self._base.items() if b}

    # ---- lookups
    def allows_field(self, item_type: str, field: str) -> bool:
        return field in self._allowed.get(item_type, ())

    def allows_creator(self, item_type: str, creator_type: str) -> bool:
        return any(c["creator_type"] == creator_type for c in self.type_creators.get(item_type, ()))

    def base_of(self, item_type: str, field: str) -> str:
        """Base field of a type's field ('university' in thesis -> 'publisher'); a base field maps to itself."""
        return self._base.get((item_type, field)) or field

    def base_any(self, field: str) -> str:
        """Base field of a field in whatever type uses it ('university' -> 'publisher')."""
        return self._base_any.get(field, field)

    def field_for_base(self, item_type: str, base: str) -> str | None:
        """The field a type uses for a base field: ('thesis', 'publisher') -> 'university'."""
        if base in self._allowed.get(item_type, ()) and not self._base.get((item_type, base)):
            return base
        for f in self.type_fields.get(item_type, ()):
            if f["base"] == base:
                return f["field"]
        return None

    def variants(self, base: str) -> set[str]:
        """A base field and every field that maps to it ('publisher' -> {publisher, university, label, ...})."""
        return {base} | {f for (_, f), b in self._base.items() if b == base}

    def primary_creator(self, item_type: str) -> str:
        for c in self.type_creators.get(item_type, ()):
            if c["primary"]:
                return c["creator_type"]
        cs = self.type_creators.get(item_type) or [{"creator_type": "author"}]
        return cs[0]["creator_type"]

    def label(self, kind: str, code: str, lang: str = DEFAULT_LANG) -> str:
        src = {"type": self.types, "field": self.fields, "creator": self.creator_types}[kind].get(code)
        if not src:
            return code
        labels = src["labels"]
        return labels.get(lang) or labels.get(lang.split("-")[0]) or labels.get(DEFAULT_LANG) or code

    def field_kind(self, field: str) -> str:
        return self.fields.get(field, {}).get("kind", "text")

    # ---- API payload
    def payload(self, lang: str = DEFAULT_LANG) -> dict:
        types = []
        for code, t in self.types.items():
            fields = []
            for f in self.type_fields.get(code, ()):
                fd = self.fields[f["field"]]
                fields.append({"code": f["field"], "label": self.label("field", f["field"], lang),
                               "kind": fd["kind"], "help": f["help"] or fd["help"], "base": f["base"],
                               "hidden": fd["hidden"], "obsolete": fd["obsolete"]})
            creators = [{"code": c["creator_type"], "label": self.label("creator", c["creator_type"], lang),
                         "primary": c["primary"], "help": self.creator_types[c["creator_type"]]["help"],
                         "citable": self.creator_types[c["creator_type"]]["citable"]}
                        for c in self.type_creators.get(code, ())]
            types.append({"code": code, "label": self.label("type", code, lang), "help": t["help"],
                          "enabled": t["enabled"], "fields": fields, "creator_types": creators})
        languages = sorted(next(iter(self.types.values()))["labels"]) if self.types else [DEFAULT_LANG]
        return {"lang": lang, "languages": languages, "types": types}


_CACHE: dict[str, Catalog] = {}


def get(conn) -> Catalog:
    """Catalog for this database, cached until the next sync()."""
    key = f"{_meta(conn, 'zotero_schema_version')}:{_meta(conn, 'zotero_overlay_hash')}"
    cat = _CACHE.get(key)
    if cat is None:
        _CACHE.clear()
        cat = _CACHE[key] = Catalog(conn)
    return cat


# --------------------------------------------------------------------------- type conversion
def convert(cat: Catalog, from_type: str, to_type: str, fields: dict[str, dict], creators: list[dict]) -> dict:
    """Move an item's values to another type without losing data.

    fields: {code: {value, source, confidence, confirmed}}; creators: [{creator_type, ...}].
    Each value stays in the same field, else goes through its base field (university -> publisher ->
    institution), else becomes a 'Label: value' line in Extra. Creators whose role the new type lacks
    become its primary role (if they had the old primary role) or contributor.
    Returns {fields, creators, report: {kept, moved, to_extra, creators}}.
    """
    out: dict[str, dict] = {}
    kept, moved, to_extra, extra_lines = [], [], [], []
    for code, val in fields.items():
        if code == "extra":
            continue
        if cat.allows_field(to_type, code) and cat.base_of(to_type, code) == cat.base_of(from_type, code):
            out[code] = dict(val)
            kept.append(code)
            continue
        target = cat.field_for_base(to_type, cat.base_of(from_type, code))
        if target and target not in out and target not in fields:
            out[target] = dict(val)
            moved.append({"from": code, "to": target})
        elif cat.allows_field(to_type, code) and code not in out:
            out[code] = dict(val)
            kept.append(code)
        else:
            label = cat.label("field", code)
            extra_lines.append(f"{label}: {val['value']}")
            to_extra.append({"field": code, "label": label, "value": val["value"]})
    if extra_lines or "extra" in fields:
        old = fields.get("extra", {}).get("value", "")
        value = "\n".join(x for x in [old.rstrip("\n")] + extra_lines if x)
        ex = dict(fields.get("extra") or {"source": "manual", "confidence": None, "confirmed": 1})
        ex["value"] = value
        out["extra"] = ex

    old_primary, new_primary = cat.primary_creator(from_type), cat.primary_creator(to_type)
    fallback = "contributor" if cat.allows_creator(to_type, "contributor") else new_primary
    new_creators, changed = [], []
    for c in creators:
        c = dict(c)
        if not cat.allows_creator(to_type, c["creator_type"]):
            target = new_primary if c["creator_type"] == old_primary else fallback
            changed.append({"name": (c.get("last_name") or c.get("first_name") or ""), "from": c["creator_type"],
                            "to": target})
            c["creator_type"] = target
        new_creators.append(c)
    return {"fields": out, "creators": new_creators,
            "report": {"kept": kept, "moved": moved, "to_extra": to_extra, "creators": changed}}
