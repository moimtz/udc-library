"""Métricas: acierto por nivel, notación completa, top-3, cada tabla auxiliar y campos."""
from __future__ import annotations
import csv
import json
import re
from pathlib import Path

from .metadata import similar
from .notation import components


def _norm_name(s):
    return Path(s).name.lower()


def load_gold(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return {_norm_name(r["file"]): r for r in csv.DictReader(fh) if r.get("file")}


def _chain(tree, code):
    n = tree.get(code)
    return [x.notation for x in tree.path(n) if x.kind == "main"] if n else []


def evaluate(results: list[dict], gold: dict, tree) -> dict:
    m = {"n": 0, "main_top1": 0, "main_top3": 0, "udc_exact_top1": 0, "nivel": {}, "aux": {}, "campos": {}}
    auxk = {"lang": "lang", "form": "form", "place": "place", "time": "time"}
    for r in results:
        g = gold.get(_norm_name(r["file"]))
        if not g or not g.get("udc"):
            continue
        sugg = r["classification"]["suggestions"]
        if not sugg:
            m["n"] += 1
            continue
        m["n"] += 1
        gc = components(g["udc"])
        gm = set(gc.get("main", []))
        pm = lambda s: set(components(s["udc"]).get("main", []))
        hit1 = pm(sugg[0]) == gm
        m["main_top1"] += hit1
        m["main_top3"] += any(pm(s) == gm for s in sugg)
        m["udc_exact_top1"] += re.sub(r"\s", "", sugg[0]["udc"]) == re.sub(r"\s", "", g["udc"])
        # nivel de profundidad (primera clase principal)
        gl = _chain(tree, next(iter(gc.get("main", [])), ""))
        pl = _chain(tree, components(sugg[0]["udc"]).get("main", [""])[0])
        for i, code in enumerate(gl):
            d = m["nivel"].setdefault(i + 1, [0, 0])
            d[1] += 1
            d[0] += int(i < len(pl) and pl[i] == code)
        pc = components(sugg[0]["udc"])
        for k, kind in auxk.items():
            a = m["aux"].setdefault(k, {"gold": 0, "pred": 0, "ok": 0})
            gs, ps = set(gc.get(kind, [])), set(pc.get(kind, []))
            a["gold"] += bool(gs)
            a["pred"] += bool(ps)
            a["ok"] += bool(gs) and gs == ps
        # campos
        f = r["fields"]
        def chk(name, ok, present):
            d = m["campos"].setdefault(name, {"gold": 0, "pred": 0, "ok": 0})
            d["gold"] += 1
            d["pred"] += present
            d["ok"] += ok
        if g.get("title"):
            tv = f.get("title", {}).get("value", "")
            chk("title", similar(tv, g["title"]) >= 0.85, bool(tv))
        if g.get("date"):
            dv = str(f.get("date", {}).get("value", ""))
            chk("date(año)", bool(dv) and dv[:4] == g["date"][:4], bool(dv))
        if g.get("language"):
            lv = f.get("language", {}).get("value", "")
            chk("language", lv == g["language"], bool(lv))
        if g.get("item_type"):
            chk("item_type", r["item_type"]["value"] == g["item_type"], True)
    n = max(1, m["n"])
    out = {"documentos_evaluados": m["n"],
           "clase_principal_top1": round(m["main_top1"] / n, 3), "clase_principal_top3": round(m["main_top3"] / n, 3),
           "notacion_completa_top1": round(m["udc_exact_top1"] / n, 3),
           "acierto_por_nivel": {f"nivel_{k}": f"{v[0]}/{v[1]}" for k, v in sorted(m["nivel"].items())},
           "tablas_auxiliares": {k: {"en_gold": v["gold"], "propuestas": v["pred"], "correctas": v["ok"]} for k, v in m["aux"].items()},
           "campos": {k: {"con_gold": v["gold"], "extraidos": v["pred"], "correctos": v["ok"]} for k, v in m["campos"].items()}}
    return out
