# PoC de clasificación UDC (Fase 1) — sin LLM por defecto

Sugiere una notación UDC **completa** (clase principal + tablas auxiliares) y rellena metadatos estilo Zotero
para PDF sin DOI/ISBN/arXiv. Corre en **CPU**, con modelos locales y recursos gratuitos. No toca `biblioteca.db`.

## 1. Instalación (Windows 11, laptop de pruebas)

```powershell
cd udc_poc
python -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```
1. El árbol UDC se lee de `biblioteca_udc/server/udc_data/udcs-skos.rdf` (lo escribe la fusión del árbol; `UDC_RDF` en `config.py`). No hay que copiarlo.
2. La primera vez, `bge-m3` se descarga (~2.3 GB) desde Hugging Face (gratis). Respaldo ligero: en `config.py`
   cambia `EMBEDDING_MODEL` a `intfloat/multilingual-e5-small`.
3. Opcionales: `py3langid` y `langdetect` (idioma), `gliner` (autores, flag `--ner`). Todos instalan en
   Python 3.15 sin compilador (lingua y rapidocr-onnxruntime se descartaron: no tienen wheels para 3.15).
4. OCR (flag `--ocr`): usa **Tesseract** a través de PyMuPDF; no hay paquete pip. En Windows:
   ```powershell
   winget install UB-Mannheim.TesseractOCR    # en el instalador, marca el idioma "Spanish"
   ```
   Modelos de todos los idiomas (126) y scripts (37), ~670 MB, en la carpeta del programa (PowerShell **como
   administrador**; `robocopy` no sobrescribe los que ya instaló el instalador):
   ```powershell
   git clone --depth 1 https://github.com/tesseract-ocr/tessdata_fast $env:TEMP\tessdata_fast
   robocopy $env:TEMP\tessdata_fast "C:\Program Files\Tesseract-OCR\tessdata" /E /XC /XN /XO /XD .git
   Remove-Item -Recurse -Force $env:TEMP\tessdata_fast
   ```
   `config.TESSDATA_DIR` usa esa carpeta si tiene `script\Latin.traineddata` (si no, `data\tessdata`). Con `OCR_LANGS = "auto"` no se usan todos a la vez (sería lento
   e impreciso): se hace OCR de prueba con el modelo de script latino, se detecta el idioma y se usa
   `<idioma>+eng`; si el texto no es latino, OSD (`TESSERACT_EXE`) detecta el script (hebreo, cirílico, árabe…).
   El motivo queda en `ocr_langs` de `results.json`. Para fijar idiomas: `OCR_LANGS = "fra+eng"` (por ejemplo).

   **Páginas leídas:** las primeras `HEAD_PAGES` y últimas `TAIL_PAGES` páginas *con contenido*, buscando hasta
   `SCAN_LIMIT` por extremo. Se saltan páginas vacías (sin texto y sin tinta: guardas, portadas lisas,
   "intentionally left blank"), capas de texto basura (OCR viejo sobre tapas decoradas) y páginas que tras el
   OCR no dan texto legible (música, grabados, manuscritos); tras `OCR_GIVE_UP` seguidas se deja de buscar en
   ese extremo. `results.json` registra `pages_used` y `blank_skipped`. Umbrales: `BLANK_INK`,
   `MIN_LANG_CONF`, `MIN_TEXT_QUALITY`, `OCR_MAX_ATTEMPTS`.

## 2. Flujo de trabajo

