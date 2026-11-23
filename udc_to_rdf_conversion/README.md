# Conversión del árbol UDC a SKOS (`udcs-skos.rdf`)

Herramientas para generar y actualizar `udcs-skos.rdf` a partir de árboles UDC en texto. Solo usan la biblioteca estándar de Python (no hace falta instalar nada).

| Archivo | Qué es |
|---|---|
| `udc_merge.py` | Fusiona un `.txt` en el RDF (estructura o etiquetas de un idioma). |
| `udc_export_txt.py` | Hace lo contrario: exporta el RDF a `.txt`, para verificar o revisar traducciones. |
| `extra_notes.json` | Notas añadidas a mano (Scope note, Application note, ejemplos, tipo de nodo). |
| `udc_records.py` | Interpreta las fichas descargadas de UDC Online y genera `udc_records.json` y `udc_records_report.txt`. |
| `udc_records.json` | Fichas de UDC Online ya interpretadas (Scope, Application e Information note, Including, ejemplos de combinación, véase también). Mismo formato que `extra_notes.json`; se genera, no se edita a mano. |
| `../udc_tree_download/record_download.js` | Script de consola que descarga esas fichas (ver «Fichas de UDC Online»). |
| `../udc_tree_download/records/` | Las fichas descargadas (`udc_records_part_0001.jsonl.gz` … `0036`). |
| `../udc_tree_download/cancelled_download.js` | Script de consola que descarga las clases canceladas (ver «Clases canceladas»). |
| `udc_cancelled.py` | Interpreta esa descarga y genera `udc_cancelled.json` y `udc_cancelled_report.txt`. |
| `udc_cancelled.json` | Clases canceladas con año, E&C y reemplazos. Se genera, no se edita a mano. |
| `UDC_hierarchy.txt` | Árbol completo en inglés (fuente de la estructura). |
| `udcs-skos.(1)rdf` | UDC Summary original (en/fi/sv). Solo se usó en la primera conversión. |
| `udcs-skos.rdf` | **Resultado** (el que usan la app y el PoC). |
| `conversion_report.txt` | Informe de la última ejecución. |

## Formato del `.txt`

```
- AUXILIARY TABLES
    -- COMMON AUXILIARY SIGNS
        +, / Table 1a - Connecting symbols. Coordination. Extension
            + Coordination. Addition
```

- Un nodo por línea: `notación␠etiqueta`. La notación termina en el primer espacio.
- Sangría de **4 espacios** por nivel (sin tabuladores, sin saltar niveles). Las notaciones no se pueden repetir.
- Las líneas que empiezan con guiones (`-`, `--`, `---`, `----`) son encabezados de grupo: en el RDF quedan **sin notación** y se identifican por el número de guiones.
- Hay 4 notaciones con comas que no se pueden cortar por el primer espacio (`+, /`, `:, ::, []`, `*, A/Z` y `-1/-9,.01/.09, \`0/\`9`). Están en `COMMA_NOTATIONS` dentro de `udc_merge.py`; si aparece otra, el script se detiene y dice cuál añadir.
- Codificación UTF-8 (con o sin BOM).

## Uso

### Añadir un idioma (caso habitual)
Descarga el árbol en ese idioma con el mismo formato y ejecuta:

```
python udc_merge.py --rdf udcs-skos.rdf --txt UDC_hierarchy_de.txt --lang de
```

- Empareja por notación (los encabezados, por número de guiones) y añade `prefLabel@de`. **No cambia la jerarquía.**
- Sobrescribe `udcs-skos.rdf` y guarda antes una copia en `udcs-skos.rdf.bak`.
- En el informe revisa: notaciones del `.txt` que no existen en el RDF, diferencias de jerarquía (solo se avisan) y nodos que quedan sin etiqueta en ese idioma.
- Si una etiqueta ya existía y cambia, la anterior se guarda como `hiddenLabel` (sigue sirviendo para búsqueda).
- Para revisar el resultado: `python udc_export_txt.py --rdf udcs-skos.rdf --out arbol_de.txt --lang de` (los nodos sin traducción salen en inglés).

