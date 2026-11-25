"""Línea de comandos:  python -m udcpoc <comando>   (ver README)."""
from __future__ import annotations
import argparse
import base64
import csv
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

import config
from .classify import Classifier
from .embed import Embedder, UDCIndex
from .evaluate import evaluate, load_gold
from .feedback import Feedback, Reranker
from .metadata import build_record, build_views
from .notation import validate
from .tree import Tree


def _load(model=None, force=False):
    tree = Tree.load(config.UDC_RDF, config.LABEL_LANGS)
    emb = Embedder(model or config.EMBEDDING_MODEL, config.EMBEDDING_DEVICE)
    idx = UDCIndex.load_or_build(tree, emb, config.INDEX_DIR, force=force)
    return tree, emb, idx


def _pdfs(paths):
    out = []
    for p in map(Path, paths):
        out += sorted(p.rglob("*.pdf")) if p.is_dir() else [p]
    return out


# ------------------------------------------------------------------ comandos
def cmd_index(a):
    t0 = time.time()
    tree, emb, idx = _load(a.model, force=a.force)
    print(json.dumps(tree.stats(), ensure_ascii=False, indent=2))
    pf = Classifier(tree, idx, emb).places
    print(f"\nIndice: {len(idx.uris)} nodos, dim {idx.emb.shape[1]}, {time.time() - t0:.0f}s")
    if pf.unresolved:
        print(f"Países CLDR sin nodo de lugar ({len(pf.unresolved)}; añade TERRITORY_UDC en config.py si importan):",
              "; ".join(pf.unresolved[:20]))


def cmd_tree(a):
    tree = Tree.load(config.UDC_RDF, config.LABEL_LANGS)
    n = 0
    for node in sorted(tree.nodes.values(), key=lambda x: tree._sort_key(x.notation)):
        if a.kind and node.kind != a.kind:
            continue
        lbl = node.label(tree.label_langs)
        if a.grep and a.grep.lower() not in lbl.lower() and a.grep not in node.notation:
            continue
        print(f"{'  ' * min(node.depth, 6)}{node.notation:<14} [{node.kind}{',rango' if node.is_range else ''}] {lbl}")
        n += 1
        if n >= a.limit:
            print("... (usa --limit para ver más)")
            break


def cmd_validate(a):
    tree = Tree.load(config.UDC_RDF, config.LABEL_LANGS)
    issues = validate(a.notation, tree)
    print("VÁLIDA" if not any(l == "error" for l, _ in issues) else "INVÁLIDA")
    for lv, msg in issues:
        print(f"  [{lv}] {msg}")


def _apply_enrichment(rec: dict) -> dict | None:
    """Consulta por ISBN/DOI/arXiv y rellena campos del tipo detectado: un valor externo gana a uno extraído
    con menos confianza. Devuelve el resultado (temas, LC/Dewey, UDC de catálogo) o None."""
    from .enrich import enrich
    from .metadata import name_to_creator
    e = enrich(rec.get("identifiers") or {})
    if not e or not e["sources"]:
        if e:
            rec["enrichment"] = {"sources": [], "errors": e["errors"]}
        return None
    src = "+".join(e["sources"])
    allowed = set(config.ZOTERO_ITEM_TYPES.get(rec["item_type"]["value"], []))
    f, filled = rec["fields"], []
    from .metadata import similar
    for k, v in e["fields"].items():
        if k not in allowed or (k in f and f[k]["confidence"] >= config.ENRICH_CONFIDENCE):
            continue
        old = f.get(k, {}).get("value")
        if k == "title" and isinstance(old, str) and similar(old[:len(v)], v) >= 0.8 and len(old) >= len(v):
            # el catálogo confirma el título del PDF, que suele estar más completo (acentos, subtítulo):
            # se conserva y sube la confianza (Open Library recorta algunos títulos)
            f[k] = {"value": old, "source": f[k]["source"] + "+" + src, "confidence": config.ENRICH_CONFIDENCE}
            filled.append(k + " (confirmado)")
            continue
        f[k] = {"value": v, "source": src, "confidence": config.ENRICH_CONFIDENCE}
        filled.append(k)
    if e["creators"] and ("creators" not in f or f["creators"]["confidence"] < config.ENRICH_CONFIDENCE):
        role = config.PRIMARY_CREATOR.get(rec["item_type"]["value"], "author")
        f["creators"] = {"value": [name_to_creator(n, role) for n in e["creators"]], "source": src,
                         "confidence": config.ENRICH_CONFIDENCE}
        filled.append("creators")
    if e["subjects"] and "tags" in allowed | {"tags"}:
        from .enrich import is_code
        tags = [s for s in e["subjects"] if not is_code(s)][:10]
        if tags and ("tags" not in f or f["tags"]["confidence"] < config.ENRICH_CONFIDENCE):
            f["tags"] = {"value": tags, "source": src, "confidence": config.ENRICH_CONFIDENCE}
            filled.append("tags")
    rec["enrichment"] = {"sources": e["sources"], "filled": filled, "subjects": e["subjects"][:12],
                         "ddc": e["ddc"], "lcc": e["lcc"], "udc": e["udc"], "errors": e["errors"]}
    return e