```powershell
python -m udcpoc index                       # 1) carga el RDF, muestra estadísticas, crea el índice
python -m udcpoc tree --kind form            # 2) inspecciona qué trae tu árbol (form, place, lang, time, common, special, main)
python -m udcpoc sample C:\libros --n 28     # 3) elige la muestra estratificada -> output\sample_plan.csv
python -m udcpoc run C:\libros_muestra       # 4) procesa PDF -> output\results.json
python -m udcpoc review --blind              # 5) revisa/confirma (con --blind primero escribes tu UDC a ciegas)
python -m udcpoc evaluate                    # 6) métricas contra output\gold.csv
python -m udcpoc validate "94(460)\"18\""    # utilidad: valida cualquier notación
```
Para procesar la muestra elegida por `sample`: `python -m udcpoc run --plan output\sample_plan.csv`.
El nombre del archivo se usa como pista de título/autores/edición/año (fuente `filename`): confirma lo que
ya trae el PDF y solo gana por sí mismo cuando el texto lo respalda. `gold.csv` deja vacías las columnas de
metadatos "verdaderos" (llénalas a mano si quieres métricas de campos); `*_detectado` es lo que extrajo el sistema.
Flags útiles de `run`: `--limit 5`, `--resume`, `--ocr`, `--ner`, `--verify` (Crossref/OpenLibrary, solo anota),
`--llm` (opcional, ver §6). **Empieza por `index` y mándame su salida**: no he visto tu RDF real y ahí se calibra
la detección de tablas auxiliares.

### 2.1 Documentos en cualquier idioma
El PoC no asume el idioma de los documentos (el de la interfaz es otra cosa: los mensajes están en español).
- **Idioma**: `py3langid` con todos sus ~140 idiomas. La tabla de lengua `=` se resuelve con el nombre inglés del
  idioma (CLDR, paquete `babel`) contra el árbol: 126 de los 140 tienen nodo UDC.
- **Lugar**: siempre se buscan las etiquetas inglesas del árbol y, además, los nombres de países y regiones de
  CLDR **en el idioma del documento** (Mexiko, Мексика, メキシコ, المكسيك…), con declinación en idiomas con casos
  (Испании, Polski, Mexikos). Los nombres de país mandan sobre homónimos del árbol (India ≠ Indian Ocean). Al
  correr `index` se listan los países sin nodo; se arreglan en `TERRITORY_UDC` (código CLDR -> notación).
- **Fechas**: meses del idioma del documento + inglés + los nombres no ambiguos de cualquier idioma CLDR.
- **Tipo, forma, resumen, palabras clave, edición, editorial, siglos, nombres de persona**: vocabulario de los
  idiomas principales (en, es, fr, de, it, pt, nl, pl, ru y otros); los nombres admiten alfabetos latino, griego
  y cirílico. Para otros idiomas la clasificación temática no depende de esto: bge-m3 es multilingüe.
- **OCR**: idioma detectado por documento (ver §1.4); sin detección fiable, modelo de alfabeto latino.

### Cómo armar el gold sin sesgo
Con 25-30 PDF de `sample_plan.csv`, usa `review --blind`: escribes **tu** UDC antes de ver la sugerencia. Si solo
aceptas la sugerencia, las métricas medirán tu tendencia a aceptar, no la calidad. Como estás aprendiendo UDC,
espera ruido en tus etiquetas; el sistema lo aprenderá también.

Tras escribir tu UDC, **Enter** la guarda tanto en el gold como en el aprendizaje. Si ya tienes tus notaciones
decididas, ponlas en `books\gold\udc_gold.csv` (columnas `file,udc,nota`; `file` = nombre del PDF):
`review --blind` las toma de ahí sin preguntar (y pregunta solo las que falten). Otro archivo: `--answers ruta.csv`;
desactivarlo: `--answers ""`. Revisar de nuevo un documento reemplaza su ejemplo de aprendizaje (no lo duplica).

### 2.2 Partituras
Se detectan por **pentagramas** (`udcpoc/music.py`): cinco líneas equidistantes repetidas, buscadas en unas pocas
páginas a baja resolución. No dependen del idioma ni del texto (en «Sobre las olas» el texto «Rosas» llevaba a la
botánica). Es partitura si la mayoría de las páginas miradas tienen pentagramas con poco texto, o basta una si el
archivo viene de IMSLP/MuseScore/LilyPond… Un libro **sobre** música (armonía, orquestación, contrapunto,
ejercicios…) no lo es aunque traiga ejemplos. Para una partitura la 1.ª sugerencia sale de reglas dentro de 78:
- **género o agrupación** por palabras clave multilingües: ópera `782`, religiosa `783`, canción `784.3`, coro
  `784.1`, orquesta `785.11`, concierto `785.6`, cámara `785.72-.79`;
