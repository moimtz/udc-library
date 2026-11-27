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
│   ├── install_autostart.bat  tareas que arrancan servidor y clasificador con Windows
│   ├── create_admin.py    crea/restablece el administrador
│   ├── udc_import.py      importa el árbol UDC (udc_data/udcs-skos.rdf) con sus notas
│   ├── udc_data/          udcs-skos.rdf, el árbol UDC completo (lo escribe la fusión de udc_to_rdf_conversion)
│   ├── zotero/            schema.json oficial de Zotero (no se edita) + zotero_overlay.json (ajustes propios)
│   ├── catalog.py         sincroniza el catálogo de tipos y campos con la base al arrancar
│   ├── library.py         ítems: guardado con procedencia, cambio de tipo, duplicados, búsqueda
│   ├── storage.py         archivo principal de un ítem y su carátula (lo usan la API y la importación)
│   ├── coherence.py       aviso si el tipo Zotero y la auxiliar de forma de la UDC no cuadran
│   ├── bulk_import.py     importación masiva de PDF que ya están en este PC (consola)
│   ├── classifier.py      cliente del clasificador (udc_poc, run_classifier.bat) para el botón Analyze
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

Requisitos: Windows, Python 3.11 o superior, Git for Windows (Git Bash) y Tailscale.

### Instalación desde cero

En el PC servidor, con tu propia sesión de Windows:

1. **Tailscale**: instálalo e inicia sesión con **tu** cuenta. En el menú de su icono activa **"Run unattended"**, para que siga conectado aunque nadie haya iniciado sesión en Windows. En la consola web de Tailscale (login.tailscale.com) activa **MagicDNS** y anota el nombre del PC (por ejemplo `pc-escuela`).
2. **Instalación anterior** (si existe): detén el servidor viejo y borra su tarea programada desde un CMD como administrador: `schtasks /Delete /TN BibliotecaUDC /F`.
3. **Python 3.11 o superior** desde python.org, marcando *"Add python.exe to PATH"*.
4. **Código**: en **Git Bash** (la primera vez se abre el navegador para iniciar sesión en GitHub):
   ```bash
   git clone https://github.com/moimtz/udc-library.git /c/udc-library
   cd /c/udc-library/biblioteca_udc/server
   ls install_server.bat run_server.bat
   ```
5. **`install_server.bat`**: ábrelo con doble clic en el Explorador (`C:\udc-library\biblioteca_udc\server`), o en un CMD. Crea el entorno virtual, instala las dependencias, te pide usuario y contraseña del administrador e importa el árbol UDC. No lo corras desde Git Bash, porque ahí la contraseña no se puede escribir de forma oculta.
6. **Ajustes** (opcional): abre `run_server.bat` con el Bloc de notas:
   - `BUDC_HOST=tailscale`: escucha en la IP de Tailscale del PC, detectada al arrancar. No hay que copiarla.
   - `BUDC_PORT=8765`: puerto. Cámbialo si choca con la otra aplicación.
   - `BUDC_MAX_STORAGE_GB=20`: **límite de almacenamiento**. Cámbialo cuando lo necesites y reinicia el servidor.
   - `BUDC_DATA_DIR`: carpeta de datos (por defecto `server\data`). Puedes apuntarla a otro disco.
7. **`run_server.bat`** (doble clic): verás `listening on http://100.x.y.z:8765`. Si Windows pregunta por el firewall, permite el acceso en redes privadas. Si Tailscale todavía no conecta, el servidor lo dice y reintenta cada 10 segundos.
8. **Prueba desde la laptop** (que debe estar en tu tailnet): abre `http://pc-escuela:8765/api/health` en el navegador.
9. **App**: recompílala (sección 2) y al iniciar sesión usa `http://pc-escuela:8765`. Con el nombre MagicDNS no dependes de la IP.
10. **Arranque automático**: ver «Que arranque solo con el PC (también tras un apagón)».

El servidor usa **su propio archivo** (`data\biblioteca.db`), no toca la base de datos de la otra aplicación.

### Actualizar el código

