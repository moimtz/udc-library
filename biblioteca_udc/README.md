# Biblioteca UDC

Biblioteca de PDF clasificada con la CDU/UDC (UDC Summary, versión libre). Tiene dos partes:

- **`server/`**: servidor en Python (FastAPI + SQLite) que corre en el PC de la escuela. Guarda los PDF, la base de datos, las carátulas, los usuarios y hace la búsqueda.
- **`app/`**: aplicación Flutter para **Windows** y **Android** (teléfono y tablet). La interfaz está en inglés.

```
biblioteca_udc/
├── README.md
├── setup_app.ps1          prepara el proyecto Flutter (app_build/)
├── server/
│   ├── main.py            punto de entrada
│   ├── install_server.bat instala dependencias y crea el administrador
│   ├── run_server.bat     inicia el servidor (aquí cambias el límite de GB)
│   ├── create_admin.py    crea/restablece el administrador
│   ├── udc_import.py      importa el árbol UDC (udc_data/udcs-skos.rdf) con sus notas
│   ├── udc_data/          udcs-skos.rdf, el árbol UDC completo (lo escribe la fusión de udc_to_rdf_conversion)
│   ├── zotero/            schema.json oficial de Zotero (no se edita) + zotero_overlay.json (ajustes propios)
│   ├── catalog.py         sincroniza el catálogo de tipos y campos con la base al arrancar
│   ├── library.py         ítems: guardado con procedencia, cambio de tipo, duplicados, búsqueda
│   ├── tests/             pruebas (pytest)
│   └── ... (config, db, rutas, notation, etc.)
└── app/
    ├── pubspec.yaml
    └── lib/               código Dart
```

## Cómo funciona (decisiones que tomé)

- **Fuente de verdad**: la base SQLite del servidor. Los PDF **no se modifican**. Cada día el servidor copia la base (se conservan 7) y exporta un JSON por recurso en `data/backups/json/` como respaldo legible.
- **Modelo de datos = Zotero**: tipos de ítem, campos, roles de creador y sus etiquetas salen del `schema.json` oficial de Zotero (ver «Datos de los ítems» abajo). Lo que no tiene campo va a Extra, como pide Zotero.
- **Archivos**: carpeta plana `data/library/`, nombrados con la clave de cita (`garciaIntroduccionTeoriaConjuntos1998.pdf`, con sufijo a, b, c si hay colisión). El material complementario de un ítem se llama `clave_s1.pdf`, `clave_s2.pdf`...
- **Búsqueda**: se hace en el servidor (regex, sensible a mayúsculas, palabra completa, por campo; sin distinguir acentos salvo en modo regex o sensible a mayúsculas). Con bibliotecas de unos miles de recursos es instantánea. No usé FTS5 porque no permite regex ni resaltado exacto; si algún día pasas de ~20,000 recursos se puede añadir.
- **UDC**: un libro puede tener una notación compuesta (`004.8:61`) y aparece en varias ramas. Al hacer clic en un nodo se muestran también los libros de sus subclases (interruptor "Include subclasses"). El árbol es el completo (~72 000 clases) generado en `udc_to_rdf_conversion/`; las notas de cada clase (Scope note, Application note, Information note, Including, ejemplos de combinación, See also) se ven en una ventana de información.
- **Usuarios**: biblioteca **compartida**. Roles: `admin` (tú), `editor` (añade, edita y elimina) y `viewer` (busca y abre). Si prefieres que cada amigo tenga su propia biblioteca privada, es un cambio importante; dímelo.
- **Caché local**: al abrir un archivo se descarga a la caché del dispositivo. Los archivos "Keep offline" no se borran nunca; el resto se elimina por menos usados cuando se supera el límite (2 GB por defecto, configurable en Settings).
- **Papelera**: el servidor guarda lo eliminado 30 días (`BUDC_TRASH_DAYS`) y luego lo borra definitivamente.
- **Autorrelleno**: busca DOI, ISBN y arXiv en las primeras y últimas páginas del PDF y consulta Crossref, Open Library y arXiv. También puedes escribir un identificador en el formulario y pulsar "Fill automatically". Cada valor llega con su fuente; nunca sobrescribe lo que una persona confirmó. La clasificación con IA queda para una fase 2.

