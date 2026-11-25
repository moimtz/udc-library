"""UDC notation -> tree nodes, for item_udc_nodes.

The tokenizer is the one of udc_poc/udcpoc/notation.py (kept in step by hand; the server is deployed
without the PoC). '004.8:61' places an item in 004.8 and 61; auxiliaries such as (460), =134.2 or "18"
place it in their own branches of the tree, which udc_nodes also holds.
"""
import re

TOKEN_RE = re.compile(r'''
    (?P<time>"[^"]*")
  | (?P<paren>\([^()]*\))
  | (?P<lang>=[0-9][0-9.]*)
  | (?P<view>\.00[0-9.]*)
  | (?P<special>\.0[0-9]+|-[1-9][0-9.]*|['`][0-9][0-9.]*)
  | (?P<common>-0[0-9.]*)
  | (?P<rel>::|[:+/])
  | (?P<main>[0-9][0-9.]*)
''', re.X)


def tokenize(s: str) -> list[tuple[str, str]]:
    """[(kind, text)]; unknown characters are skipped."""
    out, pos, s = [], 0, (s or "").strip()
    while pos < len(s):
        m = TOKEN_RE.match(s, pos)
        if not m:
            pos += 1
            continue
        out.append((m.lastgroup, m.group()))
        pos = m.end()
    return out


def _shorter(text: str) -> list[str]:
    """Candidates from the most to the least specific, keeping the wrapper: '(460.1)' -> (460.1), (460),
    (46), (4); '"1850"' -> "1850", "185", "18", "1"; '004.8' -> 004.8, 004, 00, 0."""
    if text[:1] in "(\"" and len(text) > 2:
        pre, body, post = text[0], text[1:-1], text[-1]
    else:
        pre, body, post = "", text, ""
    lead = re.match(r"^[^0-9]*", body).group()   # '=', '-0', '0.' kept: '(=1)', '-05'
    out = []
    while len(body) > len(lead):
        out.append(pre + body + post)
        body = body[:-1].rstrip(".")
    return out


def nodes_for(notation: str, known) -> list[str]:
    """Tree nodes for one notation: each component resolved to its most specific existing class."""
    found: list[str] = []
    last_main = ""
    for kind, text in tokenize(notation):
        if kind == "rel":
            continue
        cands = []
        if kind == "main":
            last_main = text
        elif kind in ("special", "view") and last_main:
            # specials sit next to their main class in the tree ('62-1'); try the main class's prefixes
            m = last_main
            while m:
                cands.append(m + text)
                m = m[:-1].rstrip(".")
        cands += _shorter(text)
        hit = next((c for c in cands if c in known), None)
        if hit and hit not in found:
            found.append(hit)
    return found