En Git Bash, con el servidor detenido: cierra la ventana de `run_server.bat` o, si usas las tareas de arranque,
`schtasks //End //TN BibliotecaUDC`. En Git Bash las opciones de `schtasks` llevan doble barra.
```bash
cd /c/udc-library
git pull
biblioteca_udc/server/.venv/Scripts/python.exe -m pip install -r biblioteca_udc/server/requirements.txt
```
Luego vuelve a abrir `run_server.bat`, o `schtasks //Run //TN BibliotecaUDC`. Haz lo mismo con el clasificador si `git pull` trajo cambios de `udc_poc`. El paso de `pip` solo hace falta si cambió `requirements.txt`, pero repetirlo no hace daño. `git pull` nunca toca `data\`: está en `.gitignore`.

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

- **A (más simple, la predeterminada)**: `BUDC_HOST=tailscale` en `run_server.bat`. Al arrancar, el servidor pregunta su IP a Tailscale (`tailscale ip -4`) y escucha solo en ella. En la app usa `http://NOMBRE-DEL-PC:8765` (MagicDNS) o `http://100.x.y.z:8765`. El tráfico va cifrado por Tailscale. Si el servidor arranca antes que Tailscale, no encuentra la dirección y `run_server.bat` lo reintenta cada 10 segundos. También puedes fijar la IP a mano: `BUDC_HOST=100.x.y.z`.
- **B (HTTPS)**: deja `BUDC_HOST=127.0.0.1` y publica el puerto con `tailscale serve`. La sintaxis cambia entre versiones; revisa `tailscale serve --help`. Necesitas MagicDNS y HTTPS activados en la consola de Tailscale, y usar un puerto HTTPS que no use ya la otra aplicación (por ejemplo 8443). **No uses `tailscale funnel`**, porque lo expondría a internet.

Tu teléfono, tablet y laptop deben estar en tu tailnet. Para tus amigos, comparte el PC con ellos desde la consola de Tailscale ("Share node") o agrégalos a tu tailnet.

### Que arranque solo con el PC (también tras un apagón)

Son tres piezas. Si falta una, el servidor no vuelve solo.

1. **Que el PC se encienda al volver la luz** (BIOS/UEFI). Reinicia y entra al setup, normalmente con F2 o
   Supr al encender; en Dell es F2. Busca una opción como **AC Recovery**, **Restore on AC Power Loss** o
   **After Power Failure**, ponla en **Power On**, guarda y sal. Ojo: si el PC pide una contraseña de BIOS o
   un PIN de BitLocker al arrancar, no podrá arrancar solo.
2. **Que no se duerma**: en un CMD como administrador:
   ```
   powercfg /change standby-timeout-ac 0
   powercfg /change hibernate-timeout-ac 0
   ```
   Tailscale con **"Run unattended"** (paso 1 de la instalación) se conecta sin que nadie inicie sesión.
3. **Tareas de arranque**: clic derecho en `biblioteca_udc\server\install_autostart.bat` > **Ejecutar como
   administrador**. Te pide la contraseña de tu usuario de Windows; con cuenta Microsoft es la contraseña de
   la cuenta, no el PIN. Crea dos tareas que arrancan con Windows, **sin que nadie inicie sesión**:
   - `BibliotecaUDC`: el servidor, 30 s después del arranque.
   - `BibliotecaUDC-Clasificador`: el clasificador, 1 minuto después. Se omite si `udc_poc` no está instalado
     en ese PC.

   Corren con tu usuario y no con SYSTEM, porque el modelo del clasificador está en tu perfil. No abren ventana:
   lo que antes salía en ella va a `biblioteca_udc\server\logs\server.log` y `udc_poc\logs\classifier.log`.
   Al pasar de 10 MB, el anterior se guarda como `.log.old`. Si se caen, se reinician solas.

   Para comprobar, reinicia el PC **sin iniciar sesión** y, desde la laptop, abre
   `http://pc-escuela:8765/api/health`. El clasificador tarda un par de minutos más.

Manejo diario, en un CMD:

| Qué | Comando |
|---|---|
| ¿Están corriendo? | `schtasks /Query /TN BibliotecaUDC /V /FO LIST` (mira «Estado») |
| Detener | `schtasks /End /TN BibliotecaUDC` y `schtasks /End /TN BibliotecaUDC-Clasificador` |
| Arrancar sin reiniciar | `schtasks /Run /TN BibliotecaUDC` (ídem el clasificador) |
| Ver el log en vivo | `powershell Get-Content "C:\udc-library\biblioteca_udc\server\logs\server.log" -Wait -Tail 30` |
| Quitar las tareas | `install_autostart.bat /remove` (como administrador) |

