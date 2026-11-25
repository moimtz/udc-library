"""Aprendizaje por recuerdo: cada confirmación se guarda como ejemplo; los vecinos votan y un
reranker ligero (regresión logística) aprende cuánto pesar cada señal. No se reentrena ningún modelo grande."""
from __future__ import annotations
import json
import pickle
import sqlite3
import time
from pathlib import Path

import numpy as np

import config

FEATURES = ["sim", "path", "parent", "depth", "knn", "flat", "beam", "see_also"]


class Feedback:
    def __init__(self, path=None):
        self.path = Path(path or config.FEEDBACK_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path))
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS docs(sha1 TEXT PRIMARY KEY, path TEXT, title TEXT, emb BLOB, notation TEXT,
            main_codes TEXT, aux TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, sha1 TEXT, candidates TEXT,
            suggested TEXT, chosen_rank INTEGER, ts REAL);
        """)

    def count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]

    def add(self, sha1, path, title, emb, notation, main_codes, aux, candidates, suggested, rank):
        """rank: 1..3 = aceptó esa sugerencia; 0 = escribió la suya."""
        ts = time.time()
        self.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?,?,?)",
                        (sha1, str(path), title or "", np.asarray(emb, dtype=np.float32).tobytes(), notation,
                         json.dumps(main_codes), json.dumps(aux), ts))
        self.db.execute("DELETE FROM events WHERE sha1=?", (sha1,))
        self.db.execute("DELETE FROM events WHERE sha1=?", (sha1,))   # revisar de nuevo reemplaza, no duplica
        self.db.execute("INSERT INTO events(sha1,candidates,suggested,chosen_rank,ts) VALUES(?,?,?,?,?)",
                        (sha1, json.dumps(candidates), json.dumps(suggested), rank, ts))
        self.db.commit()

    def neighbors(self, emb, k=None, min_sim=None, exclude_sha=None) -> list[tuple[float, list[str]]]:
        k = k or config.KNN_K
        min_sim = config.KNN_MIN_SIM if min_sim is None else min_sim
        rows = self.db.execute("SELECT sha1, emb, main_codes FROM docs").fetchall()
        out = []
        for sha, blob, codes in rows:
            if sha == exclude_sha:
                continue
            sim = float(np.dot(np.frombuffer(blob, dtype=np.float32), emb))
            if sim >= min_sim:
                out.append((sim, json.loads(codes)))
        return sorted(out, key=lambda x: -x[0])[:k]

    # ---- reranker
    def training_set(self):
        X, y = [], []
        for cands, sha in self.db.execute("SELECT e.candidates, e.sha1 FROM events e"):
            confirmed = set(json.loads(self.db.execute("SELECT main_codes FROM docs WHERE sha1=?", (sha,)).fetchone()[0]))
            cands = json.loads(cands)
            if not any(c["code"] in confirmed for c in cands):
                continue  # sin positivo entre los candidatos: no aporta al reranker (sí al kNN)
            for c in cands:
                X.append([c["feats"].get(f, 0.0) for f in FEATURES])  # confirmaciones antiguas: sin "see_also"
                y.append(1 if c["code"] in confirmed else 0)
        return np.array(X, dtype=float), np.array(y, dtype=int)

    def train_reranker(self) -> dict:
        n = self.count()
        if n < config.RERANKER_MIN_EVENTS:
            return {"trained": False, "razon": f"{n} confirmaciones (mínimo {config.RERANKER_MIN_EVENTS})"}
        X, y = self.training_set()
        if y.sum() < 5 or y.sum() == len(y):
            return {"trained": False, "razon": "pocos positivos utilizables"}
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        model = make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))
        model.fit(X, y)
        with open(config.RERANKER_PATH, "wb") as fh:
            pickle.dump({"model": model, "features": FEATURES}, fh)
        coefs = dict(zip(FEATURES, np.round(model[-1].coef_[0], 3).tolist()))
        return {"trained": True, "ejemplos": int(len(y)), "positivos": int(y.sum()), "coeficientes": coefs}


class Reranker:
    def __init__(self, model):
        self.model = model

    @classmethod
    def load(cls):
        p = Path(config.RERANKER_PATH)
        if not p.exists():
            return None
        try:
            with open(p, "rb") as fh:
                d = pickle.load(fh)
            return cls(d["model"]) if d.get("features") == FEATURES else None
        except Exception:  # noqa: BLE001
            return None

    def score(self, X: np.ndarray) -> np.ndarray:
        return self.model.decision_function(X)  # logit
