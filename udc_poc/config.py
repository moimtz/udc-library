"""
CONFIGURACIÓN EDITABLE DEL PoC UDC
==================================
Casi todo lo que querrás ajustar está en este archivo:

  1. ZOTERO_ITEM_TYPES  -> qué tipos de ítem y qué campos de Zotero se rellenan.
  2. CRITICAL_FIELDS    -> campos que marcan "incompleto" si faltan.
  3. DOCTYPE_RULES      -> palabras clave para detectar el tipo de documento.
  4. FORM_BY_DOCTYPE / FORM_BY_TEXT -> reglas de la tabla auxiliar de forma (0...).
  5. LANG_NAMES / PLACE_ALIASES_ES  -> idiomas y lugares (nombre en español -> etiqueta inglesa del UDC).
  6. Umbrales y pesos de la clasificación (se calibran en la Fase 2).
"""
from pathlib import Path

# ----------------------------------------------------------------- rutas
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
UDC_RDF = DATA_DIR / "udcs-skos.rdf"          # copia aquí tu archivo
INDEX_DIR = DATA_DIR / "index"                # embeddings del árbol (se regeneran solos)
FEEDBACK_DB = DATA_DIR / "feedback.db"        # SOLO confirmaciones; nunca toca biblioteca.db
RERANKER_PATH = DATA_DIR / "reranker.pkl"

# ------------------------------------------------------------ embeddings
EMBEDDING_MODEL = "BAAI/bge-m3"                # ~2.3 GB, multilingüe. Respaldo: "intfloat/multilingual-e5-small"
EMBEDDING_DEVICE = "cpu"                       # déjalo en cpu: la GPU es para el agente
LABEL_LANGS = ["en", "sv", "fi"]               # orden de preferencia de etiquetas del RDF

# ------------------------------------------------------------ lectura PDF
HEAD_PAGES = 6              # primeras páginas leídas
TAIL_PAGES = 3              # últimas páginas leídas
MIN_CHARS_PER_PAGE = 100    # menos que esto (promedio) => se considera escaneado
OCR_MAX_PAGES = 6           # páginas máximas a pasar por OCR
OCR_LANGS = "spa+eng"       # idiomas de Tesseract (requiere spa.traineddata)
OCR_DPI = 300               # resolución del render para OCR
TESSDATA_DIR = None         # None = autodetección; si falla: r"C:\Program Files\Tesseract-OCR\tessdata"

# ----------------------------------------------------- clasificación UDC
# Peso de cada "vista" del documento al compararlo con el árbol.
VIEW_WEIGHTS = {"front": 0.45, "toc": 0.20, "body": 0.25, "tail": 0.10}
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
# Orden en que se anexan las auxiliares "globales" a la notación.
AUX_ORDER = ["lang", "form", "place", "time"]

# Lugar y tiempo
PLACE_MIN_SCORE = 4.0       # puntaje ponderado mínimo (título x5, resumen x2, resto x1)
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
# Para añadir/quitar ítems o campos edita estas listas. El extractor produce un conjunto
# amplio de campos; solo se conservan en "fields" los que estén en la lista del tipo
# detectado. Lo demás va a "unmapped" (no se pierde). "tags" y "extra" siempre se permiten.
ZOTERO_ITEM_TYPES = {
    "book": ["title", "creators", "abstractNote", "series", "seriesNumber", "volume", "edition",
             "place", "publisher", "date", "numPages", "language", "ISBN", "url"],
    "journalArticle": ["title", "creators", "abstractNote", "publicationTitle", "volume", "issue",
                       "pages", "date", "language", "DOI", "ISSN", "url"],
    "conferencePaper": ["title", "creators", "abstractNote", "proceedingsTitle", "conferenceName",
                        "place", "publisher", "date", "pages", "language", "DOI", "ISBN", "url"],
    "thesis": ["title", "creators", "abstractNote", "thesisType", "university", "place", "date",
               "numPages", "language", "url"],
    "report": ["title", "creators", "abstractNote", "reportNumber", "reportType", "seriesTitle",
               "place", "institution", "date", "pages", "language", "url"],
    "patent": ["title", "creators", "abstractNote", "place", "country", "assignee", "issuingAuthority",
               "patentNumber", "applicationNumber", "filingDate", "issueDate", "date", "language", "url"],
    "preprint": ["title", "creators", "abstractNote", "date", "language", "DOI", "url", "repository",
                 "archiveID"],
    "standard": ["title", "creators", "abstractNote", "organization", "number", "date", "language", "url"],
    # Partituras, manuales y literatura gris sin tipo propio caen aquí:
    "document": ["title", "creators", "abstractNote", "publisher", "date", "language", "url"],
}
# Las partituras se guardan como "document" y se distinguen con una nota en "extra".
SCORE_ITEM_TYPE = "document"
CRITICAL_FIELDS = ["title", "creators", "date"]