def process(path, clf, args):
    from .pdfio import read_pdf
    pdf = read_pdf(path, ocr=args.ocr)
    rec = build_record(pdf, use_ner=args.ner)
    enr = None
    if config.ENRICH_ONLINE and not getattr(args, "offline", False):
        enr = _apply_enrichment(rec)                     # identificador primero; heurísticas e IA después
    views = build_views(pdf, rec)
    if enr:
        from .enrich import subjects_view
        sv = subjects_view(enr)
        if sv:
            views["subjects"] = sv
    f = rec["fields"]
    if getattr(args, "llm", False) or config.LLM_ENABLED:
        try:
            from .llm import llm_fill
            rec["llm"] = llm_fill("\n".join(pdf.head_text[:2]), rec)
        except Exception as e:  # noqa: BLE001
            pdf.warnings.append(f"LLM falló: {e}")
    ctx = {"item_type": rec["item_type"]["value"], "subtype": rec["item_type"]["subtype"],
           "lang": (rec["doc_language"], f.get("language", {}).get("confidence", 0.0)),
           "title": f.get("title", {}).get("value", ""), "abstract": f.get("abstractNote", {}).get("value", ""),
           "tags": ", ".join(f.get("tags", {}).get("value", [])),
           "filename": Path(path).stem.replace("_", " ")}
    if enr and enr.get("udc"):
        ctx["external_udc"] = {"codes": enr["udc"], "source": "+".join(s for s in enr["sources"])}
    if rec.get("score"):
        # partitura: la clase sale de reglas dentro de 78 (género, plantilla por pentagramas, instrumento, forma)
        ctx["score"] = {**rec["score"], "per_system": pdf.staff.per_system if pdf.staff else 0,
                        "text": " ".join([ctx["filename"], pdf.meta.get("title", ""), ctx["title"],
                                          "\n".join(pdf.head_text[:3])])[:4000]}
    if pdf.scanned and not pdf.ocr_used:
        # sin texto real, el resto de vistas es ruido: clasificar solo por el título (si lo hay)
        views = {"front": ctx["title"]} if ctx["title"] else {}
        ctx["title_only"] = True
    cls = clf.suggest(views, ctx, sha=pdf.sha1)
    out = {"file": str(path), "sha1": pdf.sha1, "pages": pdf.n_pages, "scanned": pdf.scanned, "ocr": pdf.ocr_used,
           "ocr_langs": pdf.ocr_langs, "pages_used": [i + 1 for i in pdf.pages_used],
           "blank_skipped": pdf.blank_skipped, **rec, "classification": cls, "warnings": pdf.warnings}
    if getattr(args, "verify", False):
        from .verify import verify_record
        out["verification"] = verify_record(rec)
    return out


