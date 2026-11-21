# Biblioteca UDC: contexto del proyecto

Documento único para retomar el trabajo en Claude Code. Responder siempre en español. Explicar el código cuando el usuario lo pida (está aprendiendo Python y Dart). Comentarios breves en el código.

## 1. Concepto

Biblioteca personal de PDF (libros, tesis, artículos, patentes, partituras, literatura gris) organizada con la UDC/CDU (UDC Summary abierto). Uso propio y de unos pocos amigos.

Funciones:
- Árbol UDC navegable (inspirado en el UDC Summary).
- Búsqueda: regex, mayúsculas, palabra completa, por campo; filtros de tipo, año, idioma y UDC.
- Ficha bibliográfica con carátula; abrir en el visor PDF del sistema.
- Alta manual y masiva, y autorrelleno de metadatos.
- En curso: sugerencia de clasificación UDC con IA local.

Restricciones generales: todo local, gratuito y sin claves de API. Solo son opcionales las consultas a Crossref, Open Library y arXiv. UI de la app en inglés. Los PDF son sobre todo en español.

## 2. Stack y entorno

- **Cliente:** Flutter/Dart, Windows de escritorio y Android (Xiaomi 12 con HyperOS y Android 15; tablet futura). Paquetes: provider, http, file_picker (^10.3.7), path_provider, shared_preferences, open_filex.
- **Servidor:** Python 3.11+, FastAPI + Uvicorn, SQLite, PyMuPDF, httpx (Crossref, Open Library, arXiv), rdflib. Corre en un PC Windows de la escuela, accesible solo por Tailscale en HTTP (`http://100.x.y.z:8765`). Ese PC ya corre otra app y un agente Qwen 3.5 9B (4 bits) con contexto grande, vía Ollama a futuro, en una RTX 3060 de 12 GB con ~24 GB de RAM. **No competir por esa GPU: los embeddings van en CPU.**
- **Laptop de pruebas:** Dell i5-1135G7, 16 GB de RAM, MX330 de 2 GB (inútil para ML), Windows 11.
- **Estructura:**
  ```
  biblioteca_udc/
  ├── server/            FastAPI, rutas, db, búsqueda, importadores, .bat
  ├── app/               pubspec.yaml y lib/ (Dart)
  ├── setup_app.ps1      genera app_build/ (plataformas Flutter + copia de app/)
  ├── README.md
  udc_poc/               PoC de clasificación (CLI), aparte
  ```
  Nunca editar `app_build/`: se regenera con `setup_app.ps1`.
- **Ejecución:** `server/install_server.bat` (venv, dependencias, crea el admin) y `server/run_server.bat` (variables `BUDC_HOST`, `BUDC_PORT`, `BUDC_MAX_STORAGE_GB`=20, `BUDC_TRASH_DAYS`=30, `BUDC_DATA_DIR`). `create_admin.py` y `udc_import.py` leen `BUDC_DATA_DIR` del entorno: hay que definirla con `set` antes de ejecutarlos manualmente.

## 3. Arquitectura de datos (servidor)

**SQLite es la fuente de verdad** (`data/biblioteca.db`). Los PDF no se modifican.

- **Archivos:** carpeta plana `data/library/`. Nombre = clave de cita: apellido del primer autor en minúsculas + 3 palabras significativas del título en CamelCase + año (ej. `garciaIntroduccionTeoriaConjuntos1998.pdf`), con sufijo a, b, c si hay colisión. Otras carpetas: `covers/`, `trash/`, `tmp/` y `backups/` (copia diaria de la base, 7 conservadas, y un JSON por recurso).
- **Tablas:**
  - `users` (rol admin/editor/viewer), `sessions` (token hasheado).
  - `field_defs` y `item_types`: tipos y campos ampliables en runtime por el admin.
  - `items`: citekey, item_type, title, year, language, udc (cadena completa, ej. `004.8:61`), creators (JSON), data (JSON con el resto de campos), filename, sha256, size, pages, cover_page, added_at, modified_at, added_by, deleted_at (papelera).
  - `item_udc` (item_id, code, node_code): relación muchos a muchos; un libro puede estar en varias ramas. `node_code` es el prefijo más largo de `code` que existe en `udc_nodes`.
  - `udc_nodes` (code, parent, labels JSON por idioma, ord, node_type `heading`/`info`, notes JSON con scope/app/including/examples/related) y `meta`. Se llena con `udc_import.py` desde `udcs-skos.rdf` (árbol completo, ~72 000 clases).
