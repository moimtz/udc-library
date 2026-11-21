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
│   ├── udc_import.py      importa el árbol UDC (udcs-skos.rdf) con sus notas
│   └── ... (config, db, rutas, búsqueda, duplicados, etc.)
└── app/
    ├── pubspec.yaml
    └── lib/               código Dart
```

## Cómo funciona (decisiones que tomé)

- **Fuente de verdad**: la base SQLite del servidor. Los PDF **no se modifican**. Cada día el servidor copia la base (se conservan 7) y exporta un JSON por recurso en `data/backups/json/` como respaldo legible.
- **Archivos**: carpeta plana `data/library/`, nombrados con la clave de cita (`garciaIntroduccionTeoriaConjuntos1998.pdf`, con sufijo a, b, c si hay colisión).
- **Búsqueda**: se hace en el servidor (regex, sensible a mayúsculas, palabra completa, por campo; sin distinguir acentos salvo en modo regex o sensible a mayúsculas). Con bibliotecas de unos miles de recursos es instantánea. No usé FTS5 porque no permite regex ni resaltado exacto; si algún día pasas de ~20,000 recursos se puede añadir.
- **UDC**: un libro puede tener una notación compuesta (`004.8:61`) y aparece en varias ramas. Al hacer clic en un nodo se muestran también los libros de sus subclases (interruptor "Include subclasses"). El árbol es el completo (~72 000 clases) generado en `udc_to_rdf_conversion/`; las notas de cada clase (Scope note, Application note, Including, ejemplos de combinación, See also) se ven en una ventana de información.
- **Usuarios**: biblioteca **compartida**. Roles: `admin` (tú), `editor` (añade, edita y elimina) y `viewer` (busca y abre). Si prefieres que cada amigo tenga su propia biblioteca privada, es un cambio importante; dímelo.
- **Caché local**: al abrir un archivo se descarga a la caché del dispositivo. Los archivos "Keep offline" no se borran nunca; el resto se elimina por menos usados cuando se supera el límite (2 GB por defecto, configurable en Settings).
- **Papelera**: el servidor guarda lo eliminado 30 días (`BUDC_TRASH_DAYS`) y luego lo borra definitivamente.
- **Autorrelleno**: busca DOI, ISBN y arXiv en las primeras y últimas páginas del PDF y consulta Crossref, Open Library y arXiv. También puedes escribir un identificador en el formulario y pulsar "Fill automatically". La clasificación con IA queda para una fase 2.

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

1. Usa el RDF definitivo: `udc_to_rdf_conversion/udcs-skos.rdf` (árbol completo, orden, encabezados y notas; ver el README de esa carpeta). Cópialo al PC del servidor.
2. En la carpeta `server` (si usas otra carpeta de datos, define antes `set BUDC_DATA_DIR=...`):
   ```
   .venv\Scripts\python.exe udc_import.py C:\ruta\udcs-skos.rdf --langs en,es
   ```
   Tarda unos segundos. Reemplaza el árbol completo y vuelve a enlazar los libros existentes con sus clases. Repítelo cada vez que regeneres el RDF (por ejemplo, tras añadir las fichas de UDC Online o un idioma).
3. Reinicia el servidor. En la app, Settings > "Language of UDC class names" cambia entre inglés y español (si falta el idioma, se muestra en inglés).

Qué guarda por clase (tabla `udc_nodes`): notación, padre, etiquetas, orden global (recorrido en profundidad respetando `udcx:order`), tipo (`heading` = encabezado sin notación, como MAIN TABLES; `info` = nodo informativo no asignable, como INFORMATION ON SPECIAL AUXILIARY TABLES) y `notes` (JSON con `scope`, `app`, `including` y `examples` por idioma, y `related`). Las bases creadas antes reciben las columnas nuevas solas al arrancar el servidor.

API de la ventana de información:
- `GET /api/udc/tree`: cada nodo trae además `type` y `has_info` (solo cuando aplican). Se envía comprimido con gzip si el cliente lo acepta (8.9 MB → 1.5 MB con el árbol completo). Solo esta ruta: comprimir los PDF ocultaría su tamaño y la barra de progreso de descarga.
- `GET /api/udc/node?code=330.322`: notas de una clase, su ruta de ancestros y las clases de "See also" con sus etiquetas. La notación va en la consulta porque puede contener `/`.

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

### Usuarios

Se administran desde la app (menú > "Users and resource types"): crear, cambiar rol, restablecer contraseña, deshabilitar y eliminar. Si olvidas tu contraseña de administrador: `.venv\Scripts\python.exe create_admin.py` con el mismo nombre de usuario.

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
- **Árbol**: clic en una clase para listar sus libros. "Collapse all" / "Expand all" arriba a la derecha. El icono ⓘ abre la ventana de información de la clase: notas, ejemplos de combinación (`◇`) y "See also", que muestra la ficha de esa clase en la misma ventana (la flecha vuelve atrás). Los encabezados (MAIN TABLES…) solo se despliegan y los nodos informativos abren directamente su ventana: ninguno de los dos se puede elegir como clase. La ventana necesita conexión con el servidor.
- **Búsqueda**: escribe y pulsa Enter. `Aa` = sensible a mayúsculas, `Word` = palabra completa, `.*` = regex. El menú desplegable acota por campo. El icono de filtros abre tipo, años, idioma y la ventana con el árbol UDC completo.
- **Resultados**: clic en un título para desplegar la ficha (con coincidencias resaltadas y la carátula). Botones Open, Edit fields, Keep offline y Delete. Se ordenan por título, autor, año o fecha de incorporación.
- **Añadir**: menú lateral > "Add files". Se abre una ventana por PDF (con el contador "2 of 5"). Elige la página de carátula, rellena a mano o con "Fill automatically", y pulsa "Add". Si el archivo parece duplicado, eliges Replace existing, Keep both o Skip.
- **Sin conexión**: la app muestra los archivos guardados en el dispositivo. Menú > "Saved on this device".

## Qué probé y qué no

Pude probar aquí la lógica del servidor que no depende de librerías externas: claves de cita, extracción y validación de DOI/ISBN/arXiv, búsqueda (acentos, regex, palabra completa, mayúsculas), detección de duplicados, árbol UDC y conteos, y el análisis de las respuestas de Crossref, Open Library y arXiv. Todo el código Python compila.

**No pude ejecutar**: el servidor completo (FastAPI, PyMuPDF, rdflib) ni la app Flutter, porque este entorno no tiene internet ni esas herramientas. Es probable que al compilar por primera vez aparezcan errores pequeños (versiones de paquetes, advertencias de APIs nuevas). Pégame el mensaje exacto y los corrijo. Del importador de UDC no pude verificar el formato real del archivo descargado.

Ventana de información (noviembre de 2026): `udc_import.py` se probó con el RDF real (71 811 clases, 862 con notas, encabezados y orden correctos); las rutas `/api/udc/tree` y `/api/udc/node`, con el cliente de pruebas de FastAPI; y la migración, sobre una base antigua. La app pasa `flutter analyze` sin errores, pero la ventana todavía no se ha probado en pantalla.

## Problemas comunes

- **"Cannot reach the server"**: revisa que el servidor esté corriendo, que Tailscale esté conectado en ambos dispositivos y que la dirección coincida con `BUDC_HOST` y el puerto.
- **La app de Android no conecta con `http://`**: confirma que `setup_app.ps1` se ejecutó (agrega `usesCleartextTraffic`), o usa HTTPS con la opción B.
- **El PDF no se abre en Android**: instala un visor de PDF (el de Xiaomi o Google Drive). Si el sistema indica "no app", es porque falta uno.
- **Windows no encuentra Visual Studio**: instala la carga de trabajo "Desktop development with C++" y corre `flutter doctor`.
- **"Storage limit reached"**: sube `BUDC_MAX_STORAGE_GB` en `run_server.bat` y reinicia, o vacía la papelera.
