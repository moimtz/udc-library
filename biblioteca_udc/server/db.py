"""SQLite schema and connection helpers.

Item data follows Zotero's model: the catalog tables (item_types, fields, item_type_fields, creator_types,
item_type_creators) are filled from zotero/schema.json + zotero/zotero_overlay.json by catalog.sync(); every
item value is a row in item_fields / item_creators with its provenance (source, confidence, confirmed).
"""
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
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);

-- ------------------------------------------------------------------ UDC tree
CREATE TABLE IF NOT EXISTS udc_nodes(
  code TEXT PRIMARY KEY, parent TEXT, labels TEXT NOT NULL, ord INTEGER NOT NULL DEFAULT 0,
  node_type TEXT,   -- NULL = normal class; 'heading' (group without notation) or 'info' (informative, not assignable)
  notes TEXT        -- JSON for the class information window (scope, app, including, examples, related) or NULL
);
-- Cancelled UDC classes (udcx:CancelledClass in udcs-skos.rdf). Not part of the tree; a notation may have been
-- cancelled and later reused, so it can also exist in udc_nodes.
CREATE TABLE IF NOT EXISTS udc_cancelled(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT NOT NULL, year INTEGER, ec TEXT, label TEXT, including TEXT,
  replaced_by TEXT NOT NULL DEFAULT '[]',   -- JSON list of notations, in UDC Online order
  note TEXT                                 -- e.g. 'No replacement'
);
CREATE INDEX IF NOT EXISTS idx_udc_cancelled_code ON udc_cancelled(code);