- si no hay palabras: **pentagramas por sistema** (2 teclado, 3 voz y piano, 4 cuarteto, 8+ orquesta);
- instrumento solista → `780.8:instrumento` (`780.616.433` piano, `780.616.31` clave, `780.614.332` violín…);
- **forma** con `:` (`78.083.2` variaciones, `78.083.3` tocata, `78.085.2` vals…). Ejemplo:
  `780.8:780.616.433:78.083.3`. El idioma solo se añade si la obra es vocal.
Umbrales: `SCORE_*` en `config.py`. Las sugerencias 2 y 3 se limitan a la rama 78.

### 2.3 Identificador primero (ISBN, DOI, arXiv)
`run` consulta por identificador **antes** de heurísticas o IA (`udcpoc/enrich.py`; `--offline` lo desactiva):
- **Open Library** (ISBN): título, editorial, lugar, fecha, páginas, **temas** y clasificación **LC/Dewey**;
- **Crossref** (DOI): título, autores, revista, editorial, fecha, volumen, número, páginas, ISSN;
- **arXiv**: título, autores, fecha, resumen y categorías (cs.CL…), traducidas a texto;
- **UDC de catálogo**: la Biblioteca Nacional de Polonia (MARC 080) cuando el libro está en su catálogo. Open
  Library, Crossref y arXiv **no** traen UDC; la UDC está en catálogos nacionales (Polonia, España, Chequia,
  Eslovenia, Croacia…). Si llega una UDC válida, es la 1.ª sugerencia.

Los campos externos entran con confianza 0.9 (ganan a lo extraído del PDF); si el título del catálogo coincide
con el del PDF se conserva el más completo. Los temas y las clases LC/Dewey (en texto) forman la vista
`subjects` del clasificador, con peso 0.3 (calibrado con el gold: más peso arrastra a clases vecinas).
Solo se envía el identificador; las respuestas quedan en `data/lookup_cache.json`.

## 3. Dónde editar (todo en `config.py`)

| Qué | Variable |
|---|---|
| Ítems de Zotero y sus campos | No se editan aquí: `ZOTERO_ITEM_TYPES` se lee de `biblioteca_udc/server/zotero/` (el `schema.json` oficial de Zotero + `zotero_overlay.json`, los mismos que usa el servidor). Tipos activos: `enabled_types` del overlay |
| Campos críticos (marcan "incompleto") | `CRITICAL_FIELDS` |
| Cómo se detecta el tipo de documento | `DOCTYPE_RULES` (regex y pesos) |
| Tabla de forma `(0...)` | `FORM_BY_DOCTYPE`, `FORM_BY_TEXT` (palabras clave que se buscan en las **etiquetas inglesas** del árbol) |
| Idiomas y lugares | Automático para cualquier idioma (ver §2.1). Excepciones: `LANG_UDC`, `TERRITORY_UDC`, `PLACE_ALIASES`; restringir el detector: `LANGID_LANGS` |
| Partituras | `SCORE_ITEM_TYPE` + `SCORE_EXTRA` (como indica Zotero: `book` con `Type: musical_score` en `extra`) |
| Umbrales y pesos | `LOW_CONFIDENCE`, `MIN_SIM`, `AUX_MIN_SIM`, `DEFAULT_WEIGHTS`, `VIEW_WEIGHTS`, … |
| Cuándo un ejemplo de combinación gana a su clase | `EXAMPLE_MARGIN` (ver §4.1) |
| Clases alternativas por "See also" | `SEE_ALSO_FROM`, `SEE_ALSO_MAX` (ver §4.2) |
| Orden de auxiliares en la notación | `AUX_ORDER` |

Para añadir un tipo nuevo (p. ej. `computerProgram`): actívalo en `enabled_types` de `zotero_overlay.json` (servidor y PoC lo toman de ahí) y, si quieres detectarlo, agrégalo a `DOCTYPE_RULES`. Sin señales claras el tipo propuesto es `book` (Zotero desaconseja `document`).

## 4. Cómo interpretar `results.json`

Un objeto por PDF:

- **`item_type`**: tipo detectado (`value`), `confidence` y `scores` por tipo. Si `confidence` < 0.4, desconfía.
- **`fields`**: cada campo con `value`, `source` y `confidence`. Fuentes: `layout` (maquetación), `regex`, `inid` (portada de patente),
  `pdfmeta`, `ner`, `stopwords/lingua` (idioma), `llm`. **Si un dato no aparece en el documento, el campo no existe** (nunca se inventa).
  `missing_critical` lista los críticos ausentes; `unmapped` guarda lo extraído que no pertenece al tipo.
- **`classification.suggestions`**: hasta 3, ordenadas.
  - `udc`: notación compuesta y **validada** (si no es sintácticamente válida o la clase no existe, se descarta).
  - `confidence`: reparto relativo entre candidatos (no es una probabilidad calibrada hasta que haya datos).
  - `aux`: cada auxiliar con `source`: `language-detection`, `gazetteer`, `regex`, `rules` (fiables en general) o
    `embedding (experimental)` (auxiliares comunes/especiales/punto de vista: tómalas con cautela).
  - `explain`: similitud del nodo, media de la ruta, voto de vecinos, `retroceder_a` (ancestros por si la sugerencia es demasiado profunda) y `segundo_tema` (si se propuso `A:B`).
  - `issues`: avisos; `warning` = código no presente en el Summary (puede existir en la tabla completa).
- **`classification.low_confidence`** + `note`: si es `true`, se sugiere igualmente pero **revísala a mano**.
- **`verification`** (solo con `--verify`): `verificado`, `dudoso` o `conflicto` frente a Crossref/OpenLibrary. **Nunca sobrescribe**; `relleno_sugerido` solo propone campos vacíos. No aplica a patentes, partituras ni literatura gris.
- **`warnings`**: p. ej. PDF escaneado sin `--ocr`.

### 4.1 Ejemplos de combinación (recuadros `◇` de UDC Online)
El RDF guarda los ejemplos de cada clase como `skos:example` (`330.322.014.3    Net investment`). Al cargar el árbol:
- Los que solo **alargan** la notación de su clase se vuelven nodos hijos (`origin: "example"`), anidados por prefijo
  decimal: `330.322 > 330.322.01 > 330.322.014 > 330.322.014.3`. Se embeben con su ruta, el haz llega a ellos y el
  validador los acepta. En `results.json`: `main[].origin = "example"` y `explain.origen = "ejemplo de combinación de 330.322 …"`.
- Las combinaciones con `:` `+` `(` `=` (p. ej. `17:7`) no se vuelven nodos: se añaden al texto de su clase (`e.g. …`).
- Un ejemplo solo se propone si su similitud supera a la de su clase en `EXAMPLE_MARGIN` (0 por defecto; súbelo si
  ves ejemplos demasiado específicos). `retroceder_a` incluye siempre la clase.
- `udc:includingNote` («Including …») y `udc:informationNote` también entran en el texto del nodo.
- Si el RDF trae `udcx:auxType` (marca oficial de UDC Online), decide si una clase es principal o auxiliar especial; sin
  ella se deduce de la notación. Con el árbol actual corrige ~1 100 auxiliares especiales que parecían principales
  (`661.187.047`) y ~170 principales que parecían especiales (`621.039.5…`). Dentro de las tablas comunes se conserva
  el tipo fino (`place`, `lang`, `time`…). `tree` lo indica en `marca_auxiliar_oficial`.
- Límite: solo llega a las combinaciones que la UDC trae como ejemplo; armar combinaciones nuevas es tarea de la Fase 2.
- Al cambiar notas o ejemplos en el RDF, el índice se regenera solo (la huella incluye el texto embebido).

### 4.2 «See also» (clases alternativas de otra rama)
Las referencias ⇨ de UDC Online (`skos:related`, p. ej. `903.26 Objects of worship` ⇨ `2-533 Object of worship`)
enlazan clases de ramas distintas. El PoC las usa en **ambos sentidos** (UDC Online a veces solo las pone en uno):

- **Candidatas nuevas:** las `SEE_ALSO_FROM` (10) mejores candidatas aportan sus clases enlazadas, a un solo salto.
  Compiten con la misma fórmula que las demás; sirve para llegar a una rama que la búsqueda en haz no exploró.
  Solo entran clases de la tabla principal (la puntuación usa la cadena de clases principales). En `explain.via_see_also`
  se indica desde qué clase llegó.