## Datos de los ítems (esquema Zotero)

Documento de diseño: «Biblioteca UDC: esquema de datos (Zotero)» (Claude Docs). Resumen:

- **Catálogo**: `server/zotero/schema.json` es el archivo oficial de Zotero (zotero/zotero-schema, versión 45), copiado tal cual; `zotero_overlay.json` añade solo lo nuestro: tipos activos, ayuda de cada campo (en inglés, de la página de Zotero), tipo de control y campos ocultos. Al arrancar, el servidor compara la versión del esquema y una huella del overlay con las guardadas en `meta` y, si cambian, actualiza las tablas `item_types`, `fields`, `item_type_fields`, `creator_types` e `item_type_creators`. Nunca borra lo que usan ítems existentes: un campo que Zotero quite queda `obsolete` (solo lectura). **Actualizar Zotero = reemplazar `schema.json` y reiniciar.** El PoC lee los mismos dos archivos.
- **Tipos**: se siembran los 37 de Zotero; activos en v1 (los únicos para ítems nuevos): artwork, book, bookSection, case, conferencePaper, dictionaryEntry, encyclopediaArticle, journalArticle, letter, magazineArticle, manuscript, map, newspaperArticle, patent, preprint, presentation, report, standard, statute, thesis. Se activan otros editando `enabled_types` en el overlay. Partituras: book (o manuscript) con `Type: musical_score` en Extra.
- **Valores en filas**: `items` guarda solo la clave de cita, el tipo y columnas derivadas para ordenar y filtrar (`sort_title`, `sort_creator`, `date_sort`, `year`, `language`). Cada campo es una fila de `item_fields` con `value`, `norm` (fecha ISO, ISBN-13, DOI en minúsculas, código de idioma), `source`, `confidence` y `confirmed`; los creadores van en `item_creators`, las notaciones en `item_udc` (y los nodos del árbol, derivados, en `item_udc_nodes`), las etiquetas en `tags`/`item_tags` y las notas en `item_notes`. Disparadores de SQLite impiden guardar un campo o un rol que el tipo no admite.
- **Procedencia**: lo que escribe una persona es `manual` y queda confirmado. Al guardar la ficha, los valores automáticos que la persona deja tal cual pasan a confirmados conservando su fuente. Un proceso automático nunca pisa un valor confirmado (lo devuelve como sugerencia) y sobre uno sin confirmar solo escribe si tiene más confianza.
- **Cambio de tipo**: nada se pierde. Cada valor se queda en su campo, o pasa por su campo base (`university` → `publisher` → `institution`), o se añade a Extra como `Label: valor`. Los creadores con un rol que el tipo nuevo no tiene pasan a su rol principal o a `contributor`.
- **Archivos**: `attachments`, con un archivo principal por ítem (el que da la carátula) y material complementario con etiqueta (solo PDF en v1; cuenta para `BUDC_MAX_STORAGE_GB`).
- **Sin compatibilidad con el esquema anterior**: el esquema Zotero es el definitivo. Una base creada con una versión anterior no se migra: se borra `data/biblioteca.db` y se empieza de cero (ver «Instalar el esquema Zotero en un servidor existente»).

## 1. Servidor (PC de la escuela)

Requisitos: Windows, Python 3.11 o superior.

1. Copia la carpeta `server/` al PC (por ejemplo `C:\biblioteca_udc\server`).
2. Ejecuta `install_server.bat`. Crea el entorno virtual, instala las dependencias y te pide usuario y contraseña del administrador.
3. Abre `run_server.bat` con el Bloc de notas y revisa estas líneas:
   - `BUDC_PORT=8765`: puerto. Cámbialo si choca con la otra aplicación.
   - `BUDC_MAX_STORAGE_GB=20`: **límite de almacenamiento**. Cámbialo cuando lo necesites y reinicia el servidor.
   - `BUDC_DATA_DIR`: carpeta de datos (por defecto `server\data`). Puedes apuntarla a otro disco.
