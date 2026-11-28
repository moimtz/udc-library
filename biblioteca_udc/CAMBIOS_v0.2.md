# Cambios v0.2: frontend (Windows y Android) y búsqueda

Este documento dice qué cambió, en qué archivo y en qué función, para que puedas hacer ajustes finos sin saber
Flutter. Todas las rutas son relativas a `biblioteca_udc/`.

---

## 0. Antes de probar

1. **El servidor también cambió** (la búsqueda nueva vive ahí). Copia a la PC de la escuela:
   `server/search.py` (nuevo), `server/routes_library.py`, `server/library.py` y `server/tests/test_api.py`.
   Luego reinicia el servidor. Con el servidor viejo, la app nueva **ignora el cuadro "Número CDU"**.
   La app vieja (v0.1) sigue funcionando con el servidor nuevo.
2. Prepara y abre la app (en PowerShell, dentro de `biblioteca_udc`):
   ```
   powershell -ExecutionPolicy Bypass -File .\setup_app.ps1
   cd app_build
   flutter run -d windows
   ```
   Con la app abierta en `flutter run`, cada vez que guardes un cambio en `app/lib` y lo copies a `app_build/lib`,
   pulsa `r` en la terminal para ver el cambio sin reiniciar. Lo más simple es volver a correr `setup_app.ps1`.
3. Pruebas automáticas:
   - App: `flutter test` dentro de `app_build`. Son 11 pruebas: dibujan las pantallas en tamaño laptop y teléfono,
     en inglés y en español, y fallan si aparece un desbordamiento (las franjas rojas) o una excepción.
   - Servidor: `.venv\Scripts\python.exe -m pytest tests` dentro de `server`. Son 44 pruebas.

   Estado actual: las 11 pruebas de la app y las 44 del servidor pasan, y `flutter analyze` no da errores
   (quedan 3 avisos de API obsoleta que ya estaban antes).

---

## 1. Dónde se ajusta el aspecto: `app/lib/core/theme.dart`

Todo lo visual quedó en constantes con nombre al inicio del archivo:

| Constante | Qué controla | Valor |
|---|---|---|
| `kFsTitle` | Letra de títulos de ventana y barra superior (esta +1) | `17` |
| `kFsSection` | Títulos de sección: nº de resultados, títulos de la ayuda | `14` |
| `kFsBody` | Texto general: árbol, cuadros de búsqueda, menús, título de la tarjeta, secciones dentro de la ficha | `13` |
| `kFsSmall` | Campos de la ficha, etiquetas del buscador, casillas, botones | `12` |
| `kFsTiny` | Detalles: línea autores \| año \| tamaño, notas pequeñas | `11` |
| `kInfoFontSize` | Texto de lectura de las ventanas de información y ayuda | `13.5` |
| `kControlHeight` | Alto común de cuadros de búsqueda, "Campo", botón de árbol y "Buscar" (apenas más que el texto) | `28` |
| `kSearchBoxWidth` | Ancho de los cuadros del buscador (se encogen solos si el panel es más angosto) | `230` |
| `kCheckScale` | Tamaño de las casillas (1.0 = el de Flutter) | `0.82` |
| `kTooltipDelay` | Tiempo con el mouse quieto antes de que aparezca un globo | `2 s` |
| `kScrollbarGap` | Espacio a la derecha de cada fila del árbol para que el (i) libre la barra de scroll | `14` |
| `kIconSize` | Íconos pequeños (?), (i), árbol, contraer | `17` |
| `kRadius` | Redondeo de botones, recuadros y tarjetas | `8` |
| `kGap` | Separación entre cuadros, casillas y dropdowns | `6` |
| `kTreeRowHeight`, `kTreeIndent` | Alto de fila y sangría por nivel del árbol | `28`, `16` |
| `kFaintAlpha`, `kHintAlpha` | Transparencia del (i)/"Sin clasificar" y de las sugerencias dentro de los cuadros | `0.45`, `0.55` |
| `kTreeMin`, `kTreeMax` | Límites del panel izquierdo (buscador + árbol) al arrastrar, como fracción de la ventana. Su ancho inicial es el del buscador (ver sección 2) | `0.25`, `0.70` |
| `kWideLayout` | Ancho a partir del cual se ven los dos paneles lado a lado (debajo: modo teléfono) | `720` |
| `kMenuItemHeight` | Alto de cada opción de los dropdowns y menús | `36` |

