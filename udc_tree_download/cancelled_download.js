/*
 * Descarga las clases CANCELADAS de UDC Online (notación, año, E&C, etiqueta y reemplazos).
 *
 * Uso: con la sesión iniciada, en la página de búsqueda (search.php), pegar este archivo en la consola (F12)
 * y pulsar "Empezar". Tarda ~20-30 min (~1 000 búsquedas, despacio).
 *
 * Cómo funciona:
 * - Busca por prefijo de notación con "Include cancelled" y recorre todas sus páginas (100 resultados cada una).
 * - Si una página trae menos filas de las anunciadas (pasa con un solo dígito: "0" anuncia 1994 resultados
 *   y muestra una fila), divide el prefijo ("0" -> "00".."09", "0.", "0-", ...) y anota si las cuentas cuadran.
 * - Guarda una parte por prefijo de primer nivel: udc_cancelled_part_01.jsonl.gz, ... Líneas:
 *     {"q": prefijo, "p": página, "n": notación, "h": html de la celda}   (cancelada)
 *     {"q": prefijo, "live": [notaciones vigentes de esa página]}           (para comparar con el árbol)
 *     {"check": {...}}                                                       (cuentas por prefijo)
 * - Si la sesión caduca o se cierra la pestaña, al volver a pegarlo continúa en el prefijo pendiente.
 *   Para empezar de cero: localStorage.removeItem("udcCanNext")
 * Repetición (FIX): con FIX no vacío solo baja esos prefijos, como partes 22, 23... (udc_cancelled.py se queda con
 * la última versión de cada prefijo). Las páginas que vengan incompletas se guardan como {"diag": ...}.
 *   Para repetirla desde cero: localStorage.removeItem("udcCanFixNext")
 * Después: python udc_to_rdf_conversion/udc_cancelled.py
 * Nota: las búsquedas quedan en el historial de búsquedas de tu sesión.
 */
