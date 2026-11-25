"""Datos de localización (CLDR vía `babel`): nombres de idiomas, países y meses en cualquier idioma.

El PoC no asume un idioma de documento: el idioma se detecta y de aquí salen los nombres de países y meses
en ese idioma. La tabla de lugar y la de lengua del UDC están en inglés, así que todo se lleva al nombre
inglés de CLDR y de ahí al nodo del árbol. Sin `babel` se degrada a inglés (y a lo que haya en config)."""
from __future__ import annotations
import unicodedata
from functools import lru_cache


# Idiomas con declinación de nombres propios (el nombre del país cambia de terminación según el caso).
INFLECTED = {"ru", "uk", "be", "bg", "pl", "cs", "sk", "sl", "hr", "sr", "bs", "mk", "lt", "lv", "et", "fi",
             "hu", "de", "is", "el", "la", "tr", "az", "kk", "ky", "uz", "tt", "ka", "hy", "eu", "ga", "cy"}


def _babel():
    try:
        import babel  # noqa: F401
        return True
    except ImportError:
        return False


def base(lang: str | None) -> str | None:
    """'pt-BR' / 'pt_BR' -> 'pt'."""
    return lang.replace("_", "-").split("-")[0].lower() if lang else None


@lru_cache(maxsize=None)
def _locale(lang: str):
    from babel import Locale, UnknownLocaleError
    try:
        return Locale.parse(lang)
    except (UnknownLocaleError, ValueError):
        return None


@lru_cache(maxsize=None)
def language_name_en(iso: str | None) -> str | None:
    """Nombre inglés de un código ISO 639 ('ja' -> 'Japanese', 'grc' -> 'Ancient Greek')."""
    if not iso or not _babel():
        return None
    return _locale("en").languages.get(iso) or _locale("en").languages.get(base(iso))


@lru_cache(maxsize=None)
def territory_names(lang: str | None) -> dict[str, str]:
    """{nombre del país/región en `lang`: código CLDR ('MX', '029' Caribe, '419' América Latina...)}."""
    lang = base(lang)
    if not lang or not _babel():
        return {}
    loc = _locale(lang)
    if loc is None:
        return {}
    out = {}
    for code, name in loc.territories.items():
        if code in ("ZZ", "QO", "EU", "EZ", "UN") or len(name) < 3:   # desconocida, organizaciones
            continue
        out[name] = code
        short = name.split(" (")[0]          # "Macao (RAE de China)" -> "Macao"
        if len(short) >= 4:
            out.setdefault(short, code)
    return out


@lru_cache(maxsize=None)
def territory_en(code: str) -> str | None:
    return _locale("en").territories.get(code) if _babel() else None


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c)).strip(". ")


_EN_MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}
_EN_MONTHS.update({m[:3]: i for m, i in _EN_MONTHS.items()})
_EN_MONTHS["sept"] = 9


def _months_of(lang: str) -> dict[str, int]:
    from babel.dates import get_month_names
    loc = _locale(lang)
    out: dict[str, int] = {}
    if loc is None:
        return out
    for ctx in ("format", "stand-alone"):         # 'format' trae genitivos: polaco 'listopada'
        for width in ("wide", "abbreviated"):
            try:
                names = get_month_names(width, context=ctx, locale=loc)
            except Exception:  # noqa: BLE001
                continue
            for num, name in names.items():
                k = _fold(name)
                if len(k) >= 3 and not k.isdigit():
                    out[k] = num
    return out


@lru_cache(maxsize=None)
def _unambiguous_months() -> dict[str, int]:
    """Nombres de mes de todos los idiomas CLDR que significan el mismo mes en todos ellos
    ('mayo', 'juillet', 'März'...; fuera 'listopad', que es noviembre en polaco y octubre en croata)."""
    from babel import localedata
    seen: dict[str, set] = {}
    for lang in {l.split("_")[0] for l in localedata.locale_identifiers()}:
        for k, v in _months_of(lang).items():
            seen.setdefault(k, set()).add(v)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


@lru_cache(maxsize=None)
def month_names(lang: str | None) -> dict[str, int]:
    """{nombre o abreviatura de mes en minúsculas y sin acentos: 1..12}. Con el idioma del documento,
    sus meses mandan; además valen el inglés y los nombres no ambiguos de cualquier idioma."""
    out = dict(_EN_MONTHS)
    if not _babel():
        return out
    out.update(_unambiguous_months())
    lang = base(lang)
    if lang and lang != "en":
        out.update(_months_of(lang))             # el idioma del documento manda
    return out


def fold(s: str) -> str:
    return _fold(s)
