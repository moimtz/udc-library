"""
CONFIGURACIÓN EDITABLE DEL PoC UDC
==================================
Casi todo lo que querrás ajustar está en este archivo:

  1. ZOTERO_ITEM_TYPES  -> tipos de ítem y campos de Zotero (se leen del schema.json de Zotero; no se editan).
  2. CRITICAL_FIELDS    -> campos que marcan "incompleto" si faltan.
  3. DOCTYPE_RULES      -> palabras clave para detectar el tipo de documento.
  4. FORM_BY_DOCTYPE / FORM_BY_TEXT -> reglas de la tabla auxiliar de forma (0...).
  5. LANG_UDC / TERRITORY_UDC / PLACE_ALIASES -> excepciones de idiomas y lugares (el resto sale de CLDR).
  6. Umbrales y pesos de la clasificación (se calibran en la Fase 2).
"""
from pathlib import Path

# ----------------------------------------------------------------- rutas
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
GOLD_ANSWERS = BASE_DIR / "books" / "gold" / "udc_gold.csv"   # tus UDC a ciegas (file, udc): review --blind las usa
UDC_RDF = BASE_DIR.parent / "biblioteca_udc" / "server" / "udc_data" / "udcs-skos.rdf"   # el de la fusión
INDEX_DIR = DATA_DIR / "index"                # embeddings del árbol (se regeneran solos)
FEEDBACK_DB = DATA_DIR / "feedback.db"        # SOLO confirmaciones; nunca toca biblioteca.db
RERANKER_PATH = DATA_DIR / "reranker.pkl"

# ------------------------------------------------------------ embeddings
EMBEDDING_MODEL = "BAAI/bge-m3"                # ~2.3 GB, multilingüe. Respaldo: "intfloat/multilingual-e5-small"
EMBEDDING_DEVICE = "cpu"                       # déjalo en cpu: la GPU es para el agente
LABEL_LANGS = ["en", "sv", "fi"]               # orden de preferencia de etiquetas del RDF

# ------------------------------------------------------------ lectura PDF
HEAD_PAGES = 6              # páginas CON CONTENIDO leídas al inicio (las vacías no cuentan)
TAIL_PAGES = 3              # páginas con contenido leídas al final
SCAN_LIMIT = 40             # páginas máximas recorridas (por cada extremo) buscando contenido
# Texto legible (capa del PDF o resultado de OCR): al menos BLANK_MAX_CHARS letras/dígitos y
#  - página larga (>= LONG_PAGE_TOKENS palabras): confianza del detector de idioma >= MIN_LANG_CONF
#    (texto real ~1.0; basura de OCR sobre música, grabados, tapas decoradas o manuscritos <= 0.65);
#  - página corta (portada): fracción de caracteres en palabras de letras >= MIN_TEXT_QUALITY.
BLANK_MAX_CHARS = 10        # portada "TÍTULO / Autor" ya cuenta
LONG_PAGE_TOKENS = 40
MIN_LANG_CONF = 0.9
MIN_TEXT_QUALITY = 0.45
OCR_GIVE_UP = 4             # páginas seguidas sin texto legible tras OCR => se deja de buscar en ese extremo
# Página vacía = sin texto legible y casi sin tinta: se renderiza a BLANK_DPI y se mide la fracción de
# píxeles claramente más oscuros que el fondo (portadas lisas, guardas, traspaso de tinta de la otra cara).
BLANK_INK = 0.003
BLANK_DPI = 40
OCR_MAX_ATTEMPTS = 20      # páginas máximas pasadas por OCR por documento (incluye pruebas y páginas ilegibles)
OCR_PROBE_PAGES = 3         # páginas usadas para detectar idioma/script
OSD_MIN_CONF = 5.0          # confianza mínima de OSD para aceptar un script no latino
# Idiomas de Tesseract: "auto" detecta el idioma por documento (1.ª página con OCR_PROBE, luego el idioma
# detectado + inglés; si el texto no es latino, el script por OSD). O una cadena fija, p. ej. "spa+eng".
OCR_LANGS = "auto"
OCR_PROBE = "script/Latin"  # modelo para la primera pasada (cubre todas las lenguas de alfabeto latino)
OCR_FALLBACK = "eng"        # sin tessdata_fast o sin detección fiable (con tessdata_fast: script/Latin)
OCR_DPI = 300               # resolución del render para OCR
# Modelos de tessdata_fast (todos los idiomas + carpeta script/). Se usa la primera carpeta que los tenga:
# la del programa Tesseract y, si no, data/tessdata. None = autodetección de PyMuPDF (solo lo que haya).
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"   # solo para OSD (detectar el script)
TESSDATA_DIR = next((str(d) for d in (Path(TESSERACT_EXE).parent / "tessdata", DATA_DIR / "tessdata")
                     if (d / "script" / "Latin.traineddata").exists()), None)