# ====================================================== 2. TIPO DE DOCUMENTO
# (regex, peso). Se evalúan sobre el texto de las primeras páginas (minúsculas).
DOCTYPE_RULES = {
    "patent": [(r"\(54\)", 3), (r"\(57\)\s*abstract", 3), (r"\bpatent\b", 2), (r"\binventors?\b", 2),
               (r"\b(us|ep|wo)\s?\d{4}/?\d{5,}", 3), (r"\bpatente\b", 2), (r"\(72\)", 2)],
    "thesis": [(r"\b(tesis|thesis|dissertation|tesina|disertaci[oó]n|trabajo de grado|trabajo fin de)\b", 3),
               (r"\b(universidad|university|universit[ée])\b", 1),
               (r"\b(doctor|doctorado|maestr[ií]a|licenciatura|master|ph\.?\s?d)\b", 2),
               (r"\b(director|asesor|advisor|supervisor)\b", 1)],
    "report": [(r"\b(informe|report|reporte|white paper|working paper|documento de trabajo)\b", 2),
               (r"\b(report no|informe n|technical report|reporte t[eé]cnico)\b", 2)],
    "journalArticle": [(r"\babstract\b|\bresumen\b", 1), (r"\bkeywords?\b|palabras clave", 1),
                       (r"\b10\.\d{4,9}/", 2), (r"\b(vol\.?|volume|volumen)\s*\d+", 1),
                       (r"\b(journal|revista|issn)\b", 2)],
    "conferencePaper": [(r"\b(proceedings|conference|congreso|simposio|symposium|workshop)\b", 3)],
    "book": [(r"\bisbn\b", 3), (r"\b(editorial|ediciones|publisher|press)\b", 1),
             (r"\b([ií]ndice|table of contents|contents|contenido)\b", 1),
             (r"all rights reserved|derechos reservados|todos los derechos", 2)],
    "standard": [(r"\b(iso|iec|astm|ieee std|une|nom|ansi|asme|din|nfpa)[\s\-]?[a-z]?\d", 3),
                 (r"\b(standard|norma|especificaci[oó]n)\b", 1)],
    "score": [(r"\b(partitura|score|sheet music|op\.\s?\d+|allegro|andante|moderato|adagio|presto)\b", 2),
              (r"\b(piano|violin|violín|cello|guitar|guitarra|orchestra|orquesta|flute|flauta)\b", 1),
              (r"\b(arr\.|arreglo|transcription|transcripci[oó]n|imslp)\b", 1)],
}
BOOK_MIN_PAGES = 120        # más páginas => sesga hacia libro
DEFAULT_DOCTYPE = "document"

# ===================================================== 3. TABLA DE FORMA (0...)
# Se resuelve contra las ETIQUETAS del árbol (inglés): se busca la primera palabra clave
# contenida en la etiqueta de un nodo de forma. Revisa con:  python -m udcpoc tree --kind form
# Un libro "normal" NO lleva forma: (02) Books in general no informa nada en la práctica UDC.
FORM_BY_DOCTYPE = {
    "thesis": ["dissertation", "thesis", "theses"],
    "patent": ["patent"],
    "standard": ["normative"],              # (083) Technical and normative documents
    "report": ["report"],
    "conferencePaper": ["conference", "congress"],
    "journalArticle": ["periodical", "serial"],
}
# Se evalúan en orden sobre título + nombre del archivo + resumen; gana la primera que encaje.
FORM_BY_TEXT = [
    (r"\b(solucionario|solutions? manual|problemas resueltos|ejercicios|exercises|problem book|aufgaben|"
     r"workbook|cuaderno de)\b", ["practical instruction"]),                       # (076)
    (r"\b(diccionario|dictionary|dictionnaire|glosario|glossary)\b", ["dictionar", "glossar"]),
    (r"\b(manual|handbook|gu[ií]a pr[aá]ctica|vademecum|prontuario)\b", ["handbook", "manual"]),  # (035)
    (r"\b(enciclopedia|encyclop)", ["encyclop"]),
    (r"\b(bibliograf[ií]a anotada|annotated bibliography)\b", ["bibliograph"]),
    (r"\b(atlas)\b", ["atlas"]),
    (r"\b(ansi|asme|iso|din|astm|nfpa|ieee std)\s?[a-z]?\d", ["normative"]),        # (083)
    (r"\b(libro de texto|textbook|a first course|first course|introduction to|introducci[oó]n a|"
     r"fundamentals of|fundamentos de|curso de|lecciones de|principles of|principios de|"
     r"\d+(st|nd|rd|th) edition|\d+\s?(a|ª|ra|da|ta|va)\.? edici[oó]n)\b", ["educational texts"]),  # (075)
    (r"\b(antolog[ií]a|anthology)\b", ["anthology"]),
]