### Actualizar la estructura (nueva edición en inglés)
```
python udc_merge.py --rdf udcs-skos.rdf --txt UDC_hierarchy.txt --lang en --prune
```

- Modo `structure` (por defecto con `--lang en`): crea nodos nuevos, mueve los que cambian de padre, actualiza orden y etiqueta. Nunca borra notas.
- `--prune` elimina los nodos que no están en el `.txt`. Úsalo **solo con el árbol completo**; sin `--prune`, los nodos ausentes se conservan al final de sus hermanos.

### Primera conversión (ya hecha, solo como referencia)
```
python udc_merge.py --rdf "udcs-skos.(1)rdf" --txt UDC_hierarchy.txt --lang en --prune --keep-langs en --out udcs-skos.rdf
```
Resultado: 71 811 nodos; 2 425 heredaron notas del Summary; se descartaron los literales fi/sv y 27 notaciones obsoletas del Summary (`=43`, `568`, `54-1/-4`…; la lista está en el informe), junto con sus 12 ejemplos.

### Opciones
| Opción | Efecto |
|---|---|
| `--lang xx` | Idioma de las etiquetas del `.txt` (por defecto `en`). |
| `--mode structure\|labels` | Fuerza el modo (por defecto `structure` si `--lang en`, `labels` en otro caso). |
| `--prune` | (structure) borra los nodos ausentes del `.txt`. |
| `--keep-langs en,de` | Descarta del RDF de entrada los literales de otros idiomas. |
| `--notes archivo.json` | Notas extra (por defecto `extra_notes.json` junto al script, si existe). |
| `--cancelled archivo.json` | Clases canceladas (por defecto `udc_cancelled.json` junto al script, si existe). Sin el archivo se conservan las que ya trae el RDF. |
| `--records archivo.json` | Fichas de UDC Online (por defecto `udc_records.json` junto al script, si existe). Se aplican **antes** que `--notes`. |
| `--out archivo.rdf` | Salida (por defecto sobrescribe `--rdf`, con `.bak`). |
| `--report archivo.txt` | Informe (por defecto `conversion_report.txt` junto a la salida). |
| `--dry-run` | Solo genera el informe; no toca el RDF. |

## Notas manuales: `extra_notes.json`
Se aplican en cada ejecución (son idempotentes), así que no se pierden al regenerar. Clave = notación (o `heading-N` para un encabezado):

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

Cada campo reemplaza los valores de ese idioma. Un texto vacío se ignora y queda señalado en el informe. Campos admitidos: `nodeType`, `auxType`, `prefLabel`, `scopeNote`, `applicationNote`, `informationNote`, `includingNote`, `example` y `related` (lista de notaciones; reemplaza la lista del nodo).

## Fichas de UDC Online (`udc_records.json`)

Cada clase tiene en UDC Online una ficha con información que el árbol no trae: notas, «Including», referencias y los recuadros `◇` de **ejemplos de combinación** (p. ej. en `330.322`: `330.322.014.3 Net investment`). No son nodos del árbol; se guardan como notas del nodo que las muestra.

Flujo (en tres pasos separados: si hay que corregir la interpretación, no se vuelve a descargar):

1. **Descarga** (navegador, ~3 h): con la sesión de UDC Online abierta, pegar `udc_tree_download/record_download.js` en la consola y elegir `UDC_hierarchy.txt`. Primero guarda `udc_record_sample_330.322.html` y comprueba que contiene «Net investment». Luego guarda `udc_records_part_0001.jsonl.gz`, … (HTML casi crudo, comprimido) en la carpeta de descargas. Si se interrumpe, al volver a pegarlo continúa en la parte pendiente. Mover las partes a `udc_tree_download/records/`.
2. **Interpretación** (Python, ~1 min):
   ```
   python udc_records.py
   ```
   (`--parts carpeta` si las partes están en otro sitio). Genera `udc_records.json` y `udc_records_report.txt`.