# ----------------------------------------------------- clasificación UDC
# Partituras: detección visual de pentagramas (udcpoc/music.py)
SCORE_SAMPLE_PAGES = 6      # páginas repartidas por el documento que se miran (rápido: render a SCORE_DPI)
SCORE_DPI = 80
SCORE_LINE_FRAC = 0.35      # fracción del ancho que debe cubrir una línea de pentagrama
SCORE_MIN_STAVES = 3        # pentagramas por página para contarla como página de partitura
SCORE_MIN_PAGES_FRAC = 0.5  # fracción de páginas miradas que deben ser de partitura
SCORE_MAX_GAP_FRAC = 0.009  # separación máx. entre líneas (fracción del alto): pentagrama ~0.006, renglón ~0.012
CATALOG_UDC_CONFIDENCE = 0.8  # UDC asignada por un catálogo bibliotecario (MARC 080)
SCORE_RULES_CONFIDENCE = 0.6 # confianza mostrada para la clase musical deducida por reglas
SCORE_MAX_TEXT = 1000      # caracteres máx. de texto en una página de partitura
FRONT_MIN_CHARS = 60       # título+resumen más cortos que esto: la vista "front" se completa con las 1.as páginas
# Peso de cada "vista" del documento al compararlo con el árbol.
VIEW_WEIGHTS = {"front": 0.45, "toc": 0.20, "body": 0.25, "tail": 0.10,
                # temas de catálogo (Open Library, Crossref, arXiv). Calibrado el 2026-11-24 con el gold
                # (12 docs con identificador): 0.3 = mismos aciertos exactos que sin temas y +5 niveles de área;
                # 0.6 arrastraba a clases vecinas (Roth -> lógica matemática).
                "subjects": 0.30}
# Enriquecimiento por identificador (udcpoc/enrich.py): ISBN/DOI/arXiv -> campos, temas, LC/Dewey y UDC de catálogo.
ENRICH_ONLINE = True        # `run --offline` lo desactiva
ENRICH_CONFIDENCE = 0.9     # confianza de los campos traídos por identificador (gana a lo extraído del PDF)
ENRICH_UDC_CATALOGS = True  # consultar catálogos nacionales con UDC (hoy: Biblioteca Nacional de Polonia)
ENRICH_TIMEOUT = 20
K_FLAT = 40                 # candidatos por búsqueda plana
BEAM_WIDTH = 5              # ramas abiertas en la búsqueda en haz
MAX_DEPTH = 22              # profundidad máxima del árbol (21, en 598.192.162) + 1; el bucle termina antes si no hay hijos
# Un nodo de ejemplo (origin='example') solo se propone si su similitud supera a la de su nodo
# anfitrión por al menos este margen; si no, se propone el anfitrión. Calibrar en la Fase 2.
EXAMPLE_MARGIN = 0.0
# "See also" (skos:related, en ambos sentidos): las SEE_ALSO_FROM mejores candidatas aportan sus clases enlazadas
# (solo de la tabla principal) como candidatas nuevas; compiten con la misma fórmula y el reranker recibe la marca
# "see_also". Cada sugerencia lista hasta SEE_ALSO_MAX enlaces (cualquier tabla) en "ver_tambien". 0 = desactivado.
SEE_ALSO_FROM = 10
SEE_ALSO_MAX = 5
# Pesos iniciales (antes de que haya confirmaciones suficientes para entrenar el reranker).
DEFAULT_WEIGHTS = {"sim": 1.0, "path": 0.5, "knn": 0.6, "depth": 0.02}
SOFTMAX_TEMP = 0.08         # convierte puntuaciones en "confianza" relativa
LOW_CONFIDENCE = 0.35       # confianza del top-1 por debajo de esto => aviso de baja confianza
MIN_SIM = 0.30              # similitud mínima del top-1 (calibrar con datos reales)
# Segundo tema con ':' solo si está a menos de esta distancia de puntuación del top-1 Y es de otra
# rama desde el 2.º nivel (no 537.3:537.6). Las puntuaciones rondan 0.8, así que un cociente no sirve.
SECOND_TOPIC_MAX_GAP = 0.01
MIN_SUGGEST_DEPTH = 2       # no sugerir clases de 1 dígito (0-9): son demasiado generales
KNN_K = 7
KNN_MIN_SIM = 0.55
RERANKER_MIN_EVENTS = 30    # confirmaciones necesarias para entrenar el reranker