# ============================================ 4. IDIOMAS (ISO 639-1 -> etiqueta UDC en inglés)
LANG_NAMES = {
    "es": "Spanish", "en": "English", "fr": "French", "de": "German", "it": "Italian",
    "pt": "Portuguese", "ca": "Catalan", "gl": "Galician", "eu": "Basque", "la": "Latin",
    "nl": "Dutch", "sv": "Swedish", "fi": "Finnish", "da": "Danish", "no": "Norwegian",
    "ru": "Russian", "pl": "Polish", "cs": "Czech", "el": "Greek", "tr": "Turkish",
    "ar": "Arabic", "he": "Hebrew", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
}

# ======================== 5. LUGARES (nombre en español -> etiqueta inglesa de la tabla de lugar)
PLACE_ALIASES_ES = {
    "España": "Spain", "México": "Mexico", "Estados Unidos": "United States", "EE. UU.": "United States",
    "Reino Unido": "United Kingdom", "Gran Bretaña": "United Kingdom", "Francia": "France",
    "Alemania": "Germany", "Italia": "Italy", "Portugal": "Portugal", "Argentina": "Argentina",
    "Chile": "Chile", "Colombia": "Colombia", "Perú": "Peru", "Venezuela": "Venezuela", "Cuba": "Cuba",
    "Brasil": "Brazil", "Rusia": "Russia", "China": "China", "Japón": "Japan", "India": "India",
    "Canadá": "Canada", "Grecia": "Greece", "Egipto": "Egypt", "Europa": "Europe", "África": "Africa",
    # "América Latina" no existe en el Summary (abarca (7) y (8)); se omite a propósito.
    "Bolivia": "Bolivia", "Ecuador": "Ecuador", "Uruguay": "Uruguay",
    "Paraguay": "Paraguay", "Guatemala": "Guatemala", "Costa Rica": "Costa Rica", "Panamá": "Panama",
    "Honduras": "Honduras", "Nicaragua": "Nicaragua", "El Salvador": "El Salvador",
    # El Summary no detalla el Caribe: República Dominicana y Puerto Rico van a (729) Caribbean territories.
    "República Dominicana": "Caribbean territories", "Puerto Rico": "Caribbean territories",
    "Caribe": "Caribbean territories", "Países Bajos": "Netherlands",
    "Holanda": "Netherlands", "Suiza": "Switzerland", "Suecia": "Sweden", "Noruega": "Norway",
    "Dinamarca": "Denmark", "Finlandia": "Finland", "Polonia": "Poland", "Turquía": "Turkey",
    "Irán": "Iran", "Irak": "Iraq", "Israel": "Israel", "Corea": "Korea", "Australia": "Australia",
    "Marruecos": "Morocco", "Argelia": "Algeria", "Sudáfrica": "South Africa",
    "Oceanía": "States and regions of the South Pacific",  # (9) en el Summary
}

# Palabras que indican "esto es una organización/encabezado, no una persona".
ORG_HINTS = (r"universidad|university|facultad|faculty|instituto|institute|department|departamento|escuela|school|"
             r"centro|center|centre|laboratorio|laboratory|press|editorial|journal|revista|abstract|resumen|"
             r"keywords|palabras|tesis|thesis|informe|report|congreso|conference|proceedings|copyright|isbn|issn|"
             r"derechos|rights|licen[cs]e|www|http|doi|volume|volumen|número|number")
