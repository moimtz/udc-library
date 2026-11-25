"""Text helpers: accent folding, citation keys, names."""
import re
import string
import unicodedata

# Words skipped in citation keys (compared after transliteration to ASCII).
STOP_WORDS = {
    # English
    "a", "an", "the", "of", "on", "in", "at", "to", "for", "and", "or", "with", "from", "by", "as", "its", "is",
    # Spanish / Portuguese / Catalan
    "al", "ante", "con", "de", "del", "desde", "e", "el", "en", "entre", "la", "las", "lo", "los", "o", "para",
    "por", "se", "sobre", "su", "sus", "u", "un", "una", "unas", "unos", "y", "que", "da", "das", "do", "dos",
    "um", "uma", "no", "na", "nos", "nas", "com", "els", "les", "i",
    # French
    "le", "du", "des", "et", "au", "aux", "sur", "dans", "pour", "par", "l", "d",
    # German / Dutch
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "und", "im", "zur", "zum", "von", "het",
    "een", "van", "voor", "op",
    # Italian
    "il", "lo", "gli", "di", "della", "delle", "dei", "nel", "nella", "per",
    # Russian / Ukrainian / Polish (transliterated) and Scandinavian
    "v", "na", "s", "k", "ob", "ot", "dlya", "w", "z", "och", "og", "af", "av", "til", "till",
}


def strip_accents(s: str) -> str:
    """Remove accents, one character in -> one character out."""
    return "".join(unicodedata.normalize("NFD", ch)[0] for ch in s)


def to_ascii(s: str) -> str:
    """Transliterate any script to ASCII ('Достоевский' -> 'Dostoevskiy', '夏目漱石' -> 'XiaMuShuShi').
    Without the optional 'anyascii' package, only accents are removed (other scripts are dropped)."""
    try:
        from anyascii import anyascii
        return anyascii(s)
    except ImportError:
        return strip_accents(s)


def fold(s: str) -> str:
    """Lower-case and remove accents while keeping the exact same length, so
    match offsets found in the folded text are valid in the original text."""
    out = []
    for ch in s:
        base = unicodedata.normalize("NFD", ch)[0]
        low = base.lower()
        out.append(low if len(low) == 1 else base)
    return "".join(out)


def make_citekey(first_creator: str, title: str, year: int | None, words: int = 3) -> str:
    """firstcreatorlastname + first 3 significant title words (CamelCase) + year.

    Example: garciaIntroduccionTeoriaConjuntos1998
    """
    author = re.sub(r"[^a-z0-9]", "", to_ascii(first_creator or "").lower())[:30] or "anon"
    tokens = [t for t in re.findall(r"[A-Za-z0-9]+", to_ascii(title or ""))
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
    """'Last, First' or 'First Last' -> {'first_name', 'last_name'} (heuristic; editable by the user)."""
    raw = " ".join((raw or "").split())
    if "," in raw:
        last, first = raw.split(",", 1)
        return {"first_name": first.strip(), "last_name": last.strip()}
    parts = raw.split(" ")
    if len(parts) == 1:
        return {"first_name": "", "last_name": parts[0]}
    return {"first_name": " ".join(parts[:-1]), "last_name": parts[-1]}