# Auxiliares propuestos por embeddings (experimental): similitud mínima y margen sobre el 2.º.
# common subió de 0.45 a 0.60: con bge-m3 real salía "-026" (sim 0.48-0.53) como ruido. Calibrar en Fase 2.
AUX_MIN_SIM = {"common": 0.60, "special": 0.45, "viewpoint": 0.50}
AUX_MARGIN = 0.03
# Orden de cita estándar de las auxiliares comunes tras la clase: lugar, tiempo, forma, idioma.
AUX_ORDER = ["place", "time", "form", "lang"]

# Lugar y tiempo
PLACE_MIN_SCORE = 3.0       # puntaje ponderado mínimo (título x5, resumen x2, índice x1.5, texto x1)
PLACE_DOMINANCE = 2.0       # el 1.º debe duplicar al 2.º
TIME_MIN_MENTIONS = 2

# ---------------------------------------------------------- verificación
CROSSREF_MAILTO = ""        # pon tu correo para el "polite pool" de Crossref (opcional)
VERIFY_TYPES = {"journalArticle", "book", "conferencePaper"}   # tipos que sí viven en catálogos
VERIFY_MIN_SIM = 0.90       # título >= esto => "verificado"; < 0.60 => "conflicto"
VERIFY_CONFLICT_SIM = 0.60

# ------------------------------------------------------------- LLM (opcional)
LLM_ENABLED = False
LLM_BASE_URL = "http://localhost:11434/v1"     # Ollama / llama.cpp / cualquier endpoint compatible OpenAI
LLM_MODEL = "qwen3.5:9b"
LLM_MAX_CHARS = 6000

# =========================================================== 1. ESQUEMA ZOTERO
# No se edita aquí: sale del schema.json oficial de Zotero y de zotero_overlay.json (tipos activos), los mismos
# archivos que usa el servidor (biblioteca_udc/server/zotero/), para que PoC, servidor y app no diverjan.
# El extractor produce un conjunto amplio de campos; solo se conservan en "fields" los que admite el tipo
# detectado. Lo demás va a "unmapped" (no se pierde). "creators", "tags" y "extra" siempre se permiten.
ZOTERO_DIR = BASE_DIR.parent / "biblioteca_udc" / "server" / "zotero"


def _load_zotero():
    import json
    schema = json.loads((ZOTERO_DIR / "schema.json").read_text(encoding="utf-8"))
    overlay = json.loads((ZOTERO_DIR / "zotero_overlay.json").read_text(encoding="utf-8"))
    enabled = overlay["enabled_types"]
    hidden = set(overlay.get("hidden_fields", []))
    by_type = {t["itemType"]: t for t in schema["itemTypes"]}
    types = {code: ["creators"] + [f["field"] for f in by_type[code]["fields"] if f["field"] not in hidden]
             for code in enabled}
    primary = {code: next((c["creatorType"] for c in by_type[code]["creatorTypes"] if c.get("primary")), "author")
               for code in enabled}
    return types, primary