- Con las tareas instaladas **no abras `run_server.bat` con doble clic**: el puerto ya está ocupado y la ventana
  repetirá el error. Para verlo en una ventana, primero detén la tarea.
- Si después de `/End` sigue respondiendo `/api/health`, quedó un `python.exe` vivo: ciérralo desde el
  Administrador de tareas (pestaña Detalles) o reinicia el PC.
- Si cambias la contraseña de Windows, vuelve a ejecutar `install_autostart.bat`; si no, las tareas no arrancan.
- `install_autostart.bat` también borra la tarea antigua `BibliotecaUDC`, la que corría como SYSTEM.

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

### Clasificador (botón «Analyze» de la app)

El botón **Analyze** del formulario (al añadir o editar) sugiere tipo, campos y UDC a partir del propio PDF.
Lo hace el PoC de clasificación, que corre como **servicio aparte** en este mismo PC, solo en `127.0.0.1:8766`,
con su propio venv (torch, bge-m3) y en CPU. La biblioteca funciona igual sin él: la app desactiva el botón.

1. Instala el PoC en el servidor como dice `udc_poc\README.md` §1 (venv, `pip install`, Tesseract para OCR) y
   corre una vez `.venv\Scripts\python.exe -m udcpoc index` (descarga el modelo y crea el índice).
2. Arráncalo junto al servidor: `udc_poc\run_classifier.bat` (ventana aparte). El modelo **no** se carga al
   arrancar: se carga con el primer Analyze (~1 minuto más ese análisis), ocupa ~2,5 GB mientras se usa y se
   libera tras 15 minutos sin análisis (queda ~0,9 GB). Se cambia en `udc_poc\config.py`:
   `SERVICE_IDLE_MINUTES` (0 = cargarlo al arrancar y no liberarlo nunca). Para que arranque con el PC, `install_autostart.bat` crea también su tarea (ver
   «Que arranque solo con el PC»).
3. Otro puerto o ninguno: `set BUDC_CLASSIFIER_URL=http://127.0.0.1:8766` en `run_server.bat` (vacío = sin
   clasificador).

Un PDF a la vez (cola), ~30 s cada uno; el OCR se usa solo si el PDF es escaneado. Nada se guarda hasta que
pulsas Save/Add; al guardar, la UDC principal se envía al clasificador como ejemplo de aprendizaje
(`udc_poc\data\feedback.db`), solo si ese PDF fue analizado con el botón.

### Importación masiva (PDF copiados al PC del servidor)

Para cargar muchos PDF sin subirlos por la red: se copian al PC del servidor (USB, disco externo…) y se
importan desde una carpeta local. El servidor puede seguir encendido. Son dos pasos y en medio decides tú.

1. **Analizar** con el PoC de clasificación, en este PC o en la laptop con una copia de los mismos PDF. Lo
   que viaja es solo `results.json`: los archivos se emparejan por contenido (SHA-1), no por ruta.
   ```powershell
   cd udc_poc
   .venv\Scripts\python.exe -m udcpoc run C:\Importar --ocr --resume    # -> output\results.json (lento, reanudable)
   ```
2. **Planear** (en el servidor, no escribe nada en la base):
   ```powershell
   cd biblioteca_udc\server
   .venv\Scripts\python.exe bulk_import.py plan C:\ruta\results.json C:\Importar --gold C:\ruta\udc_gold.csv
   ```
   Crea `C:\Importar\import_plan.xlsx` (una fila por PDF, también de subcarpetas) e `import_plan.json` (los
   datos completos; no lo edites). En Excel puedes cambiar las columnas blancas: `action` (`load`/`skip`),
   `type` (código Zotero: `book`, `thesis`…; los valores se mueven como en la app), `title`, `creators`
   (`Apellido, Nombre; Institución`), `date`, `udc` (varias con ` ; `), `cover_page` y `to_review` (bórrala si
   ya revisaste la fila). Las grises son informativas: `udc_source` (`classifier` o `gold`), confianza,
   `warnings` (tipo ↔ forma), `duplicate_of` y la clave de cita prevista.
   - Se omiten de entrada (`skip`): los PDF sin análisis, los ilegibles y los posibles duplicados, tanto de la
     biblioteca como de otro archivo de la misma carpeta (mismo archivo, DOI, ISBN o título + autor + año muy
     parecidos). Para conservar ambos, cambia a `load`.
   - `--gold`: CSV `file,udc,nota` con tus notaciones (como `udc_poc\books\gold\udc_gold.csv`); esas UDC entran
     confirmadas y la nota va a las notas del ítem.
