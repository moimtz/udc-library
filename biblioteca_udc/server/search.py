"""Search used by the app from v0.2: a UDC-number box and a text box, both free by default.

Text box (smart_text_matcher)
    Free search (default), always ignoring case and accents:
      words          every word must appear (in any field chosen), in any order: `redes neuronales`
      "a phrase"     the words together, in this order
      a | b          either of them (also `a OR b`)
      -word          items with that word are left out
      *  ?           wildcards: `electr*` = electr + any letters, `organi?ation` = one character
    Exact search: the whole text is one phrase that must appear as whole words (wildcards still work).

UDC box (udc_filter)
    Free search (default): every component typed must appear in one of the item's UDC numbers, itself or one
    of its subdivisions. `61` finds 616.1 and 004.8:61; `004.8:61` finds items that have both (the signs between
    the components are not compared, so the user narrows the search component by component); `(460)` finds
    616(460.1). A trailing * is accepted (it means the same).
    Exact search: the item's UDC number is exactly the one typed (spaces ignored); * and ? are wildcards.
    Include cancelled: an item classed with a cancelled number whose replacement falls under the searched one is
    also found (e.g. a book classed with an old 568.1 is found when searching for its replacement).
"""
import json
import re

import notation
from textutil import fold

# ------------------------------------------------------------------------------------------------ text
_TERM_RE = re.compile(r'"([^"]*)"|(\S+)')


def _wild(text: str) -> str:
    """Regex for one folded term: * -> letters/digits, ? -> one character, spaces -> any whitespace."""
    out = []
    for ch in text:
        if ch == "*":
            out.append(r"\w*")
        elif ch == "?":
            out.append(".")
        elif ch.isspace():
            out.append(r"\s+")
        else:
            out.append(re.escape(ch))
    return "".join(out)


def parse_text_query(query: str, exact: bool) -> tuple[list[list[re.Pattern]], list[re.Pattern]]:
    """(groups, excluded): an item matches when each group has one pattern that matches and no excluded one
    does. A group with several patterns comes from `a | b`."""
    q = fold(query.strip())
    if not q:
        return [], []
    if exact:
        phrase = q.strip('"')
        return [[re.compile(rf"(?<!\w){_wild(phrase)}(?!\w)")]], []
    groups: list[list[re.Pattern]] = []
    excluded: list[re.Pattern] = []
    pending_or = False
    for m in _TERM_RE.finditer(q):
        phrase, word = m.group(1), m.group(2)
        if word in ("|", "or"):
            pending_or = bool(groups)
            continue
        negative = word is not None and word.startswith("-") and len(word) > 1
        text = phrase if phrase is not None else (word[1:] if negative else word)
        if not text.strip("*?"):
            continue
        rx = re.compile(_wild(text))
        if negative:
            excluded.append(rx)
        elif pending_or:
            groups[-1].append(rx)
        else:
            groups.append([rx])
        pending_or = False
    return groups, excluded


def smart_text_matcher(query: str, exact: bool = False):
    """match(fields: {code: text}) -> {code: spans} when the item matches, else None. Offsets refer to the
    original text (fold keeps the length)."""
    groups, excluded = parse_text_query(query, exact)
    if not groups and not excluded:
        return None

    def match(fields: dict[str, str]):
        folded = {k: fold(v) for k, v in fields.items() if v}
        for rx in excluded:
            if any(rx.search(t) for t in folded.values()):
                return None
        hits: dict[str, list[list[int]]] = {}
        for group in groups:
            found = False
            for rx in group:
                for k, t in folded.items():
                    for m in rx.finditer(t):
                        if m.end() > m.start():
                            found = True
                            spans = hits.setdefault(k, [])
                            if len(spans) < 100:
                                spans.append([m.start(), m.end()])
            if not found:
                return None
        return hits

    return match


# ------------------------------------------------------------------------------------------------ UDC
def _key(kind: str, text: str) -> str:
    """Comparable form of one component: no dots or spaces, and without the closing ) or " so that a prefix
    means a subdivision: (46 is a prefix of (460, "18 of "1850."""
    t = text.replace(" ", "")
    if kind in ("paren", "time") and len(t) > 1 and t[-1] in ')"':
        t = t[:-1]
    return kind + ":" + t.replace(".", "")


