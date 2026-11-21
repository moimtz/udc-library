(async () => {

    const MAX_CONCURRENT = 5;
    const DELAY_MS = 50;

    const allNodes = new Map();
    const fetched = new Set();
    const roots = [];
    const errors = [];

    function sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }

    function cleanTitle(title) {
        const div = document.createElement("div");
        div.innerHTML = title || "";
        return div.textContent.trim().replace(/\s+/g, " ");
    }

    function makeNode(node) {
        return {
            key: String(node.key),
            title: cleanTitle(node.title),
            folder: !!node.folder,
            lazy: !!node.lazy,
            children: []
        };
    }

    /*
     * ---------------------------------------------------------
     * 1. OBTENER SOLAMENTE LAS RAÍCES REALES DEL ÁRBOL
     * ---------------------------------------------------------
     */

    const tree = $.ui.fancytree.getTree("#tree");

    if (!tree) {
        throw new Error("No se encontró el árbol #tree.");
    }

    const rootNode = tree.getRootNode();

    if (!rootNode.children || rootNode.children.length === 0) {
        throw new Error("El árbol no contiene nodos raíz.");
    }

    console.log("Obteniendo nodos raíz...");

    for (const child of rootNode.children) {

        const node = makeNode(child);

        roots.push(node);
        allNodes.set(node.key, node);

        /*
         * Puede haber hijos que ya estén cargados en el navegador.
         * Los registramos, pero NO los agregamos a 'roots'.
         */
        function registerLoadedChildren(ftNode, parentNode) {

            if (!ftNode.children) {
                return;
            }

            for (const ftChild of ftNode.children) {

                const childNode = makeNode(ftChild);

                parentNode.children.push(childNode.key);

                allNodes.set(childNode.key, childNode);

                registerLoadedChildren(ftChild, childNode);
            }
        }

        registerLoadedChildren(child, node);
    }

    console.log(`Raíces encontradas: ${roots.length}`);
    console.log(`Nodos inicialmente registrados: ${allNodes.size}`);

    /*
     * ---------------------------------------------------------
     * 2. DESCARGAR LOS HIJOS DE UN NODO LAZY
     * ---------------------------------------------------------
     */

    async function fetchChildren(node) {

        if (fetched.has(node.key)) {
            return;
        }

        fetched.add(node.key);

        const url =
            `getTreeData.php?mode=children&parent=${encodeURIComponent(node.key)}`;

        try {

            const response = await fetch(url, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store"
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const text = await response.text();

            let data;

            try {
                data = JSON.parse(text);
            } catch (e) {
                throw new Error(
                    "La respuesta no es JSON: " + text.substring(0, 300)
                );
            }

            if (!Array.isArray(data)) {
                throw new Error("La respuesta JSON no es un arreglo.");
            }

            /*
             * Guardamos los hijos de ESTE nodo.
             */
            node.children = [];

            for (const rawChild of data) {

                const child = makeNode(rawChild);

                node.children.push(child.key);

                /*
                 * Si ya existe, conservamos el nodo original.
                 * Esto evita crear estructuras duplicadas.
                 */
                if (!allNodes.has(child.key)) {
                    allNodes.set(child.key, child);
                }
            }

        } catch (error) {

            errors.push({
                key: node.key,
                title: node.title,
                error: error.message
            });

            console.error(
                `Error cargando ${node.key} - ${node.title}:`,
                error
            );
        }
    }

    /*
     * ---------------------------------------------------------
     * 3. PROCESAR TODAS LAS RAMAS LAZY
     * ---------------------------------------------------------
     */

    let pending = Array.from(allNodes.values())
        .filter(node => node.lazy && !fetched.has(node.key));

    let iteration = 0;

    while (pending.length > 0) {

        iteration++;

        console.log(
            `\nIteración ${iteration}: ${pending.length} ramas por cargar...`
        );

        const nextPending = [];

        for (let i = 0; i < pending.length; i += MAX_CONCURRENT) {

            const batch = pending.slice(i, i + MAX_CONCURRENT);

            await Promise.all(
                batch.map(async node => {

                    await fetchChildren(node);

                    /*
                     * Después de cargar este nodo, revisamos
                     * cuáles de sus hijos también son lazy.
                     */
                    for (const childKey of node.children) {

                        const child = allNodes.get(childKey);

                        if (
                            child &&
                            child.lazy &&
                            !fetched.has(child.key)
                        ) {
                            nextPending.push(child);
                        }
                    }
                })
            );

            console.log(
                `Progreso: ${allNodes.size} nodos registrados`
            );

            await sleep(DELAY_MS);
        }

        /*
         * También revisamos TODOS los nodos registrados.
         *
         * Esto es importante porque un nodo lazy puede haber
         * aparecido indirectamente en una rama ya descargada.
         */
        const discovered = Array.from(allNodes.values())
            .filter(node =>
                node.lazy &&
                !fetched.has(node.key)
            );

        pending = [
            ...nextPending,
            ...discovered
        ];

        /*
         * Eliminar posibles duplicados de pending.
         */
        const uniquePending = new Map();

        for (const node of pending) {
            uniquePending.set(node.key, node);
        }

        pending = Array.from(uniquePending.values());
    }

    console.log("\n-----------------------------------");
    console.log("Descarga de datos terminada.");
    console.log(`Nodos registrados: ${allNodes.size}`);
    console.log(`Ramas procesadas: ${fetched.size}`);
    console.log(`Errores: ${errors.length}`);
    console.log("-----------------------------------");

    /*
     * ---------------------------------------------------------
     * 4. CONSTRUIR EL TXT DESDE LAS RAÍCES
     * ---------------------------------------------------------
     *
     * ESTA ES LA PARTE IMPORTANTE.
     *
     * Solamente recorremos:
     *
     *     roots
     *        |
     *        +-- hijo
     *        |     |
     *        |     +-- nieto
     *        |
     *        +-- hijo
     *
     * No recorremos allNodes como si cada nodo fuera una raíz.
     */

    const lines = [];
    const printed = new Set();

    function writeNode(nodeKey, depth) {

        const node = allNodes.get(String(nodeKey));

        if (!node) {
            console.warn(
                `No se encontró el nodo ${nodeKey}`
            );
            return;
        }

        /*
         * Evita que el mismo nodo se escriba dos veces.
         */
        if (printed.has(node.key)) {
            return;
        }

        printed.add(node.key);

        const indentation = "    ".repeat(depth);

        lines.push(
            indentation + node.title
        );

        /*
         * Recorrer exclusivamente los hijos de este nodo.
         */
        for (const childKey of node.children) {
            writeNode(childKey, depth + 1);
        }
    }

    console.log("\nConstruyendo jerarquía final...");

    /*
     * SOLAMENTE las raíces originales.
     */
    for (const root of roots) {
        writeNode(root.key, 0);
    }

    /*
     * ---------------------------------------------------------
     * 5. COMPROBACIÓN
     * ---------------------------------------------------------
     */

    console.log("\n-----------------------------------");
    console.log("Construcción terminada.");
    console.log(`Nodos únicos escritos: ${printed.size}`);
    console.log(`Nodos registrados: ${allNodes.size}`);
    console.log("-----------------------------------");

    if (printed.size !== allNodes.size) {

        console.warn(
            `Advertencia: ${allNodes.size - printed.size} nodos registrados ` +
            `no fueron alcanzados desde las raíces.`
        );
    }

    /*
     * ---------------------------------------------------------
     * 6. GENERAR ARCHIVO TXT
     * ---------------------------------------------------------
     */

    const contenido = lines.join("\n");

    const blob = new Blob(
        [contenido],
        { type: "text/plain;charset=utf-8" }
    );

    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");

    a.href = url;
    a.download = "UDC_hierarchy.txt";

    document.body.appendChild(a);
    a.click();

    document.body.removeChild(a);

    URL.revokeObjectURL(url);

    /*
     * ---------------------------------------------------------
     * 7. REPORTE DE ERRORES
     * ---------------------------------------------------------
     */

    if (errors.length > 0) {

        console.warn("\nERRORES DURANTE LA DESCARGA:");

        for (const error of errors) {

            console.warn(
                `${error.key} | ${error.title} | ${error.error}`
            );
        }
    }

    console.log("\n===================================");
    console.log("      EXTRACCIÓN COMPLETADA");
    console.log("===================================");
    console.log(`Raíces originales: ${roots.length}`);
    console.log(`Nodos encontrados: ${allNodes.size}`);
    console.log(`Nodos escritos: ${printed.size}`);
    console.log(`Errores: ${errors.length}`);
    console.log("Archivo: UDC_hierarchy.txt");
    console.log("===================================");

})();