3. **Cargar** (con el plan cerrado en Excel):
   ```powershell
   .venv\Scripts\python.exe bulk_import.py load C:\Importar\import_plan.xlsx --user <tu usuario>
   ```
   Copia cada PDF a `data\library` (los originales no se tocan) y crea el ítem. Lo que viene del clasificador
   queda **sin confirmar** con su fuente y confianza (icono ✦ en la app); lo que editaste en el plan y las UDC
   del gold quedan confirmados. La sugerencia 1 de UDC es la notación principal; las 2 y 3 van a una nota.
   Cada ítem lleva la etiqueta del lote (`import AAAA-MM-DD`, o `--tag`) y `to review` si su fila tenía
   motivos. La carátula es la primera página con contenido; se cambia en la app (Edit fields). Al final
   escribe `import_report_<fecha>.csv` (cargado / omitido / error, con el motivo).
   Se puede repetir o interrumpir (Ctrl+C): un archivo que ya está en la biblioteca nunca se añade dos veces.
   Requiere `openpyxl` (en `requirements.txt`: tras actualizar el código, `pip install -r requirements.txt`).

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
- **Tipo y forma UDC**: al guardar, si el tipo de ítem y la auxiliar de forma de la UDC no cuadran (una tesis sin `(043)`, una patente sin `(088.8)`, una norma sin `(083.74)`, un libro con `(043)`, una partitura fuera de `78`…), un aviso permite volver a editar o guardar igual; al abrir un ítem así para editarlo, una franja lo recuerda. Es un aviso, no una regla: las reglas están en `udc_form_by_type` de `zotero_overlay.json`.
- **Búsqueda**: escribe y pulsa Enter. `Aa` = sensible a mayúsculas, `Word` = palabra completa, `.*` = regex. El menú desplegable acota por campo. El icono de filtros abre tipo, años, idioma y la ventana con el árbol UDC completo.
- **Resultados**: clic en un título para desplegar la ficha (con coincidencias resaltadas y la carátula). Botones Open, Edit fields, Keep offline y Delete. Se ordenan por título, autor, año o fecha de incorporación. Los valores sugeridos automáticamente que nadie ha confirmado llevan el icono ✦ (al pasar el ratón dice la fuente y la confianza).
- **Supplementary material**: en la ficha, debajo de los botones. Cada archivo con su etiqueta (Errata, Solutions manual, Parts...) y sus botones Open y Keep offline; los editores añaden, renombran, reordenan o mandan a la papelera. Debajo, las notas del ítem.
- **Añadir**: menú lateral > "Add files". Se abre una ventana por PDF (con el contador "2 of 5"). Elige la página de carátula y el tipo de ítem (el formulario muestra los campos de ese tipo en el orden de Zotero, con su ayuda en el icono ?), rellena a mano o con "Fill automatically" y pulsa "Add". Al cambiar de tipo los valores se mueven solos y la app avisa si algo fue a Extra. Si el archivo parece duplicado, eliges Replace existing, Keep both o Skip.
- **Sin conexión**: la app muestra los archivos guardados en el dispositivo. Menú > "Saved on this device".

## 4. Servidor temporal en la laptop de pruebas

Mientras el PC de la escuela no esté disponible, la laptop de pruebas (Dell i5, 16 GB) hace de servidor: la
biblioteca, el clasificador y, si quieres, la app de Windows corren en ella. El teléfono y los demás
dispositivos entran por Tailscale, igual que entrarían al PC de la escuela. Los datos que se creen aquí son
**reales**: cuando el PC de la escuela vuelva, se mudan (4.6).

Los comandos son para **CMD** (no Git Bash). El código es la carpeta de trabajo `C:\UDC Library`, no un clon aparte.

### 4.1 Preparar la laptop

1. **Tailscale** conectado con tu cuenta y, en el menú de su icono, **"Run unattended"**. Anota el nombre
   MagicDNS de la laptop en la consola de Tailscale (p. ej. `dell-laptop`).
