"""Servicio local del clasificador para el servidor de la biblioteca:  python -m udcpoc serve

Corre en el mismo PC que el servidor y escucha solo en 127.0.0.1 (config.SERVICE_HOST/PORT). Carga
el modelo con el primer análisis y lo libera tras SERVICE_IDLE_MINUTES sin uso (--idle; 0 = cargarlo al
arrancar y no liberarlo). Atiende una cola: un trabajo a la vez, porque la CPU es compartida. HTTP + JSON:

  GET  /health          {ready, loaded, error, queue}
  POST /jobs            {path, name, meta}            -> 202 {job}    analizar un PDF (meta vuelve tal cual;
                                                                      name = nombre original del archivo)
  POST /learn           {sha256, notation, title, file} -> 202 {job}  aprender la UDC que guardó una persona
  GET  /jobs/<id>       {status: queued|running|done|error, position, loading, result | error, meta}

- OCR solo si el PDF es escaneado (sin capa de texto útil).
- Cada análisis deja data/service_cache/<sha256>.json (embedding y candidatos): /learn lo necesita para
  añadir el ejemplo a feedback.db sin volver a leer el PDF. Un PDF nunca analizado no se aprende.
- Los trabajos terminados se olvidan a la hora (JOB_TTL).
"""
from __future__ import annotations

import base64
import gc
import hashlib
import json
import queue
import re
import shutil
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import numpy as np

import config

JOB_TTL = 3600
MAX_BODY = 64 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}")


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.q: queue.Queue = queue.Queue()
        self.ready = False
        self.loaded = False                    # el modelo está en memoria (ver _worker y SERVICE_IDLE_MINUTES)
        self.error: str | None = None


S = _State()


# --------------------------------------------------------------------------- trabajos
def _new_job(kind: str, payload: dict, meta: dict) -> str:
    jid = uuid.uuid4().hex[:16]
    with S.lock:
        cut = time.time() - JOB_TTL
        for k in [k for k, j in S.jobs.items() if j["status"] in ("done", "error") and j["ended"] < cut]:
            del S.jobs[k]
        S.jobs[jid] = {"id": jid, "kind": kind, "status": "queued", "meta": meta, "created": time.time(),
                       "ended": 0.0}
    S.q.put((jid, payload))
    return jid


def _position(job: dict) -> int:
    """1 = el siguiente. 0 si ya corre o terminó. Llamar con S.lock tomado."""
    if job["status"] != "queued":
        return 0
    ahead = sum(1 for j in S.jobs.values()
                if j["status"] == "running" or (j["status"] == "queued" and j["created"] < job["created"]))
    return ahead + 1