- **Auth:** PBKDF2-SHA256 y sesiones por token (60 días). Biblioteca **compartida** entre todos los usuarios. Roles: admin (gestiona usuarios y tipos), editor (añade, edita, elimina), viewer (busca y abre). Límite de intentos de login en memoria.
- **API (`/api`):**
  - auth: login, logout, me.
  - users: CRUD (admin).
  - schema, types, fields, stats.
  - `udc/tree`: nodos con conteos, `type` y `has_info`, y número de "unclassified" (gzip si el cliente lo acepta).
  - `udc/node?code=`: notas de una clase para la ventana de información (ⓘ en el árbol).
  - items: listado con búsqueda en Python (regex, acentos plegados, resaltado de coincidencias devuelto como offsets por campo), ordenado por título, autor, año o fecha de alta.
  - Alta en dos pasos: `POST /uploads` (devuelve temp_id, hash, páginas, metadatos y duplicados) y luego `POST /items` con `duplicate_action` = check, keep_both o replace.
  - autofill (DOI, ISBN, arXiv), `file`, `cover`, páginas de vista previa, papelera (restaurar y borrar definitivo; purga a los 30 días).
- **Duplicados:** por sha256, DOI, ISBN y título/autor/año parecidos.
- **Mantenimiento:** purga de la papelera, limpieza de `tmp/`, copia de la base y export JSON, cada 6 h.
- **Cliente:** caché local de PDF con límite (2 GB), LRU; los archivos "Keep offline" no se borran nunca. Sin conexión muestra solo lo guardado en el dispositivo. Al abrir, descarga a la caché y abre con el visor del sistema (Windows: `explorer.exe`; Android: `open_filex`).
- **UI:** ventana principal con dos paneles (árbol y búsqueda a la izquierda, resultados a la derecha; en vertical se apilan). Clic en un título despliega la ficha con carátula y los botones Open / Edit fields / Keep offline / Delete. Menú lateral con "Add files" (una ventana por PDF, con cola "2 of 5", selector de página de carátula y aviso de duplicados), "Saved on this device", Trash, Users and resource types (admin), Settings y About (atribución CC BY-SA 3.0 de la UDC).

## 4. Clasificación con IA local (Fase 1: `udc_poc/`)

CLI: `python -m udcpoc <cmd>`. Todo lo editable está en `config.py`. El PoC añade sugerencia de clasificación UDC completa (con tablas auxiliares) y relleno de metadatos cuando fallan las consultas por DOI, ISBN o arXiv.

### Decisiones fijas

- **Árbol:** `udcs-skos.rdf` (Summary abierto). **Las etiquetas vienen solo en inglés, finés y sueco: no hay español.** Los documentos son sobre todo en español, así que se usa un embedder multilingüe: `BAAI/bge-m3`, con `intfloat/multilingual-e5-small` como respaldo si bge-m3 es lento en CPU. Sinónimos, alias y gazetteer en español se mantienen en `config.py`.
- **Sin LLM por defecto.** Queda un módulo opcional y apagado (endpoint compatible con OpenAI/Ollama), que se decide en la Fase 2 con una ablación con/sin LLM.
- **Esquema de campos de Zotero** como referencia universal. Tipos: book, journalArticle, conferencePaper, thesis, report, patent, preprint, standard, document. Las partituras van como `document` con «Tipo: partitura» en `extra`.
- **Procedencia por campo:** cada campo se guarda como `{value, source, confidence}`. La verificación contra catálogos (Crossref, Open Library) **nunca sobrescribe**, solo aplica a book, journalArticle y conferencePaper, y lo manual siempre gana. Si el dato no existe en el documento, el campo no se crea (no se inventa).
- **Limitación del material:** el Summary tiene pocas auxiliares especiales; las sugerencias son más cortas que con la tabla completa y se marcan con `warning`.
- El usuario está aprendiendo UDC: sus etiquetas iniciales tendrán ruido.

### Módulos de `udcpoc/`

- `tree.py`: lee el RDF (rdflib, con respaldo en ElementTree). Construye la jerarquía con `skos:broader` y `narrower`, o por prefijo de notación. Clasifica cada nodo por tabla (main, lang, form, place, ethnic, time, common, special, viewpoint) y marca los nodos de rango.
- `notation.py`: tokeniza, valida (sintaxis más existencia en el árbol) y compone notaciones. Orden de auxiliares: lang, form, place, time.
- `embed.py`: `Embedder` (con opción `dummy` para pruebas) y `UDCIndex`, que embebe la ruta jerárquica más sinónimos y notas de cada nodo y la cachea.
- `pdfio.py`: lectura con PyMuPDF de las primeras 6 y últimas 3 páginas, líneas con tamaño de letra, TOC, detección de escaneados y OCR opcional (rapidocr).
- `metadata.py`: extracción sin LLM.
  - Tipo de documento: reglas con regex y pesos.
  - Título: bloque contiguo con la letra más grande.
  - Autores: heurística y GLiNER opcional.
  - Año, editorial, resumen, palabras clave e idioma (lingua, langdetect o stopwords).
  - Identificadores con checksum de ISBN.
  - Patentes: campos INID.
  - Construcción de las 4 «vistas» del documento: front, toc, body y tail.