2. **Que no se duerma** (si se suspende, nadie puede entrar). Configuración > Sistema > Energía:
   «Cuando esté enchufado, suspender después de» = **Nunca**. En Panel de control > Opciones de energía > «Elegir
   el comportamiento del cierre de la tapa»: **No hacer nada** con corriente. Déjala enchufada.
3. **Espacio**: `BUDC_MAX_STORAGE_GB` (20 GB por defecto) debe caber en el disco de la laptop. Se cambia en `run_server.bat`.

### 4.2 Servidor

1. Instalación (crea `.venv`, instala dependencias, pide usuario y contraseña del administrador e importa el
   árbol UDC, ~1 minuto). Haz doble clic en `C:\UDC Library\biblioteca_udc\server\install_server.bat`, o en un CMD:
   ```
   cd "C:\UDC Library\biblioteca_udc\server"
   install_server.bat
   ```
   Los datos quedan en `server\data` (ignorada por git).
2. Pruebas automáticas (deben pasar las 42):
   ```
   .venv\Scripts\python.exe -m pip install pytest
   .venv\Scripts\python.exe -m pytest tests -q
   ```
3. Arranque: **`run_server.bat`** (doble clic), tal como está (`BUDC_HOST=tailscale`). Debe decir
   `listening on http://100.x.y.z:8765`. Si Windows pregunta por el firewall, **permite** el acceso.
4. Comprueba desde el **teléfono** (con Tailscale conectado): `http://dell-laptop:8765/api/health`. Si no
   responde, revisa que la regla de firewall de `python.exe` permita la red de Tailscale.

El servidor escucha solo en la IP de Tailscale, así que en la propia laptop la dirección también es
`http://dell-laptop:8765`; `127.0.0.1` no funciona.

### 4.3 Clasificador

El PoC ya está instalado en la laptop (`udc_poc\.venv`, índice creado, Tesseract). Escucha solo en `127.0.0.1`:
solo lo usa el servidor, que está al lado.

1. Arranca `C:\UDC Library\udc_poc\run_classifier.bat` (doble clic). Dice `Clasificador listo.` al momento; el
   modelo se carga con el primer Analyze (`Modelo cargado (... N ejemplos aprendidos)`).
2. Comprueba en la laptop `http://127.0.0.1:8766/health`: debe decir `"ready": true`.

Cada ítem analizado que se guarde en la app se vuelve ejemplo de aprendizaje en `udc_poc\data\feedback.db` (la
misma base que alimenta `review`). Si quieres poder descartar lo que aprenda en esta etapa, respáldala antes:
`copy data\feedback.db data\feedback_antes_servidor.db` (y lo mismo con `reranker.pkl`), en la carpeta `udc_poc`.

Ocupa ~2,5 GB de RAM mientras analiza y ~0,9 GB tras 15 minutos sin uso: con el servidor y la app cabe en 16 GB. Mientras corres `udcpoc run` (4.5), ciérralo para
no cargar un segundo modelo. Ese rato, el botón Analyze queda desactivado.

**Arranque automático** (opcional): igual que en el PC de la escuela, con `install_autostart.bat` (sección 1,
«Que arranque solo con el PC»). Al mudarte, quítalas de la laptop con `install_autostart.bat /remove`.

### 4.4 App y botón Analyze

1. **Windows** (en la laptop): compila y abre la app (sección 2): `setup_app.ps1`, luego `cd app_build` y
   `flutter run -d windows`. **Android**: compila el APK (sección 2, «Distribuir»). En ambos, inicia sesión con
   `http://dell-laptop:8765` y el administrador de 4.2.
2. Pruebas sugeridas con unos pocos PDF:
   - **Add files → Analyze**: mensaje de progreso; campos rellenados con ✦; chips con 3 UDC (el cursor encima
     muestra etiqueta, auxiliares y clases más generales); tocar un chip cambia la notación principal. Luego Add.
   - **PDF escaneado**: tarda más y el aviso final dice `(with OCR)`. Uno con texto no usa OCR.
   - **Valores tuyos primero**: escribe un título o autor antes de Analyze. No se sobrescriben: aparecen en la
     tarjeta «The classifier suggests other values» con Use / Dismiss.
   - **Tipo elegido**: cambia el tipo (p. ej. Thesis) antes de Analyze. Se respeta, y si el clasificador
     detecta otro, lo propone en la tarjeta.
   - **Edit fields → Analyze** en un ítem guardado: no toca lo confirmado.
   - **Clasificador apagado**: cierra su ventana y abre un formulario nuevo. Analyze queda desactivado y el
     cursor encima dice «Classifier not available on the server».
   - La ventana del clasificador deja una línea por trabajo: `[analyze] archivo.pdf  done  (15.2 s)` al
     analizar y `[learn] ...` al guardar.

