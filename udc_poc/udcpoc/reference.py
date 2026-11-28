"""Libro de referencia: los datos correctos de cada PDF de la colección (books/gold/referencia.xlsx).

Sirve para tres cosas:
  1. guiar la importación masiva (bulk_import.py plan --gold referencia.csv toma de aquí UDC, tipo, título,
     autores y fecha en lugar de lo que adivinó el clasificador);
  2. ir sumando PDF nuevos (reference add) sin repetir ninguno: cada fila se identifica por el SHA-256 del
     archivo, así que renombrarlo o moverlo no rompe nada;
  3. comparar clasificadores: reference predictions guarda lo que propuso una versión (hoja Predicciones,
     separada de la verdad para que la revisión siga siendo a ciegas) y reference evaluate calcula sus métricas
     contra la hoja Libros (hoja Resumen, una columna por versión).

Hojas: Instrucciones, Libros (la verdad: se edita), Predicciones (no se edita), Resumen (calculada).
Cada vez que se guarda se exporta también referencia.csv (hoja Libros en texto, para git).

    python -m udcpoc reference add books                       # PDF nuevos -> filas prellenadas, estado 'pendiente'
    python -m udcpoc reference predictions output\\results.json --as v0.1.0
    python -m udcpoc reference evaluate [--solo-verificados]
    python -m udcpoc reference export                          # solo regenera referencia.csv
"""
from __future__ import annotations

import csv
import hashlib
import re
from datetime import date
from pathlib import Path, PureWindowsPath

import config
from .metadata import detect_language, find_identifiers, parse_filename, similar
from .notation import components

REF_XLSX = config.BASE_DIR / "books" / "gold" / "referencia.xlsx"

# (columna, se edita a mano?, ancho). Las grises se calculan o vienen del archivo.
LIBROS = [
    ("sha256", False, 12), ("sha1", False, 10), ("archivo", False, 44), ("ruta", False, 30),
    ("paginas", False, 7), ("texto", False, 8),
    ("type", True, 14), ("title", True, 50), ("creators", True, 34), ("contributors", True, 26),
    ("edition", True, 8), ("volume", True, 7), ("series", True, 20), ("number", True, 14),
    ("publication", True, 24), ("issue", True, 6), ("pages", True, 9), ("date", True, 10),
    ("publisher", True, 22), ("place", True, 16), ("ISBN", True, 16), ("DOI", True, 14),
    ("language", True, 8), ("original_language", True, 8),
    ("udc", True, 28), ("udc_alternativas", True, 28), ("fuente_udc", True, 18), ("nota_udc", True, 30),
    ("cover_page", True, 7), ("estado", True, 11), ("revisado", True, 16), ("fuente_datos", True, 24),
    ("observaciones", True, 30),
    ("clase_principal", False, 18), ("aux_forma", False, 12), ("aux_idioma", False, 10),
    ("aux_lugar", False, 12), ("aux_tiempo", False, 10), ("aux_otros", False, 14),
]
PRED = ["version", "sha256", "archivo", "type", "title", "creators", "date", "language", "udc_1", "udc_2",
        "udc_3", "confianza", "baja_confianza", "cover_page", "warnings", "fecha"]
ESTADOS = ["pendiente", "propuesto", "verificado", "dudoso"]
EVALUABLE = {"propuesto", "verificado"}
COLS = [c for c, _, _ in LIBROS]
EDITABLE = {c for c, e, _ in LIBROS if e}
AUX = {"form": "aux_forma", "lang": "aux_idioma", "place": "aux_lugar", "time": "aux_tiempo"}

