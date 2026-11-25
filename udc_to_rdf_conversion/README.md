# Árbol UDC: descarga y fusión (`udcs-skos.rdf`)

Herramientas para mantener `udcs-skos.rdf`, el árbol UDC completo (jerarquía, etiquetas, notas, ejemplos de
combinación, «See also», tipo de auxiliar y clases canceladas) que usan el servidor, la app y el PoC. Solo usan la
biblioteca estándar de Python.

**Dónde está cada cosa.** El **RDF final** vive en `biblioteca_udc/server/udc_data/udcs-skos.rdf`: lo leen
`udc_import.py` (servidor) y el PoC (`udc_poc/config.py`). Todo lo demás se queda en esta carpeta. Los scripts usan
estas rutas por defecto (constantes `CONVERSION_DIR`, `GENERATED_DIR` y `SERVER_UDC_DIR` de `modules/udc_merge.py`):
no hay que mover nada a mano.

```
udc_to_rdf_conversion/
├── udc_main_tree_fusion.py   el que se ejecuta: snapshot → RDF
├── udc_export_txt.py         herramienta aparte: RDF → .txt (verificar, revisar traducciones)
├── extra_notes.json          notas añadidas a mano (se aplican al final de cada fusión)
├── tree_decisions.json       excepciones a la colocación automática de clases (vacío por defecto)
├── udcs-skos.rdf.bak         respaldo: el RDF antes de la última fusión (no se sube a git)
├── modules/                  código que usa la fusión: udc_merge.py, udc_records.py, udc_cancelled.py
└── generated/                salidas intermedias de la última fusión (el RDF ya contiene su información)
```

| En `generated/` | Qué es |
|---|---|
| `UDC_hierarchy.txt` | El árbol en texto, generado desde el snapshot (formato abajo). |
| `udc_records.json` | Las fichas ya interpretadas (mismo formato que `extra_notes.json`). |
| `udc_cancelled.json` | Las clases canceladas ya interpretadas. |
| `fusion_report.txt`, `conversion_report.txt`, `udc_records_report.txt`, `udc_cancelled_report.txt` | Informes de la última fusión. |
| `*_es.txt`, `*_es.json` | Lo mismo para una descarga en otro idioma (sufijo del idioma). |

`generated/` se puede vaciar cuando se quiera: el servidor y el PoC solo leen el RDF, y la fusión lo regenera desde el
snapshot. La descarga está en `../udc_tree_download/udc_tree_download.js` y los snapshots se guardan en
`../udc_tree_download/snapshots/`.

## Actualización completa: dos pasos

1. **Descarga** (navegador, ~1-2 h estimadas; se puede pausar y seguir otro día): con la sesión de UDC Online
   iniciada, en la página de búsqueda (`search.php`), pegar `udc_tree_download/udc_tree_download.js` en la consola
   (F12) y pulsar «Empezar / Continuar». El avance se guarda en el navegador (IndexedDB): si se recarga la página o
   caduca la sesión, iniciar sesión, pegarlo de nuevo y pulsar el mismo botón. Al terminar descarga
   `udc_snapshot_AAAA-MM-DD.json.gz` (guardarlo en `udc_tree_download/snapshots/`). «Exportar ahora» saca uno
   parcial para revisar; «Borrar datos» empieza de cero (hacerlo antes de cada descarga nueva, p. ej. de otro idioma,
   en el mismo navegador).
   - Fase 1, árbol: `getTreeData.php`, rama por rama (jerarquía, orden, etiquetas y la clave interna de cada ficha,
     con la que también se bajan las 4 notaciones con comas).
   - Fase 2, fichas: la ficha de una clase lista **todas** sus subdivisiones con sus notas, 100 por página
     (`n=…&p=k&x=1&cs=0&z=-2`). Solo se pide la de las clases que aún no estén cubiertas: ~1 000-2 000 peticiones en
     lugar de 72 000. Los dígitos sueltos (`0`, `5`) solo devuelven una fila; se bajan sus hijos. Antes comprueba que
     la ficha de `330.322` traiga su ejemplo `330.322.014.3`.
   - Fase 3, búsqueda con «Include cancelled»: canceladas y lista de notaciones vigentes, por prefijo de notación
     (100 resultados por página; los prefijos de un solo dígito anuncian miles y muestran una fila, así que se
     dividen: `0` → `00`…`09`, `0.`, `0-`…). Las páginas a las que les faltan filas se guardan (`diag`).
   - Fase 4, huecos: ficha propia de las vigentes que no salieron en ninguna ficha.
   - Guarda también los nombres de los campos de la interfaz (formulario de búsqueda: «Scope Note»…) y su idioma.
