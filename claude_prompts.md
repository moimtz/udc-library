Necesito que me des tu opinión respecto al siguiente proyecto, especificando los aspectos generales y pormenores. Aún no he definido lenguajes, frameworks y posiblemente algunos detalles. Una vez definido cada detalle, ahora sí podrás generar los archivos y códigos del proyecto, pero yo te daré autorización.

La laptop que tengo es una Dell Intel(R) 11th Gen Core(TM) i5-1135G7 @ 2.40GHz, 16 GB de RAM, NVIDIA GeForce MX330 (2 GB) Intel(R) Iris(R) Xe Graphics (128 MB), 1.84 GB de almacenamiento, Windows 11 Home Single Language.

El teléfono que tengo es Xiaomi 12, SO: Xiaomi HyperOS, version de Android 15.

La tablet está por definir, aún no la tengo, pero será para Android.

Se trata de una biblioteca que organiza los archivos .pdf (recursos literarios, i.e. libros, tesis, artículos, patentes, y t recurso bibliográfico) con clasificación UDC (versión libre, no de licencia) para Windows y Android (tablet y teléfono). La aplicación tiene la capacidad de buscar los libros mediante un \_tree directory menu\_ y mediante una barra de búsqueda; de desplegar la información bibliográfica del archivo; y abrir el documento en el visor PDF predeterminado del sistema. También tendrá la capacidad de integrar nuevos recursos literarios manualmente y se implementará una IA para clasificarlos automáticamente (trabajo a futuro).

Lista de funcionalidades especificas:

1. Consulta: 

   1. Mediante el \_tree directory menu\_ (tomar en cuenta que la navegabilidad de la UI en el árbol está inspirado en el UDC Summary): al hacer clic en cada subdirectorio en el contenedor central se despliegan las todos los libros que corresponden a esa clasificación. 
   2. Mediante una barra de búsqueda: busca por cualquier campo de la información bibliográfica. Permite búsqueda por regex, sensible a caps, por palabra completa y otras herramientas comunes en cuadros de búsqueda. También un dropdown que permite acotar la búsqueda por campo. La búsqueda arroja en el contenedor central todos los libros que coincidan con la búsqueda.
   3. Los resultados de la búsqueda se arrojan como una lista de títulos con poca información adicional en la fila (autor(es), año, tipo de recurso-libro, artículo, tesis...-, peso del archivo) en el contenedor central, al hacer clic en uno, se despliega ahí mismo un contenedor hacia abajo con información bibliográfica detallada y completa a la izquierda (más o menos como lo que tiene Zotero, si viene de la búsqueda por la barra de búsqueda, se resaltan las coincidencias con otro color) y la carátula del recurso literario. Se incluye un botón de "Abrir", "Editar Campos" y otro de "Eliminar" (con su warning correspondiente de cesto de basura).
2. Incorporación

   1. En Menú lateral (con otras funciones por definir) botón de "Añadir Archivo", se abre el Explorador de Archivos y selecciona uno o varios .pdf y por cada uno, se abre una ventana flotante donde se ve la carátula (permite elegir la página del .pdf como carátula) con campos de la información bibliográfica para rellenar (el nombre del archivo se cambia automáticamente con el formato de Zotero: primerautorTituloDelTrabajoXXX con XXX=año, si conoces las reglas que utiliza Zotero para asignar el citation key automáticamente mejor). Al final, un botón de "Añadir" y otro de "Rellenar Automáticamente" (que se habilitará hasta que se implemente la IA o algún otro algoritmo que propongas). Se confirma de añadido o un mensaje de error correspondiente (con una barra de color en la misma ventana, en la parte superior, se espera por unos segundos y se cierra, de ser exitoso). Se abren tantas ventanas flotantes una tras otra según la cantidad de .pdf's elegidos.

Lista de pantallas/pestañas:

1. Una ventana principal con dos contenedores: a la izquierda el \_tree directory menu\_, con una barra de búsqueda y sus herramientas en la parte superior izquierda y botones de "Collapse All" y "Expand All" en la superior derecha; y a la derecha la lista desplegable de resultados. En la aplicación para tablet/teléfono, en horizontal tendría la misma configuración, pero en vertical, los contenedores estarán arriba y abajo.
2. Un menú lateral con la funcionalidad de "Añadir Archivo" y un símbolo de +. El workflow y ventanas ya se definieron previemante.

