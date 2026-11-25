"""Partituras: detección visual de pentagramas y clasificación dentro de la clase 78 (Música).

Por qué visual: el texto de una partitura es poco y engañoso (en «Sobre las olas» se leía «Rosas» y salía la
familia de las rosas). Un pentagrama —cinco líneas horizontales paralelas y equidistantes que se repiten— es
inequívoco, no depende del idioma y funciona igual en escaneos que en partituras grabadas digitalmente.
El número de pentagramas por sistema indica además la plantilla: 1 instrumento melódico, 2 teclado,
3 voz y piano (o trío), 4 cuarteto, muchos = orquesta."""
from __future__ import annotations
import re
from dataclasses import dataclass, field

import config


# ------------------------------------------------------------------ detección de pentagramas
def _line_rows(a, min_frac: float) -> list[float]:
    """Centros de las filas oscuras que cruzan casi todo el ancho (líneas horizontales largas)."""
    import numpy as np
    h, w = a.shape
    dark = a < float(np.median(a)) - 50          # relativo al fondo: las líneas finas vectoriales salen grises
    # el ancho se mide por franjas: un escaneo algo torcido no tiene la línea entera en una sola fila
    strips = np.array_split(dark, 4, axis=1)
    frac = np.mean([s.mean(axis=1) for s in strips], axis=0)
    rows = np.where(frac >= min_frac)[0]
    lines, start = [], None
    for i, r in enumerate(rows):
        if start is None:
            start = r
        if i == len(rows) - 1 or rows[i + 1] != r + 1:
            if r - start <= 4:                   # una línea, no un bloque negro (foto, mancha)
                lines.append((start + r) / 2)
            start = None
    return lines


def _staves(lines: list[float], page_h: int) -> list[tuple[float, float, float]]:
    """Grupos de 5 líneas equidistantes con separación pequeña: (arriba, abajo, separación)."""
    out, i = [], 0
    while i + 4 < len(lines):
        g = [lines[i + k + 1] - lines[i + k] for k in range(4)]
        # separación de pentagrama: 3-7 px a 80 dpi; renglones de texto escaneado dan 10-13 px
        if min(g) >= 2 and max(g) <= page_h * config.SCORE_MAX_GAP_FRAC and max(g) / min(g) <= 1.45:
            out.append((lines[i], lines[i + 4], sum(g) / 4))
            i += 5
        else:
            i += 1
    return out


@dataclass
class StaffInfo:
    pages_checked: int = 0
    score_pages: int = 0
    staves_per_page: float = 0.0
    per_system: int = 0                          # pentagramas por sistema (estimado)
    detail: list = field(default_factory=list)

    @property
    def is_score(self) -> bool:
        return self.pages_checked > 0 and self.score_pages >= max(1, config.SCORE_MIN_PAGES_FRAC * self.pages_checked)


# Libros SOBRE música (teoría, armonía, orquestación, métodos): traen ejemplos en pentagrama pero no son partituras.
_ABOUT_MUSIC = re.compile(
    r"\b(harmony|harmonie|harmonielehre|armon[ií]a|armonia|гармони\w*|counterpoint|contrapunto|contrepoint|kontrapunkt|"
    r"orchestration|orquestaci[oó]n|instrumentation|instrumentaci[oó]n|theory|teor[ií]a|th[ée]orie|theorie|"
    r"analysis|an[aá]lisis|analyse|treatise|tratado|trait[ée]|lehrbuch|method|m[ée]todo|m[ée]thode|methode|"
    r"aufgaben|exercises|ejercicios|exercices|задач\w*|composition|composici[oó]n|kompositionslehre|"
    r"musician'?s guide|principles of|solfeggio|solfeo|solf[eè]ge|gradus)\b", re.I)
_SCORE_SOURCE = re.compile(r"imslp|mutopia|musescore|lilypond|sibelius|finale|dorico|noteflight|petrucci", re.I)


