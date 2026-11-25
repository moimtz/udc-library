"""Housekeeping: empty old trash, clean temp uploads, back up the database."""
import asyncio
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import config
import library as lib
from db import connect


def purge_trash() -> int:
    """Delete items, and supplementary files trashed on their own, older than TRASH_DAYS."""
    from routes_library import purge_attachment, purge_item

    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.TRASH_DAYS)).isoformat(timespec="seconds")
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM items WHERE deleted_at IS NOT NULL AND deleted_at < ?", (cutoff,)).fetchall()
        for r in rows:
            purge_item(conn, r)
        atts = conn.execute("SELECT * FROM attachments WHERE role='supplementary' AND deleted_at IS NOT NULL "
                            "AND deleted_at < ?", (cutoff,)).fetchall()
        for a in atts:
            purge_attachment(conn, a)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def clean_tmp() -> None:
    for p in config.TMP_DIR.glob("*"):
        if time.time() - p.stat().st_mtime > 24 * 3600:
            p.unlink(missing_ok=True)


def backup_db() -> None:
    dest = config.BACKUP_DIR / f"biblioteca-{datetime.now():%Y%m%d}.db"
    if not dest.exists():
        src = connect()
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
            src.close()
    for old in sorted(config.BACKUP_DIR.glob("biblioteca-*.db"))[:-config.BACKUPS_KEPT]:
        old.unlink(missing_ok=True)


def export_json() -> None:
    """One JSON per item: a human-readable safety copy, not the source of truth."""
    conn = connect()
    try:
        keep = set()
        ids = [r[0] for r in conn.execute("SELECT id FROM items")]
        for item in lib.load_items(conn, ids):
            name = f"{item['citekey']}.json"
            keep.add(name)
            (config.JSON_BACKUP_DIR / name).write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding="utf-8")
        for p in config.JSON_BACKUP_DIR.glob("*.json"):
            if p.name not in keep:
                p.unlink(missing_ok=True)
    finally:
        conn.close()


def run_all() -> None:
    for fn in (purge_trash, clean_tmp, backup_db, export_json):
        try:
            fn()
        except Exception as e:  # never stop the server because of housekeeping
            print(f"[maintenance] {fn.__name__} failed: {e}")


async def loop() -> None:
    while True:
        await asyncio.sleep(6 * 3600)
        await asyncio.to_thread(run_all)