- **Alternativas visibles:** cada sugerencia trae `ver_tambien` (hasta `SEE_ALSO_MAX`, de cualquier tabla, también
  auxiliares como `2-533`) con su similitud con el documento; `run` y `review` muestran las 3 primeras.
- **Reranker:** recibe la marca `see_also` (1 si la clase está enlazada desde una de las mejores candidatas) y aprende
  de tus confirmaciones cuánto vale. Las confirmaciones antiguas valen igual (sin la marca, cuenta como 0); un
  `reranker.pkl` entrenado antes de este cambio se descarta y se reentrena con `python -m udcpoc train`.
- Pendiente para la calibración: preferir una clase enlazada como segundo tema (`A:B`) en casi-empates.
- `SEE_ALSO_FROM = 0` lo desactiva.

### 4.3 Clases canceladas
El RDF trae las clases canceladas de UDC Online (`udcx:CancelledClass`: año, E&C, etiqueta antigua y reemplazos). No son nodos: nunca se proponen.

- **Validador:** si un componente no existe porque fue cancelado, el mensaje lo dice y da los reemplazos (`568.1 fue cancelada en la UDC [2011, E&C33] (Reptilia. Fossil reptiles); se reemplaza por: 56; 598.1`). Mismo nivel que antes: error en la clase principal, aviso en auxiliares. Las notaciones reutilizadas (`94`) son válidas.
- **Evaluación:** si tu gold usa una clase principal cancelada con **un solo** reemplazo, acertar ese reemplazo cuenta en `clase_principal_top1_con_reemplazos` / `top3_con_reemplazos` (las métricas de siempre no cambian); `gold_con_notaciones_canceladas` dice cuántos documentos lo usan.
- Pendiente (calibración): detectar la notación impresa en el PDF y añadir la etiqueta antigua al texto del reemplazo.

### Métricas de `evaluate`
- `clase_principal_top1/top3`: la(s) clase(s) principal(es) coinciden con tu gold en la sugerencia 1 / en alguna de las 3.
- `notacion_completa_top1`: coincide toda la notación (muy exigente).
- `acierto_por_nivel`: `nivel_2: 14/20` = en 20 documentos cuyo gold llega a profundidad 2, acertó 14 (descendiendo por el árbol).
- `tablas_auxiliares`: por tabla, cuántas tenía tu gold, cuántas propuso y cuántas acertó (da precisión y cobertura).
- `campos`: título (similitud ≥ 0.85), año, idioma y tipo.

### 4.4 Libro de referencia (`books\gold\referencia.xlsx`)
Los datos correctos de **cada PDF de la colección** (no solo de la muestra gold): UDC completa con
alternativas aceptadas, datos bibliográficos (tipo Zotero, título, autores, traductores/editores, edición,
volumen, serie, número, revista, fecha, editorial, lugar, ISBN, DOI, idioma, idioma original) y página de
portada. Cada fila se identifica por el **SHA-256** del archivo: renombrarlo o moverlo no la rompe.
- Hoja **Libros**: la verdad; se edita (las columnas grises se calculan: clase principal y auxiliares por
  tabla). `estado`: `pendiente` · `propuesto` (llenado por una IA o un catálogo, sin revisión humana) ·
  `verificado` (revisado por una persona) · `dudoso`. `fuente_udc` dice quién decidió la UDC.
- Hoja **Predicciones**: lo que propuso cada versión del clasificador. Está aparte para revisar a ciegas.
- Hoja **Resumen**: métricas por versión, una columna por versión (las mismas de `evaluate` más
  «aceptando alternativas», primer autor y página de portada).
- Al guardar se escribe también `referencia.csv` (la hoja Libros en texto), que **sí va a git**.

