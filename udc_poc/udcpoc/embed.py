"""Embeddings locales (CPU) y el índice del árbol UDC."""
from __future__ import annotations
import hashlib
import json
import re
import unicodedata
from pathlib import Path

import numpy as np


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


class Embedder:
    """name='dummy' => vectores hash léxicos (solo para pruebas sin descargar modelos)."""

    def __init__(self, name: str, device: str = "cpu"):
        self.name = name
        self.dummy = name == "dummy"
        if self.dummy:
            self.dim = 512
            return
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(name, device=device)
        self.model.max_seq_length = 512
        self.dim = self.model.get_sentence_embedding_dimension()
        self.e5 = "e5" in name.lower()

    def encode(self, texts: list[str], role: str = "passage", batch_size: int = 16, progress: bool = False):
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        if self.dummy:
            return np.stack([self._hash(t) for t in texts])
        if self.e5:
            texts = [("query: " if role == "query" else "passage: ") + t for t in texts]
        v = self.model.encode(texts, batch_size=batch_size, normalize_embeddings=True,
                              show_progress_bar=progress, convert_to_numpy=True)
        return v.astype(np.float32)

    def _hash(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in re.findall(r"[a-z0-9]+", strip_accents(text).lower()):
            if len(w) < 3:
                continue
            h = int(hashlib.md5(w[:5].encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0 if (h >> 20) & 1 else -1.0
        n = np.linalg.norm(v)
        return v / n if n else v


def normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


class UDCIndex:
    """Embeddings de todos los nodos no-rango del árbol (texto = ruta jerárquica + sinónimos + nota)."""

    def __init__(self, tree, uris: list[str], emb: np.ndarray):
        self.tree, self.uris, self.emb = tree, uris, emb
        self.pos = {u: i for i, u in enumerate(uris)}

    @classmethod
    def load_or_build(cls, tree, embedder: Embedder, cache_root: Path, force=False, progress=True):
        slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", embedder.name)
        d = Path(cache_root) / slug
        d.mkdir(parents=True, exist_ok=True)
        meta_p, emb_p = d / "meta.json", d / "emb.npy"
        fp = tree.fingerprint()
        if not force and meta_p.exists() and emb_p.exists():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            if meta.get("fingerprint") == fp:
                return cls(tree, meta["uris"], np.load(emb_p))
        nodes = tree.indexable()
        emb = embedder.encode([tree.node_text(n) for n in nodes], role="passage", progress=progress)
        uris = [n.uri for n in nodes]
        np.save(emb_p, emb)
        meta_p.write_text(json.dumps({"fingerprint": fp, "uris": uris, "model": embedder.name}), encoding="utf-8")
        return cls(tree, uris, emb)