ZOTERO_ITEM_TYPES, PRIMARY_CREATOR = _load_zotero()   # {tipo: [campos]}, {tipo: rol principal}
# Partituras, como indica Zotero: libro (o manuscrito) con "Type: musical_score" en Extra.
SCORE_ITEM_TYPE = "book"
SCORE_EXTRA = "Type: musical_score"
CRITICAL_FIELDS = ["title", "creators", "date"]

# ====================================================== 2. TIPO DE DOCUMENTO
# (regex, peso). Se evalúan sobre el texto de las primeras páginas (minúsculas).
DOCTYPE_RULES = {
    "patent": [(r"\(54\)", 3), (r"\(57\)\s*(abstract|r[ée]sum[ée]|zusammenfassung|resumen|resumo)", 3),
               (r"\b(patent|patente|brevet|brevetto|patentschrift|offenlegungsschrift|патент)\b|特許|专利", 2),
               (r"\b(inventors?|inventor(es|a)?|inventeurs?|erfinder|inventori)\b", 2),
               (r"\b(us|ep|wo)\s?\d{4}/?\d{5,}", 3), (r"\(72\)", 2)],
    "thesis": [(r"\b(thesis|dissertation|tesis|tesina|disertaci[oó]n|trabajo de grado|trabajo fin de|thèse|"
                r"mémoire|doktorarbeit|masterarbeit|diplomarbeit|tesi di laurea|tesi|tese|disserta[cç][aã]o|"
                r"proefschrift|avhandling|v[äa]it[öo]skirja|praca (?:magisterska|doktorska|dyplomowa)|"
                r"диссертация|дипломная)\b|学位論文|学位论文|博士论文", 3),
               (r"\b(universit\w*|universidad|uniwersytet|университет|hochschule|[ée]cole)\b|大学|大學", 1),
               (r"\b(doctor\w*|maestr[ií]a|licenciatura|master|ph\.?\s?d|dottorato|mestrado|doutorado|"
                r"kandidat|магистр|кандидат)\b", 2),
               (r"\b(director|asesor|advisor|supervisor|directeur|betreuer|relatore|orientador|"
                r"научный руководитель)\b", 1)],
    "report": [(r"\b(report|informe|reporte|rapport|bericht|relazione|relat[óo]rio|raport|отч[её]т|"
                r"white paper|working paper|documento de trabajo|document de travail|arbeitspapier)\b", 2),
               (r"\b(report no|informe n|technical report|reporte t[eé]cnico|rapport technique|"
                r"technischer bericht)\b", 2)],
    "journalArticle": [(r"\b(abstract|resumen|r[ée]sum[ée]|zusammenfassung|riassunto|resumo|streszczenie|"
                        r"аннотация)\b|摘要|要旨", 1),
                       (r"\b(keywords?|palabras clave|mots[- ]cl[ée]s|schl[üu]sselw[öo]rter|parole chiave|"
                        r"palavras[- ]chave|słowa kluczowe|ключевые слова)\b|关键词|キーワード", 1),
                       (r"\b10\.\d{4,9}/", 2), (r"\b(vol\.?|volume|volumen|band|bd\.|том)\s*\d+", 1),
                       (r"\b(journal|revista|revue|zeitschrift|rivista|tidskrift|czasopismo|журнал|issn)\b", 2)],
    "conferencePaper": [(r"\b(proceedings|conference|congreso|simposio|symposium|workshop|conf[ée]rence|congr[eè]s|"
                         r"colloque|actes|konferenz|tagung|tagungsband|convegno|congresso|atti|anais|"
                         r"конференция|труды)\b", 3)],
    "book": [(r"\bisbn\b", 3), (r"\b(editorial|ediciones|publisher|press|[ée]ditions|verlag|edizioni|editora|"
                                r"uitgeverij|f[öo]rlag|wydawnictwo|издательство)\b|出版社", 1),
             (r"\b([ií]ndice|table of contents|contents|contenido|table des mati[eè]res|sommaire|"
              r"inhaltsverzeichnis|inhalt|indice|sum[áa]rio|spis tre[śs]ci|содержание|оглавление)\b|目次|目录", 1),
             (r"all rights reserved|derechos reservados|todos los derechos|tous droits r[ée]serv[ée]s|"
              r"alle rechte vorbehalten|tutti i diritti riservati|todos os direitos reservados|"
              r"все права защищены", 2)],
    "standard": [(r"\b(iso|iec|astm|ieee std|une|nom|ansi|asme|din|nfpa|nf|jis|gost|гост|gb/t)"
                  r"[\s\-]?[a-z]?\d", 3),
                 (r"\b(standard|norma|norme|normativa|стандарт)\b", 1)],
    "bookSection": [(r"\b(chapter|cap[ií]tulo|chapitre|kapitel|capitolo|rozdział|глава)\s+\d+\b", 1),
                    (r"\b(in|en|dans|im)\s*:\s", 1),
                    (r"\b(eds?\.|editors?|coord(?:s|inadores)?\.?|hrsg\.|dir\.|a cura di|org\.|под ред\.)\s", 1)],
    "magazineArticle": [(r"\b(magazine|semanario|weekly|magazin|hebdomadaire|settimanale)\b", 2)],
    "newspaperArticle": [(r"\b(newspaper|peri[oó]dico|staff writer|corresponsal|edici[oó]n impresa|quotidien|"
                          r"zeitung|quotidiano|jornal|gazeta|газета)\b", 2),
                         (r"\b(times|gazette|herald|tribune|daily)\b", 1)],
    "encyclopediaArticle": [(r"\b(encyclop(?:a)?edia|enciclopedia|encyclop[ée]die|enzyklop[äa]die|enciclop[ée]dia|"
                             r"энциклопедия)\b|百科", 2)],
    "dictionaryEntry": [(r"\b(dictionary|diccionario|dictionnaire|w[öo]rterbuch|dizionario|dicion[áa]rio|"
                         r"woordenboek|ordbok|słownik|sözlük|словарь)\b|辞典|词典|辭典", 2)],
    "presentation": [(r"\b(slides?|diapositivas|presentaci[oó]n|presentation|pr[ée]sentation|pr[äa]sentation|"
                      r"vortrag|presentazione|apresenta[cç][aã]o|webinar|keynote|ponencia|доклад)\b", 2)],
    "manuscript": [(r"\b(manuscript|manuscrito|manuscrit|manuskript|manoscritto|рукопись|unpublished|"
                    r"in preparation|sin publicar|in[ée]dit|unver[öo]ffentlicht|borrador|draft|brouillon|"
                    r"entwurf)\b", 2)],
    "letter": [(r"\b(dear|estimad[oa]s?|querid[oa]s?|cher|ch[èe]re|sehr geehrte[rn]?|liebe[rn]?|"
                r"gentile|prezad[oa]|уважаем\w*)\b", 1),
               (r"\b(sincerely|yours truly|atentamente|cordialmente|saludos cordiales|cordialement|"
                r"mit freundlichen gr[üu](?:ß|ss)en|distinti saluti|atenciosamente|с уважением)\b", 2)],
    "map": [(r"\b(scale|escala|[ée]chelle|ma(?:ß|ss)stab|scala|масштаб)\s*1\s*:\s*[\d.,\s]{3,}", 4),
            (r"\b(map|mapa|carte|karte|carta geografica|карта|cartograf\w*|cartograph\w*|kartograph\w*|"
             r"legend|leyenda|l[ée]gende)\b", 1)],
    "artwork": [(r"\b(oil on canvas|[oó]leo sobre|huile sur toile|[öo]l auf leinwand|olio su tela|"
                 r"watercolou?r|acuarela|aquarelle|aquarell|acquerello|sculpture|escultura|skulptur|scultura|"
                 r"lithograph|litograf[ií]a|lithographie)\b", 3)],
    "case": [(r"\b(supreme court|court of appeals?|suprema corte|tribunal supremo|tribunal colegiado|juzgado|"
              r"cour de cassation|conseil d'[ée]tat|cour d'appel|bundesgerichtshof|bundesverfassungsgericht|"
              r"corte di cassazione|supremo tribunal|верховный суд)\b", 3),
             (r"\b(plaintiff|defendant|appellant|demandante|demandado|quejoso|sentencia|amparo|arr[eê]t|"
              r"urteil|sentenza|ac[óo]rd[ãa]o)\b", 2)],
    "statute": [(r"\b(diario oficial|official journal|bolet[ií]n oficial|gaceta oficial|federal register|"
                 r"journal officiel|bundesgesetzblatt|gazzetta ufficiale|di[áa]rio oficial|dziennik ustaw)\b", 3),
                (r"\b(ley|decreto|reglamento|act|statute|loi|d[ée]cret|gesetz|verordnung|legge|lei|закон)\b", 1),
                (r"\b(art[ií]culo|article|section|artikel|articolo|artigo|статья)\s+\d+", 1),
                (r"\b(se expide|decreta|promulga|enacted|promulgu[ée]|verk[üu]ndet|promulgata)\b", 2)],
    # "score" no es un tipo de Zotero: activa la regla de partituras (SCORE_ITEM_TYPE + SCORE_EXTRA).
    # Sin falsos amigos: "partition" (matemáticas en inglés), "largo"/"lento" (español corriente).
    "score": [(r"\b(partitura|score|sheet music|noten|spartito|op\.\s?\d+|bwv\s?\d+|"
               r"allegro|andante|andantino|moderato|adagio|presto)\b", 2),
              (r"\b(piano|klavier|pianoforte|violin|viol[ií]n|violon|violine|geige|violino|cello|guitar|guitarra|"
               r"guitare|gitarre|orchestra|orquesta|orchestre|orchester|flute|flauta|fl[uû]te|fl[öo]te)\b", 1),
              (r"\b(arr\.|arreglo|bearbeitung|transcription|transcripci[oó]n|imslp)\b", 1)],
}
# Tipos que solo cuentan si su PRIMERA regla (la palabra que los define) aparece; las demás solo suman.
# Evita que un libro sea "tesis" porque la contraportada cita "Maestría en…, University of…".
DOCTYPE_NEEDS_FIRST = {"thesis"}
BOOK_MIN_PAGES = 120       # más páginas => sesga hacia libro
# Zotero desaconseja "document": sin señales claras se propone libro, con confianza baja.
DEFAULT_DOCTYPE = "book"