def components(udc_text: str) -> list[tuple[str, str]]:
    """[(key, original text)] of the components of one UDC number (signs left out)."""
    return [(_key(k, t), t) for k, t in notation.tokenize(udc_text) if k != "rel"]


def _component_spans(udc_text: str, wanted: list[str]) -> list[list[int]]:
    """Offsets in udc_text of the components whose key starts with one of `wanted`."""
    out = []
    for m in notation.TOKEN_RE.finditer(udc_text):
        if m.lastgroup == "rel":
            continue
        k = _key(m.lastgroup, m.group())
        if any(k.startswith(w) for w in wanted):
            out.append([m.start(), m.end()])
    return out


def _wild_full(text: str) -> re.Pattern:
    body = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in text)
    return re.compile(f"^{body}$", re.I)


_cancelled_cache: tuple[tuple, list[tuple[str, list[str]]]] | None = None


def _cancelled_pairs(conn) -> list[tuple[str, list[str]]]:
    """[(key of the cancelled notation, keys of its replacements)], parsed once while the table is unchanged
    (parsing the ~12 000 rows takes most of a second)."""
    global _cancelled_cache
    stamp = tuple(conn.execute("SELECT COUNT(*), COALESCE(MAX(rowid), 0) FROM udc_cancelled").fetchone())
    if _cancelled_cache and _cancelled_cache[0] == stamp:
        return _cancelled_cache[1]
    pairs = []
    for code, replaced_by in conn.execute("SELECT code, replaced_by FROM udc_cancelled"):
        try:
            targets = json.loads(replaced_by)
        except ValueError:
            continue
        old = components(code)
        if old:
            pairs.append((old[0][0], [k for t in targets for k, _ in components(t)]))
    _cancelled_cache = (stamp, pairs)
    return pairs


def _cancelled_alternatives(conn, query_keys: list[str]) -> dict[str, list[str]]:
    """For each query component: keys of cancelled notations replaced by a class under it."""
    out: dict[str, list[str]] = {k: [] for k in query_keys}
    for old, targets in _cancelled_pairs(conn):
        for q in query_keys:
            if old not in out[q] and any(k.startswith(q) for k in targets):
                out[q].append(old)
    return out


def udc_filter(conn, query: str, exact: bool = False, include_cancelled: bool = False):
    """keep(item) -> spans in item['udc_text'] (possibly empty) when the item matches, else None."""
    q = query.strip()
    if not q:
        return None
    if exact:
        wanted = [q.replace(" ", "")]
        if include_cancelled:
            for code, replaced_by in conn.execute("SELECT code, replaced_by FROM udc_cancelled"):
                try:
                    if q.replace(" ", "") in [t.replace(" ", "") for t in json.loads(replaced_by)]:
                        wanted.append(code.replace(" ", ""))
                except ValueError:
                    pass
        patterns = [_wild_full(w) for w in wanted]

        def keep_exact(item):
            text = item["udc_text"]
            spans, pos = [], 0
            for n in [u["notation"] for u in item["udc"]]:
                start = text.find(n, pos)
                if any(p.match(n.replace(" ", "")) for p in patterns):
                    spans.append([max(start, 0), max(start, 0) + len(n)])
                pos = max(start, 0) + len(n)
            return spans or None

        return keep_exact

    q = q.rstrip("*")
    keys = [k for k, _ in components(q)]
    if not keys:
        # only signs (a tree node such as ':' or '+'): items whose number uses that sign
        sign = q

        def keep_sign(item):
            i = item["udc_text"].find(sign)
            return [[i, i + len(sign)]] if i >= 0 else None

        return keep_sign
    alts = _cancelled_alternatives(conn, keys) if include_cancelled else {k: [] for k in keys}

    def keep(item):
        have = [k for u in item["udc"] for k, _ in components(u["notation"])]
        wanted = []
        for q_key in keys:
            options = [q_key, *alts[q_key]]
            if not any(h.startswith(o) for h in have for o in options):
                return None
            wanted.extend(options)
        return _component_spans(item["udc_text"], wanted)

    return keep