(async () => {
    const DELAY_MS = 250;
    const RETRIES = 3;
    const PAGE = 100;
    const TOP = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                 "=", "(", "\"", "-", ".", "'", "`", "+", "*", ":", "["];
    // caracteres que pueden seguir a un prefijo al dividirlo
    const NEXT = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "-", "`", "'", "(", "\"", "=", ":", "/", "+", "*", "["];
    const MAX_DEPTH = 6;
    // Prefijos a repetir (vacío = descarga completa). Los de la primera descarga con cuentas que no cuadraron.
    const FIX = ["330.", "389", ".", "37", "58", "62", "("];
    const LIST = FIX.length ? FIX : TOP;
    const OFFSET = FIX.length ? 21 : 0;                        // número de la primera parte - 1
    const KEY = FIX.length ? "udcCanFixNext" : "udcCanNext";   // avance guardado en localStorage

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // ------------------------------------------------------------ panel
    const panel = document.createElement("div");
    panel.style.cssText = "position:fixed;top:10px;right:10px;z-index:99999;background:#fff;border:2px solid #333;" +
        "padding:10px;font:13px sans-serif;max-width:380px;box-shadow:0 2px 8px #0005";
    panel.innerHTML = '<b>Descarga de clases canceladas</b><br><button id="udcCdRun">Empezar</button>' +
        '<div id="udcCdStatus" style="margin-top:6px;white-space:pre-wrap"></div>';
    document.body.appendChild(panel);
    setInterval(() => { if (!document.body.contains(panel)) document.body.appendChild(panel); }, 1000);
    const status = msg => { panel.querySelector("#udcCdStatus").textContent = msg; console.log("[canceladas]", msg); };

    // ------------------------------------------------------------ búsqueda
    class SessionExpired extends Error {}
    const form = document.getElementById("searchform");
    const action = form?.getAttribute("action") || "search.php";

    function body(notation, page) {
        const fd = new URLSearchParams();
        if (form) for (const e of form.elements) {
            if (!e.name || e.type === "submit" || e.type === "button") continue;
            if (e.type === "checkbox") { if (e.checked) fd.set(e.name, e.value); }
            else fd.set(e.name, "");
        }
        fd.delete("exactnotation");
        fd.delete("include_examples");
        fd.set("includecancelled", "includecancelled");
        fd.set("notation", notation);
        fd.set("term", "");
        fd.set("pageid", String(page));
        fd.set("cb", "Y");
        fd.set("search", "");
        return fd;
    }

    function parse(text) {
        const doc = new DOMParser().parseFromString(text, "text/html");
        const m = text.match(/(\d+) matching records found/);
        const total = m ? +m[1] : (/No results/i.test(text) ? 0 : null);
        const cancelled = [], live = [];
        for (const tr of doc.querySelectorAll("table.table-condensed > tbody > tr, table.table-condensed > tr")) {
            const ntd = tr.querySelector("td.table-notation");
            if (!ntd) continue;
            const n = ntd.textContent.trim();
            if (ntd.classList.contains("cancelled_text")) {
                const note = tr.querySelector("td.notefield");
                cancelled.push({ n, h: note ? note.innerHTML.replace(/\s+/g, " ").trim() : "" });
            } else {
                live.push(n);
            }
        }
        const table = doc.querySelector("table.table-condensed");
        return { total, cancelled, live, rows: cancelled.length + live.length, table: table ? table.outerHTML : "" };
    }

    async function search(notation, page) {
        let lastErr;
        for (let i = 0; i < RETRIES; i++) {
            try {
                const r = await fetch(action, { method: "POST", credentials: "same-origin", cache: "no-store",
                    headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body(notation, page) });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const text = await r.text();
                if (text.trim() === "XP" || /name="password"/i.test(text)) throw new SessionExpired("sesión caducada");
                const res = parse(text);
                if (res.total === null) throw new Error("respuesta sin recuento");
                await sleep(DELAY_MS);
                return res;
            } catch (e) {
                if (e instanceof SessionExpired) throw e;
                lastErr = e;
                await sleep(1000 * (i + 1));
            }
        }
        throw lastErr;
    }

    let requests = 0;
    // Recorre un prefijo; devuelve el total que anuncia el sitio. Divide si las páginas vienen incompletas.
    async function crawl(prefix, depth, lines, checks, parentTotal = -1) {
        const first = await search(prefix, 0); requests++;
        const pages = Math.ceil(first.total / PAGE);
        const expect = p => Math.min(PAGE, first.total - p * PAGE);
        // Dividir solo si la página viene casi vacía (pasa con un solo dígito: anuncia miles y muestra 1 fila).
        // Si falta alguna fila suelta, se sigue y se guarda la página para diagnosticarla.
        if (first.total > 0 && first.rows < expect(0) / 2) {
            if (depth >= MAX_DEPTH) {
                checks.push({ prefix, total: first.total, rows: first.rows, problem: "incompleto y sin poder dividir" });
                emit(prefix, 0, first, lines);
                return first.total;
            }
            let sum = 0;
            for (const c of NEXT) sum += await crawl(prefix + c, depth + 1, lines, checks, first.total);
            // la notación exacta del prefijo (p. ej. la clase "0") no la cubre ningún hijo: diferencia esperada pequeña
            checks.push({ prefix, total: first.total, sumChildren: sum, split: true });
            emit(prefix, 0, first, lines);   // las filas que sí mostró (suele ser la notación exacta)
            return first.total;
        }
        emit(prefix, 0, first, lines);
        if (first.rows < expect(0)) diag(prefix, 0, expect(0), first, lines);
        let got = first.rows;
        for (let p = 1; p < pages; p++) {
            status(`${prefix}: página ${p + 1}/${pages}  (${requests} búsquedas)`);
            let r = await search(prefix, p); requests++;
            if (r.rows < expect(p)) { r = await search(prefix, p); requests++; }   // un reintento
            emit(prefix, p, r, lines);
            if (r.rows < expect(p)) diag(prefix, p, expect(p), r, lines);
            got += r.rows;
        }
        checks.push({ prefix, total: first.total, rows: got, pages });
        return first.total;
    }

    function diag(prefix, page, expected, res, lines) {
        lines.push(JSON.stringify({ diag: { prefix, page, expected, rows: res.rows, html: res.table } }));
    }

    function emit(prefix, page, res, lines) {
        for (const c of res.cancelled) lines.push(JSON.stringify({ q: prefix, p: page, n: c.n, h: c.h }));
        if (res.live.length) lines.push(JSON.stringify({ q: prefix, live: res.live }));
    }

    async function saveGz(lines, name) {
        const blob = await new Response(new Blob([lines.join("\n") + "\n"]).stream()
            .pipeThrough(new CompressionStream("gzip"))).blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name;
        document.body.appendChild(a); a.click(); a.remove();
    }

    panel.querySelector("#udcCdRun").onclick = async () => {
        if (!form) { status("No veo el formulario de búsqueda: abre search.php y vuelve a pegar el script."); return; }
        const t0 = Date.now();
        let next = parseInt(localStorage.getItem(KEY) || "0", 10);
        for (let i = next; i < LIST.length; i++) {
            const lines = [], checks = [];
            try {
                status(`Prefijo ${LIST[i]} (${i + 1}/${LIST.length})…`);
                await crawl(LIST[i], LIST[i].length, lines, checks);
            } catch (e) {
                status((e instanceof SessionExpired ? "La sesión caducó" : `Error: ${e.message}`) +
                       ` en el prefijo ${LIST[i]}. Inicia sesión, abre search.php y vuelve a pegar el script: ` +
                       `continuará en ese prefijo.`);
                return;
            }
            for (const c of checks) lines.push(JSON.stringify({ check: c }));
            const name = `udc_cancelled_part_${String(OFFSET + i + 1).padStart(2, "0")}.jsonl.gz`;
            await saveGz(lines, name);
            localStorage.setItem(KEY, String(i + 1));
        }
        status(`TERMINADO: ${LIST.length} partes, ${requests} búsquedas en ${((Date.now() - t0) / 60000).toFixed(1)} min.\n` +
               `Mueve udc_cancelled_part_*.jsonl.gz a udc_tree_download/cancelled/.\n` +
               `Para repetir desde cero: localStorage.removeItem("${KEY}")`);
    };
    status(`Listo (${FIX.length ? "repetición: " + FIX.join("  ") : LIST.length + " prefijos"}; empieza en el ` +
           `${parseInt(localStorage.getItem(KEY) || "0", 10) + 1}). Pulsa 'Empezar'.`);
})();