# ===================================================== 3. TABLA DE FORMA (0...)
# Se resuelve contra las ETIQUETAS del árbol (inglés): se busca la primera palabra clave
# contenida en la etiqueta de un nodo de forma. Revisa con:  python -m udcpoc tree --kind form
# Un libro "normal" NO lleva forma: (02) Books in general no informa nada en la práctica UDC.
FORM_BY_DOCTYPE = {          # se elige la notación más corta cuya etiqueta contiene la palabra
    "thesis": ["academic theses", "theses"],                 # (043.2)
    "patent": ["patent"],                                    # (088.8)
    "standard": ["standards"],                               # (083.74)
    "statute": ["legal sources"],                            # (094)
    "case": ["courts of justice", "legal sources"],          # (094.8)
    "report": ["report"],                                    # (047)
    "conferencePaper": ["conference", "congress"],
    "journalArticle": ["articles in serials"],               # (045): un artículo, no la revista (05)
    "magazineArticle": ["articles in serials"],
    "newspaperArticle": ["newspaper articles", "newspaper"],  # (046)
    "letter": ["correspondence"],                            # (044)
    "presentation": ["lectures"],                            # (042)
    "dictionaryEntry": ["dictionar"],
    "encyclopediaArticle": ["encyclop"],
    "map": ["cartographic", "map", "atlas"],                 # (084.3)
}
# Texto para la educación superior: si se detecta "texto educativo" (075) y aparece esto, se usa (075.8).
FORM_HIGHER_ED = (r"\b(universit\w*|universidad|college|undergraduate|graduate|engineer\w*|ingenier\w*|scientists|"
                  r"cient[ií]ficos|licenciatura|higher education|enseñanza superior|hochschule|\d+(st|nd|rd|th) "
                  r"edition|\d+\s?(a|ª)\.? edici[oó]n|\d+\.\s?auflage|\d+e [ée]dition)\b")
