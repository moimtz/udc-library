"""Clasificación UDC: recuperación por embeddings + búsqueda en haz sobre el árbol + vecinos confirmados +
reranker opcional + composición con tablas auxiliares + validación determinista. Sin LLM."""
from __future__ import annotations
import base64
import math
import re

import numpy as np

import config
from . import auxtables as auxmod
from .embed import normalize
from .feedback import FEATURES
from .notation import compose, validate


def _softmax(x, t):
    x = np.asarray(x, dtype=float) / t
    x = np.exp(x - x.max())
    return x / x.sum()


class Classifier:
    def __init__(self, tree, index, embedder, feedback=None, reranker=None):
        self.tree, self.index, self.embedder = tree, index, embedder
        self.feedback, self.reranker = feedback, reranker
        self.places = auxmod.PlaceFinder(tree)
        self.main_nodes = [n for n in tree.of_kind("main") if n.uri in index.pos]
        self.main_idx = np.array([index.pos[n.uri] for n in self.main_nodes])

    # ------------------------------------------------------------ utilidades
    def _lbl(self, n):
        return n.label(self.tree.label_langs)

    def _sim_fn(self, sim):
        pos = self.index.pos
        # nodos no indexados (p. ej. sin etiqueta) puntúan -1 en vez de romper el beam search
        return lambda n: float(sim[pos[n.uri]]) if n.uri in pos else -1.0

    def _see_also_candidates(self, uris, sim_of) -> dict:
        """{uri nueva: nodo que la enlaza}. Solo destinos de la tabla principal (su puntuación usa la cadena de clases
        principales); los auxiliares enlazados se muestran en "ver_tambien" pero no compiten."""
        t = self.tree
        if config.SEE_ALSO_FROM <= 0:
            return {}
        top = sorted((t.nodes[u] for u in uris), key=lambda n: -sim_of(n))[:config.SEE_ALSO_FROM]
        via = {}
        for n in top:
            src = t.nodes[n.host] if n.origin == "example" else n
            for r in t.see_also(src):
                if r.kind == "main" and not r.is_range and r.uri not in via and r.uri in self.index.pos:
                    via[r.uri] = src
        return via

    def _see_also_list(self, n, sim_of) -> list:
        """Clases "See also" de la sugerencia (o de su anfitrión, si es un ejemplo), ordenadas por similitud."""
        t = self.tree
        src = t.nodes[n.host] if n.origin == "example" else n
        rel = [(r, sim_of(r)) for r in t.see_also(src)]
        rel.sort(key=lambda x: -x[1])
        return [{"code": r.notation, "label": self._lbl(r), "sim": round(s, 3) if s > -1 else None}
                for r, s in rel[:config.SEE_ALSO_MAX]]

    def _beam(self, sim_of):
        t = self.tree
        roots = t.roots("main")
        frontier = sorted([([r], sim_of(r)) for r in roots], key=lambda x: -x[1])[:config.BEAM_WIDTH]
        found = {}
        for _ in range(config.MAX_DEPTH):
            nxt = []
            for path, sc in frontier:
                found[path[-1].uri] = max(found.get(path[-1].uri, -9), sc)
                for ch in t.real_children(path[-1], "main"):
                    s = [sim_of(x) for x in path + [ch]]
                    nxt.append((path + [ch], 0.5 * s[-1] + 0.5 * float(np.mean(s))))
            if not nxt:
                break
            frontier = sorted(nxt, key=lambda x: -x[1])[:config.BEAM_WIDTH]
        return found

    def _knn_votes(self, neighbors):
        """Devuelve f(node) -> voto en [0,1] según los vecinos ya confirmados."""
        t = self.tree
        parsed = []
        for sim, codes in neighbors:
            nodes = [t.get(c) for c in codes if t.get(c)]
            if nodes:
                parsed.append((sim ** 4, nodes))
        total = sum(w for w, _ in parsed) or 1.0

        def vote(node):
            v = 0.0
            for w, nodes in parsed:
                rel = 0.0
                for m in nodes:
                    rel = max(rel, 1.0 if m.uri == node.uri else 0.5 if t.is_related(node, m) else 0.0)
                v += w * rel
            return v / total
        return vote

    def _emb_aux(self, kind, nodes, sim_of):
        vals = sorted(((sim_of(n), n) for n in nodes if n.uri in self.index.pos), key=lambda x: -x[0])
        if not vals:
            return None
        best, second = vals[0], (vals[1][0] if len(vals) > 1 else -1.0)
        if best[0] >= config.AUX_MIN_SIM[kind] and best[0] - second >= config.AUX_MARGIN:
            n = best[1]
            return {"code": n.notation, "label": self._lbl(n), "source": "embedding (experimental)",
                    "confidence": round(best[0], 2), "evidence": f"sim={best[0]:.2f}"}
        return None

    def _branch(self, n, level=2):
        """Ancestro 'main' del nivel indicado (nivel 2 = clase de 2 dígitos, p. ej. 53 para 537.3)."""
        chain = [x for x in self.tree.path(n) if x.kind == "main"]
        return chain[min(level, len(chain)) - 1].uri

    def _special_nodes(self, main_node):
        out = []
        for x in self.tree.path(main_node):
            for c in self.tree.real_children(x, "special"):
                out.append(c)
                out.extend(d for d in self.tree.descendants(c) if d.kind == "special" and not d.is_range)
        return out

    # ------------------------------------------------------------ API principal
    def suggest(self, views: dict, ctx: dict, sha: str | None = None, topn: int = 3) -> dict:
        t = self.tree
        want = topn
        names = [n for n in config.VIEW_WEIGHTS if (views.get(n) or "").strip()]
        if not names:
            return {"suggestions": [], "low_confidence": True, "note": "Sin texto utilizable para clasificar.",
                    "mode": None}
        Q = self.embedder.encode([views[n] for n in names], role="query")
        w = np.array([config.VIEW_WEIGHTS[n] for n in names], dtype=float)
        w /= w.sum()
        sim = (self.index.emb @ Q.T) @ w
        qdoc = normalize((Q * w[:, None].astype(np.float32)).sum(0))
        sim_of = self._sim_fn(sim)

        # --- candidatos: top-K plano  U  haz sobre el árbol
        msim = sim[self.main_idx]
        order = np.argsort(-msim)[:config.K_FLAT]
        flat_rank = {self.main_nodes[i].uri: r for r, i in enumerate(order)}
        beam = self._beam(sim_of)
        uris = set(flat_rank) | set(beam)
        # si entra un nodo de ejemplo, su anfitrión también compite (para poder retroceder a él)
        uris |= {t.nodes[u].host for u in list(uris) if t.nodes[u].origin == "example"}
        # "See also": las mejores candidatas aportan sus clases enlazadas de otras ramas (un solo salto)
        via = self._see_also_candidates(uris, sim_of)
        uris |= set(via)

        neighbors = self.feedback.neighbors(qdoc, exclude_sha=sha) if self.feedback else []
        vote = self._knn_votes(neighbors)

        rows = []
        for u in uris:
            n = t.nodes[u]
            chain = [x for x in t.path(n) if x.kind == "main"]
            s = [sim_of(x) for x in chain]
            feats = {"sim": s[-1], "path": float(np.mean(s)), "parent": s[-2] if len(s) > 1 else s[-1],
                     "depth": float(len(chain)), "knn": vote(n),
                     "flat": 1.0 / (1 + flat_rank[u]) if u in flat_rank else 0.0,
                     "beam": 1.0 if u in beam else 0.0,
                     "see_also": 1.0 if u in via else 0.0}
            rows.append((n, {k: float(v) for k, v in feats.items()}))

        mode = "default"
        if self.reranker is not None:
            scores = self.reranker.score(np.array([[f[k] for k in FEATURES] for _, f in rows]))
            mode, temp = "reranker", 1.0
        else:
            W = config.DEFAULT_WEIGHTS
            scores = np.array([W["sim"] * f["sim"] + W["path"] * f["path"] + W["knn"] * f["knn"]
                               + W["depth"] * min(f["depth"], 6) for _, f in rows])
            temp = config.SOFTMAX_TEMP
        order = np.argsort(-scores)
        ranked = [(rows[i][0], rows[i][1], float(scores[i])) for i in order]
        conf_all = _softmax([r[2] for r in ranked[:8]], temp)

        # --- partitura: la 1.ª sugerencia sale de reglas dentro de 78; el resto, solo de la rama 78
        music_sug = None
        if ctx.get("score"):
            from . import music
            info = music.StaffInfo(per_system=int(ctx["score"].get("per_system") or 0))
            music_sug = music.classify(ctx["score"].get("text", ""), info)
            in78 = lambda n: any(x.notation == "78" for x in t.path(n))
            ranked = [r for r in ranked if in78(r[0])]
            conf_all = _softmax([r[2] for r in ranked[:8]], temp) if ranked else []
            topn -= 1

        # --- selección diversa (sin ancestros/descendientes entre sí)
        chosen = []
        for i, (n, f, sc) in enumerate(ranked):
            if f["depth"] < config.MIN_SUGGEST_DEPTH:  # 0-9 solas son demasiado generales
                continue
            if n.origin == "example" and f["sim"] < sim_of(t.nodes[n.host]) + config.EXAMPLE_MARGIN:
                continue  # el ejemplo no supera a su nodo anfitrión: se queda el anfitrión
            if all(not t.is_related(n, c[0]) for c in chosen):
                chosen.append((n, f, sc, float(conf_all[i]) if i < len(conf_all) else 0.0))
            if len(chosen) == topn:
                break

        # --- auxiliares globales (sin LLM)
        lang, lconf = ctx.get("lang") or (None, 0.0)
        glob = {}
        glob["lang"] = auxmod.lang_aux(lang, lconf, t)
        glob["form"] = auxmod.form_aux(ctx.get("item_type", ""), ctx.get("subtype"),
                                       " ".join([ctx.get("title", ""), ctx.get("filename", ""),
                                                 views.get("front", "")])[:3000], t)
        segs = [(ctx.get("title", ""), 5.0), (ctx.get("abstract", "") + " " + ctx.get("tags", ""), 2.0),
                (views.get("toc", ""), 1.5), (views.get("front", ""), 1.0), (views.get("body", ""), 1.0)]
        glob["place"] = self.places.find(segs, lang)
        glob["time"] = auxmod.time_aux(" ".join([ctx.get("abstract", ""), views.get("toc", "")]), t,
                                       title=ctx.get("title", ""))
        glob = {k: v for k, v in glob.items() if v}

        suggestions = []
        # --- UDC de un catálogo bibliotecario (p. ej. Biblioteca Nacional de Polonia, campo MARC 080):
        # es una clasificación hecha por catalogadores; si es válida en este árbol, va primero.
        for code in (ctx.get("external_udc") or {}).get("codes", [])[:2]:
            udc_ext = re.sub(r"[\[\]\s]", "", code)
            issues = validate(udc_ext, t)
            if udc_ext and not any(lv == "error" for lv, _ in issues) and \
                    all(s["udc"] != udc_ext for s in suggestions):
                from .notation import components
                mains_ext = components(udc_ext).get("main", [])
                suggestions.append({
                    "rank": len(suggestions) + 1, "udc": udc_ext,
                    "main": [{"code": c, "label": self._lbl(t.get(c)) if t.get(c) else c, "origin": "catalog",
                              "path": [f"{x.notation} {self._lbl(x)}" for x in t.path(t.get(c))] if t.get(c) else []}
                             for c in mains_ext],
                    "aux": {}, "ver_tambien": [], "score": 1.0, "confidence": config.CATALOG_UDC_CONFIDENCE,
                    "issues": [{"level": lv, "msg": m} for lv, m in issues],
                    "explain": {"sim_node": 1.0, "origen": f"catálogo: {ctx['external_udc']['source']}"},
                })
        if music_sug:
            vocal = music_sug["mains"][0].startswith(("782", "783", "784"))
            # en una partitura el idioma solo cuenta si hay letra (obra vocal); el "tiempo" del texto (año de la
            # edición) y la forma documental no aplican
            maux = {k: v for k, v in glob.items() if k == "place" or (k == "lang" and vocal)}
            udc = compose([{"code": c} for c in music_sug["mains"]],
                          {k: v["code"] for k, v in maux.items() if k in config.AUX_ORDER})
            issues = validate(udc, t)
            if not any(lv == "error" for lv, _ in issues):
                suggestions.append({
                    "rank": len(suggestions) + 1, "udc": udc,
                    "main": [{"code": c, "label": self._lbl(t.get(c)) if t.get(c) else c, "origin": "rules",
                              "path": [f"{x.notation} {self._lbl(x)}" for x in t.path(t.get(c))] if t.get(c) else []}
                             for c in music_sug["mains"]],
                    "aux": maux, "ver_tambien": [], "score": 1.0, "confidence": config.SCORE_RULES_CONFIDENCE,
                    "issues": [{"level": lv, "msg": m} for lv, m in issues],
                    "explain": {"sim_node": 1.0, "origen": "partitura: " + "; ".join(music_sug["evidence"]),
                                "detección": ctx["score"].get("why", "")},
                })
        for n, f, sc, conf in chosen:
            if len(suggestions) >= want:                 # catálogo + partitura + embeddings = `want` en total
                break
            rank = len(suggestions) + 1
            mains = [{"code": n.notation}]
            per = {}
            for kind, nodes in (("special", self._special_nodes(n)), ("common", t.of_kind("common")),
                                ("viewpoint", t.of_kind("viewpoint"))):
                a = self._emb_aux(kind, nodes, sim_of) if nodes else None
                if a:
                    per[kind] = a
                    code = a["code"]
                    if kind == "special":  # se anexa solo el sufijo: 27 + '-55', no 27 + '2-55'
                        code = t.special_suffix(t.get(code))
                    mains[0]["view" if kind == "viewpoint" else kind] = code
            second = None
            if rank == 1 and not ctx.get("title_only"):
                # segundo tema con ':' solo si está casi empatado y es de otra rama desde el 2.º nivel
                for n2, f2, sc2 in ranked:
                    if sc - sc2 > config.SECOND_TOPIC_MAX_GAP:
                        break
                    if n2.uri != n.uri and f2["depth"] >= config.MIN_SUGGEST_DEPTH and \
                            f2["sim"] >= config.MIN_SIM and self._branch(n2) != self._branch(n):
                        second = (n2, f2)
                        mains.append({"code": n2.notation})
                        break
            udc = compose(mains, {k: v["code"] for k, v in glob.items() if k in config.AUX_ORDER})
            issues = validate(udc, t)
            if any(lv == "error" for lv, _ in issues):
                continue
            suggestions.append({
                "rank": rank, "udc": udc,
                "main": [{"code": m["code"], "label": self._lbl(t.get(m["code"])),
                          "origin": t.get(m["code"]).origin or "class",
                          "path": [f"{x.notation} {self._lbl(x)}" for x in t.path(t.get(m["code"]))]} for m in mains],
                "aux": {**glob, **per},
                "ver_tambien": self._see_also_list(n, sim_of),
                "score": round(sc, 3), "confidence": round(conf, 2),
                "issues": [{"level": lv, "msg": m} for lv, m in issues],
                "explain": {"sim_node": round(f["sim"], 3), "sim_path_mean": round(f["path"], 3),
                            "knn_vote": round(f["knn"], 2), "en_haz": bool(f["beam"]), "en_top_plano": bool(f["flat"]),
                            "origen": (f"ejemplo de combinación de {t.nodes[n.host].notation} "
                                       f"{self._lbl(t.nodes[n.host])}" if n.origin == "example" else "clase del árbol"),
                            "via_see_also": (f"{via[n.uri].notation} {self._lbl(via[n.uri])}" if n.uri in via else None),
                            "segundo_tema": (f"{second[0].notation} {self._lbl(second[0])}" if second else None),
                            "retroceder_a": [f"{x.notation} {self._lbl(x)}" for x in t.ancestors(n) if x.kind == "main" and not x.is_range][::-1][:3]},
            })
        top = suggestions[0] if suggestions else None
        low = (top is None or top["confidence"] < config.LOW_CONFIDENCE or top["explain"]["sim_node"] < config.MIN_SIM
               or bool(ctx.get("title_only")))
        cands = [{"code": n.notation, "feats": f} for n, f, _ in ranked[:30]]
        note = "BAJA CONFIANZA: revisa manualmente." if low else ""
        if ctx.get("title_only"):
            note = "SOLO TÍTULO (PDF escaneado sin OCR): sugerencia orientativa. " + note
        return {
            "suggestions": suggestions, "low_confidence": bool(low), "mode": mode,
            "neighbors_used": len(neighbors),
            "note": note,
            "_doc_embedding": base64.b64encode(qdoc.astype(np.float32).tobytes()).decode(),
            "_candidates": cands,
        }