2. **Fusión** (Python, ~1,5 min):
   ```
   python udc_main_tree_fusion.py ../udc_tree_download/snapshots/udc_snapshot_AAAA-MM-DD.json.gz
   ```
   Guarda el RDF anterior en `udcs-skos.rdf.bak`, escribe las salidas intermedias en `generated/` y el RDF nuevo en
   `server/udc_data/` (aplica `extra_notes.json` al final). Opciones: `--dry-run` (escribe árbol, JSON e informes, no el RDF ni el respaldo),
   `--lang xx`, `--prune` (borra del RDF lo que ya no está en el sitio; solo con un snapshot completo en inglés),
   `--rdf`, `--workdir`, `--backup`, `--decisions`.
3. **Después**: reimportar en el servidor (`python udc_import.py`, ya sin ruta) y reconstruir el índice del PoC.

**Respaldo (`udcs-skos.rdf.bak`).** Cada fusión real (sin `--dry-run`) copia el RDF del servidor a
`udc_to_rdf_conversion/udcs-skos.rdf.bak` justo antes de escribirlo, y fusiona leyendo esa copia. Así el respaldo es
siempre **la versión anterior a la última fusión**: se reemplaza solo, cada vez que se fusiona. Si una fusión sale
mal, se recupera copiando el `.bak` sobre `server/udc_data/udcs-skos.rdf`. Ojo: dos fusiones seguidas (p. ej.
inglés y luego español) dejan como respaldo el estado intermedio; para conservar uno concreto, copiarlo con otro
nombre antes. Para volver más atrás, el historial de git.

**Otro idioma.** El mismo script sirve con la interfaz en cualquier idioma: reconoce filas, páginas, recuentos,
iconos (`incl_square.png`) y símbolos (`◇`, `⇨`) por la estructura del HTML, no por su texto. Luego:
```
python udc_main_tree_fusion.py <snapshot> --lang es --dry-run     (revisar informes)
python udc_main_tree_fusion.py <snapshot> --lang es
```
- El árbol solo aporta etiquetas `@es`: la jerarquía la define la descarga en inglés. Las notas de las fichas entran
  como `@es`; las canceladas no se tocan (guardan una sola etiqueta, la inglesa).
- Los nombres de las notas («Scope Note:», «Nota de…») son lo único que depende del idioma. La fusión los toma del
  propio snapshot (los nombres del formulario de búsqueda, que son los mismos que usan las fichas) y, de respaldo,
  de `NOTE_LABELS` en `modules/udc_records.py`. Si alguno no se reconoce, sale en «No reconocido» de
  `udc_records_report_es.txt` y se añade a `NOTE_LABELS`.
- Archivos con sufijo (`UDC_hierarchy_es.txt`, `udc_records_es.json`, informes `_es`), para no pisar los de inglés.

**Árbol completado por notación.** El árbol del sitio no muestra algunas clases vigentes que sí aparecen en sus
fichas o en la búsqueda (pasó con `903`, `66.047.4/.5`, `598.141/.143`, `599.63` y Guadeloupe). La fusión las añade
sola, con sus notas:
- padre = el rango más ajustado que la contiene (`903.01` → `903.01/.08`; `598.141` → `598.131/.143`); si no hay
  rango, el prefijo más largo que exista (`903.36` → `903.3`);
