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
1. Copia tu `udcs-skos.rdf` a `data\udcs-skos.rdf`.
2. La primera vez, `bge-m3` se descarga (~2.3 GB) desde Hugging Face (gratis). Respaldo ligero: en `config.py`
   cambia `EMBEDDING_MODEL` a `intfloat/multilingual-e5-small`.
3. Opcionales: `py3langid` y `langdetect` (idioma), `gliner` (autores, flag `--ner`). Todos instalan en
   Python 3.15 sin compilador (lingua y rapidocr-onnxruntime se descartaron: no tienen wheels para 3.15).
4. OCR (flag `--ocr`): usa **Tesseract** a través de PyMuPDF; no hay paquete pip. En Windows:
   ```powershell
   winget install UB-Mannheim.TesseractOCR    # en el instalador, marca el idioma "Spanish"
   ```
   Si no marcaste el español, copia `spa.traineddata` (github.com/tesseract-ocr/tessdata_best) a
   `C:\Program Files\Tesseract-OCR\tessdata`. Si PyMuPDF no lo encuentra, define `TESSDATA_DIR` en `config.py`
   (o la variable de entorno `TESSDATA_PREFIX`) con esa carpeta. Idiomas y DPI: `OCR_LANGS`, `OCR_DPI`.

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

### Cómo armar el gold sin sesgo
Con 25-30 PDF de `sample_plan.csv`, usa `review --blind`: escribes **tu** UDC antes de ver la sugerencia. Si solo
aceptas la sugerencia, las métricas medirán tu tendencia a aceptar, no la calidad. Como estás aprendiendo UDC,
espera ruido en tus etiquetas; el sistema lo aprenderá también.

## 3. Dónde editar (todo en `config.py`)

| Qué | Variable |
|---|---|
| Ítems de Zotero y sus campos | `ZOTERO_ITEM_TYPES` (una lista de campos por tipo; añade/quita nombres) |
| Campos críticos (marcan "incompleto") | `CRITICAL_FIELDS` |
| Cómo se detecta el tipo de documento | `DOCTYPE_RULES` (regex y pesos) |
| Tabla de forma `(0...)` | `FORM_BY_DOCTYPE`, `FORM_BY_TEXT` (palabras clave que se buscan en las **etiquetas inglesas** del árbol) |
| Idiomas y lugares | `LANG_NAMES`, `PLACE_ALIASES_ES` |
| Partituras | `SCORE_ITEM_TYPE` (por defecto `document` + nota `Tipo: partitura` en `extra`) |
| Umbrales y pesos | `LOW_CONFIDENCE`, `MIN_SIM`, `AUX_MIN_SIM`, `DEFAULT_WEIGHTS`, `VIEW_WEIGHTS`, … |
| Cuándo un ejemplo de combinación gana a su clase | `EXAMPLE_MARGIN` (ver §4.1) |
| Clases alternativas por "See also" | `SEE_ALSO_FROM`, `SEE_ALSO_MAX` (ver §4.2) |
| Orden de auxiliares en la notación | `AUX_ORDER` |

Para añadir un tipo nuevo (p. ej. `computerProgram`): agrégalo a `ZOTERO_ITEM_TYPES` y, si quieres detectarlo, a `DOCTYPE_RULES`.

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

## 5. Aprendizaje con tus confirmaciones
Cada confirmación (`review`) se guarda en `data/feedback.db`: embedding del documento + notación final + candidatos. Ante un
documento nuevo, los vecinos que ya clasificaste **votan** y reponderan candidatos (efecto inmediato). Con ≥ 30
confirmaciones se entrena automáticamente un reranker (regresión logística) que aprende cuánto pesa cada señal; `python -m udcpoc train` lo fuerza
y muestra los coeficientes. Es *beam search* + vecinos, no un descenso voraz: no propaga el error del primer nivel.

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