def decide(info: StaffInfo, title: str = "", filename: str = "", producer: str = "") -> tuple[bool, str]:
    """¿Es partitura? (sí/no, motivo). Pentagramas en la mayoría de las páginas miradas; con una fuente
    típica de partituras (IMSLP, MuseScore, LilyPond…) basta una página. Un libro SOBRE música no lo es."""
    if info.score_pages == 0:
        return False, ""
    about = _ABOUT_MUSIC.search(f"{title} {filename}")
    if about:
        return False, f"libro sobre música ('{about.group(0)}'), con ejemplos en pentagrama"
    src = _SCORE_SOURCE.search(f"{filename} {producer}")
    if src and info.score_pages >= 1:
        return True, f"pentagramas en {info.score_pages}/{info.pages_checked} págs. + fuente '{src.group(0)}'"
    if info.is_score:
        return True, f"pentagramas en {info.score_pages}/{info.pages_checked} págs."
    return False, ""


def per_system(staves: list[tuple[float, float, float]]) -> int:
    """Pentagramas por sistema a partir de los huecos entre pentagramas consecutivos: dentro de un sistema
    (unidos por llave) el hueco es menor que entre sistemas."""
    n = len(staves)
    if n <= 1:
        return n
    gaps = [staves[k + 1][0] - staves[k][1] for k in range(n - 1)]
    # periodicidad: con k pentagramas por sistema, cada k-ésimo hueco (entre sistemas) es el grande.
    # Se elige el k que mejor separa los huecos grandes de los pequeños (44-46-57-44-46-57 -> 3).
    # Se prueban todas las fases: si se perdió un pentagrama arriba, el patrón empieza desplazado.
    best_k, best_sep = 1, 0.0
    for k in range(2, min(6, n) + 1):
        for ph in range(k):
            big = [g for j, g in enumerate(gaps) if j % k == ph]
            small = [g for j, g in enumerate(gaps) if j % k != ph]
            if not big or not small:
                continue
            sep = min(big) / max(max(small), 1)
            if sep > best_sep + 0.05:            # ante empate, el k menor (un 2 también "encaja" como 4)
                best_k, best_sep = k, sep
    return best_k if best_sep >= 1.1 else 1      # huecos uniformes: un pentagrama por sistema (o un solo sistema)


def detect(doc, max_pages: int | None = None) -> StaffInfo:
    """Mira hasta SCORE_SAMPLE_PAGES páginas repartidas por el documento (sin la primera y la última)."""
    import numpy as np
    n = doc.page_count
    k = max_pages or config.SCORE_SAMPLE_PAGES
    idx = list(range(n)) if n <= k + 2 else sorted({1 + round(j * (n - 3) / (k - 1)) for j in range(k)})
    info = StaffInfo()
    systems = []
    for i in idx:
        pix = doc[i].get_pixmap(dpi=config.SCORE_DPI, colorspace="gray", alpha=False)
        a = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
        mw = a.shape[1] // 12
        a = a[:, mw:-mw]
        st = _staves(_line_rows(a, config.SCORE_LINE_FRAC), a.shape[0])
        info.pages_checked += 1
        info.detail.append((i + 1, len(st)))
        # una página de partitura casi no tiene texto (indicaciones, letra); un libro con ejemplos, mucho
        if len(st) >= config.SCORE_MIN_STAVES and len(doc[i].get_text().strip()) < config.SCORE_MAX_TEXT:
            info.score_pages += 1
            if len(st) >= 4:                     # con pocos pentagramas el patrón de huecos no es fiable
                systems.append(per_system(st))
            info.staves_per_page += len(st)
    if info.score_pages:
        info.staves_per_page = round(info.staves_per_page / info.score_pages, 1)
        # "1" también sale cuando el patrón no se reconoce (pentagramas perdidos): un patrón >1 que se repite
        # en al menos 2 páginas manda sobre él
        multi = [s for s in systems if s > 1]
        if multi and multi.count(max(set(multi), key=multi.count)) >= 2:
            info.per_system = max(set(multi), key=multi.count)
        else:
            info.per_system = max(set(systems), key=systems.count) if systems else 0
    return info


