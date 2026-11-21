"""Text helpers: accent folding and citation keys."""
import re
import string
import unicodedata

STOP_WORDS = {
    # Spanish
    "a", "al", "ante", "con", "de", "del", "desde", "e", "el", "en", "entre", "la",
    "las", "lo", "los", "o", "para", "por", "se", "sobre", "su", "sus", "u", "un",
    "una", "unas", "unos", "y", "que",
    # English
    "an", "the", "of", "on", "in", "at", "to", "for", "and", "or", "with", "from",
    "by", "as", "its", "is",
}


def strip_accents(s: str) -> str:
    """Remove accents, one character in -> one character out."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in s)


def fold(s: str) -> str:
    """Lower-case and remove accents while keeping the exact same length, so
    match offsets found in the folded text are valid in the original text."""
    out = []
    for ch in s:
        base = unicodedata.normalize("NFD", ch)[0]
        low = base.lower()
        out.append(low if len(low) == 1 else base)
    return "".join(out)


def make_citekey(creators: list[dict], title: str, year: int | None, words: int = 3) -> str:
    """firstauthorlastname + first 3 significant title words (CamelCase) + year.

    Example: garciaIntroduccionTeoriaConjuntos1998
    """
    pick = next((c for c in creators if c.get("role", "author") in ("author", "inventor")), None)
    if pick is None and creators:
        pick = creators[0]
    first = ""
    if pick:
        first = pick.get("last") or pick.get("first") or ""
    author = re.sub(r"[^a-z0-9]", "", strip_accents(first).lower())[:30] or "anon"
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", strip_accents(title or ""))
              if t.lower() not in STOP_WORDS]
    tpart = "".join(t[:1].upper() + t[1:].lower() for t in tokens[:words])[:60] or "Untitled"
    ypart = str(year) if year else "nd"
    return f"{author}{tpart}{ypart}"


def unique_key(base: str, is_taken) -> str:
    """Add a, b, c... (then 2, 3...) until `is_taken(key)` is False."""
    if not is_taken(base):
        return base
    for suffix in string.ascii_lowercase:
        if not is_taken(base + suffix):
            return base + suffix
    n = 2
    while is_taken(f"{base}{n}"):
        n += 1
    return f"{base}{n}"


def parse_name(raw: str) -> dict:
    """'Last, First' or 'First Last' -> {'first','last'} (heuristic; editable by the user)."""
    raw = " ".join((raw or "").split())
    if "," in raw:
        last, first = raw.split(",", 1)
        return {"first": first.strip(), "last": last.strip()}
    parts = raw.split(" ")
    if len(parts) == 1:
        return {"first": "", "last": parts[0]}
    return {"first": " ".join(parts[:-1]), "last": parts[-1]}