INSTRUCCIONES = """\
LIBRO DE REFERENCIA - datos correctos de cada PDF de la colección

Hoja Libros (la verdad). Una fila por PDF; la identifica el sha256 del archivo (renombrar o mover el PDF no la rompe).
  Columnas grises: vienen del archivo o se calculan de la UDC al guardar (no se editan).
  type: tipo de ítem de Zotero (book, bookSection, journalArticle, thesis, report, standard, patent, statute,
        manuscript, map...). Partituras: book (o manuscript si es un autógrafo).
  creators: autores, 'Apellido, Nombre; Apellido, Nombre'. Instituciones sin coma.
  contributors: otros papeles, 'Apellido, Nombre (translator); Apellido, Nombre (editor)'.
  number: número de norma, informe, patente o ley (p. ej. 'IEEE Std 315-1975', 'US 174,465').
  publication / issue / pages: revista o libro que contiene el artículo o capítulo, número y páginas.
  date: año (o AAAA-MM-DD). edition: número de edición (2, 3...). language: ISO 639 del texto (en, es, de...).
  original_language: idioma de la obra original si es una traducción.
  udc: la notación completa (principal + auxiliares de forma, lugar, tiempo e idioma).
  udc_alternativas: otras notaciones que también se aceptan como correctas, separadas por ' ; '.
  fuente_udc: quién la decidió (persona, catálogo de una biblioteca, claude-opus-5-5...).
  cover_page: página (desde 1) que sirve de portada.
  estado: pendiente (sin datos revisados) | propuesto (llenado por una IA o un catálogo, sin revisión humana)
          | verificado (revisado por una persona) | dudoso (hay que volver a verlo).
  revisado: quién y cuándo (p. ej. 'M. 2026-12-01').
Las métricas cuentan las filas 'propuesto' y 'verificado' con UDC; con --solo-verificados, solo las verificadas.

Hoja Predicciones. Lo que propuso cada versión del clasificador (no se edita: reference predictions la reescribe).
Está aparte para revisar a ciegas: si corriges la UDC mirando la propuesta, la comparación pierde valor.

Hoja Resumen. Métricas por versión (reference evaluate). Una columna por versión.

Comandos (en la carpeta udc_poc):
  .venv\\Scripts\\python.exe -m udcpoc reference add books
  .venv\\Scripts\\python.exe -m udcpoc reference predictions output\\results_v0.1.0.json --as v0.1.0
  .venv\\Scripts\\python.exe -m udcpoc reference evaluate
Cierra el Excel antes de correrlos. Cada vez que se guarda se escribe también referencia.csv (para git).
"""

PUBLISHERS = [
    "McGraw-Hill", "Pearson", "Prentice Hall", "Prentice-Hall", "Addison-Wesley", "Addison Wesley", "Wiley-VCH",
    "John Wiley", "Wiley", "Cengage", "Springer", "Elsevier", "Academic Press", "Butterworth-Heinemann", "Newnes",
    "CRC Press", "Taylor & Francis", "Taylor and Francis", "Oxford University Press", "Cambridge University Press",
    "W. W. Norton", "W. H. Freeman", "Reverté", "Birkhäuser", "Humana Press", "Woodhead", "Industrial Press",
    "Houghton Mifflin", "Artech House", "Dover", "Desert Publications", "Thomson", "Alfaomega", "Limusa",
    "Editorial Universitaria Abya-Yala", "Fondo Educativo Interamericano", "Marcel Dekker", "IEEE", "ASME",
    "Brooks/Cole", "Benjamin Cummings", "Harper", "Schirmer", "Norton", "G. Bell", "Lea & Febiger",
]


class RefError(Exception):
    pass


# --------------------------------------------------------------------------- lectura / escritura
def load(path: Path = REF_XLSX) -> dict:
    """{'libros': [fila...], 'pred': [fila...], 'resumen': [[...]]}; vacío si el archivo no existe."""
    if not path.exists():
        return {"libros": [], "pred": [], "resumen": []}
    from openpyxl import load_workbook
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as e:  # noqa: BLE001
        raise RefError(f"No se puede leer {path}: {e}")

    def rows(name):
        if name not in wb.sheetnames:
            return []
        it = wb[name].iter_rows(values_only=True)
        head = [str(h or "").strip() for h in next(it, [])]
        out = []
        for r in it:
            d = {h: _cell(v) for h, v in zip(head, r) if h}
            if any(d.values()):
                out.append(d)
        return out

    res = [list(r) for r in wb["Resumen"].iter_rows(values_only=True)] if "Resumen" in wb.sheetnames else []
    return {"libros": rows("Libros"), "pred": rows("Predicciones"), "resumen": res}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def derive(row: dict) -> dict:
    """Columnas calculadas a partir de la UDC."""
    c = components(row.get("udc", "")) if row.get("udc") else {}
    row["clase_principal"] = " ; ".join(c.get("main", []))
    for k, col in AUX.items():
        row[col] = " ".join(c.get(k, []))
    row["aux_otros"] = " ".join(x for k, v in c.items() if k not in AUX and k != "main" for x in v)
    return row