# Se evalúan en orden sobre título + nombre del archivo + resumen; gana la primera que encaje.
FORM_BY_TEXT = [
    # hojas de datos de componentes: publicación comercial de un fabricante (085)
    (r"\b(datasheet|data sheet|absolute maximum ratings|electrical characteristics|ordering information|"
     r"typical applications|pin configuration|package information)\b", ["publications of business firms"]),
    (r"\b(schaum'?s|schaum|outline series|solucionario|solutions? manual|problemas resueltos|ejercicios|"
     r"exercises|problem book|aufgaben|"
     r"[üu]bungen|exercices|esercizi|exerc[ií]cios|workbook|cuaderno de|cahier d|упражнения|задачи|"
     r"задачник)\b", ["practical instruction"]),                                            # (076)
    (r"\b(diccionario|dictionary|dictionnaire|w[öo]rterbuch|dizionario|dicion[áa]rio|woordenboek|słownik|"
     r"словарь|glosario|glossary|glossaire|glossar)\b|辞典|词典", ["dictionar", "glossar"]),
    (r"\b(manual|handbook|handbuch|manuale|gu[ií]a pr[aá]ctica|vademecum|prontuario|справочник|"
     r"руководство)\b", ["handbook", "manual"]),                                            # (035)
    (r"\b(enciclopedia|encyclop|enzyklop|энциклопедия)", ["encyclop"]),
    (r"\b(bibliograf[ií]a anotada|annotated bibliography|bibliographie comment[ée]e)\b", ["bibliograph"]),
    (r"\b(atlas|атлас)\b", ["atlas"]),
    (r"\b(ansi|asme|iso|din|astm|nfpa|ieee std|jis|gost|гост)\s?[a-z]?\d", ["normative"]),  # (083)
    (r"\b(libro de texto|textbook|lehrbuch|manuel scolaire|libro di testo|livro did[áa]tico|учебник|"
     r"a first course|first course|introduction to|introducci[oó]n a|introduction [àa]|einf[üu]hrung in|"
     r"introduzione a|introdu[cç][aã]o [àa]|введение в|fundamentals of|fundamentos de|grundlagen der|"
     r"principles of|principios de|principes de|curso de|cours de|corso di|lecciones de|le[cç]ons de|"
     r"\d+(st|nd|rd|th) edition|\d+\s?(a|ª|ra|da|ta|va)\.? edici[oó]n|\d+\.\s?auflage|\d+e [ée]dition)\b",
     ["educational texts"]),                                                                # (075)
    (r"\b(antolog[ií]a|anthology|anthologie|антология)\b", ["anthology"]),
]

