"""Verificación OPCIONAL contra catálogos abiertos. Nunca sobrescribe: solo anota 'verificado' o 'conflicto'
y propone valores para campos que estén VACÍOS. Solo aplica a tipos que viven en catálogos (config.VERIFY_TYPES).
SIN PROBAR en el entorno de desarrollo (sin red): revisar en la primera ejecución real."""
from __future__ import annotations

import config
from .metadata import similar


def _crossref(title, author_last):
    import httpx
    params = {"query.bibliographic": f"{title} {author_last or ''}".strip(), "rows": 3,
              "select": "title,author,issued,DOI,container-title,publisher"}
    if config.CROSSREF_MAILTO:
        params["mailto"] = config.CROSSREF_MAILTO
    r = httpx.get("https://api.crossref.org/works", params=params, timeout=20)
    r.raise_for_status()
    best = None
    for it in r.json().get("message", {}).get("items", []):
        t = (it.get("title") or [""])[0]
        s = similar(title, t)
        if not best or s > best[0]:
            best = (s, it, t)
    return best


def _openlibrary(title, author_last):
    import httpx
    r = httpx.get("https://openlibrary.org/search.json", params={"title": title, "author": author_last or "", "limit": 3,
                  "fields": "title,author_name,first_publish_year,publisher,isbn,language"}, timeout=20)
    r.raise_for_status()
    best = None
    for d in r.json().get("docs", []):
        s = similar(title, d.get("title", ""))
        if not best or s > best[0]:
            best = (s, d, d.get("title", ""))
    return best


def verify_record(rec: dict) -> dict:
    typ = rec["item_type"]["value"]
    f = rec["fields"]
    if typ not in config.VERIFY_TYPES or "title" not in f:
        return {"status": "no_aplica", "motivo": f"tipo '{typ}' sin catálogo abierto o sin título"}
    title = f["title"]["value"]
    last = (f.get("creators", {}).get("value") or [{}])[0].get("lastName")
    try:
        if typ == "book":
            best = _openlibrary(title, last)
            src = "openlibrary"
        else:
            best = _crossref(title, last)
            src = "crossref"
    except Exception as e:  # noqa: BLE001
        return {"status": "error_red", "motivo": str(e)[:120]}
    if not best:
        return {"status": "sin_resultados", "source": src}
    sim, item, remote_title = best
    status = "verificado" if sim >= config.VERIFY_MIN_SIM else "conflicto" if sim < config.VERIFY_CONFLICT_SIM else "dudoso"
    out = {"status": status, "source": src, "similitud_titulo": round(sim, 2), "titulo_remoto": remote_title,
           "relleno_sugerido": {}}
    if status == "verificado":  # solo propone para campos vacíos
        if src == "crossref":
            cand = {"DOI": item.get("DOI"), "publisher": item.get("publisher"),
                    "publicationTitle": (item.get("container-title") or [None])[0],
                    "date": str((item.get("issued", {}).get("date-parts") or [[None]])[0][0] or "")}
        else:
            cand = {"date": str(item.get("first_publish_year") or ""), "publisher": (item.get("publisher") or [None])[0],
                    "ISBN": (item.get("isbn") or [None])[0]}
        out["relleno_sugerido"] = {k: v for k, v in cand.items() if v and k not in f and k in
                                   config.ZOTERO_ITEM_TYPES.get(typ, [])}
    return out
