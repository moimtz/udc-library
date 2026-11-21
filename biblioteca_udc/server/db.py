"""SQLite schema and connection helpers."""
import json
import sqlite3
from datetime import datetime, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE COLLATE NOCASE,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','editor','viewer')),
  disabled INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions(
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS field_defs(
  key TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text', position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS item_types(
  code TEXT PRIMARY KEY, label TEXT NOT NULL, fields TEXT NOT NULL, position INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  citekey TEXT NOT NULL UNIQUE COLLATE NOCASE,
  item_type TEXT NOT NULL,
  title TEXT NOT NULL,
  year INTEGER,
  language TEXT,
  udc TEXT NOT NULL DEFAULT '',
  creators TEXT NOT NULL DEFAULT '[]',
  data TEXT NOT NULL DEFAULT '{}',
  filename TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  size INTEGER NOT NULL,
  pages INTEGER,
  cover_page INTEGER NOT NULL DEFAULT 1,
  added_at TEXT NOT NULL,
  modified_at TEXT NOT NULL,
  added_by INTEGER,
  deleted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_sha ON items(sha256);
CREATE TABLE IF NOT EXISTS item_udc(
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  code TEXT NOT NULL,
  node_code TEXT,
  PRIMARY KEY(item_id, code)
);
CREATE INDEX IF NOT EXISTS idx_item_udc_node ON item_udc(node_code);
CREATE TABLE IF NOT EXISTS udc_nodes(
  code TEXT PRIMARY KEY, parent TEXT, labels TEXT NOT NULL, ord INTEGER NOT NULL DEFAULT 0,
  node_type TEXT,   -- NULL = normal class; 'heading' (group without notation) or 'info' (informative, not assignable)
  notes TEXT        -- JSON for the class information window (scope, app, including, examples, related) or NULL
);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

# (key, label, kind). Types reference these keys; admins can add more at runtime.
FIELD_DEFS = [
    ("subtitle", "Subtitle", "text"), ("abstract", "Abstract", "area"),
    ("keywords", "Keywords", "text"), ("publisher", "Publisher", "text"),
    ("place", "Place of publication", "text"), ("edition", "Edition", "text"),
    ("series", "Series", "text"), ("container", "Journal / book title", "text"),
    ("volume", "Volume", "text"), ("issue", "Issue", "text"),
    ("pages_range", "Pages", "text"), ("isbn", "ISBN", "text"),
    ("issn", "ISSN", "text"), ("doi", "DOI", "text"), ("arxiv", "arXiv ID", "text"),
    ("url", "URL", "text"), ("institution", "Institution / office", "text"),
    ("degree", "Degree", "text"), ("number", "Number", "text"), ("notes", "Notes", "area"),
]

ITEM_TYPES = [
    ("book", "Book", ["subtitle", "publisher", "place", "edition", "series", "isbn", "doi", "url", "abstract", "keywords", "notes"]),
    ("chapter", "Book chapter", ["container", "publisher", "place", "edition", "pages_range", "isbn", "doi", "url", "abstract", "keywords", "notes"]),
    ("article", "Article", ["container", "volume", "issue", "pages_range", "issn", "doi", "arxiv", "url", "publisher", "abstract", "keywords", "notes"]),
    ("thesis", "Thesis", ["institution", "degree", "place", "url", "abstract", "keywords", "notes"]),
    ("patent", "Patent", ["number", "institution", "url", "abstract", "keywords", "notes"]),
    ("report", "Report", ["institution", "number", "place", "doi", "url", "abstract", "keywords", "notes"]),
    ("other", "Other", ["publisher", "doi", "url", "abstract", "keywords", "notes"]),
]

CREATOR_ROLES = ["author", "editor", "translator", "inventor", "advisor"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn():
    """FastAPI dependency."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def _migrate(conn) -> None:
    """Add new columns to an existing database (CREATE TABLE IF NOT EXISTS does not)."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(udc_nodes)")}
    for name in ("node_type", "notes"):
        if name not in cols:
            conn.execute(f"ALTER TABLE udc_nodes ADD COLUMN {name} TEXT")


def init_db() -> None:
    import udc

    config.ensure_dirs()
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        if not conn.execute("SELECT 1 FROM field_defs LIMIT 1").fetchone():
            for i, (k, label, kind) in enumerate(FIELD_DEFS):
                conn.execute("INSERT INTO field_defs(key,label,kind,position) VALUES (?,?,?,?)", (k, label, kind, i))
        if not conn.execute("SELECT 1 FROM item_types LIMIT 1").fetchone():
            for i, (code, label, fields) in enumerate(ITEM_TYPES):
                conn.execute("INSERT INTO item_types(code,label,fields,position) VALUES (?,?,?,?)",
                             (code, label, json.dumps(fields), i))
        udc.seed_minimal(conn)
        conn.commit()
    finally:
        conn.close()