def save(data: dict, path: Path = REF_XLSX) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    grey, bold = PatternFill("solid", fgColor="EEEEEE"), Font(bold=True)
    wb = Workbook()
    ws = wb.active
    ws.title = "Instrucciones"
    for line in INSTRUCCIONES.splitlines():
        ws.append([line])
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 130

    ws = wb.create_sheet("Libros")
    ws.append(COLS)
    for r in data["libros"]:
        derive(r)
        ws.append([r.get(c, "") for c in COLS])
    for i, (name, edit, width) in enumerate(LIBROS, 1):
        col = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[col].width = width
        ws.cell(row=1, column=i).font = bold
        for row in ws.iter_rows(min_row=1, min_col=i, max_col=i):
            row[0].number_format = "@"   # texto: Excel no debe convertir 004.2 en 4.2 ni 2005-03 en fecha
            if not edit:
                row[0].fill = grey
    n = max(2, ws.max_row)
    dv = DataValidation(type="list", formula1='"' + ",".join(ESTADOS) + '"', allow_blank=True)
    dv.add(f"{_col('estado')}2:{_col('estado')}{n + 500}")
    tv = DataValidation(type="list", formula1='"' + ",".join(sorted(config.ZOTERO_ITEM_TYPES)) + '"',
                        allow_blank=True, showErrorMessage=True, errorStyle="warning",
                        error="No es un tipo de Zotero conocido (se acepta igual).")
    tv.add(f"{_col('type')}2:{_col('type')}{n + 500}")
    ws.add_data_validation(dv)
    ws.add_data_validation(tv)
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions

    ws = wb.create_sheet("Predicciones")
    ws.append(PRED)
    for r in sorted(data["pred"], key=lambda r: (r.get("version", ""), r.get("archivo", "").lower())):
        ws.append([r.get(c, "") for c in PRED])
    for i, c in enumerate(PRED, 1):
        ws.cell(row=1, column=i).font = bold
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = \
            {"archivo": 44, "title": 44, "creators": 30, "warnings": 40, "sha256": 12}.get(c, 14)
    for row in ws.iter_rows():
        for cell in row:
            cell.number_format = "@"
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions

    ws = wb.create_sheet("Resumen")
    for r in data.get("resumen") or [["Sin métricas todavía: python -m udcpoc reference evaluate"]]:
        ws.append(r)
    ws.column_dimensions["A"].width = 52
    for col in "BCDEFGHIJ":
        ws.column_dimensions[col].width = 14
    for cell in ws[1]:
        cell.font = bold
        cell.alignment = Alignment(horizontal="center")
    wb.active = 1
    try:
        wb.save(path)
    except PermissionError:
        raise RefError(f"No se puede escribir {path}: ciérralo en Excel y vuelve a correr el comando.")
    export_csv(data, path.with_suffix(".csv"))


def _col(name: str) -> str:
    from openpyxl.utils import get_column_letter
    return get_column_letter(COLS.index(name) + 1)


def export_csv(data: dict, path: Path) -> None:
    rows = sorted(data["libros"], key=lambda r: r.get("ruta", "").lower())
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore")
        w.writeheader()
        w.writerows(derive(dict(r)) for r in rows)


# --------------------------------------------------------------------------- add: filas nuevas prellenadas
def file_hashes(path: Path) -> tuple[str, str]:
    s1, s256 = hashlib.sha1(), hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            s1.update(chunk)
            s256.update(chunk)
    return s1.hexdigest(), s256.hexdigest()


def _publisher(text: str) -> str:
    for p in PUBLISHERS:
        if re.search(r"(?<!\w)" + re.escape(p) + r"(?!\w)", text, re.I):
            return {"Prentice-Hall": "Prentice Hall", "Addison Wesley": "Addison-Wesley", "John Wiley": "Wiley",
                    "Taylor and Francis": "Taylor & Francis", "Norton": "W. W. Norton"}.get(p, p)
    return ""