4. Ejecuta `run_server.bat`. Si el puerto está libre, verás que Uvicorn queda escuchando. Prueba en el navegador del propio PC: `http://127.0.0.1:8765/api/health`.

El servidor usa **su propio archivo** (`data\biblioteca.db`), no toca la base de datos de la otra aplicación.

### Importar la jerarquía UDC

Sin este paso la app funciona solo con las 10 clases principales (0 a 9).

1. El RDF está en `server/udc_data/udcs-skos.rdf`: ahí lo escribe la fusión del árbol (`udc_to_rdf_conversion/udc_main_tree_fusion.py`, ver el README de esa carpeta), así que no hay que copiarlo.
2. En la carpeta `server` (si usas otra carpeta de datos, define antes `set BUDC_DATA_DIR=...`):
   ```
   .venv\Scripts\python.exe udc_import.py --langs en,es
   ```
   Sin ruta usa `udc_data/udcs-skos.rdf` (se puede pasar otra). Tarda unos segundos. Reemplaza el árbol completo y vuelve a enlazar los libros existentes con sus clases. Repítelo después de cada fusión (por ejemplo, tras una descarga nueva o un idioma).
3. Reinicia el servidor. En la app, Settings > "Language of UDC class names" cambia entre inglés y español (si falta el idioma, se muestra en inglés).

Qué guarda por clase (tabla `udc_nodes`): notación, padre, etiquetas, orden global (recorrido en profundidad respetando `udcx:order`), tipo (`heading` = encabezado sin notación, como MAIN TABLES; `info` = nodo informativo no asignable, como INFORMATION ON SPECIAL AUXILIARY TABLES) y `notes` (JSON con `scope`, `app`, `info`, `including` y `examples` por idioma, y `related`). Las bases creadas antes reciben las columnas nuevas solas al arrancar el servidor. Las clases **canceladas** del RDF (`udcx:CancelledClass`) van a la tabla `udc_cancelled` (notación, año, E&C, etiqueta antigua, «Including», reemplazos en JSON, nota); no forman parte del árbol.

API de la ventana de información:
- `GET /api/schema?lang=en-US`: tipos (con `enabled`), sus campos en el orden de Zotero (etiqueta, `kind`, ayuda, campo base, `hidden`) y sus roles de creador.
- Un ítem viaja así: `{id, citekey, item_type, fields: {code: {value, source, confidence, confirmed}}, creators: [{creator_type, last_name, first_name, field_mode, source, ...}], tags, udc: [{notation, source, ...}], attachments, notes}`, más `title`, `creators_text`, `year`, `udc_text` y `main` para listar. Al guardar, cada campo puede ir como texto (manual) o como objeto con su fuente.
- `POST /api/convert-type` convierte los valores de un formulario a otro tipo sin guardar (y dice qué fue a Extra); `POST /api/items/{id}/type` lo hace sobre un ítem guardado (`dry_run` para ver antes).
- `POST /api/items/{id}/autofill` y `POST /api/items/{id}/auto` escriben valores automáticos respetando los confirmados y devuelven `suggestions`.
- Material complementario: `POST /api/items/{id}/attachments` (`temp_id` de `/api/uploads` + `label`), `PATCH /api/attachments/{id}`, `PUT /api/items/{id}/attachments/order`, `GET /api/attachments/{id}/file`, `DELETE /api/attachments/{id}` (a la papelera) y `POST /api/attachments/{id}/restore`. Notas: `POST /api/items/{id}/notes`, `PUT` y `DELETE /api/notes/{id}`.
- La búsqueda por campo acepta campos base: buscar en `publisher` encuentra también `university`, `label` o `institution`.
- `GET /api/udc/tree`: cada nodo trae además `type`, `has_info` e `incl` (texto «Including» por idioma), solo cuando aplican. Se envía comprimido con gzip si el cliente lo acepta (11 MB → 1.85 MB con el árbol completo). Solo esta ruta: comprimir los PDF ocultaría su tamaño y la barra de progreso de descarga.
- `GET /api/udc/node?code=330.322`: notas de una clase, su ruta de ancestros y las clases de "See also" con sus etiquetas. Además, `replaces` (clases canceladas que hoy se clasifican aquí) y `earlier` (significados anteriores de la misma notación, si se canceló y luego se reutilizó); con alguno de los dos, la clase lleva `has_info`.
- `GET /api/udc/cancelled?code=568`: cancelaciones de una notación con sus reemplazos y sus etiquetas actuales (404 si nunca se canceló).
- `GET /api/udc/cancelled-index`: lista compacta de las canceladas que ya no existen (~11 800; 800 KB, gzip); la app la pide la primera vez que se filtra el árbol.
- `GET /api/udc/check?udc=681.3:004`: componentes de una notación que son canceladas (posición, notación y reemplazos). Busca la notación cancelada respetando los límites del componente y se queda con la coincidencia más larga; las notaciones reutilizadas no cuentan. La notación va en la consulta porque puede contener `/`.