3. **Fusión** (~5 s): `python udc_merge.py --rdf udcs-skos.rdf --txt UDC_hierarchy.txt --lang en`; aplica `udc_records.json` antes que `extra_notes.json`. Después, reimportar en el servidor y reconstruir el índice del PoC.

Cómo lee `udc_records.py` cada ficha:
- La ficha de una clase muestra la clase (en negrita) y sus subdivisiones, cada una con su panel oculto (`div id="rdNNN"`). Se toma cada clase de **su propia** ficha; el informe avisa si la fila de la ficha del padre difiere (en la descarga de noviembre de 2026: ninguna).
- La celda de la notación lleva la clase CSS `aux-cell` (auxiliar común) o `spec-aux-cell` (auxiliar especial) → `auxType` (`common` / `special`; sin valor = tabla principal).
- Junto a la etiqueta, el icono `title="Including"` (un recuadro) → `includingNote`. En el panel: párrafos `Scope Note:` / `Application Note:` / `Information Note:` → `scopeNote` / `applicationNote` / `informationNote`; filas `◇` (`title="Example of combination"`) → `example` (`notación␣␣␣␣texto`); filas `⇨` (`title="See also"`) → `related`.
- UDC Online escribe los guiones de las notaciones como guion no separable (U+2011: `2‑1`); se convierten a `-`.
- Todo lo que no reconoce (otro icono, otra nota, un párrafo sin etiqueta…) queda en la sección «No reconocido» del informe. Si aparece algo ahí, hay que ampliar el script, no editar el JSON.
- Los `related` hacia notaciones que no están en el árbol se descartan y se listan en el informe.

Resultado de la descarga de noviembre de 2026: 71 803 fichas (todas las clases menos las 4 notaciones con comas y los 4 encabezados), 0 errores, 0 elementos no reconocidos. Hay datos en 21 709 clases: Scope note 1 627, Application note 1 389, Information note 908, Including 11 481, ejemplos de combinación 7 210 (en 2 791 clases), véase también 8 336.