La escala de letra es la jerarquía: cada nivel es un punto menor que el anterior, y toda la app usa solo esos
tamaños. Para hacer todo más grande o más chico, cambia los cinco `kFs...` en la misma proporción.

Componentes reutilizables del mismo archivo: `Framed` (marco del selector de orden y de los dropdowns de Ajustes),
`SquareIconButton` (botón del árbol), `SmallIconButton` ((?), (i)...) y `plainButton` (estilo sin marco de
"+ Añadir archivo" y "+ Añadir nota"). Los dropdowns compactos son `widgets/compact_dropdown.dart`
(`CompactDropdown`): Ordenar, Idioma, Caché, Tipo de elemento y Rol.

### Paletas (Ajustes → Paleta)

Al final de `theme.dart` están las tres paletas (`kPalettes`), cada una con versión clara y oscura:
**Biblioteca** (petróleo y verde, la de inicio, `defaultPalette`), **Pizarra** (gris azulado y menta) y **Papel**
(sepia y oliva). Cada color tiene nombre (`PaletteColors`):

| Nombre | Dónde se ve |
|---|---|
| `primary` | Números CDU, títulos de sección, casillas marcadas, enlaces |
| `action` / `onAction` | **Botones principales** (Buscar, Abrir, Listo, Guardar, Añadir...) y su texto |
| `background` / `surface` | Fondo de la pantalla / tarjetas y panel del árbol |
| `button` / `border` | Fondo de los botones con marco / bordes y líneas del árbol |
| `text` / `textMuted` | Texto / texto secundario |
| `selection` | Fila seleccionada del árbol, barra de selección |
| `highlight` | Coincidencias de la búsqueda pintadas en los resultados |
| `warning` / `error` | Valores sin confirmar (✨) y avisos / errores y **botones de eliminar** (en rojo, `dangerButton`) |

Para cambiar un color, edita su valor (`0xFF` + RRGGBB). Para añadir una paleta, copia un bloque `AppPalette(...)`,
dale otro `id`, agrégala a `kPalettes` y pon su nombre en `l10n_es.dart`. La elección se guarda (`palette`) y
se combina con Claro / Oscuro / Sistema. El selector de Ajustes muestra cuatro puntos de color por paleta
(`PaletteSwatch`).

`buildTheme()`, en el mismo archivo, aplica esos valores. Ahí están los botones con marco, esquinas redondas y
fondo un poco más claro que el de la pantalla (`framed`), la densidad compacta y los cuadros de texto compactos.
`Framed` es el marco que rodea al selector "Ordenar".

---

## 2. Pantalla principal: `app/lib/screens/home.dart`

| Qué | Dónde |
|---|---|
| Laptop: a la izquierda buscador + árbol, a la derecha resultados. El panel izquierdo empieza tan ancho como el buscador: de "Número CDU" a "Buscar", con el mismo margen a los dos lados (`SearchPanel.margin`, 10 px) | `_WideBody`; el ancho sale de `SearchPanel.naturalWidth()`, que mide los textos en el idioma actual |
| Divisor arrastrable (el ancho se recuerda entre sesiones; **doble clic** = volver al ancho del buscador) | `_DragDivider`; guardado en `AppState.setTreeWidth` (`tree_width`, en píxeles) |
| Teléfono: buscador y árbol de frente; "Buscar" desliza los resultados desde la derecha | `HomeScreen.build` → `_TreePane(onSearched: ...)` y `openResultsPage()` (duración y curva del deslizamiento en `PageRouteBuilder`) |
| Casilla "seleccionar todo", contador y selector de orden con marco | `_ResultsPane`, `_SortSelector` |
| Barra de acciones de la selección | `_SelectionBar`; las acciones están en `core/actions.dart` → `bulkPin()` y `bulkTrashFlow()` |
| Menú lateral (en el teléfono, "Biblioteca" y "Guardado en este dispositivo" también abren los resultados) | `SideMenu` |