### 4.5 Importación masiva

Los PDF ya están en la laptop, así que no hay que copiarlos por USB: basta una carpeta local.

1. Para la primera prueba, crea una carpeta con **copias** de 5-10 PDF, p. ej. `C:\prueba_import`. Incluye uno
   que ya hayas añadido en 4.4, para ver la detección de duplicados.
2. Analízala con el PoC. Cierra antes el clasificador de 4.3. `--out` evita pisar `output\results.json` (el del gold):
   ```
   cd "C:\UDC Library\udc_poc"
   .venv\Scripts\python.exe -m udcpoc run C:\prueba_import --ocr --out C:\prueba_import\results.json
   ```
3. Plan (no escribe en la base):
   ```
   cd "C:\UDC Library\biblioteca_udc\server"
   .venv\Scripts\python.exe bulk_import.py plan C:\prueba_import\results.json C:\prueba_import
   ```
   Abre `C:\prueba_import\import_plan.xlsx` y cambia algo para probar: el título o la `udc` de una fila, y
   `action` = `skip` en otra. Guarda y **cierra Excel**.
4. Carga (el servidor puede seguir encendido):
   ```
   .venv\Scripts\python.exe bulk_import.py load C:\prueba_import\import_plan.xlsx --user <tu usuario>
   ```
   Revisa `import_report_<fecha>.csv` en la misma carpeta.
5. En la app, busca la etiqueta `import AAAA-MM-DD` y comprueba:
   - lo del clasificador va con ✦ y lo que editaste en el plan, sin ✦;
   - las sugerencias 2-3 están en las notas del ítem;
   - la etiqueta `to review` aparece donde había motivos;
   - la fila `skip` no se cargó y el duplicado quedó omitido.
6. Repite el paso 4: no debe añadir nada (el informe lo dice).

Los ítems de la importación masiva no enseñan al clasificador al guardarlos, porque el servicio no los analizó.
Para que lo hagan, pulsa Analyze en Edit fields antes de guardar (con el clasificador encendido).

La importación no tiene «deshacer» por lote: si la primera prueba no te convence, borra esos ítems desde la app
(buscando su etiqueta `import AAAA-MM-DD`) y vacía la papelera.

### 4.6 Mudar al PC de la escuela

Cuando el PC de la escuela vuelva:

1. Instálalo como en la sección 1 (código de la **misma versión**, `install_server.bat`). El administrador que
   cree se sustituye en el paso 3.
2. Detén el servidor y el clasificador en **ambos** equipos.
3. Copia la carpeta `biblioteca_udc\server\data` completa de la laptop sobre la del PC de la escuela,
   reemplazando la que creó la instalación: base, PDF, carátulas, papelera y respaldos. Los usuarios y
   contraseñas van dentro de la base.
4. Si el PC de la escuela tendrá el clasificador: copia también `udc_poc\data\feedback.db`, `reranker.pkl` y la
   carpeta `service_cache` (sin ella, los ítems ya analizados no aprenden al editarlos).
5. En el PC de la escuela, deja configurado que arranque solo: BIOS, energía y `install_autostart.bat` (sección
   1, «Que arranque solo con el PC»). Luego reinícialo. En la laptop, quita las tareas si las creaste
   (`install_autostart.bat /remove`).
6. En la app, cambia la dirección a la del PC de la escuela y vuelve a iniciar sesión.

Mientras la laptop sea el servidor, haz también la copia de la sección «Respaldo» fuera de la laptop.

## Qué probé y qué no

Pude probar aquí la lógica del servidor que no depende de librerías externas: claves de cita, extracción y validación de DOI/ISBN/arXiv, búsqueda (acentos, regex, palabra completa, mayúsculas), detección de duplicados, árbol UDC y conteos, y el análisis de las respuestas de Crossref, Open Library y arXiv. Todo el código Python compila.

