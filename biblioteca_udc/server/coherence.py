"""Coherence between an item's Zotero type and the form auxiliary (0...) of its UDC notation.

Zotero describes the document and the UDC classifies it; they meet only in the form: a thesis usually
carries (043), a patent (088.8), a standard (083.74). A mismatch is often a typing slip, so it is reported
as a warning, never enforced (UDC does not require a form). Rules: "udc_form_by_type" in zotero_overlay.json.
"""
import functools
import json

import catalog
from library import extra_vars
from notation import tokenize


@functools.lru_cache(maxsize=1)
def rules() -> dict[str, dict]:
    overlay = json.loads(catalog.OVERLAY_PATH.read_text(encoding="utf-8"))
    return {t: r for t, r in overlay.get("udc_form_by_type", {}).items() if not t.startswith("_")}


def _digits(form: str) -> str:
    return form.strip("()").replace(".", "")


def covers(expected: str, found: str) -> bool:
    """'(043)' covers '(043)' and '(043.2)' (UDC decimal hierarchy), not the broader '(04)'."""
    return _digits(found).startswith(_digits(expected))


def form_components(notation: str) -> list[str]:
    """Common auxiliaries of form in a notation: '(043.2)', '(075.8)'; places such as '(460)' are not."""
    return [t for kind, t in tokenize(notation) if kind == "paren" and t[1:2] == "0"]


def _label(conn, code: str) -> str:
    row = conn.execute("SELECT labels FROM udc_nodes WHERE code=?", (code,)).fetchone()
    lbl = (json.loads(row[0]).get("en") or "") if row else ""
    return f"{code} {lbl}".strip()


def check(conn, item_type: str, notations: list[str], extra: str = "") -> list[dict]:
    """Warnings [{kind, message}] for an item's type, its UDC notations and its Extra field."""
    notations = [n for n in notations if (n or "").strip()]
    if not notations:
        return []
    cat = catalog.get(conn)
    tlabel = cat.label("type", item_type)
    found = [f for n in notations for f in form_components(n)]
    out = []
    own = rules().get(item_type, {}).get("forms", [])
    if own and not any(covers(e, f) for e in own for f in found):
        exp = " or ".join(_label(conn, e) for e in own)
        out.append({"kind": "missing_form", "expected": own,
                    "message": f"A {tlabel} usually carries the form {exp}; its UDC has no such form."})
    for other, r in rules().items():
        if other == item_type or not r.get("reverse"):
            continue
        for f in found:
            if any(covers(e, f) for e in r["forms"]) and not any(covers(e, f) for e in own):
                out.append({"kind": "unexpected_form", "found": f, "type": other,
                            "message": f"{_label(conn, f)} is the form of a {cat.label('type', other)}, "
                                       f"but this item is a {tlabel}."})
    if extra_vars(extra).get("type") == "musical_score":
        mains = [t for n in notations for kind, t in tokenize(n) if kind == "main"]
        if not any(m.startswith("78") for m in mains):
            out.append({"kind": "score_not_78",
                        "message": "This item is a musical score (Extra: Type: musical_score), but its UDC is not "
                                   "in class 78 Music."})
    return out