def prefill(pdf: Path, root: Path) -> dict:
    """Fila nueva con lo que se puede sacar sin clasificar: nombre del archivo, metadatos del PDF y las
    primeras páginas (ISBN, año del copyright, editorial, idioma, primera página con contenido)."""
    import fitz
    from .pdfio import ink_fraction
    sha1, sha256 = file_hashes(pdf)
    doc = fitz.open(pdf)
    texts = [doc[i].get_text() for i in range(min(len(doc), 20))]
    front = "\n".join(texts)
    meta = doc.metadata or {}
    cover = 1
    for i in range(min(len(doc), 8)):
        if len(texts[i].strip()) > 20 or ink_fraction(doc[i]) >= config.BLANK_INK:
            cover = i + 1
            break
    fn = parse_filename(str(pdf))
    ids = find_identifiers(front) if front.strip() else {}
    years = [int(y) for y in re.findall(r"(?:©|\(c\)|copyright|derechos reservados)[^\n]{0,40}?((?:1[5-9]|20)\d\d)",
                                        front, re.I)]
    lang = detect_language(front)[0] if len(front.strip()) > 200 else ""
    creators = "; ".join(fn.get("authors") or []) or (meta.get("author") or "").strip()
    row = {"sha256": sha256, "sha1": sha1, "archivo": pdf.name, "ruta": pdf.relative_to(root).as_posix(),
           "paginas": str(len(doc)), "texto": "sí" if sum(len(t.strip()) for t in texts) > 200 else "no (OCR)",
           "type": "book", "title": fn.get("title") or (meta.get("title") or "").strip() or pdf.stem,
           "creators": creators, "edition": str(fn.get("edition") or ""),
           "date": str(fn.get("year") or (max(years) if years else "")),
           "publisher": _publisher(front[:20000]), "ISBN": fn.get("isbn") or ids.get("isbn", ""),
           "DOI": ids.get("doi", ""), "language": lang or "", "cover_page": str(cover), "estado": "pendiente",
           "fuente_datos": "nombre del archivo + metadatos y primeras páginas del PDF (sin revisar)"}
    doc.close()
    return row


def add(paths: list[str], ref: Path = REF_XLSX) -> int:
    data = load(ref)
    have = {r.get("sha256") for r in data["libros"]}
    root = ref.parent.parent   # books/: las rutas se guardan relativas a ella cuando se puede
    new = 0
    for p in map(Path, paths):
        files = sorted(x for x in p.rglob("*") if x.suffix.lower() == ".pdf") if p.is_dir() else [p]
        for f in files:
            f = f.resolve()
            sha = file_hashes(f)[1]
            if sha in have:
                continue
            try:
                row = prefill(f, root if root in f.parents else f.parent)
            except Exception as e:  # noqa: BLE001
                print(f"  ERROR {f.name}: {e}")
                continue
            data["libros"].append(row)
            have.add(sha)
            new += 1
            print(f"  + {row['ruta']}")
    save(data, ref)
    print(f"{new} PDF nuevos; la referencia tiene {len(data['libros'])}. {ref}")
    return new


# --------------------------------------------------------------------------- predicciones
def _creators_text(v) -> str:
    out = []
    for c in v or []:
        if c.get("name"):
            out.append(c["name"])
        else:
            out.append(", ".join(x for x in (c.get("lastName", ""), c.get("firstName", "")) if x))
    return "; ".join(out)