- `auxtables.py` (antes `aux.py`; renombrado porque AUX es un nombre reservado en Windows): lengua (ISO a etiqueta del árbol), lugar (gazetteer más alias en español), tiempo (siglos y años, solo en título, resumen e índice) y forma (palabras clave contra etiquetas).
- `classify.py`: similitud por vistas ponderadas, candidatos (top-K plano más *beam search*, ancho 5), features (`sim`, `path`, `parent`, `depth`, `knn`, `flat`, `beam`), puntuación (pesos por defecto o reranker) y confianza (softmax). Selecciona un top-3 sin ancestros ni descendientes entre sí, puede proponer un segundo tema con `:`, añade auxiliares por embeddings (comunes, especiales y punto de vista, marcadas «experimental») y valida cada sugerencia.
- `feedback.py`: SQLite separada (`data/feedback.db`). Guarda confirmaciones, hace votos *kNN* con vecinos y entrena un reranker de regresión logística con ≥30 confirmaciones.
- `verify.py` (Crossref y Open Library), `llm.py` (opcional), `evaluate.py` (métricas) y `cli.py`.

### Comandos

- `index`: carga el RDF, muestra estadísticas y crea el índice.
- `tree --kind K --grep S`: inspecciona el árbol.
- `validate`: valida una notación.
- `sample`: plan de muestra estratificada por tipo, idioma, identificador, escaneado y tema.
- `run`: procesa PDF y escribe `results.json`. Flags: `--ocr`, `--ner`, `--verify`, `--llm`, `--resume`, `--limit`.
- `review [--blind]`: revisión interactiva que alimenta el feedback y genera `gold.csv`.
- `train`: reentrena el reranker.
- `evaluate`: métricas por nivel, notación completa, top-3, cada tabla auxiliar y campos.

### Salida (`results.json`), un objeto por PDF

`item_type`, `fields` (con procedencia y confianza), `unmapped`, `missing_critical`, `classification.suggestions[]` (cada una con `udc`, `main`, `aux`, `confidence`, `issues` y `explain`), `low_confidence`, `verification` y `warnings`.

### Estado de pruebas del PoC

- **Probado:** 14 pruebas unitarias con un UDC sintético, embedder falso y `fitz` simulado. Cubren árbol, jerarquía, validador, composición, auxiliares, patentes, nombres, títulos, feedback con reranker, `run`, `review` y `evaluate`.
- **Sin probar:** RDF real con rdflib, PyMuPDF real, `bge-m3`, OCR, GLiNER, `--verify` y `--llm`. Los umbrales (`MIN_SIM`, `AUX_MIN_SIM`, `SOFTMAX_TEMP`) son provisionales.

## 5. Estado actual de la app

- Servidor corriendo en el PC de la escuela. El cliente funciona en **Windows y Android**, y el flujo se probó casi completo en ambos (login, añadir, buscar, abrir). La biblioteca sigue vacía; hay **126 PDF** por cargar.
- **Bug de arranque en Android: resuelto** (se había reportado `ClassNotFoundException: Didn't find class "Landroid/content/Context;"`). Quedó aplicado en el proyecto `dependency_overrides: path_provider_android: 2.2.23` (evita la versión con JNI) y `startupError` (`app_state.dart`) incluye el stack trace.
- **Único error consistente:** *overflow* de píxeles en algunos contenedores de la UI. No es fatal. El usuario irá reportando cada caso para corregirlos más adelante.
- **Bug conocido:** la jerarquía del árbol UDC en la app está mal.

## 6. Conflictos entre la app y el PoC (a resolver)

1. **Esquema de tipos.** La app usa book, chapter, article, thesis, patent, report y other (ampliables por el admin); el PoC usa los de Zotero. Migrar la app a Zotero y añadir procedencia y confianza por campo.
2. **Idioma de las etiquetas UDC.** La app ofrece "es" en Settings, pero el Summary no trae español (solo inglés, finés y sueco). Quitar la opción "es" o sustituirla por una traducción propia; importar con `--langs en`. Considerar mostrar solo inglés en el árbol.
3. **Importador del árbol.** `server/udc_import.py` nunca se probó con el RDF real; infiere el padre por prefijo cuando falta `skos:broader`. Reemplazarlo por el `tree.py` corregido del PoC, que también clasifica las tablas auxiliares.
4. **Notación compuesta.** `server/udc.py` solo ubica un libro en el árbol por los números de la tabla principal (`extract_codes`) e ignora las auxiliares. Sustituirlo por `notation.py` del PoC.
5. **Verificación de catálogos.** La app autorrellena desde Crossref, Open Library y arXiv sobreescribiendo los campos del formulario; el PoC exige no sobrescribir lo manual y guardar procedencia.