El buscador está sobre el árbol. Si el panel izquierdo mide 900 px o más (`SearchPanel.wideFrom`), los grupos
"Número CDU" y "Texto" van lado a lado; si no, uno debajo del otro, con "Buscar" al final de la fila "Campo".

Se quitaron "All items" (ahora es "Buscar" con todo vacío), el engrane de filtros con su ventana, "Expand all"
y el chip "Include subclasses" (ahora lo hace la casilla "Búsqueda exacta").

---

## 3. Buscador: `app/lib/widgets/search_panel.dart` (nuevo)

```
BUSCADOR                                                         (vaciar) (?)
Número CDU [____________][🌳]   Texto [____________][Buscar]
           ☐ Búsqueda exacta          ☐ Búsqueda exacta
           ☐ Incluir cancelados  Campo [Todos los campos ▾]
ÁRBOL CDU                                                        (contraer)
```

"Texto" va justo después del botón del árbol si el panel mide 620 px o más (`SearchPanel.sideBySideFrom`); si
no, debajo. Los cuadros miden `kSearchBoxWidth` (180), lo que ocupa "Incluir números cancelados".

Los cuadros de búsqueda los dibuja la app (`_SearchBox`, mismo marco que "Campo") para que el texto quede
exactamente centrado; con el borde estándar de Flutter quedaba 2 px arriba. Las cabeceras "Buscador" y
"Árbol CDU" son `PaneHeader` (en `theme.dart`).

- Las etiquetas "Número CDU", "Texto" y "Campo" van alineadas a la derecha en una columna de ancho
  `SearchPanel.labelWidth` (92). Así "Campo" queda alineado con "Texto".
- En pantallas de menos de 760 px los dos grupos se apilan (condición `wide` en `build`).
- **Campo**: menú con casillas (`_FieldPicker`). Si no marcas ninguna, busca en todos los campos. Los nombres de
  campo de Zotero llegan del servidor ya traducidos.
- 🌳 abre el Number builder y su número se coloca en el cuadro.
- (?) abre la ayuda, empezando por la parte de búsqueda.
- Clic en una clase del árbol: la pone en "Número CDU" (búsqueda libre, con subdivisiones) y busca. En el
  teléfono además desliza a los resultados. La función es `AppState.selectNode`.
- Estado de la búsqueda (cuadros, casillas, campos): `core/app_state.dart`, sección `// query`. Los parámetros que
  se envían al servidor salen de `_params()`.

**Sintaxis, siempre activa** (es la "especie de regex"; no distingue mayúsculas ni acentos):

| Cuadro | Escribes | Encuentra |
|---|---|---|
| Número CDU | `61` | 61 y sus subdivisiones, también dentro de combinaciones: 616.1, 004.8:61, 61(460) |
| | `004.8:61` | elementos que tengan 004.8 **y** 61 (los signos entre partes no se comparan: así se acota parte por parte) |
| | `(460)` | todo lo que tenga España o una de sus regiones |
| | exacta + `004.8*` | el número completo tal cual; `*` = cualquier cosa, `?` = un carácter |
| | + incluir cancelados | además, elementos clasificados con un número cancelado cuyo sustituto cae bajo el buscado |
| Texto | `redes neuronales` | las dos palabras, en cualquier orden y en cualquier campo marcado |
| | `"redes neuronales"` | la frase junta |
| | `fisica \| quimica` (o `OR`) | cualquiera de las dos |
| | `redes -sociales` | excluye los que tengan "sociales" |
| | `electr*`, `organi?ation` | comodines |
| | exacta | toda la frase, como palabras completas (los comodines siguen funcionando) |