```powershell
python -m udcpoc reference add books                                   # PDF nuevos -> filas 'pendiente' prellenadas
python -m udcpoc reference predictions output\results_v0.1.0.json --as v0.1.0
python -m udcpoc reference evaluate [--solo-verificados]               # -> hoja Resumen
python -m udcpoc reference export                                      # solo regenera referencia.csv
```
Cierra el Excel antes de correrlos. `add` saca lo que puede sin clasificar (nombre del archivo, metadatos,
ISBN y año del copyright de las primeras páginas, editorial, idioma, primera página con contenido); revisa
esas filas y pon su UDC. Para comparar una IA nueva: córrela sobre `books`, guarda su `results.json` con
`predictions --as <nombre>` y vuelve a correr `evaluate`. La importación masiva usa la referencia con
`bulk_import.py plan ... --gold referencia.csv` (ver `biblioteca_udc\README.md`).

Primera versión (2026-11-27): 175 PDF. 50 UDC de la muestra gold y 125 decididas por Claude (Opus 5.5) a partir
de la portada, la página legal y el índice, todas comprobadas contra el árbol; datos bibliográficos revisados
por Claude. Todo queda `propuesto` (salvo la corrección del usuario en Goldberg) hasta que una persona lo revise.

## 5. Aprendizaje con tus confirmaciones
Cada confirmación (`review`) se guarda en `data/feedback.db`: embedding del documento + notación final + candidatos. Ante un
documento nuevo, los vecinos que ya clasificaste **votan** y reponderan candidatos (efecto inmediato). Con ≥ 30
confirmaciones se entrena automáticamente un reranker (regresión logística) que aprende cuánto pesa cada señal; `python -m udcpoc train` lo fuerza
y muestra los coeficientes. Es *beam search* + vecinos, no un descenso voraz: no propaga el error del primer nivel.

**Desde la app** (`python -m udcpoc serve`, o `run_classifier.bat`; ver `udcpoc/service.py`): el servidor de la
biblioteca pide los análisis a este servicio local, y cuando una persona guarda un ítem analizado, su UDC
principal entra como confirmación (igual que en `review`, sin gold.csv). El análisis queda en
`data/service_cache/<sha256>.json` para poder aprender después sin volver a leer el PDF. El modelo se carga
con el primer análisis y se libera tras `SERVICE_IDLE_MINUTES` (15) sin uso; `serve --idle 0` lo deja cargado
desde el arranque. Para que el servicio
arranque con Windows (sin ventana, log en `logs/classifier.log`): `biblioteca_udc\server\install_autostart.bat`
(ver el README de `biblioteca_udc`, «Que arranque solo con el PC»).

## 6. LLM opcional (apagado)
`llm.py` habla con un endpoint compatible con OpenAI/Ollama (`LLM_BASE_URL`, `LLM_MODEL`) y solo rellena campos **ausentes**.
Se activa con `--llm`. Decisión en la Fase 2 mediante ablación (con/sin LLM).

## 7. Qué se probó y qué no (importante)
Probado aquí con un UDC **sintético** de ~30 nodos, un embedder falso y un `fitz` simulado: lectura del árbol, jerarquía
(incluida inferencia por prefijo), validador, composición, tablas auxiliares, patentes, nombres, títulos por maquetación,
feedback + reranker, `run`, `review`, `evaluate` (23 pruebas: `python -m unittest discover -s tests -t .`).

**No probado (no tuve red, ni tus archivos):** el RDF real con `rdflib`, PyMuPDF real, `bge-m3`, OCR, GLiNER,
`--verify` y `--llm`. Es de esperar que la primera ejecución real requiera ajustes, sobre todo:
1. cómo trae tu RDF las auxiliares (`tree --kind ...` lo muestra) y si la jerarquía sale bien;
2. umbrales (`MIN_SIM`, `AUX_MIN_SIM`, `SOFTMAX_TEMP`) que dependen de las similitudes reales de `bge-m3`;
3. etiquetas de la tabla de forma (`FORM_BY_*`) contra las etiquetas reales.

## 8. Limitaciones conocidas
- UDC Summary: las auxiliares especiales son pocas; sugerencias más cortas que con la tabla completa (se marca con `warning`).
- Sin LLM: títulos/autores en portadas caóticas (literatura gris, partituras) saldrán peor; no hay justificación en lenguaje natural, solo `explain`.
- El tiempo `"..."` describe el periodo del **tema**, por eso solo se lee título, resumen e índice.
- Con dos temas (`A:B`) las auxiliares globales se anexan al final; es una simplificación.