def cmd_run(a):
    tree, emb, idx = _load(a.model)
    fb = Feedback()
    clf = Classifier(tree, idx, emb, feedback=fb, reranker=Reranker.load())
    out_p = Path(a.out)
    done = {}
    if a.resume and out_p.exists():
        done = {r["sha1"]: r for r in json.loads(out_p.read_text(encoding="utf-8"))}
    results = list(done.values())
    if a.plan:  # lista de archivos de 'sample' (output/sample_plan.csv)
        with open(a.plan, encoding="utf-8-sig") as fh:
            files = [Path(r["file"]) for r in csv.DictReader(fh)]
    else:
        files = _pdfs(a.paths)
    if not files:
        sys.exit("No hay PDF: indica carpetas/archivos o --plan output\\sample_plan.csv")
    files = files[: a.limit or None]
    for i, p in enumerate(files, 1):
        t0 = time.time()
        try:
            r = process(p, clf, a)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(files)}] ERROR {p.name}: {e}")
            continue
        if r["sha1"] in done:
            continue
        results.append(r)
        top = r["classification"]["suggestions"][:1]
        print(f"[{i}/{len(files)}] {p.name}  ({time.time() - t0:.1f}s)  {r['item_type']['value']}  "
              f"{top[0]['udc'] if top else '—'}{'  ⚠ baja confianza' if r['classification']['low_confidence'] else ''}")
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nListo: {len(results)} documentos en {out_p}")


def _show(r):
    f = r["fields"]
    print("\n" + "=" * 78)
    print(Path(r["file"]).name)
    print(f"Tipo: {r['item_type']['value']}  | Título: {f.get('title', {}).get('value', '—')}")
    cr = [f"{c['firstName']} {c['lastName']}" for c in f.get("creators", {}).get("value", [])]
    print(f"Autores: {', '.join(cr) or '—'}  | Año: {f.get('date', {}).get('value', '—')}  | Idioma: {r['doc_language']}")
    if r["classification"]["note"]:
        print("⚠ ", r["classification"]["note"])
    for s in r["classification"]["suggestions"]:
        print(f"\n  [{s['rank']}] {s['udc']}   (confianza {s['confidence']:.0%})")
        for m in s["main"]:
            print(f"      {m['code']}  {' > '.join(m['path'][-3:])}")
        for k, v in s["aux"].items():
            print(f"      {k}: {v['code']} {v['label']}  [{v['source']}, {v['evidence']}]")
        if s.get("explain", {}).get("via_see_also"):
            print(f"      (llegó por el See also de {s['explain']['via_see_also']})")
        for x in s.get("ver_tambien", [])[:3]:
            print(f"      ⇨ see also: {x['code']}  {x['label']}" + (f"  (sim {x['sim']:.2f})" if x["sim"] is not None else ""))