Esta lógica vive en el **servidor**: `server/search.py`. El texto la tiene en `smart_text_matcher` y
`parse_text_query`; la CDU, en `udc_filter`. Arriba del archivo está la explicación completa. Se usa desde
`list_items` en `server/routes_library.py` (parámetros nuevos `udc_q`, `udc_exact`, `udc_cancelled`,
`text_exact`, `fields`) y desde `run_smart_search` en `server/library.py`. La prueba que la cubre es
`test_search_v02` en `server/tests/test_api.py`.

Sin conexión, la app usa un filtro sencillo: todas las palabras, y el número CDU como parte del número del
elemento. Está en `AppState._showCached`.

---

## 4. Number builder: `app/lib/widgets/udc_builder.dart` (nuevo)

Se llama siempre con `buildUdcNumber(context, initial: ..., doneLabel: ...)`. Lo usan el buscador y el
formulario del elemento (`_pickUdc` en `screens/item_form.dart`). Sustituye a `screens/udc_picker.dart`, que se
borró.

- **Laptop**: ventana flotante. **Teléfono**: página completa igual a la pantalla del árbol, pero arriba lleva el
  recuadro del número y los signos.
- Botones de signo: `+  /  :  ::  [  ]` y ⌫ (lista `_signs`). No puse `=`, `( )`, `" "` ni `-0` porque ya vienen
  dentro de los nodos auxiliares del árbol (`=134.2`, `(460)`, `"18"`); serían redundantes.
- **Reglas del clic**, en `_onClass`:
  - Una clase principal **sustituye** la última parte: 6 → 61 → 616, sin que quede "661".
  - Un auxiliar **se añade**: 616 + (460) = 616(460). Si es de la misma tabla, sustituye al anterior:
    (46) → (460).
  - Tras pulsar un signo, la clase siguiente **se añade** después del signo: 004.8 : 61 = 004.8:61.
  - Un auxiliar especial listado bajo su clase (por ejemplo `62-1`) solo añade `-1` si el número ya tiene 62.
- El recuadro también se puede editar a mano. Debajo se ve el desglose en vivo.
- **Ayuda (?)**: `widgets/udc_help.dart`. El contenido está en las listas `_en`/`_es` (cómo se arma un número) y
  `_enSearch`/`_esSearch` (cómo buscar). Es un resumen de *Using UDC: Practical Guide*: tablas principales,
  signos, auxiliares comunes y especiales, orden de cita, ejemplos y reglas del constructor. Para editarla:
  `_H('Título')`, `_P('Párrafo con «notación» y **negritas**')` y `_T([['código', 'significado'], ...])`.

---

## 5. Árbol: `app/lib/widgets/udc_tree_view.dart`

- **Cuadros [+] / [−]** para desplegar y contraer (`_ToggleBox`, tamaño `_box`) y **líneas guía** (├ └ │) dibujadas por la propia app en `_GuidePainter`. No usé el paquete
  `flutter_fancy_tree_view`: el árbol tiene unas 72 000 clases y hoy se dibuja muy rápido porque todas las filas
  miden lo mismo. El paquete cambiaría eso y sería una dependencia más que mantener. El dato de qué líneas dibujar
  sale de `UdcIndex.rows()` en `core/models.dart` (campos `isLast` y `continues` de `TreeRow`).
- Si el panel es angosto, la sangría se reduce sola para que los nombres sigan leyéndose (`indent` en `build`).
- **Globo con el nombre completo** al pasar el mouse (pulsación larga en el teléfono). Aparece a los 450 ms
  (`waitDuration` en `_Row`).
- (i) y "Sin clasificar" en tono tenue (`kFaintAlpha`). Se quitaron los conteos de archivos y "All items".

---

## 6. Tarjeta de resultados: `app/lib/widgets/item_tile.dart`