El importador también acepta el UDC Summary original (`udcsummary-skos.rdf`): sin `skos:broader` infiere el padre por la notación. El UDC Summary es © UDC Consortium bajo licencia CC BY-SA 3.0; la app incluye el aviso de atribución en "About".

### Acceso con Tailscale

Elige **una** opción:

- **A (más simple)**: en el PC ejecuta `tailscale ip -4` para ver su dirección `100.x.y.z`. En `run_server.bat` pon `BUDC_HOST=100.x.y.z`. En la app usa `http://100.x.y.z:8765`. El tráfico va cifrado por Tailscale. Si el servidor arranca antes que Tailscale, falla al abrir el puerto y `run_server.bat` lo reintenta cada 10 segundos.
- **B (HTTPS)**: deja `BUDC_HOST=127.0.0.1` y publica el puerto con `tailscale serve`. La sintaxis cambia entre versiones; revisa `tailscale serve --help`. Necesitas MagicDNS y HTTPS activados en la consola de Tailscale, y usar un puerto HTTPS que no use ya la otra aplicación (por ejemplo 8443). **No uses `tailscale funnel`**, porque lo expondría a internet.

Tu teléfono, tablet y laptop deben estar en tu tailnet. Para tus amigos, comparte el PC con ellos desde la consola de Tailscale ("Share node") o agrégalos a tu tailnet.

### Que arranque solo con el PC (opcional)

En un CMD como administrador:
```
schtasks /Create /TN "BibliotecaUDC" /SC ONSTART /RU SYSTEM /TR "C:\biblioteca_udc\server\run_server.bat"
```

### Instalar el esquema Zotero en un servidor existente

La base anterior no se migra (no tenía ítems). Con el servidor detenido:

1. Borra `data\biblioteca.db` (y `biblioteca.db-wal` / `-shm` si existen). `data\library`, `covers` y `trash` deben estar vacías.
2. Reemplaza el código de `server\` por el nuevo.
3. `.venv\Scripts\python.exe create_admin.py` (vuelve a crear el administrador) y `.venv\Scripts\python.exe udc_import.py` (vuelve a cargar el árbol).
4. Arranca con `run_server.bat`. Los demás usuarios se vuelven a crear desde la app, y en la app hay que iniciar sesión de nuevo.

### Usuarios

Se administran desde la app (menú > "Users"): crear, cambiar rol, restablecer contraseña, deshabilitar y eliminar. Si olvidas tu contraseña de administrador: `.venv\Scripts\python.exe create_admin.py` con el mismo nombre de usuario.

### Respaldo

Copia periódicamente la carpeta `data` completa (`library` + `biblioteca.db`). `data\backups\` contiene las copias diarias de la base y los JSON, pero está en el mismo disco; guarda una copia fuera del PC.

## 2. Aplicación (tu laptop)

Instala, con calma, esto (puedes pedirme ayuda con cada paso):

1. **Flutter SDK** (docs.flutter.dev/install/windows), y agrega `flutter\bin` al PATH.
2. **Visual Studio 2022** (Community) con la carga de trabajo **"Desktop development with C++"**. Es necesaria para compilar la versión de Windows.
3. **Android Studio** (para el SDK de Android). Luego `flutter doctor --android-licenses`.
4. Activa el **Modo de desarrollador** de Windows (Configuración > Privacidad y seguridad > Para desarrolladores).
5. Ejecuta `flutter doctor` y corrige lo que marque en rojo.

Luego, desde la carpeta `biblioteca_udc`:
```
powershell -ExecutionPolicy Bypass -File .\setup_app.ps1
cd app_build
flutter run -d windows
```
`setup_app.ps1` crea `app_build/` (con las carpetas de Windows y Android), copia el código de `app/`, añade el permiso de internet, permite HTTP simple (necesario si usas la opción A de Tailscale) y descarga las dependencias.

### Distribuir

- **Windows portable**: `flutter build windows --release`. Copia la carpeta `build\windows\x64\runner\Release` completa (el `.exe` necesita las DLL y `data\` que están a su lado) y ejecútala desde donde quieras.
- **Android**: `flutter build apk --release --split-per-abi`. Para el Xiaomi 12 usa `build\app\outputs\flutter-apk\app-arm64-v8a-release.apk`. Cópialo al teléfono e instálalo (permite "instalar apps desconocidas"). Para la tablet, normalmente el mismo `arm64-v8a`.

## 3. Uso

- **Iniciar sesión**: dirección del servidor, usuario y contraseña.
- **Árbol**: clic en una clase para listar sus libros. "Collapse all" / "Expand all" arriba a la derecha. Como en UDC Online, el «Including» de una clase se ve en su fila tras un recuadro (`Burial remains □ Prehistoric graves, barrows (tumuli)`); el filtro del árbol también busca en ese texto. El icono ⓘ abre la ventana de información de la clase: notas, ejemplos de combinación (`◇`) y "See also", que muestra la ficha de esa clase en la misma ventana (la flecha vuelve atrás). Los encabezados (MAIN TABLES…) solo se despliegan y los nodos informativos abren directamente su ventana: ninguno de los dos se puede elegir como clase. La ventana necesita conexión con el servidor.
- **Clases canceladas**: la ventana de una clase tiene una sección plegable «More info» con las clases canceladas que hoy se clasifican ahí (p. ej. en `004.3`: `681.3 Data processing equipment [1996, E&C18]`) y, si la notación tuvo antes otro significado, cuál era (p. ej. `94` hasta 1994). Al filtrar el árbol, las notaciones canceladas que coinciden (por notación o, desde 3 letras, por la etiqueta antigua) salen al final, tachadas y en gris; al pulsarlas se abre su ventana con los reemplazos. Al guardar un libro cuya notación usa una cancelada, un aviso ofrece usar cada reemplazo, guardar igual o volver a editar (sin conexión no se comprueba).
- **Búsqueda**: escribe y pulsa Enter. `Aa` = sensible a mayúsculas, `Word` = palabra completa, `.*` = regex. El menú desplegable acota por campo. El icono de filtros abre tipo, años, idioma y la ventana con el árbol UDC completo.
- **Resultados**: clic en un título para desplegar la ficha (con coincidencias resaltadas y la carátula). Botones Open, Edit fields, Keep offline y Delete. Se ordenan por título, autor, año o fecha de incorporación. Los valores sugeridos automáticamente que nadie ha confirmado llevan el icono ✦ (al pasar el ratón dice la fuente y la confianza).
- **Supplementary material**: en la ficha, debajo de los botones. Cada archivo con su etiqueta (Errata, Solutions manual, Parts...) y sus botones Open y Keep offline; los editores añaden, renombran, reordenan o mandan a la papelera. Debajo, las notas del ítem.
- **Añadir**: menú lateral > "Add files". Se abre una ventana por PDF (con el contador "2 of 5"). Elige la página de carátula y el tipo de ítem (el formulario muestra los campos de ese tipo en el orden de Zotero, con su ayuda en el icono ?), rellena a mano o con "Fill automatically" y pulsa "Add". Al cambiar de tipo los valores se mueven solos y la app avisa si algo fue a Extra. Si el archivo parece duplicado, eliges Replace existing, Keep both o Skip.
- **Sin conexión**: la app muestra los archivos guardados en el dispositivo. Menú > "Saved on this device".

## Qué probé y qué no

Pude probar aquí la lógica del servidor que no depende de librerías externas: claves de cita, extracción y validación de DOI/ISBN/arXiv, búsqueda (acentos, regex, palabra completa, mayúsculas), detección de duplicados, árbol UDC y conteos, y el análisis de las respuestas de Crossref, Open Library y arXiv. Todo el código Python compila.

**No pude ejecutar**: el servidor completo (FastAPI, PyMuPDF, rdflib) ni la app Flutter, porque este entorno no tiene internet ni esas herramientas. Es probable que al compilar por primera vez aparezcan errores pequeños (versiones de paquetes, advertencias de APIs nuevas). Pégame el mensaje exacto y los corrijo. Del importador de UDC no pude verificar el formato real del archivo descargado.

Ventana de información (noviembre de 2026): `udc_import.py` se probó con el RDF real (71 811 clases, 862 con notas; con las fichas de UDC Online, 22 011 con notas; encabezados y orden correctos); las rutas `/api/udc/tree` y `/api/udc/node`, con el cliente de pruebas de FastAPI; y la migración, sobre una base antigua. La app pasa `flutter analyze` sin errores, pero la ventana todavía no se ha probado en pantalla.

Clases canceladas (noviembre de 2026): importación con el RDF real (12 309 cancelaciones) y las rutas `udc/cancelled`, `udc/cancelled-index`, `udc/check` y `udc/node` probadas con el cliente de pruebas de FastAPI. En la app (`flutter analyze` sin errores) faltan las pruebas en pantalla: «More info», filas tachadas del filtro y aviso al guardar.

Esquema Zotero (noviembre de 2026): 25 pruebas automáticas del servidor (`cd server`, `python -m pytest tests`; necesitan `pytest` además de `requirements.txt`): catálogo (37 tipos, 123 campos, 767 pares tipo-campo, 170 tipo-rol), disparadores, fechas e ISBN, nodos UDC de notaciones compuestas, procedencia, cambio de tipo, material complementario, duplicados, búsqueda por campo base, notas y papelera. Además, con el árbol real: reimportación del árbol en sitio y mantenimiento. La app pasa `flutter analyze` sin errores; el formulario nuevo y la sección Supplementary material faltan de probar en pantalla.

## Problemas comunes

- **"Cannot reach the server"**: revisa que el servidor esté corriendo, que Tailscale esté conectado en ambos dispositivos y que la dirección coincida con `BUDC_HOST` y el puerto.
- **La app de Android no conecta con `http://`**: confirma que `setup_app.ps1` se ejecutó (agrega `usesCleartextTraffic`), o usa HTTPS con la opción B.
- **El PDF no se abre en Android**: instala un visor de PDF (el de Xiaomi o Google Drive). Si el sistema indica "no app", es porque falta uno.
- **Windows no encuentra Visual Studio**: instala la carga de trabajo "Desktop development with C++" y corre `flutter doctor`.
- **"Storage limit reached"**: sube `BUDC_MAX_STORAGE_GB` en `run_server.bat` y reinicia, o vacía la papelera.
