"""Bulk import: PDFs already on this PC + the classifier's results.json -> library items. Console only.

The PDFs are read from a local folder (nothing is uploaded) and copied into the library; the originals stay.
Two steps, so a person decides before anything is written:

    python bulk_import.py plan  <results.json> <pdf folder> [--gold udc_gold.csv]
        -> <pdf folder>\\import_plan.xlsx (one row per PDF, editable) + import_plan.json (full data)
    python bulk_import.py load  <pdf folder>\\import_plan.xlsx --user <username>
        -> items for the rows whose action is 'load'; import_report_<date>.csv next to the plan

results.json comes from the classification PoC (python -m udcpoc run <folder> --ocr), run on this PC or on
another one with a copy of the same PDFs: files are matched by content (SHA-1), not by path.

What an imported item looks like:
- every value keeps the source and confidence the classifier gave it and stays NOT confirmed; values you
  edit in the plan, and UDC numbers from your gold file, are saved as typed by a person (confirmed);
- with --gold referencia.csv (the PoC's reference: one row per PDF, matched by SHA-256) its type, title,
  creators, date, publisher, ISBN, UDC, cover page... win over the classifier's. Rows marked 'verificado'
  are saved as confirmed; the rest ('propuesto') with source 'import', not confirmed. A PDF the classifier
  did not analyse is planned for loading anyway when the reference has it;
- UDC: suggestion 1 as the main notation; suggestions 2-3 and the classifier's notes go to an item note;
- tags: the batch tag ('import YYYY-MM-DD', to find or undo the batch) and 'to review' when the plan's
  to_review cell has reasons (low confidence, a key field missing, a UDC form that does not fit the type:
  coherence.py). Clear the cell for rows you already checked in the plan;
- cover: the first page with content (blank pages skipped by the classifier); change it later in the app.

Duplicates (same file, DOI, ISBN, or very similar title + first creator + year), against the library and
against the other files of the plan, are listed in duplicate_of with action 'skip'; set 'load' to keep both.
Safe to run again: a file already in the library (same SHA-256) is never added twice. Each item is saved
in its own transaction, so stopping halfway (Ctrl+C) keeps what was done. The server may keep running.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path, PureWindowsPath

import catalog
import coherence
import config
import library as lib
import pdfutil
import storage
from db import SOURCES, connect, init_db, now

PLAN_NAME = "import_plan.xlsx"
COLUMNS = ["action", "file", "type", "title", "creators", "date", "udc", "udc_source", "udc_confidence",
           "cover_page", "to_review", "warnings", "duplicate_of", "citekey", "sha256"]
EDITABLE = {"action", "type", "title", "creators", "date", "udc", "cover_page", "to_review"}
WIDTHS = {"action": 8, "file": 40, "type": 14, "title": 50, "creators": 30, "date": 11, "udc": 24,
          "udc_source": 12, "udc_confidence": 9, "cover_page": 7, "to_review": 34, "warnings": 50,
          "duplicate_of": 30, "citekey": 28, "sha256": 12}
REVIEW_TAG = "to review"
EXTERNAL = ("crossref", "openlibrary", "arxiv")
LANGID = ("py3langid", "langdetect", "lingua", "stopwords", "langid")
LOW_FIELD_CONFIDENCE = 0.4


class PlanError(Exception):
    pass


# --------------------------------------------------------------------------- small helpers
def hashes(path: Path) -> tuple[str, str, int]:
    s1, s256, size = hashlib.sha1(), hashlib.sha256(), 0
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            s1.update(chunk)
            s256.update(chunk)
            size += len(chunk)
    return s1.hexdigest(), s256.hexdigest(), size


def map_source(src: str) -> str:
    """The classifier's source names -> the server's SOURCES. 'filename+openlibrary' -> openlibrary (the
    catalogue confirmed it), 'regex:copyright' -> regex, 'py3langid' -> langid, 'pdf' (page count) -> pdfmeta."""
    parts = [p.split(":")[0].strip().lower() for p in re.split(r"[+/]", src or "") if p.strip()]
    for e in EXTERNAL:
        if e in parts:
            return e
    p = parts[0] if parts else ""
    if p in LANGID:
        return "langid"
    if p == "pdf":
        return "pdfmeta"
    return p if p in SOURCES and p != "manual" else "import"


def creators_text(creators: list[dict]) -> str:
    """'Last, First; Institution' (the format the plan's creators column is edited in)."""
    return "; ".join(f"{c['last_name']}, {c['first_name']}" if c["first_name"] else c["last_name"]
                     for c in creators)


def parse_creators(text: str, role: str, source: str = "manual") -> list[dict]:
    out = []
    for part in (p.strip() for p in (text or "").split(";")):
        if not part:
            continue
        if "," in part:
            last, first = (x.strip() for x in part.split(",", 1))
            out.append({"creator_type": role, "last_name": last, "first_name": first, "field_mode": 0,
                        "source": source})
        else:   # one-field name (institutions)
            out.append({"creator_type": role, "last_name": part, "first_name": "", "field_mode": 1,
                        "source": source})
    return out


def read_gold(path: Path | None) -> dict[str, dict]:
    """Two formats:
    - udc_gold.csv (file,udc,nota) -> {file name (lower case): {udc, note}};
    - the PoC's reference (referencia.csv or .xlsx: sha256, archivo, type, title, creators, udc, estado...;
      see udc_poc/udcpoc/reference.py) -> the whole row, under 'sha:<sha256>' and under the file name."""
    if not path:
        return {}
    if not path.exists():
        raise PlanError(f"Gold file not found: {path}")
    if path.suffix.lower() == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(path, read_only=True, data_only=True)
        if "Libros" not in wb.sheetnames:
            raise PlanError(f"{path.name} has no 'Libros' sheet (is it the PoC's referencia.xlsx?).")
        it = wb["Libros"].iter_rows(values_only=True)
        head = [str(h or "").strip() for h in next(it, [])]
        rows = [{h: ("" if v is None else str(v).strip()) for h, v in zip(head, r) if h} for r in it]
    else:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        if r.get("sha256"):   # reference row
            r = {k: (v or "").strip() for k, v in r.items()}
            out["sha:" + r["sha256"].lower()] = r
            if r.get("archivo"):
                out.setdefault(r["archivo"].lower(), r)
        elif (r.get("file") or "").strip():
            out[PureWindowsPath(r["file"]).name.lower()] = {"udc": (r.get("udc") or "").strip(),
                                                            "note": (r.get("nota") or r.get("note") or "").strip()}
    return out


# reference column -> base field (each item type has its own variant: publicationTitle -> bookTitle...)
REF_FIELDS = {"edition": "edition", "volume": "volume", "series": "series", "number": "number",
              "publication": "publicationTitle", "issue": "issue", "pages": "pages", "publisher": "publisher",
              "place": "place", "ISBN": "ISBN", "DOI": "DOI", "language": "language"}


def apply_reference(cat, item: dict, note: str, review: list[str], ref: dict) -> str:
    """The reference row's values over the classifier's item (they win wherever the row has a value).
    Rows with estado 'verificado' count as typed by a person (confirmed); the rest ('propuesto': filled by
    an AI or a catalogue) keep the source 'import' and stay unconfirmed. Returns the item note."""
    src = "manual" if ref.get("estado") == "verificado" else "import"
    itype = ref.get("type", "")
    if itype and itype != item["item_type"]:
        if itype in cat.types and cat.types[itype]["enabled"]:
            conv = catalog.convert(cat, item["item_type"], itype,
                                   {k: {**v, "confirmed": 0} for k, v in item["fields"].items()}, item["creators"])
            item["fields"] = {k: {kk: vv for kk, vv in v.items() if kk != "confirmed"}
                              for k, v in conv["fields"].items()}
            item["creators"], item["item_type"] = conv["creators"], itype
        else:
            review.append(f"reference type '{itype}' not available")
    t = item["item_type"]
    extra = []

    def put(base: str, value: str, code: str | None = None):
        if not value:
            return
        code = code or (base if cat.allows_field(t, base) else cat.field_for_base(t, base))
        if code:
            item["fields"][code] = {"value": value, "source": src}
        else:
            extra.append(f"{cat.label('field', base)}: {value}")

    put("title", ref.get("title", ""), lib.title_field(cat, t))
    put("date", ref.get("date", ""))
    for col, base in REF_FIELDS.items():
        put(base, ref.get(col, ""))
    if extra:
        old = item["fields"].get("extra", {}).get("value", "")
        item["fields"]["extra"] = {"value": "\n".join(([old] if old else []) + extra), "source": "import"}
    if ref.get("creators") or ref.get("contributors"):
        creators = parse_creators(ref.get("creators", ""), cat.primary_creator(t), src)
        for part in (p.strip() for p in ref.get("contributors", "").split(";") if p.strip()):
            m = re.match(r"(.*?)\s*\((\w+)\)$", part)
            name, role = (m.group(1), m.group(2)) if m else (part, "contributor")
            if not cat.allows_creator(t, role):
                role = "contributor" if cat.allows_creator(t, "contributor") else cat.primary_creator(t)
            creators += parse_creators(name, role, src)
        item["creators"] = creators
    lines = []
    if ref.get("udc"):
        item["udc"] = [{"notation": ref["udc"], "source": src}]
        lines.append(f"UDC from the reference ({ref.get('fuente_udc') or 'no source given'}"
                     f"{', reviewed by a person' if src == 'manual' else ', not reviewed by a person'}).")
        if ref.get("udc_alternativas"):
            lines.append(f"Also accepted: {ref['udc_alternativas']}")
        if ref.get("nota_udc"):
            lines.append(f"Classification note: {ref['nota_udc']}")
    if ref.get("observaciones"):
        lines.append(f"Reference: {ref['observaciones']}")
    # reasons to review that the reference already answers
    covered = []
    if ref.get("title"):
        covered.append("no title found")
    if ref.get("creators") or ref.get("contributors"):
        covered.append("no creators found")
    if ref.get("date"):
        covered.append("no date found")
    if itype and item["item_type"] == itype:
        covered += ["item type uncertain", "type '"]
    if ref.get("udc"):
        covered += ["UDC with low confidence", "no UDC suggestion"]
    review[:] = [r for r in review if not any(r.startswith(c) for c in covered) and not r.startswith("low confidence")]
    weak = [k for k, v in item["fields"].items() if (v.get("confidence") or 1) < LOW_FIELD_CONFIDENCE and k != "extra"]
    if weak:
        review.append("low confidence: " + ", ".join(weak))
    return "\n".join(lines + ([note] if note else []))


def read_results(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """results.json -> ({sha1: record}, {file name (lower case): record})."""
    try:
        recs = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PlanError(f"Cannot read {path}: {e}")
    by_sha = {r["sha1"]: r for r in recs if r.get("sha1")}
    by_name = {PureWindowsPath(r["file"]).name.lower(): r for r in recs if r.get("file")}
    return by_sha, by_name


# --------------------------------------------------------------------------- classifier record -> item
def item_from_record(cat, rec: dict | None, pdf: Path, gold: dict | None) -> tuple[dict, str, list[str]]:
    """Returns (item for library.save_item, note text, reasons to review)."""
    review: list[str] = []
    if rec is None:
        rec = {"item_type": {"value": "book"}, "fields": {}, "classification": {"suggestions": []}}
        review.append("not analysed by the classifier")
    itype = rec["item_type"]["value"]
    if itype not in cat.types or not cat.types[itype]["enabled"]:
        review.append(f"type '{itype}' not available, saved as Book")
        itype = "book"
    elif (rec["item_type"].get("confidence") or 1) < LOW_FIELD_CONFIDENCE:
        review.append("item type uncertain")
    fields: dict[str, dict] = {}
    extra_lines: list[str] = []
    creators, tags = [], []
    for code, v in (rec.get("fields") or {}).items():
        src, conf = map_source(v.get("source", "")), v.get("confidence")
        if code == "creators":
            primary = cat.primary_creator(itype)
            for c in v["value"]:
                role = c.get("creatorType") or primary
                last, first = (c.get("lastName") or "").strip(), (c.get("firstName") or "").strip()
                if c.get("name"):
                    last, first = c["name"].strip(), ""
                creators.append({"creator_type": role if cat.allows_creator(itype, role) else primary,
                                 "last_name": last, "first_name": first, "field_mode": 0 if first else 1,
                                 "source": src, "confidence": conf})
            continue
        if code == "tags":
            tags += [{"name": t, "source": src} for t in v["value"]]
            continue
        value = str(v.get("value") or "").strip()
        if not value:
            continue
        if code == "extra":
            extra_lines.append(value)
            continue
        target = code if cat.allows_field(itype, code) else cat.field_for_base(itype, cat.base_any(code))
        if target and target not in fields:
            fields[target] = {"value": value, "source": src, "confidence": conf}
        else:
            extra_lines.append(f"{cat.label('field', code)}: {value}")
    if extra_lines:
        fields["extra"] = {"value": "\n".join(extra_lines), "source": "import", "confidence": None}
    tfield = lib.title_field(cat, itype)
    if not fields.get(tfield, {}).get("value"):
        fields[tfield] = {"value": pdf.stem, "source": "filename", "confidence": 0.3}
        review.append("no title found: the file name was used")
    for crit, present in (("creators", bool(creators)), ("date", bool(cat.field_for_base(itype, "date") in fields))):
        if not present:
            review.append(f"no {crit} found")
    weak = [k for k, v in fields.items() if (v["confidence"] or 1) < LOW_FIELD_CONFIDENCE and k != "extra"]
    if weak:
        review.append("low confidence: " + ", ".join(weak))

    note_lines, udc = [], []
    cls = rec.get("classification") or {}
    sugg = cls.get("suggestions") or []
    if gold and gold.get("udc") and "sha256" not in gold:   # reference rows: apply_reference()
        udc = [{"notation": gold["udc"], "source": "manual"}]
        if gold.get("note"):
            note_lines.append(f"Classification note: {gold['note']}")
    elif sugg:
        udc = [{"notation": sugg[0]["udc"], "source": "classifier", "confidence": sugg[0].get("confidence")}]
        if cls.get("low_confidence"):
            review.append("UDC with low confidence")
    else:
        review.append("no UDC suggestion")
    if sugg:
        note_lines.append("UDC suggestions of the classifier (not confirmed):")
        for s in sugg[:3]:
            main = s.get("main") or [{}]
            label = " : ".join(m.get("label", "") for m in main if m.get("label"))
            pct = f"{round((s.get('confidence') or 0) * 100)}%"
            note_lines.append(f"{s.get('rank', '')}. {s['udc']}  ({pct})  {label}")
            back = (s.get("explain") or {}).get("retroceder_a") or []
            if back:
                note_lines.append(f"   broader: {' > '.join(back[:3])}")
        if cls.get("note"):
            note_lines.append(f"Classifier: {cls['note']}")
    item = {"item_type": itype, "fields": fields, "creators": creators, "tags": tags, "udc": udc}
    note = "\n".join(note_lines)
    if gold and "sha256" in gold:
        note = apply_reference(cat, item, note, review, gold)
    return item, note, review


def apply_edits(cat, entry: dict, row: dict) -> tuple[dict, int]:
    """The plan row's edited columns over the planned item. Edited values count as typed by a person."""
    item = json.loads(json.dumps(entry["item"]))
    orig = entry["row"]
    new_type = (row.get("type") or "").strip()
    if new_type and new_type != item["item_type"]:
        if new_type not in cat.types or not cat.types[new_type]["enabled"]:
            raise lib.ItemError(f"Unknown or unavailable item type '{new_type}'.")
        conv = catalog.convert(cat, item["item_type"], new_type,
                               {k: {**v, "confirmed": 0} for k, v in item["fields"].items()}, item["creators"])
        item["fields"] = {k: {kk: vv for kk, vv in v.items() if kk != "confirmed"} for k, v in conv["fields"].items()}
        item["creators"], item["item_type"] = conv["creators"], new_type
    itype = item["item_type"]

    def edited(col):
        return (row.get(col) or "").strip() != (orig.get(col) or "").strip()

    if edited("title"):
        if not (row.get("title") or "").strip():
            raise lib.ItemError("The title cannot be empty.")
        item["fields"][lib.title_field(cat, itype)] = {"value": row["title"].strip(), "source": "manual"}
    dfield = cat.field_for_base(itype, "date")
    if edited("date") and dfield:
        if (row.get("date") or "").strip():
            item["fields"][dfield] = {"value": row["date"].strip(), "source": "manual"}
        else:
            item["fields"].pop(dfield, None)
    if edited("creators"):
        item["creators"] = parse_creators(row.get("creators", ""), cat.primary_creator(itype))
    if edited("udc"):
        u = (row.get("udc") or "").strip()
        item["udc"] = [{"notation": n.strip(), "source": "manual"} for n in u.split(";") if n.strip()]
    try:
        cover = int(float(row.get("cover_page") or entry["cover_page"]))
    except ValueError:
        raise lib.ItemError(f"Cover page '{row.get('cover_page')}' is not a number.")
    return item, cover


# --------------------------------------------------------------------------- plan
BATCH_DUP = "this folder: "


def dup_text(dups: list[dict], planned: dict[int, str] | None = None) -> str:
    """'#12 citekey (reason)' for items in the library; 'this folder: file (reason)' for a file planned earlier."""
    planned = planned or {}
    return "; ".join(f"{BATCH_DUP}{planned[d['id']]} ({d['reason']})" if d["id"] in planned else
                     f"#{d['id']} {d['citekey']} ({d['reason']}{', in trash' if d['in_trash'] else ''})"
                     for d in dups)


def item_dups(conn, sha256: str | None, item: dict, cat) -> list[dict]:
    f = item["fields"]
    dval = f.get(cat.field_for_base(item["item_type"], "date") or "date", {}).get("value", "")
    d = lib.parse_date(dval)
    year = (int(d[:4]) or None) if d else None
    first = next((c["last_name"] or c["first_name"] for c in item["creators"]), "")
    return lib.find_duplicates(conn, sha256=sha256, doi=f.get("DOI", {}).get("value"),
                               isbn=f.get("ISBN", {}).get("value"),
                               title=f.get(lib.title_field(cat, item["item_type"]), {}).get("value"),
                               year=year, first_creator=first)


def cmd_plan(a) -> None:
    folder = Path(a.folder).resolve()
    if not folder.is_dir():
        raise PlanError(f"Not a folder: {folder}")
    by_sha, by_name = read_results(Path(a.results))
    gold = read_gold(Path(a.gold) if a.gold else None)
    pdfs = sorted(p for p in folder.rglob("*") if p.suffix.lower() == ".pdf" and p.is_file())
    if not pdfs:
        raise PlanError(f"No PDF files in {folder}")
    init_db()
    conn = connect()
    cat = catalog.get(conn)
    entries, seen, used = [], {}, set()
    planned: dict[int, str] = {}   # temporary item id -> file: the plan is saved and undone in one transaction,
    conn.execute("BEGIN")          # so later files see the earlier ones (duplicates, unique citation keys)
    print(f"Planning {len(pdfs)} PDF files from {folder} ...")
    for i, pdf in enumerate(pdfs, 1):
        rel = pdf.relative_to(folder).as_posix()
        sha1, sha256, size = hashes(pdf)
        rec = by_sha.get(sha1)
        matched_by_name = False
        if rec is None and pdf.name.lower() in by_name:
            rec, matched_by_name = by_name[pdf.name.lower()], True
        if rec is not None:
            used.add(rec.get("sha1"))
        try:
            pages = pdfutil.page_count(pdf)
        except pdfutil.PdfError as e:
            entries.append({"file": rel, "sha256": sha256, "size": size, "error": str(e),
                            "row": {"action": "skip", "file": rel, "to_review": f"unreadable PDF: {e}",
                                    "sha256": sha256}})
            print(f"[{i}/{len(pdfs)}] {rel}: unreadable PDF ({e})")
            continue
        g = gold.get("sha:" + sha256) or gold.get(pdf.name.lower())
        ref = g if g and "sha256" in g else None
        item, note, review = item_from_record(cat, rec, pdf, g)
        if rec is None and ref:
            review = [r for r in review if r != "not analysed by the classifier"]
        if matched_by_name:
            review.append("matched to the classifier's results by file name only (the file changed?)")
        if ref and ref["sha256"].lower() != sha256:
            review.append("matched to the reference by file name only (the file changed?)")
        used_pages = (rec or {}).get("pages_used") or [1]
        if ref and ref.get("cover_page", "").isdigit():
            used_pages = [ref["cover_page"]]
        cover = min(max(int(used_pages[0]), 1), pages or 1)
        warnings = [w["message"] for w in coherence.check(conn, item["item_type"],
                                                          [u["notation"] for u in item["udc"]],
                                                          item["fields"].get("extra", {}).get("value", ""))]
        if warnings:
            review.append("UDC form does not fit the type")
        action, dup = "load", ""
        if rec is None and not ref:
            action = "skip"
        if sha256 in seen:
            action, dup = "skip", f"same file as {seen[sha256]} in this folder"
        else:
            seen[sha256] = rel
            dups = item_dups(conn, sha256, item, cat)
            if dups:
                action, dup = "skip", dup_text(dups, planned)
        # validate and preview the citation key; a row to load stays (undone at the end) for the next checks
        citekey = ""
        conn.execute("SAVEPOINT plan_item")
        try:
            iid = lib.save_item(conn, None, item, confirm=False)
            citekey = conn.execute("SELECT citekey FROM items WHERE id=?", (iid,)).fetchone()[0]
            if action == "load":
                planned[iid] = rel
        except lib.ItemError as e:
            action = "skip"
            review.append(f"invalid: {e}")
        if action != "load":
            conn.execute("ROLLBACK TO plan_item")
        conn.execute("RELEASE plan_item")
        f = item["fields"]
        u = item["udc"][0] if item["udc"] else {}
        row = {"action": action, "file": rel, "type": item["item_type"],
               "title": f[lib.title_field(cat, item["item_type"])]["value"],
               "creators": creators_text(item["creators"]),
               "date": f.get(cat.field_for_base(item["item_type"], "date") or "date", {}).get("value", ""),
               "udc": " ; ".join(x["notation"] for x in item["udc"]),
               "udc_source": ("reference" if ref and ref.get("udc") else
                              "gold" if u.get("source") == "manual" else u.get("source", "")),
               "udc_confidence": "" if u.get("confidence") is None else round(u["confidence"], 2),
               "cover_page": cover, "to_review": "; ".join(review), "warnings": " | ".join(warnings),
               "duplicate_of": dup, "citekey": citekey, "sha256": sha256}
        entries.append({"file": rel, "sha256": sha256, "size": size, "pages": pages, "item": item, "note": note,
                        "cover_page": cover, "needs_review": bool(review), "row": row})
        flag = "" if action == "load" else f"  [{action}{': ' + dup if dup else ''}]"
        print(f"[{i}/{len(pdfs)}] {rel}  {item['item_type']}  {row['udc'] or '-'}"
              f"{'  (review)' if review else ''}{flag}")
    conn.rollback()   # the plan writes nothing
    conn.close()
    plan_path = Path(a.out).resolve() if a.out else folder / PLAN_NAME
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"created": datetime.now().isoformat(timespec="seconds"), "folder": str(folder),
            "results": str(Path(a.results).resolve()), "entries": entries}
    plan_path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    write_xlsx(plan_path, [e["row"] for e in entries])
    missing = [r["file"] for s, r in by_sha.items() if s not in used]
    n_load = sum(e["row"]["action"] == "load" for e in entries)
    print(f"\nPlan: {plan_path}\n  {n_load} to load, {len(entries) - n_load} to skip, "
          f"{sum(bool(e['row']['to_review']) for e in entries)} to review.")
    if missing:
        print(f"  {len(missing)} analysed file(s) not found in the folder: "
              + ", ".join(PureWindowsPath(m).name for m in missing[:10]) + (" ..." if len(missing) > 10 else ""))
    print("Edit the plan if needed (action load/skip, type, title, creators, date, udc, cover_page), save it and "
          f"run:\n  python bulk_import.py load \"{plan_path}\" --user <username>")


# --------------------------------------------------------------------------- spreadsheet
def write_xlsx(path: Path, rows: list[dict]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    ws = wb.active
    ws.title = "plan"
    ws.append(COLUMNS)
    grey = PatternFill("solid", fgColor="EEEEEE")
    for c, name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True)
        if name not in EDITABLE:
            cell.fill = grey
        ws.column_dimensions[cell.column_letter].width = WIDTHS[name]
    for r in rows:
        ws.append([str(r.get(c, "")) for c in COLUMNS])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.number_format = "@"   # text: Excel must not turn 004.2 into 4.2 or 2005-03 into a date
            if COLUMNS[cell.column - 1] not in EDITABLE:
                cell.fill = grey
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    try:
        wb.save(path)
    except PermissionError:
        raise PlanError(f"Cannot write {path}: close it in Excel and run again.")


def read_xlsx(path: Path) -> list[dict]:
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise PlanError(f"Cannot read the plan {path}: {e}")
    rows = list(wb.active.iter_rows(values_only=True))
    if not rows:
        return []
    head = [str(h or "").strip() for h in rows[0]]
    if "sha256" not in head or "action" not in head:
        raise PlanError("The plan has no 'sha256' or 'action' column (was it made by bulk_import.py plan?).")
    out = []
    for r in rows[1:]:
        d = {h: ("" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)))
             for h, v in zip(head, r)}
        if d.get("sha256"):
            out.append(d)
    return out