| Qué | Dónde |
|---|---|
| Casilla de selección | `ItemTile.build` (`Checkbox`) → `AppState.toggleSelected` |
| Título en 1 línea con "..." y globo con el título completo | `ItemTile.build` (`maxLines: 1`) |
| Autores: máximo 3, luego "(+n)"; globo con todos | `shortCreators(item, max: 3)` |
| Fila "Fecha de adición" en la ficha | `_Detail.build` → `formatAdded()` (formato `AAAA-MM-DD HH:MM`, hora local) |
| Botones de acción hasta abajo, después de Material suplementario y Notas | final de `_Detail.build` |
| **Desglose de la CDU** (cada parte con su significado; clic = información de la clase) | `widgets/udc_breakdown.dart` → `UdcBreakdown`; la separación en partes está en `core/udc_notation.dart` (`tokenizeUdc`, `explainUdc`) |
| Material suplementario más compacto (abrir y sin conexión como íconos) | `SupplementarySection` |

En el desglose, un significado en gris cursiva es el de la clase más amplia que existe en el árbol; pasa cuando
el número es más detallado que el árbol. Los signos (`:`, `+`...) muestran su nombre.

**Citation key**: se quitó de la ficha, del buscador y de la búsqueda en "todos los campos". En la base de datos
sigue existiendo, porque el servidor la usa como nombre del PDF en disco y para exportar a Zotero. En el
formulario, la casilla ahora dice "Regenerar nombres de archivo" y hace lo mismo que antes.

---

## 7. Ventana de información de clase: `app/lib/widgets/udc_info_dialog.dart`

- Cada sección lleva un título con ícono y el texto dentro de un recuadro suave con una barra de color a la
  izquierda (`_Section`).
- Los textos largos (como "INFORMATION ON SPECIAL AUXILIARY TABLES") se parten donde la nota enumera
  ("A.", "(a)", "(b)"...); cada parte lleva su marca como insignia. "Examples:", "e.g." y similares van resaltados.
  Las notaciones dentro del texto aparecen en color y, si la clase existe, son subrayadas y se pueden pulsar.
  Esto lo hace `widgets/rich_note.dart` (`RichNote`, `richLine`), que también usa la ayuda.

---

## 8. Idioma: `app/lib/core/i18n.dart` y `app/lib/core/l10n_es.dart`

- El idioma que elige el usuario (Ajustes → Idioma) se aplica a **toda** la app: menús, mensajes, ayuda, nombres
  de campos de Zotero (el servidor ya los da en español con `es-ES`), árbol CDU y los textos propios de Flutter
  (copiar, pegar, atrás). La primera vez se usa el idioma del sistema. Una clase sin nombre en español se muestra
  en inglés.
- **Cómo funciona**: en el código cada texto va como `tr('English text')`. `l10n_es.dart` es una tabla
  `'English text': 'Texto en español'`. Para corregir una traducción, edita el lado derecho. Si falta un texto en
  la tabla, sale en inglés; nunca se rompe nada.
- No usé el sistema ARB de Flutter que te había propuesto: requiere un paso de generación de código y más
  configuración en `app_build`. Esta tabla es un solo archivo de texto y no depende de herramientas.
- También están traducidos los mensajes de error más comunes del servidor (sección final de la tabla).
- Para añadir otro idioma: copia `l10n_es.dart` (por ejemplo `l10n_fr.dart`), traduce el lado derecho y agrégalo
  en `i18n.dart` (`uiLanguages` y `_tables`).
- Para ver qué textos del código faltan en la tabla, busca en VS Code (Ctrl+Shift+F) la expresión regular
  `tr\('` y compara con la tabla. Hoy no falta ninguno.
- Ajuste guardado: `ui_lang`. Antes era `udc_lang` y solo cambiaba el árbol; la app lee el valor viejo si existe.

---

## 9. Bugs

