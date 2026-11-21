"""Server settings.

Every value can be overridden with an environment variable. The easiest place to
change them is run_server.bat (look for the lines that start with `set BUDC_`).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("BUDC_DATA_DIR", BASE_DIR / "data")).resolve()

# --- Easy-to-change limits -------------------------------------------------
MAX_STORAGE_GB = float(os.environ.get("BUDC_MAX_STORAGE_GB", "20"))  # PDFs + trash
TRASH_DAYS = int(os.environ.get("BUDC_TRASH_DAYS", "30"))
SESSION_DAYS = int(os.environ.get("BUDC_SESSION_DAYS", "60"))
BACKUPS_KEPT = int(os.environ.get("BUDC_BACKUPS_KEPT", "7"))

# --- Network ---------------------------------------------------------------
HOST = os.environ.get("BUDC_HOST", "127.0.0.1")
PORT = int(os.environ.get("BUDC_PORT", "8765"))

# Crossref asks API users to identify themselves (optional but polite).
CONTACT_EMAIL = os.environ.get("BUDC_CONTACT_EMAIL", "")

MAX_BYTES = int(MAX_STORAGE_GB * 1024**3)

LIBRARY_DIR = DATA_DIR / "library"
COVERS_DIR = DATA_DIR / "covers"
TRASH_DIR = DATA_DIR / "trash"
TMP_DIR = DATA_DIR / "tmp"
BACKUP_DIR = DATA_DIR / "backups"
JSON_BACKUP_DIR = BACKUP_DIR / "json"
DB_PATH = DATA_DIR / "biblioteca.db"


def ensure_dirs() -> None:
    for d in (LIBRARY_DIR, COVERS_DIR, TRASH_DIR, TMP_DIR, BACKUP_DIR, JSON_BACKUP_DIR):
        d.mkdir(parents=True, exist_ok=True)