def predictions(results: Path, version: str, ref: Path = REF_XLSX) -> int:
    import json
    data = load(ref)
    if not data["libros"]:
        raise RefError(f"La referencia está vacía: corre primero 'reference add'. ({ref})")
    by_sha1 = {r["sha1"]: r for r in data["libros"] if r.get("sha1")}
    by_name = {r["archivo"].lower(): r for r in data["libros"]}
    recs = json.loads(results.read_text(encoding="utf-8"))
    rows, missing = [], []
    for rec in recs:
        lib = by_sha1.get(rec.get("sha1")) or by_name.get(PureWindowsPath(rec.get("file", "")).name.lower())
        if lib is None:
            missing.append(PureWindowsPath(rec.get("file", "")).name)
            continue
        f, cls = rec.get("fields") or {}, rec.get("classification") or {}
        sugg = [s["udc"] for s in cls.get("suggestions") or []] + ["", "", ""]
        conf = (cls.get("suggestions") or [{}])[0].get("confidence")
        rows.append({"version": version, "sha256": lib["sha256"], "archivo": lib["archivo"],
                     "type": (rec.get("item_type") or {}).get("value", ""),
                     "title": str(f.get("title", {}).get("value", "")),
                     "creators": _creators_text(f.get("creators", {}).get("value")),
                     "date": str(f.get("date", {}).get("value", "")),
                     "language": str(f.get("language", {}).get("value", "") or rec.get("doc_language") or ""),
                     "udc_1": sugg[0], "udc_2": sugg[1], "udc_3": sugg[2],
                     "confianza": "" if conf is None else f"{conf:.2f}",
                     "baja_confianza": "sí" if cls.get("low_confidence") else "",
                     "cover_page": str((rec.get("pages_used") or [""])[0]),
                     "warnings": " | ".join(w if isinstance(w, str) else w.get("message", str(w))
                                            for w in rec.get("warnings") or []),
                     "fecha": date.today().isoformat()})
    data["pred"] = [r for r in data["pred"] if r.get("version") != version] + rows
    save(data, ref)
    print(f"{len(rows)} predicciones de '{version}' guardadas en la hoja Predicciones.")
    if missing:
        print(f"  {len(missing)} documento(s) de results.json no están en la referencia (usa 'reference add'): "
              + ", ".join(missing[:8]) + (" ..." if len(missing) > 8 else ""))
    return len(rows)


# --------------------------------------------------------------------------- métricas
def _norm(s: str) -> str:
    return re.sub(r"\s", "", s or "")


def _accepted(row: dict) -> list[str]:
    return [_norm(x) for x in [row.get("udc", "")] + (row.get("udc_alternativas") or "").split(";") if _norm(x)]


def _main(n: str) -> set:
    return set(components(n).get("main", [])) if n else set()


def _surname(s: str) -> str:
    first = (s or "").split(";")[0].strip()
    return re.sub(r"\W", "", (first.split(",")[0] if "," in first else (first.split() or [""])[-1]).lower())


def metrics(libros: list[dict], preds: list[dict], tree, only_verified=False) -> dict:
    from .evaluate import evaluate
    ok_states = {"verificado"} if only_verified else EVALUABLE
    truth = {r["sha256"]: r for r in libros if r.get("udc") and r.get("estado") in ok_states}
    gold, results, extra = {}, [], {"udc_aceptada_top1": 0, "principal_aceptada_top1": 0,
                                    "principal_aceptada_top3": 0, "autor": [0, 0], "portada": [0, 0], "n": 0}
    for p in preds:
        t = truth.get(p.get("sha256"))
        if not t:
            continue
        key = p["sha256"]
        gold[key] = {"udc": t["udc"], "title": t.get("title", ""), "date": t.get("date", ""),
                     "language": t.get("language", ""), "item_type": t.get("type", "")}
        sugg = [{"udc": u} for u in (p.get("udc_1"), p.get("udc_2"), p.get("udc_3")) if u]
        results.append({"file": key, "item_type": {"value": p.get("type", "")},
                        "fields": {"title": {"value": p.get("title", "")}, "date": {"value": p.get("date", "")},
                                   "language": {"value": p.get("language", "")}},
                        "classification": {"suggestions": sugg}})
        acc = _accepted(t)
        mains = [_main(a) for a in acc]
        extra["n"] += 1
        extra["udc_aceptada_top1"] += bool(sugg) and _norm(sugg[0]["udc"]) in acc
        extra["principal_aceptada_top1"] += bool(sugg) and _main(sugg[0]["udc"]) in mains
        extra["principal_aceptada_top3"] += any(_main(s["udc"]) in mains for s in sugg)
        if t.get("creators"):
            extra["autor"][1] += 1
            extra["autor"][0] += bool(p.get("creators")) and _surname(p["creators"]) == _surname(t["creators"])
        if t.get("cover_page"):
            extra["portada"][1] += 1
            extra["portada"][0] += (p.get("cover_page") or "") == t["cover_page"]
    m = evaluate(results, {k: v for k, v in gold.items()}, tree) if results else {}
    # evaluate() busca por nombre de archivo en minúsculas: las claves ya son sha256 en minúsculas
    n = max(1, extra["n"])
    m["udc_completa_top1_con_alternativas"] = round(extra["udc_aceptada_top1"] / n, 3)
    m["clase_principal_top1_con_alternativas"] = round(extra["principal_aceptada_top1"] / n, 3)
    m["clase_principal_top3_con_alternativas"] = round(extra["principal_aceptada_top3"] / n, 3)
    m["primer_autor"] = f"{extra['autor'][0]}/{extra['autor'][1]}"
    m["pagina_de_portada"] = f"{extra['portada'][0]}/{extra['portada'][1]}"
    return m