| Bug | Causa | Arreglo |
|---|---|---|
| Pantalla roja al añadir material suplementario ("bottom overflowed by 99319 pixels") | `askText` (el cuadro que pide la etiqueta) liberaba su controlador de texto mientras el diálogo aún se cerraba. Eso lanza un error durante el dibujo, y Flutter pone en su lugar un recuadro de error de 100 000 px de alto (100 000 − 681 = 99 319). Además, después se recargaba toda la lista de resultados con la ficha abierta | `core/actions.dart`: `askText` libera el controlador después de la animación, y `addSupplementaryFlow` solo actualiza las cifras de almacenamiento (`AppState.refreshStats`), sin recargar la lista |
| Pantalla roja ocasional | 1) El mismo error en los diálogos de notas, etiqueta y usuarios. 2) En el árbol, el número de la clase no podía encogerse: en ramas profundas o paneles angostos la fila se desbordaba | 1) `askText` y `screens/admin.dart` (`_addUser`, `_resetPassword`). 2) El número y el nombre van en un solo texto con "...", y la sangría se reduce sola |
| (encontrado al probar) La app se cerraba al escalar la letra | El tema base no trae tamaños; escalar sin tamaños falla | `buildTheme`: usa los tamaños de Material antes de escalar |

---

## 10. Archivos

**Nuevos**: `app/lib/core/theme.dart`, `core/i18n.dart`, `core/l10n_es.dart`, `core/udc_notation.dart`,
`widgets/search_panel.dart`, `widgets/udc_builder.dart`, `widgets/udc_breakdown.dart`, `widgets/udc_help.dart`,
`widgets/rich_note.dart`, `app/test/ui_test.dart`, `server/search.py`.

**Reescritos o muy cambiados**: `main.dart`, `core/app_state.dart`, `core/actions.dart`, `screens/home.dart`,
`screens/settings.dart`, `widgets/item_tile.dart`, `widgets/udc_tree_view.dart`.

**Con cambios menores** (textos traducibles y ajustes puntuales): `core/models.dart` (líneas del árbol),
`screens/item_form.dart`, `screens/login.dart`, `screens/trash.dart`, `screens/admin.dart`,
`widgets/udc_info_dialog.dart`, `app/pubspec.yaml` (`flutter_localizations` y versión 0.2.0), `setup_app.ps1`
(copia también las pruebas), `server/routes_library.py`, `server/library.py`, `server/tests/test_api.py`.

**Borrado**: `app/lib/screens/udc_picker.dart` (lo sustituye el Number builder).

---

## 11. Pendiente o a revisar en pantalla

- No pude ver la app funcionando: las pruebas la dibujan, pero el aspecto final (colores, tamaños) hay que mirarlo
  y ajustarlo con `theme.dart`.
- Los avisos de coherencia tipo↔forma CDU los arma el servidor con datos variables, así que siguen en inglés.
- "Exportar selección (CSV)" no está hecho (lo propuse como opcional).
- El árbol en español depende de que la base del servidor tenga los nombres en español. En la base de esta
  laptop, por ejemplo, la clase 61 solo tiene nombre en inglés.

---

## 12. Interfaz optimista (papelera y "Enviar a la papelera")

- **Papelera** (`screens/trash.dart`): al pulsar Restaurar o Eliminar, la fila muestra una rueda
  ("Restaurando..."). Luego muestra ✓ "Restaurado" y se recoge sola (`_showDone` 1.1 s, `_fold` 0.25 s). Si el
  servidor falla, muestra el error en la fila con "Reintentar". Solo "Eliminar definitivamente" pide
  confirmación, porque no se puede deshacer.
- **Enviar a la papelera** desde los resultados (uno o varios): los elementos salen de la lista en el acto. Si el
  servidor los rechaza, vuelven a su lugar con un aviso. Funciones `AppState.takeOut()` / `putBack()`, usadas
  en `deleteItemFlow` y `bulkTrashFlow` (`core/actions.dart`).
- **Barra de selección**: solo los botones, sin fondo, alineados a la izquierda, de `kActionButtonHeight` (34)
  de alto.
- **Árbol**: en los nombres "Table 1a - ...", "Table 1b - ...", el "Table 1x" va en gris tenue más claro
  (`kTableAlpha`) y en negritas, con un espacio en lugar del guion (`_labelSpans` en `udc_tree_view.dart`).