# ============================================ 4. IDIOMAS DE LOS DOCUMENTOS
# El idioma de los documentos no se asume: se detecta (py3langid, ~140 idiomas) y la tabla de lengua "=" se
# resuelve con el nombre inglés del idioma (CLDR, paquete babel) contra las etiquetas del árbol.
LANG_MIN_CONF = 0.5         # por debajo, el idioma queda "desconocido" (texto escaso o basura de OCR)
LANGID_LANGS = None        # None = todos los idiomas del detector; o una lista ISO 639-1 para restringirlo
# Solo donde el nombre CLDR no coincide con la etiqueta UDC (verificado contra el árbol). None = sin nodo.
LANG_UDC = {
    "bn": "=214.32", "km": "=612.4", "ky": "=512.154", "si": "=214.61", "ug": "=512.132", "gd": "=152.2",
    "fy": "=112.45", "fo": "=113.2", "nn": "=113.5", "no": "=113.5", "nb": "=113.5", "hbo": "=411.161",
    "ary": "=411.21", "arz": "=411.21", "ace": "=621.252.1", "rw": "=432.846.2", "se": "=511.12",
    "sdh": "=222.5", "ltg": "=174", "mn": "=512.3", "ht": "=133.18", "bs": "=163.4", "id": "=621.25",
    "wuu": "=581", "yue": "=581", "dz": "=584.6", "zxx": None,
}