def _pending() -> int:
    with S.lock:
        return sum(1 for j in S.jobs.values() if j["status"] in ("queued", "running"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _analyze(src: Path, name: str, clf, jid: str) -> dict:
    """Analiza una copia con el nombre original: el nombre es pista de título/autores (los PDF subidos
    llegan con un nombre aleatorio) y el servidor puede mover el suyo mientras tanto (Windows bloquea
    los archivos abiertos)."""
    if not src.is_file():
        raise ValueError("the file is gone (saved or discarded before the analysis started)")
    name = Path(name or src.name).name
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    work = config.SERVICE_CACHE.parent / "service_tmp" / jid
    work.mkdir(parents=True, exist_ok=True)
    try:
        path = work / name
        shutil.copyfile(src, path)
        return _analyze_copy(path, clf)
    finally:
        shutil.rmtree(work, ignore_errors=True)


_ocr_pool = None


def _read_with_ocr(path: Path):
    """read_pdf(ocr=True) en un proceso aparte: el OCR de PyMuPDF (Tesseract) no suelta el GIL y congela
    todo el proceso hasta ~25 s por página, así que el servicio dejaba de contestar y el servidor daba el
    análisis por perdido. Un proceso hijo persistente (se crea la primera vez; se rehace si muere)."""
    global _ocr_pool
    from concurrent.futures import ProcessPoolExecutor
    from concurrent.futures.process import BrokenProcessPool
    from .pdfio import read_pdf
    for attempt in (1, 2):
        if _ocr_pool is None:
            _ocr_pool = ProcessPoolExecutor(max_workers=1)
        try:
            return _ocr_pool.submit(read_pdf, str(path), True).result()
        except BrokenProcessPool:
            _ocr_pool = None
            if attempt == 2:
                raise


def _analyze_copy(path: Path, clf) -> dict:
    from .cli import process
    from .pdfio import read_pdf
    pdf = read_pdf(path, ocr=False)
    if pdf.scanned:
        pdf = _read_with_ocr(path)              # OCR solo cuando hace falta
    args = SimpleNamespace(ocr=pdf.ocr_used, ner=False, offline=False, verify=False, llm=False)
    rec = process(path, clf, args, pdf=pdf)
    sha256 = _sha256(path)
    cl = rec["classification"]
    cache = {"sha1": rec["sha1"], "sha256": sha256, "file": path.name,
             "title": rec["fields"].get("title", {}).get("value", ""),
             "emb": cl.pop("_doc_embedding", None), "candidates": cl.pop("_candidates", []),
             "suggested": [s["udc"] for s in cl.get("suggestions", [])], "ts": time.time()}
    config.SERVICE_CACHE.mkdir(parents=True, exist_ok=True)
    (config.SERVICE_CACHE / f"{sha256}.json").write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    rec["sha256"] = sha256
    return rec


def _learn(p: dict, tree, fb, clf) -> dict:
    """Como `review`: la UDC guardada por una persona se vuelve ejemplo (kNN) y reentrena el reranker."""
    from .feedback import Reranker
    from .notation import components, validate
    sha256 = str(p.get("sha256") or "").lower()
    notation = str(p.get("notation") or "").strip()
    if not SHA256.fullmatch(sha256):
        raise ValueError("sha256 no válido")
    f = config.SERVICE_CACHE / f"{sha256}.json"
    if not f.exists():
        return {"learned": False, "reason": "not analysed"}
    c = json.loads(f.read_text(encoding="utf-8"))
    if not c.get("emb"):
        return {"learned": False, "reason": "no text to learn from"}
    bad = [m for lv, m in validate(notation, tree) if lv == "error"]
    if bad:
        return {"learned": False, "reason": "invalid notation: " + "; ".join(bad)}
    row = fb.db.execute("SELECT notation FROM docs WHERE sha1=?", (c["sha1"],)).fetchone()
    if row and row[0] == notation:
        return {"learned": False, "reason": "already learned"}

    def bare(s):
        return re.sub(r"\s", "", s)

    same = [i for i, s in enumerate(c["suggested"], 1) if bare(s) == bare(notation)]
    rank = same[0] if same else 0                       # 1..3 = era una sugerencia; 0 = otra
    comp = components(notation)
    emb = np.frombuffer(base64.b64decode(c["emb"]), dtype=np.float32)
    fb.add(c["sha1"], p.get("file") or c["file"], p.get("title") or c["title"], emb, notation,
           comp.get("main", []), {k: comp.get(k, []) for k in ("lang", "form", "place", "time")},
           c["candidates"], c["suggested"], rank)
    info = fb.train_reranker()
    if info.get("trained"):
        clf.reranker = Reranker.load()
    return {"learned": True, "rank": rank, "examples": fb.count(), "reranker": info}


def _load_model(model) -> SimpleNamespace:
    """Árbol, modelo de embeddings, índice y feedback.db (~40 s, ~3-4 GB)."""
    from .classify import Classifier
    from .cli import _load
    from .feedback import Feedback, Reranker
    t0 = time.time()
    tree, emb, idx = _load(model)
    fb = Feedback()
    clf = Classifier(tree, idx, emb, feedback=fb, reranker=Reranker.load())
    print(f"Modelo cargado ({time.time() - t0:.0f} s, {fb.count()} ejemplos aprendidos).")
    return SimpleNamespace(tree=tree, fb=fb, clf=clf)


def _worker(a) -> None:
    """Procesa la cola. Todo (incluida la conexión a feedback.db) vive en este hilo.

    Con a.idle > 0 el modelo se carga con el primer trabajo y se libera tras a.idle minutos sin trabajos
    (la RAM vuelve al sistema; el siguiente análisis tarda ~40 s más). Con 0 se carga al arrancar y se queda."""
    idle = max(0.0, float(getattr(a, "idle", config.SERVICE_IDLE_MINUTES) or 0)) * 60
    m = None
    try:
        from . import classify, feedback  # noqa: F401  (una instalación rota se ve al arrancar, no al primer clic)
        if not idle:
            m = _load_model(a.model)
    except Exception as e:  # noqa: BLE001
        S.error = f"{type(e).__name__}: {e}"
        print("No se pudo cargar el clasificador:", S.error)
        return
    S.ready, S.loaded = True, m is not None
    print("Clasificador listo." + (f" El modelo se carga con el primer análisis y se libera tras "
                                   f"{idle / 60:g} min sin uso." if idle else ""))
    last = time.time()
    while True:
        try:
            jid, payload = S.q.get(timeout=30)
        except queue.Empty:
            if m is not None and idle and time.time() - last > idle:
                m = None
                S.loaded = False
                gc.collect()
                print(f"Modelo liberado tras {idle / 60:g} min sin uso.")
            continue
        with S.lock:
            job = S.jobs.get(jid)
            if job is None:
                continue
            job["status"] = "running"
        t0 = time.time()
        try:
            if m is None:
                with S.lock:
                    job["loading"] = True
                try:
                    m = _load_model(a.model)
                    S.loaded = True
                finally:
                    with S.lock:
                        job.pop("loading", None)
            if job["kind"] == "analyze":
                out = {"result": _analyze(Path(payload["path"]), payload.get("name", ""), m.clf, jid)}
            else:
                out = {"result": _learn(payload, m.tree, m.fb, m.clf)}
            status = "done"
        except Exception as e:  # noqa: BLE001
            status, out = "error", {"error": f"{type(e).__name__}: {e}"}
        last = time.time()
        secs = round(last - t0, 1)
        with S.lock:
            job.update(status=status, ended=time.time(), seconds=secs, **out)
        what = Path(payload.get("path") or payload.get("file") or "").name
        print(f"[{job['kind']}] {what}  {status}  ({secs} s)" + (f"  {out['error']}" if status == "error" else ""))


# --------------------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    server_version = "udcpoc"

    def log_message(self, *args):          # sin una línea por petición (el servidor consulta cada 2 s)
        pass

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"ready": S.ready, "loaded": S.loaded, "error": S.error, "queue": _pending()})
        m = re.fullmatch(r"/jobs/([0-9a-f]{16})", self.path)
        if not m:
            return self._send(404, {"error": "not found"})
        with S.lock:
            job = S.jobs.get(m.group(1))
            if job is None:
                return self._send(404, {"error": "unknown or expired job"})
            out = {k: v for k, v in job.items() if k not in ("created", "ended")}
            out["position"] = _position(job)
        self._send(200, out)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                return self._send(413, {"error": "body too large"})
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._send(400, {"error": "invalid JSON"})
        if S.error:
            return self._send(503, {"error": f"the classifier could not start: {S.error}"})
        if self.path == "/jobs":
            path = str(body.get("path") or "")
            if not path or not Path(path).is_file():
                return self._send(400, {"error": "file not found"})
            meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
            payload = {"path": path, "name": str(body.get("name") or "")}
            return self._send(202, {"job": _new_job("analyze", payload, meta)})
        if self.path == "/learn":
            return self._send(202, {"job": _new_job("learn", body, {})})
        self._send(404, {"error": "not found"})


def serve(a) -> None:
    threading.Thread(target=_worker, args=(a,), daemon=True).start()
    httpd = ThreadingHTTPServer((a.host, a.port), _Handler)
    print(f"Clasificador en http://{a.host}:{a.port}  Ctrl+C para salir")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