- posición = el orden del sitio, si alguna página lista al padre y luego a la clase; si no (el sitio la muestra fuera
  de lugar), orden de notación de la UDC (`-`, `.0`, `` ` ``, `.1`…`.9`);
- las vigentes sin ficha (sin etiqueta, como los rangos `622.01/.06`, `629.3.01/.08`, `681.7.01/.08`) no se añaden;
- excepciones en `tree_decisions.json`: `"exclude": ["notación", …]` para no añadir una, `"parent": {"notación":
  "padre"}` para forzar el padre;
- `fusion_report.txt` lista cada clase añadida con su padre y el criterio (rango / prefijo).

Criterio general: si el sitio se contradice, decide la notación.

**Probado** (noviembre de 2026) con un snapshot armado con la descarga anterior (árbol original del sitio, fichas y
búsqueda): la fusión colocó sola las 56 clases que antes se añadieron a mano y reprodujo el árbol byte a byte y el
RDF idéntico (salvo la fecha); también corre con `--lang es`. El script del navegador está verificado en sintaxis;
la primera descarga real es su prueba (si algo falla, lo descargado queda guardado y se puede exportar).

## Formato del `.txt`

```
- AUXILIARY TABLES
    -- COMMON AUXILIARY SIGNS
        +, / Table 1a - Connecting symbols. Coordination. Extension
            + Coordination. Addition
```

- Un nodo por línea: `notación␠etiqueta`. La notación termina en el primer espacio.
- Sangría de **4 espacios** por nivel (sin tabuladores, sin saltar niveles). Las notaciones no se pueden repetir.
- Las líneas que empiezan con guiones (`-`, `--`, `---`, `----`) son encabezados de grupo: en el RDF quedan **sin
  notación** y se identifican por el número de guiones.
- Hay 4 notaciones con comas que no se pueden cortar por el primer espacio (`+, /`, `:, ::, []`, `*, A/Z` y
  `-1/-9,.01/.09, \`0/\`9`). Están en `COMMA_NOTATIONS` dentro de `udc_merge.py`; si aparece otra, el script se
  detiene y dice cuál añadir.
- Codificación UTF-8 (con o sin BOM).

## Uso por partes

La fusión hace todo esto sola; estos comandos sirven para casos puntuales, desde esta carpeta
(`D` = `../biblioteca_udc/server/udc_data`, `G` = `generated`).

- Añadir las etiquetas de un idioma desde un `.txt` (no cambia la jerarquía; la etiqueta anterior que cambie queda
  como `hiddenLabel`):
  ```
  python modules/udc_merge.py --rdf D/udcs-skos.rdf --txt UDC_hierarchy_de.txt --lang de
  ```
- Actualizar la estructura desde un `.txt` en inglés (crea, mueve y reordena; nunca borra notas; `--prune` borra lo
  que no esté en el `.txt`, solo con el árbol completo):
  ```
  python modules/udc_merge.py --rdf D/udcs-skos.rdf --txt G/UDC_hierarchy.txt --lang en
  ```
- Reinterpretar partes `*.jsonl.gz` sin la fusión: `python modules/udc_records.py --parts carpeta` (líneas
  `{"n": notación, "h": html}`) y `python modules/udc_cancelled.py --parts carpeta` (líneas de la fase 3). Escriben
  en `G`.

Opciones de `udc_merge.py`:

| Opción | Efecto |
|---|---|
| `--lang xx` | Idioma de las etiquetas del `.txt` (por defecto `en`). |
| `--mode structure\|labels` | Fuerza el modo (por defecto `structure` si `--lang en`, `labels` en otro caso). |
| `--prune` | (structure) borra los nodos ausentes del `.txt`. |
| `--keep-langs en,de` | Descarta del RDF de entrada los literales de otros idiomas. |
| `--notes archivo.json` | Notas extra (por defecto `extra_notes.json` de esta carpeta, si existe). |
| `--records archivo.json` | Fichas (por defecto `G/udc_records.json`, si existe). Se aplican **antes** que `--notes`. |
| `--cancelled archivo.json` | Canceladas (por defecto `G/udc_cancelled.json`, si existe). Sin el archivo se conservan las que ya trae el RDF. |
| `--out archivo.rdf` | Salida (por defecto sobrescribe `--rdf`, con `.bak` al lado). |
| `--report archivo.txt` | Informe (por defecto `G/conversion_report.txt`). |
| `--dry-run` | Solo genera el informe; no toca el RDF. |

## Notas manuales: `extra_notes.json`
Se aplican en cada ejecución (son idempotentes), así que no se pierden al regenerar. Clave = notación (o `heading-N`
para un encabezado):

```json
{
  "-1/-9,.01/.09, `0/`9": {
    "nodeType": "info",
    "prefLabel": {"es": "Información sobre las tablas auxiliares especiales"},
    "scopeNote": {"en": "…", "es": "…"},
    "applicationNote": {"en": "…"},
    "example": {"en": ["62-242-436    Engine pistons - spherical"]}
  }
}
```