# ------------------------------------------------------------------ clasificación dentro de 78
# Palabras clave multilingües (en, es, fr, de, it, pt, ru). El orden importa: lo más específico primero.
GENRES = [   # (regex, notación principal, motivo)
    (r"\b(opera|ópera|opéra|oper|operetta|opereta|opérette|zarzuela|singspiel|опера)\b", "782", "ópera"),
    (r"\b(missa|mass|misa|messe|requiem|réquiem|motet|motete|mottetto|magnificat|te deum|stabat mater|"
     r"psalm|salmo|psaume|psalmen|hymn|himno|hymne|inno|passion|pasión|oratorio|oratorium|kantate|"
     r"cantata sacra|литургия)\b", "783", "música religiosa"),
    # \w* delante: compuestos alemanes (Klavierkonzert, Streichquartett, Klaviertrio)
    (r"\b(concerto|concierto|\w*konzert|concert pour|концерт)\b", "785.6", "concierto"),
    (r"\b(symphony|sinfon[ií]a|symphonie|\w*sinfonie|sinfonia|симфония|overture|obertura|ouverture|"
     r"for orchestra|para orquesta|pour orchestre|für orchester|per orchestra|full score)\b", "785.11", "orquesta"),
    (r"\b(octet|octeto|\w*oktett|ottetto)\b", "785.78", "octeto"),
    (r"\b(septet|septeto|\w*septett|settimino)\b", "785.77", "septeto"),
    (r"\b(sextet|sexteto|\w*sextett|sestetto)\b", "785.76", "sexteto"),
    (r"\b(quintet|quinteto|\w*quintett|quintette|quintetto)\b", "785.75", "quinteto"),
    (r"\b(quartet|cuarteto|\w*quartett|quatuor|quartetto|квартет)\b", "785.74", "cuarteto"),
    (r"\b((?:klavier|streich|horn|klarinetten|flöten|bläser)?trio|tr[ií]o|трио)\b", "785.73", "trío"),
    (r"\b(duo|d[uú]o|duet|dueto|duett)\b", "785.72", "dúo"),
    (r"\b(choir|chorus|coro|chœur|choeur|chor|хор|satb|a cappella)\b", "784.1", "coro"),
    (r"\b(song|songs|canci[oó]n|canciones|lied|lieder|m[ée]lodie|chanson|canzone|romanza|romance|"
     r"voice and piano|voz y piano|chant et piano|gesang|singstimme|романс|песня)\b", "784.3", "canción"),
]
INSTRUMENTS = [  # (regex, notación del instrumento)
    (r"\b(harpsichord|cembalo|clavecin|clave|clavicembalo)\b|clavier-?(?:[üu]|ue)bung", "780.616.31"),
    (r"\b(piano|pianoforte|klavier\w*|fortepiano|фортепиано)\b", "780.616.433"),
    (r"\b(violin\w*|viol[ií]n|violon|geige\w*|violino|скрипка)\b", "780.614.332"),
    (r"\b(viola|alto|bratsche)\b", "780.614.333"),
    (r"\b(cello\w*|violoncello|violonchelo|violoncelle|виолончель)\b", "780.614.334"),
    (r"\b(double bass|contrabajo|contrebasse|kontrabass|contrabbasso)\b", "780.614.335"),
    (r"\b(guitar|guitarra|guitare|gitarre|chitarra|гитара)\b", "780.614.131"),
    (r"\b(harp|arpa|harpe|harfe)\b", "780.613"),
    (r"\b(flute|flauta|fl[ûu]te|fl[öo]te|flauto)\b", "780.641.2"),
    (r"\b(recorder|flauta dulce|blockfl[öo]te|fl[ûu]te à bec|flauto dolce)\b", "780.642.1"),
    (r"\b(clarinet|clarinete|clarinette|klarinette|clarinetto)\b", "780.643.1"),
    (r"\b(saxophone|saxof[oó]n|saxofon)\b", "780.643.2"),
    (r"\b(oboe|hautbois)\b", "780.644.1"),
    (r"\b(bassoon|fagot|basson|fagott|fagotto)\b", "780.644.2"),
    (r"\b(trumpet|trompeta|trompette|trompete|tromba)\b", "780.646.1"),
    (r"\b(trombone|posaune)\b", "780.646.2"),
    (r"\b(horn|corno|cor|trompa)\b", "780.646.3"),
    (r"\b(tuba)\b", "780.646.4"),
    (r"\b(accordion|acorde[oó]n|accord[ée]on|akkordeon|fisarmonica|bandoneon|bandone[oó]n)\b", "780.647.2"),
    (r"\b(harmonium|armonio)\b", "780.647.3"),
]
FORMS = [    # (regex, notación de forma)
    (r"\b(variations?|variaciones|variationen|variazioni|вариации|goldberg)\b", "78.083.2"),
    (r"\b(prelude|preludio|pr[ée]lude|pr[äa]ludium|fugue|fuga|fuge)\b", "78.083.2"),
    (r"\b(toccata|toccatina|fantasia|fantas[ií]a|fantaisie|phantasie|capriccio|capricho|arabesque|"
     r"humoresque|moment musical)\b", "78.083.3"),
    (r"\b(nocturne|nocturno|notturno|serenade|serenata|s[ée]r[ée]nade|berceuse|canci[oó]n de cuna|"
     r"wiegenlied|song without words|lied ohne worte)\b", "78.083.4"),
    (r"\b(rhapsody|rapsodia|rhapsodie|ballade|balada)\b", "78.083.5"),
    (r"\b([ée]tude|estudio|etüde|etude|studie|studio)\b", "78.083.7"),
    (r"\b(suite|divertimento|partita)\b", "78.083.1"),
    (r"\b(sonatina|sonatine)\b", "78.082.3"),
    (r"\b(sonata|sonate)\b", "78.082.2"),
    (r"\b(waltz|vals|valse|walzer|valzer|вальс|polka|galop|galopp)\b", "78.085.2"),
    (r"\b(mazurka|polonaise|polonesa|polacca|habanera|jota|danz[oó]n|tango|czardas|csárdás)\b", "78.085.7"),
    (r"\b(minuet|minueto|menuet|menuett|minuetto|gavotte|gavota|sarabande|zarabanda|bourr[ée]e|gigue|"
     r"giga|allemande|courante|pavane|galliard)\b", "78.085.1"),
    (r"\b(march|marcha|marche|marsch|marcia|марш)\b", "78.084"),
    (r"\b(ballet|ballett|балет)\b", "78.085.5"),
]


