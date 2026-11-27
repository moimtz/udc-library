"""Library files: an item's main PDF and its cover. Used by the API (routes_library.py) and by the bulk
import (bulk_import.py), so both store files the same way."""
import shutil
from pathlib import Path

import config
import pdfutil
from db import now


def used_bytes(conn) -> int:
    """Bytes taken by every attachment (also those in the trash): what BUDC_MAX_STORAGE_GB limits."""
    return conn.execute("SELECT COALESCE(SUM(size),0) FROM attachments").fetchone()[0]


def cover_path(item_id: int) -> Path:
    return config.COVERS_DIR / f"{item_id}.jpg"


def add_main_file(conn, item_id: int, src: Path, *, sha256: str, size: int, pages: int | None, cover_page: int,
                  user_id, copy: bool = False) -> Path:
    """Put `src` in the library as <citekey>.pdf (moved, or copied with copy=True), record it as the item's main
    attachment and render the cover. Runs in the caller's transaction (the caller commits). If anything fails,
    the file goes back where it was and the error is raised. Returns the stored path."""
    citekey = conn.execute("SELECT citekey FROM items WHERE id=?", (item_id,)).fetchone()[0]
    dest = config.LIBRARY_DIR / f"{citekey}.pdf"
    cover = min(max(cover_page, 1), pages or 1)
    if copy:
        shutil.copyfile(src, dest)
    else:
        shutil.move(str(src), dest)
    try:
        conn.execute("INSERT INTO attachments(item_id, role, filename, sha256, size, mime, pages, cover_page, "
                     "added_at, added_by) VALUES (?,'main',?,?,?,'application/pdf',?,?,?,?)",
                     (item_id, dest.name, sha256, size, pages, cover, now(), user_id))
        pdfutil.save_cover(dest, cover_path(item_id), cover)
    except Exception:
        undo_main_file(dest, src, copy)
        raise
    return dest


def undo_main_file(dest: Path, src: Path, copy: bool) -> None:
    """Reverse add_main_file's file move (after a failed commit)."""
    if copy:
        dest.unlink(missing_ok=True)
    elif dest.exists():
        shutil.move(str(dest), src)