# ======================== 5. LUGARES
# Los nombres de países y regiones salen de CLDR en el idioma del documento (+ inglés) y se llevan al nodo
# de la tabla de lugar por su nombre inglés. Aquí solo van las excepciones, verificadas contra el árbol.
TERRITORY_UDC = {            # código CLDR -> notación UDC, cuando el nombre inglés no coincide
    "CZ": "(437.3)", "TR": "(560)", "CI": "(666.8)", "CD": "(675)", "CG": "(672.4)", "HK": "(512.317)",
    "MO": "(512.318)", "VA": "(456.31)", "MM": "(591)", "BA": "(497.6)", "AG": "(729.76)", "TT": "(729.87)",
    "LC": "(729.822)", "KN": "(729.73)", "VC": "(729.824)", "ST": "(669.95)", "FO": "(491.2)",
    "CW": "(729.882.1)", "GF": "(882)", "NC": "(932)", "WF": "(961.7)", "SJ": "(984.1)", "SH": "(699.2)",
    "TC": "(729.68)", "VI": "(729.71)", "BL": "(729.743)", "PM": "(718.9)", "CC": "(592.5)", "EA": "(647)",
    "MX": "(720)", "GM": "(665.1)", "IC": "(460.41)",
    "001": "(100)", "002": "(6)", "150": "(4)", "009": "(9)", "029": "(729)", "011": "(66)", "035": "(59)",
    "017": "(674)",
    # Sin nodo propio en el UDC (abarcan varias clases): se ignoran a propósito.
    "019": None, "419": None, "005": None, "013": None, "021": None, "202": None, "142": None, "QO": None,
}
# Nombres que CLDR no trae (abreviaturas, nombres históricos o coloquiales), por idioma del documento.
# Valor: código CLDR o notación UDC.
PLACE_ALIASES = {
    "en": {"USA": "US", "U.S.A.": "US", "UK": "GB", "Great Britain": "GB", "Holland": "NL", "Burma": "MM",
           "Ivory Coast": "CI", "West Indies": "(729)", "Antilles": "(729)"},
    "es": {"EE. UU.": "US", "EE.UU.": "US", "EUA": "US", "Gran Bretaña": "GB", "Holanda": "NL",
           "Antillas": "(729)", "Indias Occidentales": "(729)", "Nueva España": "MX"},
    "fr": {"Antilles": "(729)", "Hollande": "NL"},
    "de": {"Holland": "NL", "Antillen": "(729)"},
    "pt": {"Holanda": "NL", "Antilhas": "(729)"},
    "it": {"Olanda": "NL", "Antille": "(729)"},
}

# Palabras que indican "esto es una organización/encabezado, no una persona".
ORG_HINTS = (r"universi\w*|uniwersytet|университет|hochschule|facultad|faculty|facult[ée]|fakult[äa]t|"
             r"facolt[àa]|faculdade|instituto|institute|institut|istituto|институт|department|departamento|"
             r"d[ée]partement|abteilung|dipartimento|escuela|school|[ée]cole|schule|scuola|escola|centro|center|"
             r"centre|zentrum|laboratorio|laboratory|laboratoire|labor|press|editorial|[ée]ditions|verlag|"
             r"edizioni|editora|journal|revista|revue|zeitschrift|rivista|abstract|resumen|r[ée]sum[ée]|"
             r"zusammenfassung|keywords|palabras|mots|tesis|thesis|th[eè]se|tesi|tese|informe|report|rapport|"
             r"bericht|congreso|conference|conf[ée]rence|konferenz|proceedings|copyright|isbn|issn|derechos|"
             r"droits|rechte|diritti|direitos|rights|licen[cs]e|lizenz|www|http|doi|volume|volumen|band|"
             r"n[úu]mero|number|num[ée]ro|nummer")