def _first(rules, text):
    for rx, code, *why in rules:
        if re.search(rx, text, re.I):
            return code, (why[0] if why else re.search(rx, text, re.I).group(0))
    return None, None


def classify(text: str, info: StaffInfo | None) -> dict:
    """Notación dentro de 78 para una partitura: {'mains': [...], 'evidence': [...]}.
    Prioridad: género/agrupación por palabras clave; si no hay, la plantilla por pentagramas por sistema."""
    t = " ".join((text or "").split())
    ev = []
    genre, why = _first(GENRES, t)
    instr, iw = _first(INSTRUMENTS, t)
    form, fw = _first(FORMS, t)
    ps = info.per_system if info else 0
    if genre:
        ev.append(f"género: {why}")
    elif ps >= 8:
        genre = "785.11"; ev.append(f"{ps} pentagramas por sistema: orquesta")
    elif ps == 4 and not instr:
        genre = "785.74"; ev.append("4 pentagramas por sistema: cuarteto")
    elif ps == 3 and not instr:
        genre = "784.3"; ev.append("3 pentagramas por sistema: voz y piano")
    mains = [genre] if genre else ["780.8"]
    if not genre:
        if not instr and ps == 2:
            instr, iw = "780.616.433", "2 pentagramas por sistema: teclado"
        ev.append("música para un instrumento")
    if instr and (not genre or genre in ("785.6",)):
        mains.append(instr); ev.append(f"instrumento: {iw}")
    if form and genre not in ("782", "783"):
        mains.append(form); ev.append(f"forma: {fw}")
    return {"mains": mains, "evidence": ev}
