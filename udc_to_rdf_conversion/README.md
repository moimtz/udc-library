# Conversión del árbol UDC a SKOS (`udcs-skos.rdf`)

Herramientas para generar y actualizar `udcs-skos.rdf` a partir de árboles UDC en texto. Solo usan la biblioteca estándar de Python (no hace falta instalar nada).

| Archivo | Qué es |
|---|---|
| `udc_merge.py` | Fusiona un `.txt` en el RDF (estructura o etiquetas de un idioma). |
| `udc_export_txt.py` | Hace lo contrario: exporta el RDF a `.txt`, para verificar o revisar traducciones. |
| `extra_notes.json` | Notas añadidas a mano (Scope note, Application note, ejemplos, tipo de nodo). |
| `udc_records.json` | Fichas de UDC Online ya interpretadas (notas, Including, ejemplos de combinación, véase también). Mismo formato que `extra_notes.json`; se genera, no se edita a mano. |
| `../udc_tree_download/record_download.js` | Script de consola que descarga esas fichas (ver «Fichas de UDC Online»). |
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

Cada campo reemplaza los valores de ese idioma. Un texto vacío se ignora y queda señalado en el informe. Campos admitidos: `nodeType`, `prefLabel`, `scopeNote`, `applicationNote`, `includingNote`, `example` y `related` (lista de notaciones; reemplaza la lista del nodo).

## Fichas de UDC Online (`udc_records.json`)

Cada clase tiene en UDC Online una ficha con información que el árbol no trae: notas, «Including», referencias y los recuadros `◇` de **ejemplos de combinación** (p. ej. en `330.322`: `330.322.014.3 Net investment`). No son nodos del árbol; se guardan como notas del nodo que las muestra.

Flujo (en tres pasos separados: si hay que corregir la interpretación, no se vuelve a descargar):

1. **Descarga** (navegador, ~1-2 h): con la sesión de UDC Online abierta, pegar `udc_tree_download/record_download.js` en la consola y elegir `UDC_hierarchy.txt`. Primero guarda `udc_record_sample_330.322.html` y comprueba que contiene «Net investment». Luego guarda `udc_records_part_0001.jsonl.gz`, … (HTML casi crudo, comprimido). Si se interrumpe, al volver a pegarlo continúa en la parte pendiente.
2. **Interpretación** (Python): `udc_records.py` lee las partes y genera `udc_records.json` con el mismo formato que `extra_notes.json`.
3. **Fusión**: `udc_merge.py` como siempre; lo aplica antes que `extra_notes.json`.

Orden de precedencia por nodo y campo: Summary original < `udc_records.json` < `extra_notes.json` (lo manual siempre gana). Un campo presente y no vacío reemplaza al anterior; uno vacío no borra nada. Si se corrige `udc_records.py` y hay que **quitar** datos ya fusionados, regenerar desde cero con el comando de «Primera conversión» (lee el Summary original y vuelve a aplicar todo).

## Qué contiene el RDF (lo que debe leer la app)

| Dato | Propiedad | Notas |
|---|---|---|
| Identificador | `rdf:about` = `urn:udc:` + notación codificada (`urn:udc:62-1%2F-9`) | Se calcula de la notación; no hay que gestionarlo. Encabezados: `urn:udc:heading-1`…`-4`. |
| Notación | `skos:notation` | Ausente en los encabezados. |
| Etiqueta | `skos:prefLabel@xx` | Si falta el idioma elegido, usar `en`. |
| Padre / hijos | `skos:broader` / `skos:narrower` | Raíces: `skos:topConceptOf`. |
| Orden entre hermanos | `udcx:order` (`urn:udc:ext#order`) | Entero desde 0, orden del `.txt`. |
| Tipo de nodo | `udcx:nodeType` | `heading` (grupo sin notación) o `info` (informativo, no asignable). Sin valor = clase normal. |
| Scope note | `skos:scopeNote@xx` | |
| Application note | `udc:applicationNote@xx` (`http://udcdata.info/udc-schema#`) | Incluye las antiguas `skos:note` del Summary. |
| Including | `udc:includingNote@xx` | Conceptos incluidos en la clase («Including …»). |
| Ejemplos | `skos:example@xx` | Formato `notación␣␣␣␣texto`. Son los recuadros `◇` (ejemplos de combinación). |
| Véase también | `skos:related` | |
| Etiquetas anteriores | `skos:hiddenLabel@xx` | Solo para búsqueda. |

### Ventana de información de la app (implementada)
Misma ventana para los nodos `info` (p. ej. `-1/-9,.01/.09, \`0/\`9` INFORMATION ON SPECIAL AUXILIARY TABLES) y para cualquier clase con notas o ejemplos:

- **Servidor** (`udc_import.py`): lee este RDF respetando `udcx:order`, `nodeType` y los encabezados; guarda en `udc_nodes` las columnas `node_type` y `notes` (JSON: `scope`, `app`, `including` y `examples` = `[{code, label}]` por idioma; `related` = `[code]`). `GET /api/udc/tree` solo añade `type` y `has_info`; `GET /api/udc/node?code=…` devuelve las notas de una clase. Detalles en `biblioteca_udc/README.md`.
- **App** (`udc_tree_view.dart`, `udc_info_dialog.dart`): icono ⓘ en los nodos con `has_info`; los nodos `info` y los encabezados no se pueden elegir como clase (los `info` abren directamente la ventana). Secciones: Scope note, Application note, Including, Examples of combination (`◇ notación  texto`) y See also (abre la ficha de esa clase en la misma ventana). Si falta el idioma elegido, se usa `en`.
- **IA** (`udc_poc`): ya lee `includingNote` y `skos:example` (ver README del PoC).

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