Cada campo reemplaza los valores de ese idioma. Un texto vacío se ignora y queda señalado en el informe. Campos
admitidos: `nodeType`, `auxType`, `prefLabel`, `scopeNote`, `applicationNote`, `informationNote`, `includingNote`,
`example` y `related` (lista de notaciones; reemplaza la lista del nodo).

Precedencia por nodo y campo: lo que ya trae el RDF < `udc_records.json` < `extra_notes.json` (lo manual siempre
gana). Un campo presente y no vacío reemplaza al anterior; uno vacío no borra nada. Para **quitar** datos ya
fusionados, partir del respaldo o de una versión anterior del RDF en git.

## Fichas de UDC Online (`modules/udc_records.py`)

Cada clase tiene en UDC Online una ficha con información que el árbol no trae: notas, «Including», referencias y los
recuadros `◇` de **ejemplos de combinación** (p. ej. en `330.322`: `330.322.014.3 Net investment`). No son nodos del
árbol; se guardan como notas del nodo que las muestra. El HTML se guarda casi crudo en el snapshot: si hay que corregir
la interpretación, se corrige `udc_records.py` y se repite la fusión con el mismo snapshot, sin descargar.

Cómo lee cada ficha:
- La ficha de una clase muestra la clase (en negrita) y **todas** sus subdivisiones, cada una con su panel oculto
  (`div id="rdNNN"`), 100 por página. Si una clase aparece en varias fichas se toma la de su propia ficha (si la hay);
  el informe avisa si dos fichas difieren.
- La celda de la notación lleva la clase CSS `aux-cell` (auxiliar común) o `spec-aux-cell` (auxiliar especial) →
  `auxType` (`common` / `special`; sin valor = tabla principal).
- Junto a la etiqueta, el icono del recuadro (`incl_square.png`) → `includingNote`. En el panel: párrafos
  `Scope Note:` / `Application Note:` / `Information Note:` (o sus nombres en otro idioma) → `scopeNote` /
  `applicationNote` / `informationNote`; filas `◇` → `example` (`notación␣␣␣␣texto`); filas `⇨` → `related`.
- UDC Online escribe los guiones de las notaciones como guion no separable (U+2011: `2‑1`); se convierten a `-`.
- Todo lo que no reconoce (otro icono, otra nota, un párrafo sin etiqueta…) queda en «No reconocido» del informe. Si
  aparece algo ahí, hay que ampliar el script, no editar el JSON.
- Los `related` hacia notaciones que no están en el árbol se descartan y se listan en el informe.

Descarga de noviembre de 2026 (con scripts anteriores): 71 803 fichas, 0 errores, 0 elementos no reconocidos; datos en
21 709 clases (Scope note 1 627, Application note 1 389, Information note 908, Including 11 481, 7 210 ejemplos de
combinación en 2 791 clases, véase también 8 336). Avisos normales del informe: ~1 050 etiquetas difieren entre ficha y
árbol (casi siempre un punto final o `º`/`°`; se conserva la del árbol), y el sitio lista algunas clases fuera de
lugar (las `(729.741.…)` de Guadeloupe salen bajo Saint Kitts y `(728.4)`; las de `66.047.4/.5`, bajo `599.63`).

## Clases canceladas (`modules/udc_cancelled.py`)

UDC Online conserva las clases canceladas desde 1993 y las muestra al buscar con «Include cancelled» (noviembre de
2026: 12 287 notaciones, 12 309 cancelaciones; 22 sin reemplazo, 3 219 con varios; 335 notaciones canceladas se
volvieron a usar con otro significado, p. ej. `94`):

```
568  x [2011, E&C33] Sauropsida (fossil). Synapsida (fossil)  → 56; 598
```

Notación cancelada, año, número de *Extensions and Corrections* (E&C), etiqueta antigua y clases que la reemplazan
(de 0 a 12; «No replacement» si no hay). Sirven para convertir libros clasificados con ediciones antiguas. udcc.org
publica archivos anuales, pero solo de 1994 a 2011; UDC Online trae también las posteriores.

El informe `udc_cancelled_report.txt` lista formatos no reconocidos, prefijos cuyas cuentas no cuadran, reemplazos
que no son clases del árbol (p. ej. combinaciones como `94(4/9)`), notaciones canceladas que hoy vuelven a existir y
la comparación de las notaciones **vigentes** de la búsqueda con el árbol. Es normal que algunas páginas traigan menos
filas de las anunciadas: el sitio anuncia más de las que muestra (en la tabla `.00x` el recuento es el doble).