# --------------------------------------------------------------------------- load
def accepted_dup(conn, d: dict, row: dict, sha_to_file: dict[str, str]) -> bool:
    """A possible duplicate the plan listed for this row (the person set the row to 'load' anyway): an item
    of the library ('#12 ') or one loaded from another file of the same plan ('this folder: file')."""
    listed = row.get("duplicate_of") or ""
    if f"#{d['id']} " in listed:
        return True
    att = conn.execute("SELECT sha256 FROM attachments WHERE item_id=? AND role='main'", (d["id"],)).fetchone()
    other = sha_to_file.get(att[0]) if att else None
    return bool(other) and f"{BATCH_DUP}{other} " in listed


def cmd_load(a) -> None:
    plan_path = Path(a.plan).resolve()
    meta_path = plan_path.with_suffix(".json")
    if not meta_path.exists():
        raise PlanError(f"Missing {meta_path.name} next to the plan (both come from 'plan').")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    folder = Path(meta["folder"])
    entries = {e["sha256"]: e for e in meta["entries"]}
    sha_to_file = {e["sha256"]: e["file"] for e in meta["entries"]}
    rows = read_xlsx(plan_path)
    init_db()
    conn = connect()
    user = conn.execute("SELECT id, role, disabled FROM users WHERE username=?", (a.user,)).fetchone()
    if not user or user["disabled"] or user["role"] not in ("admin", "editor"):
        raise PlanError(f"'{a.user}' is not an active editor or administrator.")
    cat = catalog.get(conn)
    tag = a.tag or f"import {date.today().isoformat()}"
    todo = [r for r in rows if r.get("action", "").strip().lower() == "load"]
    print(f"{len(todo)} of {len(rows)} rows marked 'load'. Batch tag: '{tag}'.")
    if not todo:
        return
    if not a.yes and input("Load them now? [y/N] ").strip().lower() not in ("y", "yes", "s", "si", "sí"):
        print("Nothing done.")
        return
    report, counts = [], {"loaded": 0, "skipped": 0, "error": 0}
    for i, row in enumerate(todo, 1):
        e = entries.get(row["sha256"])
        name = row.get("file") or (e or {}).get("file", "?")
        res = {"file": name, "result": "", "item_id": "", "citekey": "", "message": ""}
        try:
            if e is None or "item" not in e:
                raise lib.ItemError("row not in import_plan.json (edit only the white columns).")
            pdf = folder / e["file"]
            if not pdf.exists():
                raise lib.ItemError(f"file not found: {pdf}")
            if hashes(pdf)[1] != e["sha256"]:
                raise lib.ItemError("the file changed since the plan was made; run 'plan' again.")
            item, cover = apply_edits(cat, e, row)
            dups = item_dups(conn, e["sha256"], item, cat)
            # the duplicates listed in the plan were accepted by setting the row to 'load'; a file already in
            # the library never is (running 'load' twice adds nothing)
            same_file = [d for d in dups if d["reason"] == "Identical file"]
            new_dups = [d for d in dups if not accepted_dup(conn, d, row, sha_to_file)]
            if same_file:
                res.update(result="skipped", message=f"already in the library: {dup_text(same_file)}")
            elif new_dups:
                res.update(result="skipped", message=f"possible duplicate not in the plan: {dup_text(new_dups)}. "
                                                     "Run 'plan' again and set the row to 'load' to keep both.")
            elif storage.used_bytes(conn) + e["size"] > config.MAX_BYTES:
                res.update(result="error", message=f"storage limit reached ({config.MAX_STORAGE_GB:g} GB)")
            if res["result"]:
                counts[res["result"]] += 1
                report.append(res)
                print(f"[{i}/{len(todo)}] {name}: {res['result']} - {res['message']}")
                if res["result"] == "error":
                    break
                continue
            item["tags"].append({"name": tag, "source": "import"})
            review = bool((row.get("to_review") or "").strip())   # cleared in the plan = already reviewed
            if review:
                item["tags"].append({"name": REVIEW_TAG, "source": "import"})
            dest = None
            try:
                iid = lib.save_item(conn, user["id"], item, confirm=False)
                if e.get("note"):
                    ts = now()
                    conn.execute("INSERT INTO item_notes(item_id, body, created_at, created_by, modified_at) "
                                 "VALUES (?,?,?,?,?)", (iid, e["note"], ts, user["id"], ts))
                dest = storage.add_main_file(conn, iid, pdf, sha256=e["sha256"], size=e["size"], pages=e["pages"],
                                             cover_page=cover, user_id=user["id"], copy=True)
                conn.commit()
            except Exception:
                conn.rollback()
                if dest is not None:
                    storage.undo_main_file(dest, pdf, copy=True)
                raise
            ck = conn.execute("SELECT citekey FROM items WHERE id=?", (iid,)).fetchone()[0]
            warns = coherence.check(conn, item["item_type"], [u["notation"] for u in item["udc"]],
                                    item["fields"].get("extra", {}).get("value", ""))
            res.update(result="loaded", item_id=iid, citekey=ck,
                       message=" | ".join(w["message"] for w in warns))
            counts["loaded"] += 1
            print(f"[{i}/{len(todo)}] {name} -> #{iid} {ck}{'  (to review)' if review else ''}")
        except lib.ItemError as ex:
            res.update(result="error", message=str(ex))
            counts["error"] += 1
            print(f"[{i}/{len(todo)}] {name}: ERROR {ex}")
        report.append(res)
    conn.close()
    rep = plan_path.with_name(f"import_report_{datetime.now():%Y%m%d-%H%M%S}.csv")
    with rep.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "result", "item_id", "citekey", "message"])
        w.writeheader()
        w.writerows(report)
    print(f"\nLoaded {counts['loaded']}, skipped {counts['skipped']}, errors {counts['error']}. Report: {rep}")
    print(f"In the app, search the tag '{tag}' for this batch and '{REVIEW_TAG}' for what needs checking.")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Bulk import of local PDFs classified by the PoC (see the docstring).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan", help="make import_plan.xlsx from results.json and a folder of PDFs")
    p.add_argument("results", help="results.json written by 'python -m udcpoc run'")
    p.add_argument("folder", help="folder with the PDFs (subfolders included)")
    p.add_argument("--gold", help="CSV file,udc,nota with UDC numbers decided by a person (saved as confirmed), "
                                  "or the PoC's reference (referencia.csv / referencia.xlsx: its values win)")
    p.add_argument("--out", help=f"plan file (default: <folder>\\{PLAN_NAME})")
    p.set_defaults(f=cmd_plan)
    p = sub.add_parser("load", help="create the items marked 'load' in the plan")
    p.add_argument("plan", help=PLAN_NAME)
    p.add_argument("--user", required=True, help="editor or administrator recorded as the one who added them")
    p.add_argument("--tag", help="batch tag (default: 'import YYYY-MM-DD')")
    p.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    p.set_defaults(f=cmd_load)
    a = ap.parse_args(argv)
    try:
        a.f(a)
    except PlanError as e:
        sys.exit(f"Error: {e}")
    except KeyboardInterrupt:
        sys.exit("\nStopped. What was loaded stays; run 'load' again to continue (loaded files are skipped).")


if __name__ == "__main__":
    main()