**No pude ejecutar**: el servidor completo (FastAPI, PyMuPDF, rdflib) ni la app Flutter, porque este entorno no tiene internet ni esas herramientas. Es probable que al compilar por primera vez aparezcan errores pequeños (versiones de paquetes, advertencias de APIs nuevas). Pégame el mensaje exacto y los corrijo. Del importador de UDC no pude verificar el formato real del archivo descargado.

Ventana de información (noviembre de 2026): `udc_import.py` se probó con el RDF real (71 811 clases, 862 con notas; con las fichas de UDC Online, 22 011 con notas; encabezados y orden correctos); las rutas `/api/udc/tree` y `/api/udc/node`, con el cliente de pruebas de FastAPI; y la migración, sobre una base antigua. La app pasa `flutter analyze` sin errores, pero la ventana todavía no se ha probado en pantalla.

Clases canceladas (noviembre de 2026): importación con el RDF real (12 309 cancelaciones) y las rutas `udc/cancelled`, `udc/cancelled-index`, `udc/check` y `udc/node` probadas con el cliente de pruebas de FastAPI. En la app (`flutter analyze` sin errores) faltan las pruebas en pantalla: «More info», filas tachadas del filtro y aviso al guardar.

Esquema Zotero (noviembre de 2026): 25 pruebas automáticas del servidor (`cd server`, `python -m pytest tests`; necesitan `pytest` además de `requirements.txt`): catálogo (37 tipos, 123 campos, 767 pares tipo-campo, 170 tipo-rol), disparadores, fechas e ISBN, nodos UDC de notaciones compuestas, procedencia, cambio de tipo, material complementario, duplicados, búsqueda por campo base, notas y papelera. Además, con el árbol real: reimportación del árbol en sitio y mantenimiento. La app pasa `flutter analyze` sin errores; el formulario nuevo y la sección Supplementary material faltan de probar en pantalla.

Importación masiva y coherencia tipo ↔ forma (25 de noviembre de 2026): 36 pruebas del servidor (11 nuevas: reglas de forma, `udc/check`, guardado sin confirmar, mapeo de fuentes, plan sin escrituras, duplicados de lote, carga con ediciones y repetición sin duplicar). Además, de punta a punta con el árbol real y los 50 resultados del PoC sobre `udc_poc\books` (172 PDF): plan en ~30 s, carga de 50 ítems en ~20 s, segunda carga sin cambios. La app pasa `flutter analyze` sin errores; el aviso al guardar y la franja falta de probarlos en pantalla.

Botón Analyze (25 de noviembre de 2026): 42 pruebas del servidor (6 nuevas, con el clasificador simulado:
disponibilidad, análisis de una subida y de un ítem guardado, ajuste al tipo pedido, estados y errores,
aprendizaje al guardar). De punta a punta con el modelo real: un libro de 160 páginas analizado en 15 s y su
UDC aprendida al guardar. La app no muestra errores en el analizador de Dart; falta probar el formulario en pantalla (4.4).

## Problemas comunes

- **"Cannot reach the server"**: revisa que el servidor esté corriendo, que Tailscale esté conectado en ambos dispositivos y que la dirección coincida con `BUDC_HOST` y el puerto.
- **Con las tareas de arranque no hay ventana**: los mensajes y errores están en `server\logs\server.log` y
  `udc_poc\logs\classifier.log`. Si tras un reinicio no responde, mira primero ahí. Que no haya log significa
  que la tarea no arrancó: revisa su «Último resultado» con `schtasks /Query /TN BibliotecaUDC /V /FO LIST`.
  Lo más común es que la contraseña de Windows haya cambiado.
- **`Tailscale is not connected yet` en la ventana del servidor (o en su log)**: Tailscale no tiene sesión iniciada o no está conectado. Ábrelo desde su icono y conéctalo; el servidor reintenta solo cada 10 segundos.
- **La app de Android no conecta con `http://`**: confirma que `setup_app.ps1` se ejecutó (agrega `usesCleartextTraffic`), o usa HTTPS con la opción B.
- **El PDF no se abre en Android**: instala un visor de PDF (el de Xiaomi o Google Drive). Si el sistema indica "no app", es porque falta uno.
- **Windows no encuentra Visual Studio**: instala la carga de trabajo "Desktop development with C++" y corre `flutter doctor`.
- **"Storage limit reached"**: sube `BUDC_MAX_STORAGE_GB` en `run_server.bat` y reinicia, o vacía la papelera.