## 7. Fases

0. Inventario (hecho).
1. PoC standalone de clasificación (código entregado, falta validar con datos reales).
2. Muestra de ~28 PDF clasificados a ciegas y luego unos cientos. Comparar embedders, ablación con/sin LLM y calibrar umbrales.
3. Bucle de retroalimentación (kNN y reranker) con datos reales.
4. Integración en la app: servicio FastAPI, UI Flutter de confirmación con top-3 y aviso de baja confianza, cola de revisión por confianza, migrar la jerarquía corregida al servidor y campos de procedencia/confianza en `biblioteca.db`.

## 8. TODO en orden

1. Corregir los overflows de píxeles de la UI, según los reporte el usuario (no son fatales).
2. Arreglar la jerarquía del árbol UDC en la app: subir el parser corregido al servidor y reimportar (conflictos 3 y 4).
3. Importador masivo en el servidor (`import_folder.py`): leer una carpeta `inbox` (no `library/`), deduplicar por hash, extraer metadatos, mover a `library/` con su clave de cita y registrar sin UDC (quedan en "Unclassified"). Opción `--online` para consultar Crossref, Open Library y arXiv. Debe respetar `BUDC_MAX_STORAGE_GB`.
4. Fase 1: copiar `udcs-skos.rdf` a `data/`, `python -m udcpoc index` y revisar la salida (jerarquía, tablas auxiliares detectadas, alias de lugar sin resolver). Revisar con `tree --kind form|lang|place|time|common|special` y ajustar `FORM_BY_*`, `LANG_NAMES` y `PLACE_ALIASES_ES`.
5. Ejecutar `run --limit 5` sobre PDF reales y corregir fallos de PyMuPDF y de extracción de portada.
6. `sample` sobre los 126 PDF, elegir ~28 y crear el gold con `review --blind`.
7. Calibrar umbrales con las similitudes reales de bge-m3; si es lento en CPU, usar multilingual-e5-small.
8. Probar OCR, `--ner` y `--verify` y decidir si se quedan.
9. Ablación con/sin LLM y medir el impacto de Ollama en la RTX 3060 durante la migración al servidor.
10. Escalar a unos cientos de PDF, entrenar el reranker y evaluar.
11. Migrar la app al esquema Zotero con procedencia por campo (conflicto 1) y resolver cómo se guardan partituras y literatura gris.
12. Diseñar e integrar la Fase 4: endpoints, esquema SQLite con procedencia, UI de confirmación.

## 9. Advertencias para quien continúe

- **Qué está validado y qué no.** El servidor y la app se ejecutaron en el entorno real del usuario y el flujo casi completo funciona en Windows y Android. Sin embargo, no hay tests automáticos y no se han ejercitado con volumen real (126 PDF) ni todos los casos límite (duplicados, reemplazo, papelera, usuarios y roles, límite de almacenamiento). En un entorno aparte solo se probó la lógica pura (claves de cita, identificadores, búsqueda, duplicados, conteos del árbol, parseo de Crossref, Open Library y arXiv).
- **No se verificó el formato real del RDF** con el importador de la app. El PoC tampoco se probó con el RDF real. Revisar la salida de `index` antes de confiar en la jerarquía, y confirmar que el archivo `udcs-skos.rdf` coincide con lo que esperan los parsers.
- **Las etiquetas del árbol no tienen español.** El embedder multilingüe compensa parcialmente, pero la similitud entre un documento en español y una etiqueta en inglés será menos precisa. Los umbrales provisionales pueden requerir calibración distinta por idioma del documento.
- **No competir por la GPU del servidor.** El agente Qwen 3.5 9B en la RTX 3060 es prioritario. Embeddings, OCR y NER van en CPU; cualquier uso de Ollama debe medirse antes de activarse.
- **Seguridad básica.** El tráfico va en HTTP por Tailscale y Android lo permite con `usesCleartextTraffic="true"` (lo añade `setup_app.ps1`). El token de sesión se guarda en `shared_preferences`, sin cifrado. Para un grupo reducido es aceptable; si crece, usar HTTPS (`tailscale serve`) y almacenamiento seguro.
- **El servidor no tiene tests automáticos.** Antes de tocar la búsqueda, los duplicados o la lógica de UDC, añadir pruebas con los datos de ejemplo.
- **No ejecutar nada en el servidor de producción sin avisar al usuario.** Es el PC de la escuela, con otra app en marcha y límites de espacio y GPU.
- **Copiar PDF directamente a `library/` no los registra** y puede sobrescribir archivos al asignar claves de cita. Usar el importador masivo desde una carpeta aparte.