-- ------------------------------------------------------------------ catalog (written only by catalog.sync)
CREATE TABLE IF NOT EXISTS item_types(
  code      TEXT PRIMARY KEY,                 -- Zotero name: 'book', 'thesis'
  labels    TEXT NOT NULL,                    -- JSON {"en-US": "Book", "es-ES": "Libro", ...}
  help      TEXT NOT NULL DEFAULT '',
  enabled   INTEGER NOT NULL DEFAULT 0,       -- 1 = can be chosen for new items
  position  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS fields(
  code      TEXT PRIMARY KEY,                 -- 'university', 'DOI'
  labels    TEXT NOT NULL,
  kind      TEXT NOT NULL DEFAULT 'text' CHECK(kind IN ('text','longtext','date','url')),
  help      TEXT NOT NULL DEFAULT '',
  hidden    INTEGER NOT NULL DEFAULT 0,       -- citationKey (= items.citekey)
  obsolete  INTEGER NOT NULL DEFAULT 0        -- dropped by a newer Zotero schema; read-only
);
CREATE TABLE IF NOT EXISTS item_type_fields(
  item_type  TEXT NOT NULL REFERENCES item_types(code),
  field      TEXT NOT NULL REFERENCES fields(code),
  base_field TEXT REFERENCES fields(code),    -- university -> publisher; NULL if not a variant
  position   INTEGER NOT NULL,                -- Zotero's form order
  help       TEXT,                            -- type-specific help; NULL = fields.help
  PRIMARY KEY(item_type, field)
);
CREATE INDEX IF NOT EXISTS idx_itf_base ON item_type_fields(base_field);
CREATE TABLE IF NOT EXISTS creator_types(
  code      TEXT PRIMARY KEY,
  labels    TEXT NOT NULL,
  help      TEXT NOT NULL DEFAULT '',
  citable   INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS item_type_creators(
  item_type    TEXT NOT NULL REFERENCES item_types(code),
  creator_type TEXT NOT NULL REFERENCES creator_types(code),
  is_primary   INTEGER NOT NULL DEFAULT 0,
  position     INTEGER NOT NULL,
  PRIMARY KEY(item_type, creator_type)
);

-- ------------------------------------------------------------------ items
CREATE TABLE IF NOT EXISTS items(
  id           INTEGER PRIMARY KEY,
  citekey      TEXT NOT NULL UNIQUE COLLATE NOCASE,   -- also Zotero's citationKey and the file name base
  item_type    TEXT NOT NULL REFERENCES item_types(code),
  -- derived on every write (library.refresh_derived), for listing, sorting and filtering
  sort_title   TEXT NOT NULL DEFAULT '',
  sort_creator TEXT NOT NULL DEFAULT '',
  date_sort    TEXT,                                  -- 'YYYY-MM-DD', 00 for unknown parts
  year         INTEGER,
  language     TEXT,
  added_at     TEXT NOT NULL,
  added_by     INTEGER REFERENCES users(id),
  modified_at  TEXT NOT NULL,
  modified_by  INTEGER REFERENCES users(id),
  deleted_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_type ON items(item_type);
CREATE INDEX IF NOT EXISTS idx_items_deleted ON items(deleted_at);

CREATE TABLE IF NOT EXISTS item_fields(
  item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  field      TEXT NOT NULL REFERENCES fields(code),   -- the type's own field: 'university', not 'publisher'
  value      TEXT NOT NULL,
  norm       TEXT,                                    -- ISO date, ISBN/ISSN digits, lower-case DOI, language code
  source     TEXT NOT NULL,
  confidence REAL,
  confirmed  INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  updated_by INTEGER REFERENCES users(id),
  PRIMARY KEY(item_id, field)
);
CREATE INDEX IF NOT EXISTS idx_if_norm ON item_fields(field, norm);

CREATE TABLE IF NOT EXISTS item_creators(
  item_id      INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  position     INTEGER NOT NULL,
  creator_type TEXT NOT NULL REFERENCES creator_types(code),
  last_name    TEXT NOT NULL DEFAULT '',             -- the full name when field_mode = 1
  first_name   TEXT NOT NULL DEFAULT '',
  field_mode   INTEGER NOT NULL DEFAULT 0 CHECK(field_mode IN (0,1)),
  source       TEXT NOT NULL,
  confidence   REAL,
  confirmed    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(item_id, position)
);
CREATE INDEX IF NOT EXISTS idx_ic_name ON item_creators(last_name);

CREATE TABLE IF NOT EXISTS attachments(
  id         INTEGER PRIMARY KEY,
  item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK(role IN ('main','supplementary')),
  label      TEXT NOT NULL DEFAULT '',
  position   INTEGER NOT NULL DEFAULT 0,
  filename   TEXT NOT NULL UNIQUE,                   -- citekey.pdf; supplementary citekey_s1.pdf, ...
  sha256     TEXT NOT NULL,
  size       INTEGER NOT NULL,
  mime       TEXT NOT NULL,
  pages      INTEGER,
  cover_page INTEGER,
  added_at   TEXT NOT NULL,
  added_by   INTEGER REFERENCES users(id),
  deleted_at TEXT,
  CHECK(role = 'main' OR label <> '')
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_att_one_main ON attachments(item_id) WHERE role = 'main';
CREATE INDEX IF NOT EXISTS idx_att_sha ON attachments(sha256);

CREATE TABLE IF NOT EXISTS tags(
  id   INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE
);
CREATE TABLE IF NOT EXISTS item_tags(
  item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  tag_id  INTEGER NOT NULL REFERENCES tags(id),
  source  TEXT NOT NULL,
  PRIMARY KEY(item_id, tag_id)
);
CREATE TABLE IF NOT EXISTS item_notes(
  id          INTEGER PRIMARY KEY,
  item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  body        TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  created_by  INTEGER REFERENCES users(id),
  modified_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_udc(
  item_id    INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,                       -- 0 = main notation
  notation   TEXT NOT NULL,
  source     TEXT NOT NULL,
  confidence REAL,
  confirmed  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(item_id, position)
);
CREATE TABLE IF NOT EXISTS item_udc_nodes(                -- derived from item_udc (notation.nodes_for)
  item_id   INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  node_code TEXT NOT NULL REFERENCES udc_nodes(code),
  PRIMARY KEY(item_id, node_code)
);
CREATE INDEX IF NOT EXISTS idx_iun_node ON item_udc_nodes(node_code);

-- ------------------------------------------------------------------ integrity against the catalog
CREATE TRIGGER IF NOT EXISTS trg_if_type BEFORE INSERT ON item_fields
WHEN NOT EXISTS (SELECT 1 FROM item_type_fields t JOIN items i ON i.item_type = t.item_type
                 WHERE i.id = NEW.item_id AND t.field = NEW.field)
BEGIN SELECT RAISE(ABORT, 'field not allowed for item type'); END;

CREATE TRIGGER IF NOT EXISTS trg_if_type_upd BEFORE UPDATE OF field, item_id ON item_fields
WHEN NOT EXISTS (SELECT 1 FROM item_type_fields t JOIN items i ON i.item_type = t.item_type
                 WHERE i.id = NEW.item_id AND t.field = NEW.field)
BEGIN SELECT RAISE(ABORT, 'field not allowed for item type'); END;

CREATE TRIGGER IF NOT EXISTS trg_ic_type BEFORE INSERT ON item_creators
WHEN NOT EXISTS (SELECT 1 FROM item_type_creators t JOIN items i ON i.item_type = t.item_type
                 WHERE i.id = NEW.item_id AND t.creator_type = NEW.creator_type)
BEGIN SELECT RAISE(ABORT, 'creator type not allowed for item type'); END;

CREATE TRIGGER IF NOT EXISTS trg_ic_type_upd BEFORE UPDATE OF creator_type, item_id ON item_creators
WHEN NOT EXISTS (SELECT 1 FROM item_type_creators t JOIN items i ON i.item_type = t.item_type
                 WHERE i.id = NEW.item_id AND t.creator_type = NEW.creator_type)
BEGIN SELECT RAISE(ABORT, 'creator type not allowed for item type'); END;

CREATE TRIGGER IF NOT EXISTS trg_items_type BEFORE UPDATE OF item_type ON items
WHEN EXISTS (SELECT 1 FROM item_fields f WHERE f.item_id = NEW.id AND NOT EXISTS
               (SELECT 1 FROM item_type_fields t WHERE t.item_type = NEW.item_type AND t.field = f.field))
  OR EXISTS (SELECT 1 FROM item_creators c WHERE c.item_id = NEW.id AND NOT EXISTS
               (SELECT 1 FROM item_type_creators t WHERE t.item_type = NEW.item_type
                AND t.creator_type = c.creator_type))
BEGIN SELECT RAISE(ABORT, 'convert fields and creators before changing item type'); END;
"""

# Where a value came from. 'manual' = typed by a person.
SOURCES = {"manual", "pdfmeta", "layout", "regex", "inid", "filename", "ner", "crossref", "openlibrary", "arxiv",
           "llm", "classifier"}

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH, check_same_thread=False, timeout=30)
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


def init_db() -> None:
    import catalog
    import udc

    config.ensure_dirs()
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        catalog.sync(conn)
        udc.seed_minimal(conn)
        conn.commit()
    finally:
        conn.close()