Avisos del informe que no son errores del script:
- 1 053 etiquetas difieren entre la ficha y el árbol (casi todas por un punto final en «etc.» o por `º`/`°`). Se conserva la del árbol.
- Las 33 subdivisiones de `903` (Prehistory) faltaban en la descarga del árbol; se añadieron a mano a `UDC_hierarchy.txt` (noviembre de 2026; el árbol pasa a 71 844 nodos) con el mismo patrón que el resto: los rangos `903.01/.08` y ``903`1`` cuelgan de `903` y sus miembros, de ellos. Como no tienen ficha propia, sus notas se toman de la ficha de `903`.
- La comparación de la descarga de canceladas con el árbol encontró 19 notaciones vigentes más que faltaban. Se añadieron 16 (noviembre de 2026; el árbol pasa a 71 860 nodos), con sus fichas bajadas aparte (`udc_records_part_0037.jsonl.gz`, de `udc_tree_download/temp_script_missing.js`): `66.047.4/.5` y sus 10 subdivisiones (bajo `66.047.4/.6`), `598.141/.143` y sus 3 subdivisiones (bajo `598.131/.143`) y `599.63` (bajo `599.63/.64`). Las otras 3, `622.01/.06`, `629.3.01/.08` y `681.7.01/.08`, son rangos que solo aparecen en la búsqueda: su vista de ficha no devuelve nada y sus miembros ya cuelgan directamente de `622`, `629.3` y `681.7`, así que no se añadieron.
- 7 notaciones `(729.741.…)` (Guadeloupe) aparecen en la ficha de `(729.732.1)` (Saint Kitts), pero la ficha de `(729.741)` dice que no tiene subdivisiones: es un error de UDC Online y se ignoran.

Orden de precedencia por nodo y campo: Summary original < `udc_records.json` < `extra_notes.json` (lo manual siempre gana). Un campo presente y no vacío reemplaza al anterior; uno vacío no borra nada. Si se corrige `udc_records.py` y hay que **quitar** datos ya fusionados, regenerar desde cero con el comando de «Primera conversión» (lee el Summary original y vuelve a aplicar todo).

## Clases canceladas (`udc_cancelled.json`)

UDC Online conserva las clases canceladas desde 1993 y las muestra al buscar con «Include cancelled» (descarga de noviembre de 2026: 12 287 notaciones, 12 309 cancelaciones; 22 sin reemplazo, 3 219 con varios; 335 notaciones canceladas se volvieron a usar con otro significado, p. ej. `94`):

```
568  x [2011, E&C33] Sauropsida (fossil). Synapsida (fossil)  → 56; 598
```

Notación cancelada, año, número de *Extensions and Corrections* (E&C), etiqueta antigua y clases que la reemplazan (de 0 a 12; «No replacement» si no hay). Sirven para convertir libros clasificados con ediciones antiguas. udcc.org publica archivos anuales, pero solo de 1994 a 2011; UDC Online trae también las posteriores.

Flujo (igual que las fichas):

1. **Descarga** (navegador, ~20-30 min): con la sesión abierta, en la página de búsqueda (`search.php`), pegar `udc_tree_download/cancelled_download.js` y pulsar «Empezar». Busca por prefijo de notación con «Include cancelled» y recorre todas las páginas (100 resultados cada una). Buscar un solo dígito (`0`…`9`) anuncia miles de resultados pero muestra una fila, así que el script divide esos prefijos (`00`…`09`, `0.`, `0-`…) y anota si las cuentas cuadran. Guarda `udc_cancelled_part_01.jsonl.gz` … `21` (una parte por prefijo; si se interrumpe, continúa en la pendiente). Mover las partes a `udc_tree_download/cancelled/`. Si el informe señala prefijos con cuentas que no cuadran, se repiten solo esos: ponerlos en `FIX` dentro del script; salen como partes 22, 23… y `udc_cancelled.py` se queda con la última versión de cada prefijo. Las páginas a las que les falten filas se guardan (`diag`) y aparecen en el informe para diagnosticarlas. En la descarga de noviembre de 2026 quedaron algunas: el sitio anuncia más resultados de los que muestra (en la tabla `.00x` el recuento es el doble de las filas; en `37`, `58`, `62` y `(` falta alguna fila que tampoco está en el HTML). No es una pérdida de la descarga.
2. **Interpretación**: `python udc_cancelled.py` → `udc_cancelled.json` y `udc_cancelled_report.txt`. El informe lista formatos no reconocidos, prefijos cuyas cuentas no cuadran, reemplazos que no son clases del árbol actual (p. ej. combinaciones como `94(4/9)`) y notaciones canceladas que hoy vuelven a existir (`94`, cancelada en 1994). De paso compara las notaciones **vigentes** que devolvió la búsqueda con `UDC_hierarchy.txt`.
3. **Fusión**: `udc_merge.py` como siempre (`--cancelled`).

En el RDF van **fuera de la jerarquía**, como `udcx:CancelledClass` (no `skos:Concept`), para que la app, el servidor y el PoC no las lean como clases; una misma notación puede estar cancelada y volver a usarse. Se probó que el árbol exportado, `udc_import.py` y el PoC dan lo mismo con y sin ellas.

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

`udcx:replacedByNotation` guarda todos los reemplazos en orden (también los que no son clases del árbol); `dct:isReplacedBy` enlaza solo los que sí lo son. Opcionales: `udc:includingNote` y `udcx:replacementNote` (p. ej. «No replacement»).

## Qué contiene el RDF (lo que debe leer la app)

| Dato | Propiedad | Notas |
|---|---|---|
| Identificador | `rdf:about` = `urn:udc:` + notación codificada (`urn:udc:62-1%2F-9`) | Se calcula de la notación; no hay que gestionarlo. Encabezados: `urn:udc:heading-1`…`-4`. |
| Notación | `skos:notation` | Ausente en los encabezados. |
| Etiqueta | `skos:prefLabel@xx` | Si falta el idioma elegido, usar `en`. |
| Padre / hijos | `skos:broader` / `skos:narrower` | Raíces: `skos:topConceptOf`. |
| Orden entre hermanos | `udcx:order` (`urn:udc:ext#order`) | Entero desde 0, orden del `.txt`. |
| Tipo de nodo | `udcx:nodeType` | `heading` (grupo sin notación) o `info` (informativo, no asignable). Sin valor = clase normal. |
| Tipo de auxiliar | `udcx:auxType` | `common` o `special`, según la marca de UDC Online. Sin valor = tabla principal (y los 8 nodos sin ficha: encabezados y notaciones con comas). Árbol actual: 39 418 principales, 15 458 comunes, 16 968 especiales. |
| Scope note | `skos:scopeNote@xx` | |
| Application note | `udc:applicationNote@xx` (`http://udcdata.info/udc-schema#`) | Incluye las antiguas `skos:note` del Summary. |
| Information note | `udc:informationNote@xx` | Información de contexto (p. ej. otros nombres de una lengua). |
| Including | `udc:includingNote@xx` | Conceptos incluidos en la clase («Including …»). |
| Ejemplos | `skos:example@xx` | Formato `notación␣␣␣␣texto`. Son los recuadros `◇` (ejemplos de combinación). |
| Véase también | `skos:related` | |
| Etiquetas anteriores | `skos:hiddenLabel@xx` | Solo para búsqueda. |
| Clases canceladas | `udcx:CancelledClass` (aparte de los conceptos) | Ver «Clases canceladas». Las usan el servidor (`udc_cancelled`), la app («More info», filtro del árbol, aviso al guardar) y el PoC (validador y evaluación). |

### Ventana de información de la app (implementada)
Misma ventana para los nodos `info` (p. ej. `-1/-9,.01/.09, \`0/\`9` INFORMATION ON SPECIAL AUXILIARY TABLES) y para cualquier clase con notas o ejemplos:

- **Servidor** (`udc_import.py`): lee este RDF respetando `udcx:order`, `nodeType` y los encabezados; guarda en `udc_nodes` las columnas `node_type` y `notes` (JSON: `scope`, `app`, `including` y `examples` = `[{code, label}]` por idioma; `related` = `[code]`). `GET /api/udc/tree` solo añade `type` y `has_info`; `GET /api/udc/node?code=…` devuelve las notas de una clase. Detalles en `biblioteca_udc/README.md`.
- **App** (`udc_tree_view.dart`, `udc_info_dialog.dart`): icono ⓘ en los nodos con `has_info`; los nodos `info` y los encabezados no se pueden elegir como clase (los `info` abren directamente la ventana). Secciones: Scope note, Application note, Information note, Including, Examples of combination (`◇ notación  texto`) y See also (abre la ficha de esa clase en la misma ventana). Si falta el idioma elegido, se usa `en`.
- **IA** (`udc_poc`): lee `includingNote`, `informationNote` y `skos:example` (ver README del PoC).

## Verificación tras cada cambio
1. Leer el resumen de `conversion_report.txt`; con el mismo `.txt` otra vez debe decir 0 creados, 0 modificados.
2. Ida y vuelta de la estructura:
   ```
   python udc_export_txt.py --rdf udcs-skos.rdf --out check.txt
   ```
   `check.txt` debe ser idéntico byte a byte a `UDC_hierarchy.txt` (`fc /b check.txt UDC_hierarchy.txt` en Windows).
3. Opcional, con rdflib (en `udc_poc/.venv`): el archivo carga en ~20 s (~500 000 triples).

## Avisos
- Con ~72 000 nodos, calcular embeddings en el PoC (`python -m udcpoc index`) con bge-m3 en CPU lleva horas.
- Tras regenerar `udcs-skos.rdf`, hay que volver a importarlo en el servidor (`udc_import.py`, ver `biblioteca_udc/README.md`) para que la app vea los cambios.