El manejo de datos es local. Tentativamente los .pdf se almacenarían junto con los archivos de la aplicación. Cada uno tendría un JSON asociado con su información bibliográfica correspondiente. Es tentativo, por lo que si crees que esta idea no es eficiente, el paradigma puede cambiar.

TODO: Manejo de duplicados. Posibilidad de incorporar un rellenado de campos automático por identificador como Zotero (por DOI, ISBN, arXiv, etc): que la IA identifique el ISBN dentro del documento y haga la búsqueda (sopesemos primero los alcances de la IA, porque la veo más como una herramienta universal).

***

Sugerencias aprobadas:

1. Todo lo del punto 4

   1. Para el filtro de búsqueda UDC que aparezca una ventana con el árbol UDC completo para seleccionar el filtro.
   2. ¿Me explicas de nuevo la parte de "Ordenamiento por título, autor, año y fecha de incorporación"? ¿Es parte de los resultados de búsqueda?
2. En el punto 5: Incorporación de archivos, una ventana con tal vez un toast que indique la cola, o simplemente un indicador dentro de la misma ventana.
3. Detección y eliminación de duplicados.
4. Lo del punto 6: autorelleno de info bibliografica con regex y API gratuita e IA para sugerir la clasificación. Para lo de IA parece ser una buena idea lo de los embeddings, un amigo me comentó sobre all-MiniLM-L6-v2, ¿qué opinas?, ¿qué alcances y limitaciones tendría? Esta opción es aún tentativa, pero suena bien.

Ahora vamos a los puntos importantes respecto a la arquitectura de datos que faltaron definir. 

Creo que en lugar de JSON para almacenar la info bibliografica, será mejor almacenarla en la metadata del archivo, ¿no? Ahora, otro punto muy diferente es cómo requieres la jerarquía UDC y dónde la descargo. 

Ahora, hay una PC en la escuela (en la red de la escuela) que tiene tailscale, ya hace server en un puerto para otra app, pero podría correr esta app en el mismo PC en otro puerto y conectarme con un usuario/contraseña únicos sin afectar las otras posibles apps que estén corriendo en la PC, ya tiene una db también que se podría reutilizar (haciendo su propia DB), usando sqlite3 en python por ejemplo. La idea es que los archivos .pdf estén en el servidor y yo pueda manipularlos (editarlo, subirlos, eliminarlos, etc) mediante acceso a internet. 

Ahora, cuando se abra el archivo se haría una descarga local temporal, ¿no? El objetivo es hacerlo también ligero y lo menos redundante posible, pero también quiero conservar los documentos de uso recurrente locales por un tiempo para evitar esperar mucho tiempo en lo que cargan.

***

Ok, la aplicación ha corrido con algunos pormenores que se corregirán más adelante, por ahora me interesa avanzar con la siguiente etapa que es la implementación de la IA (potencialmente _embbedings_) para sugerir una clasificación UDC completa (incluyendo tablas auxiliares, lo importante es explotar el potencial del árbol) y rellenar campos en los casos en los que la consulta de DOI, ISBN y arXiv halla fallado (quizás con las primeras páginas y las últimas).

Mi idea (vaga, abierta a cambios y mejoras) es hacer un experimento _standalone_ como prueba de concepto con algunos PDF's. Luego, una fase de entrenamiento, con unos cientos de PDF's y finalmente, la implementación en la app. Creo que puede ser importante que la IA reciba refuerzo por cada clasificación que confirme yo como usuario para mejorarla a largo plazo (incluso podría implementarse un algoritmo _greedy_, si lo crees propio). Pero algo que sí quiero explotar son las tablas auxiliares, para que la clasificación sea lo más completa y detallada posible, y que se rellenen los campos lo más que se pueda.

Entonces, dame los pormenores que consideres de ejecución, hazme las preguntas necesarias para comenzar con la programación (recuerda que hasta que te autorice).