def summary_table(per_version: dict[str, dict], only_verified: bool) -> list[list]:
    versions = sorted(per_version)
    rows = [["Métrica (" + ("solo verificados" if only_verified else "propuestos + verificados") + ")"] + versions]

    def put(label, getter):
        rows.append([label] + [getter(per_version[v]) for v in versions])

    put("Documentos evaluados", lambda m: m.get("documentos_evaluados", 0))
    put("Clase principal correcta (1.ª sugerencia)", lambda m: m.get("clase_principal_top1"))
    put("Clase principal correcta (entre las 3 primeras)", lambda m: m.get("clase_principal_top3"))
    put("Clase principal correcta, aceptando alternativas (1.ª)", lambda m: m.get("clase_principal_top1_con_alternativas"))
    put("Clase principal correcta, aceptando alternativas (top 3)", lambda m: m.get("clase_principal_top3_con_alternativas"))
    put("Notación completa idéntica (1.ª)", lambda m: m.get("notacion_completa_top1"))
    put("Notación completa, aceptando alternativas (1.ª)", lambda m: m.get("udc_completa_top1_con_alternativas"))
    levels = sorted({k for m in per_version.values() for k in m.get("acierto_por_nivel", {})},
                    key=lambda k: int(k.split("_")[1]))
    for k in levels:
        put(f"Acierto jerárquico, {k.replace('_', ' ')}", lambda m, k=k: m.get("acierto_por_nivel", {}).get(k, ""))
    for aux, label in (("form", "forma"), ("lang", "idioma"), ("place", "lugar"), ("time", "tiempo")):
        put(f"Auxiliar de {label}: correctas / en la referencia",
            lambda m, a=aux: "{correctas}/{en_gold}".format(**m["tablas_auxiliares"][a]) if a in m.get("tablas_auxiliares", {}) else "")
    for f, label in (("title", "Título (similitud ≥ 0,85)"), ("date(año)", "Año"), ("language", "Idioma"),
                     ("item_type", "Tipo de ítem")):
        put(label, lambda m, f=f: "{correctos}/{con_gold}".format(**m["campos"][f]) if f in m.get("campos", {}) else "")
    put("Primer autor (apellido)", lambda m: m.get("primer_autor", ""))
    put("Página de portada", lambda m: m.get("pagina_de_portada", ""))
    rows.append([])
    rows.append([f"Calculado el {date.today().isoformat()} con python -m udcpoc reference evaluate"])
    return rows


def evaluate_ref(tree, only_verified=False, ref: Path = REF_XLSX) -> dict:
    data = load(ref)
    versions = sorted({p["version"] for p in data["pred"] if p.get("version")})
    if not versions:
        raise RefError("No hay predicciones: corre primero 'reference predictions <results.json> --as <versión>'.")
    per = {v: metrics(data["libros"], [p for p in data["pred"] if p.get("version") == v], tree, only_verified)
           for v in versions}
    data["resumen"] = summary_table(per, only_verified)
    save(data, ref)
    for r in data["resumen"]:
        print("  ".join(f"{str(x):<14}" if i else f"{str(x):<58}" for i, x in enumerate(r)))
    return per