def cmd_review(a):
    tree = Tree.load(config.UDC_RDF, config.LABEL_LANGS)
    results = json.loads(Path(a.results).read_text(encoding="utf-8"))
    fb = Feedback()
    gold_p = Path(a.gold)
    gold_exists = gold_p.exists()
    seen = {r["file"] for r in csv.DictReader(open(gold_p, encoding="utf-8-sig"))} if gold_exists else set()
    # Respuestas preparadas (columnas file, udc): en modo ciego se usan sin preguntar.
    answers = {}
    ans_p = Path(a.answers) if a.answers else None
    if a.blind and ans_p and ans_p.exists():
        with open(ans_p, encoding="utf-8-sig") as fh:
            answers = {Path(x["file"]).name: x["udc"].strip() for x in csv.DictReader(fh) if x.get("udc", "").strip()}
        print(f"Respuestas de {ans_p}: {len(answers)}")
    from .notation import components
    auto = 0
    for r in results:
        if r["file"] in seen:
            continue
        mine = None
        if a.blind:
            print("\n" + "=" * 78 + f"\n{Path(r['file']).name}  — {r['fields'].get('title', {}).get('value', '')}")
            mine = answers.get(Path(r["file"]).name)
            if mine:
                print(f"Tu UDC (de {ans_p.name}): {mine}")
            else:
                mine = input("Tu UDC SIN ver sugerencias (enter = omitir): ").strip()
            if not mine:
                continue
        if mine:
            bad = [m for lv, m in validate(mine, tree) if lv == "error"]
            if bad:
                print("  Tu UDC no es válida:", "; ".join(bad), "→ se omite este documento")
                continue
        sug = r["classification"]["suggestions"]
        if mine and Path(r["file"]).name in answers:
            ans = ""                                     # respuesta preparada: se guarda sin preguntar
            top = sug[0]["udc"] if sug else "—"
            print(f"  sistema: {top}")
            auto += 1
        else:
            _show(r)
            prompt = ("\nEnter = guardar TU UDC · 1/2/3 = aceptar sugerencia · e = escribir otra · s = saltar · "
                      "q = salir > " if mine else "\n1/2/3 = aceptar · e = escribir otra · s = saltar · q = salir > ")
            ans = input(prompt).strip().lower()
        if ans == "q":
            break
        if ans == "" and mine:
            # lo aprendido es TU notación (no una sugerencia que quizá estaba mal)
            same = [i for i, s in enumerate(sug, 1) if re.sub(r"\s", "", s["udc"]) == re.sub(r"\s", "", mine)]
            final, rank = mine, (same[0] if same else 0)
        elif ans == "s" or not ans:
            continue
        elif ans in ("1", "2", "3") and int(ans) <= len(sug):
            final, rank = sug[int(ans) - 1]["udc"], int(ans)
        elif ans == "e":
            final, rank = input("UDC: ").strip(), 0
            bad = [m for lv, m in validate(final, tree) if lv == "error"]
            if bad:
                print("  No válida:", "; ".join(bad))
                continue
        else:
            continue
        gold_final = mine or final
        cl = r["classification"]
        emb = np.frombuffer(base64.b64decode(cl["_doc_embedding"]), dtype=np.float32)
        comp = components(final)
        fb.add(r["sha1"], r["file"], r["fields"].get("title", {}).get("value", ""), emb, final,
               comp.get("main", []), {k: comp.get(k, []) for k in ("lang", "form", "place", "time")},
               cl["_candidates"], [s["udc"] for s in sug], rank)
        new = not gold_p.exists()
        with open(gold_p, "a", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            if new:
                # title/date/language/item_type = VERDAD, vacías: llénalas tú si quieres métricas de metadatos
                # (evaluate ignora las vacías). Las *_detectado son lo que extrajo el sistema, como referencia.
                w.writerow(["file", "udc", "title", "date", "language", "item_type",
                            "title_detectado", "date_detectado", "language_detectado", "item_type_detectado"])
            f = r["fields"]
            w.writerow([r["file"], gold_final, "", "", "", "",
                        f.get("title", {}).get("value", ""), f.get("date", {}).get("value", ""),
                        r["doc_language"], r["item_type"]["value"]])
        print(f"  ✔ guardado ({fb.count()} confirmaciones)")
    if auto:
        print(f"\n{auto} documentos guardados desde {ans_p.name}")
    info = fb.train_reranker()
    print("Reranker:", json.dumps(info, ensure_ascii=False))


def cmd_train(a):
    print(json.dumps(Feedback().train_reranker(), ensure_ascii=False, indent=2))


def cmd_evaluate(a):
    tree = Tree.load(config.UDC_RDF, config.LABEL_LANGS)
    res = json.loads(Path(a.results).read_text(encoding="utf-8"))
    m = evaluate(res, load_gold(a.gold), tree)
    print(json.dumps(m, ensure_ascii=False, indent=2))
    Path(a.out).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_sample(a):
    """Plan de muestra estratificada: tipo x idioma x (con/sin identificador) x (escaneado)."""
    from collections import defaultdict
    from .pdfio import read_pdf
    from .metadata import detect_doctype, detect_language, find_identifiers
    clf = None
    if a.topics:
        tree, emb, idx = _load(a.model)
        clf = Classifier(tree, idx, emb)
    rows = []
    for p in _pdfs(a.paths):
        try:
            d = read_pdf(p, ocr=False)
        except Exception as e:  # noqa: BLE001
            print("ERROR", p.name, e)
            continue
        txt = "\n".join(d.head_text)
        ids = find_identifiers(txt + "\n".join(d.tail_text))
        typ = detect_doctype("\n".join(d.head_text[:2]), ids, d.n_pages)[0]
        lang = detect_language(txt)[0] or "?"
        topic = "?"
        if clf:
            rec = build_record(d)
            s = clf.suggest(build_views(d, rec), {"item_type": typ, "lang": (lang, 0)})["suggestions"]
            topic = s[0]["main"][0]["code"][:1] if s else "?"
        rows.append({"file": str(p), "tipo": typ, "idioma": lang, "con_id": bool(ids), "escaneado": d.scanned,
                     "tema": topic, "paginas": d.n_pages})
    groups = defaultdict(list)
    for r in rows:
        groups[(r["tipo"], r["idioma"], r["con_id"], r["escaneado"], r["tema"])].append(r)
    keys = sorted(groups, key=lambda k: (len(groups[k]), k))
    picked = []
    while len(picked) < min(a.n, len(rows)) and any(groups.values()):
        for k in keys:
            if groups[k] and len(picked) < a.n:
                picked.append(groups[k].pop(0))
    with open(a.out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(picked)
    print(f"{len(rows)} PDF analizados; muestra de {len(picked)} en {a.out}")
    from collections import Counter
    for col in ("tipo", "idioma", "con_id", "escaneado", "tema"):
        print(f"  {col}: {dict(Counter(r[col] for r in picked))}")


def main():
    ap = argparse.ArgumentParser(prog="udcpoc", description="PoC de clasificación UDC (sin LLM por defecto)")
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("index", help="carga el RDF, muestra estadísticas y construye el índice de embeddings")
    s.add_argument("--model"); s.add_argument("--force", action="store_true"); s.set_defaults(f=cmd_index)
    s = sp.add_parser("tree", help="inspecciona el árbol cargado")
    s.add_argument("--kind"); s.add_argument("--grep"); s.add_argument("--limit", type=int, default=80); s.set_defaults(f=cmd_tree)
    s = sp.add_parser("validate", help="valida una notación UDC")
    s.add_argument("notation"); s.set_defaults(f=cmd_validate)
    s = sp.add_parser("sample", help="propone una muestra estratificada de PDF")
    s.add_argument("paths", nargs="+"); s.add_argument("--n", type=int, default=28)
    s.add_argument("--topics", action="store_true"); s.add_argument("--model")
    s.add_argument("--out", default=str(config.OUTPUT_DIR / "sample_plan.csv")); s.set_defaults(f=cmd_sample)
    s = sp.add_parser("run", help="procesa PDF y genera results.json")
    s.add_argument("paths", nargs="*"); s.add_argument("--out", default=str(config.OUTPUT_DIR / "results.json"))
    s.add_argument("--plan", help="CSV de 'sample' con la columna 'file' (en lugar de rutas)")
    s.add_argument("--limit", type=int); s.add_argument("--resume", action="store_true")
    s.add_argument("--ocr", action="store_true"); s.add_argument("--ner", action="store_true")
    s.add_argument("--verify", action="store_true"); s.add_argument("--llm", action="store_true")
    s.add_argument("--offline", action="store_true",
                   help="no consultar catálogos por ISBN/DOI/arXiv (por defecto sí; ver config.ENRICH_ONLINE)")
    s.add_argument("--model"); s.set_defaults(f=cmd_run)
    s = sp.add_parser("review", help="revisión interactiva: confirma/corrige y alimenta el aprendizaje")
    s.add_argument("results", nargs="?", default=str(config.OUTPUT_DIR / "results.json"))
    s.add_argument("--gold", default=str(config.OUTPUT_DIR / "gold.csv"))
    s.add_argument("--blind", action="store_true", help="primero tu UDC a ciegas (para un gold sin sesgo)")
    s.add_argument("--answers", default=str(config.GOLD_ANSWERS),
                   help="CSV (file, udc) con tus UDC ya decididas: con --blind se usan sin preguntar; "
                        "'' para desactivar")
    s.set_defaults(f=cmd_review)
    s = sp.add_parser("train", help="reentrena el reranker con las confirmaciones"); s.set_defaults(f=cmd_train)
    s = sp.add_parser("evaluate", help="métricas contra gold.csv")
    s.add_argument("results", nargs="?", default=str(config.OUTPUT_DIR / "results.json"))
    s.add_argument("--gold", default=str(config.OUTPUT_DIR / "gold.csv"))
    s.add_argument("--out", default=str(config.OUTPUT_DIR / "metrics.json")); s.set_defaults(f=cmd_evaluate)
    a = ap.parse_args()
    sys.exit(a.f(a) or 0)