En el RDF van **fuera de la jerarquía**, como `udcx:CancelledClass` (no `skos:Concept`), para que la app, el servidor
y el PoC no las lean como clases; una misma notación puede estar cancelada y volver a usarse.

```xml
<udcx:CancelledClass rdf:about="urn:udc:cancelled:568%402011">
  <udcx:cancelledNotation>568</udcx:cancelledNotation>
  <rdfs:label xml:lang="en">Sauropsida (fossil). Synapsida (fossil)</rdfs:label>
  <owl:deprecated rdf:datatype="…#boolean">true</owl:deprecated>
  <udcx:cancelledYear rdf:datatype="…#integer">2011</udcx:cancelledYear>
  <udcx:cancelledIn>E&amp;C33</udcx:cancelledIn>
  <udcx:replacedByNotation>56</udcx:replacedByNotation>
  <dct:isReplacedBy rdf:resource="urn:udc:56"/>
  …
</udcx:CancelledClass>
```

`udcx:replacedByNotation` guarda todos los reemplazos en orden (también los que no son clases del árbol);
`dct:isReplacedBy` enlaza solo los que sí lo son. Opcionales: `udc:includingNote` y `udcx:replacementNote`.

## Qué contiene el RDF

| Dato | Propiedad | Notas |
|---|---|---|
| Identificador | `rdf:about` = `urn:udc:` + notación codificada (`urn:udc:62-1%2F-9`) | Se calcula de la notación. Encabezados: `urn:udc:heading-1`…`-4`. |
| Notación | `skos:notation` | Ausente en los encabezados. |
| Etiqueta | `skos:prefLabel@xx` | Si falta el idioma elegido, usar `en`. |
| Padre / hijos | `skos:broader` / `skos:narrower` | Raíces: `skos:topConceptOf`. |
| Orden entre hermanos | `udcx:order` (`urn:udc:ext#order`) | Entero desde 0, orden del `.txt`. |
| Tipo de nodo | `udcx:nodeType` | `heading` (grupo sin notación) o `info` (informativo, no asignable). Sin valor = clase normal. |
| Tipo de auxiliar | `udcx:auxType` | `common` o `special`, según la marca de UDC Online. Sin valor = tabla principal. |
| Scope note | `skos:scopeNote@xx` | |
| Application note | `udc:applicationNote@xx` (`http://udcdata.info/udc-schema#`) | Incluye las antiguas `skos:note` del UDC Summary. |
| Information note | `udc:informationNote@xx` | Información de contexto (p. ej. otros nombres de una lengua). |
| Including | `udc:includingNote@xx` | Conceptos incluidos en la clase («Including …»). |
| Ejemplos | `skos:example@xx` | Formato `notación␣␣␣␣texto`. Son los recuadros `◇` (ejemplos de combinación). |
| Véase también | `skos:related` | |
| Etiquetas anteriores | `skos:hiddenLabel@xx` | Solo para búsqueda. |
| Clases canceladas | `udcx:CancelledClass` (aparte de los conceptos) | Las usan el servidor, la app y el PoC. |

Historia: el RDF nació del UDC Summary (en/fi/sv, ~2 400 clases), fusionado con el árbol completo de UDC Online
(noviembre de 2026; 2 425 clases heredaron notas del Summary). Estado actual: 71 867 clases y 12 309 cancelaciones.

## Verificación tras cada fusión
1. `fusion_report.txt` y `conversion_report.txt`: repetir la fusión con el mismo snapshot debe dar 0 creados,
   0 modificados.
2. Ida y vuelta de la estructura (desde esta carpeta):
   ```
   python udc_export_txt.py --rdf ../biblioteca_udc/server/udc_data/udcs-skos.rdf --out check.txt
   fc /b check.txt generated\UDC_hierarchy.txt
   ```
3. Opcional, con rdflib (en `udc_poc/.venv`): el archivo carga en ~20 s.

## Avisos
- Con ~72 000 nodos, calcular embeddings en el PoC (`python -m udcpoc index`) con bge-m3 en CPU lleva horas.
- Tras cada fusión hay que volver a importar en el servidor (`udc_import.py`) para que la app vea los cambios.
