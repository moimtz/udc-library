"""Módulo OPCIONAL (apagado por defecto). Endpoint compatible con OpenAI/Ollama.
Solo se usa para metadatos difíciles, por lotes, y SOLO rellena campos ausentes. SIN PROBAR aquí."""
from __future__ import annotations
import json
import re

import config

PROMPT = ("Extrae metadatos bibliográficos del texto de las primeras páginas de un documento. "
          "Responde SOLO un objeto JSON con las claves: title, creators (lista de 'Nombre Apellido'), date, publisher, "
          "abstractNote. Si un dato NO aparece explícitamente en el texto, usa null. No inventes nada.")


def llm_fill(front_text: str, rec: dict) -> dict:
    import httpx
    r = httpx.post(f"{config.LLM_BASE_URL}/chat/completions", timeout=300, json={
        "model": config.LLM_MODEL, "temperature": 0,
        "messages": [{"role": "system", "content": PROMPT},
                     {"role": "user", "content": front_text[:config.LLM_MAX_CHARS]}]})
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    data = json.loads(m.group(0)) if m else {}
    from .metadata import name_to_creator
    added = []
    for k, v in data.items():
        if not v or k in rec["fields"] or k not in config.ZOTERO_ITEM_TYPES[rec["item_type"]["value"]]:
            continue
        if k == "creators":
            v = [name_to_creator(n) for n in v if isinstance(n, str)]
        rec["fields"][k] = {"value": v, "source": "llm", "confidence": 0.4}
        added.append(k)
    return {"campos_añadidos": added}
