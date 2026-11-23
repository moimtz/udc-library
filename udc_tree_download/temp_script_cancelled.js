/*
 * Segundo sondeo de UDC Online: SOLO clases canceladas (~3 min, ~110 búsquedas, despacio).
 *
 * Uso: con la sesión iniciada en UDC Online, en la página de búsqueda (search.php), pegar este archivo
 * en la consola (F12) y pulsar el botón del panel. Al terminar (o si la sesión caduca) descarga
 * udc_probe_cancelled.json.gz. Desde la consola: udcCancel.save() guarda lo que lleve.
 *
 * Qué averigua:
 *   A. si la casilla "Include cancelled" cambia los resultados (568 con y sin ella);
 *   B. si la paginación funciona (=43, páginas 1 y 2);
 *   C. cuántos resultados y cuántas canceladas hay por prefijo (0-9, auxiliares...), con y sin la
 *      casilla, para estimar el total de canceladas y cuánto tardaría bajarlas todas;
 *   D. todas las páginas de algunos prefijos con canceladas conocidas, para ver todas las variantes del
 *      formato (sin reemplazo, varios reemplazos, notas...).
 * Nota: las búsquedas quedan en el historial de búsquedas de tu sesión, como si las hicieras a mano.
 */
(async () => {
    const DELAY_MS = 300;
    const PREFIXES = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                      "=", "(", "\"", "-", "'", "`", ".", "+", "*", ":", "["];
    const FULL = ["568", "=43", "54-1", "681.3", "4", "(0"];   // D: todas sus páginas (máx. MAX_PAGES)
    const MAX_PAGES = 10;

    const out = { meta: { started: new Date().toISOString(), url: location.href }, tests: {}, prefixes: [],
                  full: [], cancelledRows: [], errors: [] };
    const sleep = ms => new Promise(r => setTimeout(r, ms));

    // ------------------------------------------------------------ panel
    const panel = document.createElement("div");
    panel.style.cssText = "position:fixed;top:10px;right:10px;z-index:99999;background:#fff;border:2px solid #333;" +
        "padding:10px;font:13px sans-serif;max-width:380px;box-shadow:0 2px 8px #0005";
    panel.innerHTML = '<b>Sondeo de canceladas</b><br><button id="udcCnRun">Empezar</button> ' +
        '<button id="udcCnSave">Guardar ahora</button><div id="udcCnStatus" style="margin-top:6px;white-space:pre-wrap"></div>';
    document.body.appendChild(panel);
    setInterval(() => { if (!document.body.contains(panel)) document.body.appendChild(panel); }, 1000);
    const status = msg => { panel.querySelector("#udcCnStatus").textContent = msg; console.log("[canceladas]", msg); };

    // ------------------------------------------------------------ búsqueda
    class SessionExpired extends Error {}
    const form = document.getElementById("searchform");
    const action = form?.getAttribute("action") || "search.php";

    function body(notation, cancelled, page) {
        const fd = new URLSearchParams();
        if (form) for (const e of form.elements) {   // casillas de campos como en tu formulario
            if (!e.name || e.type === "submit" || e.type === "button") continue;
            if (e.type === "checkbox") { if (e.checked) fd.set(e.name, e.value); }
            else fd.set(e.name, "");
        }
        fd.delete("includecancelled");
        fd.delete("exactnotation");
        fd.delete("include_examples");
        if (cancelled) fd.set("includecancelled", "includecancelled");
        fd.set("notation", notation);
        fd.set("term", "");
        fd.set("pageid", String(page));   // 0 = primera página (como searchRecord())
        fd.set("cb", "Y");
        fd.set("search", "");
        return fd;
    }

    // Una fila de resultado -> objeto. Canceladas: td.cancelled_text; reemplazos tras "→".
    function parseRows(doc) {
        const rows = [];
        for (const tr of doc.querySelectorAll("table.table-condensed > tbody > tr, table.table-condensed > tr")) {
            const ntd = tr.querySelector("td.table-notation");
            if (!ntd) continue;
            const cancelled = ntd.classList.contains("cancelled_text");
            const note = tr.querySelector("td.notefield");
            const r = { n: ntd.textContent.trim(), cancelled };
            if (cancelled && note) {
                r.text = note.textContent.replace(/\s+/g, " ").trim();
                r.html = note.innerHTML.replace(/\s+/g, " ").trim();
                r.to = [...note.querySelectorAll("a")].map(a => a.textContent.trim());
            }
            rows.push(r);
        }
        return rows;
    }

    async function search(notation, cancelled, page) {
        const r = await fetch(action, { method: "POST", credentials: "same-origin", cache: "no-store",
            headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body(notation, cancelled, page) });
        const text = await r.text();
        if (text.trim() === "XP" || /name="password"/i.test(text)) throw new SessionExpired("sesión caducada");
        const doc = new DOMParser().parseFromString(text, "text/html");
        const total = (text.match(/(\d+) matching records found/) || [])[1];
        const pages = doc.querySelectorAll("#page_number option").length;   // incluye una opción vacía
        const rows = parseRows(doc);
        const res = { notation, cancelled, page, status: r.status, total: total ? +total : (/No results/i.test(text) ? 0 : null),
                      pageOptions: pages, rows: rows.length, cancelledRows: rows.filter(x => x.cancelled).length,
                      first: rows[0]?.n, last: rows[rows.length - 1]?.n };
        for (const x of rows) if (x.cancelled) out.cancelledRows.push({ q: notation, page, ...x });
        await sleep(DELAY_MS);
        return res;
    }

    const save = async () => {
        out.meta.finished = new Date().toISOString();
        // canceladas únicas
        const seen = new Set();
        out.cancelledRows = out.cancelledRows.filter(x => !seen.has(x.n) && seen.add(x.n));
        const blob = await new Response(new Blob([JSON.stringify(out)]).stream()
            .pipeThrough(new CompressionStream("gzip"))).blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "udc_probe_cancelled.json.gz";
        document.body.appendChild(a); a.click(); a.remove();
        status(`Guardado udc_probe_cancelled.json.gz (${(blob.size / 1024).toFixed(0)} KB, ` +
               `${out.cancelledRows.length} canceladas distintas).`);
    };
    panel.querySelector("#udcCnSave").onclick = save;
    window.udcCancel = { save, out };

    panel.querySelector("#udcCnRun").onclick = async () => {
        const t0 = Date.now();
        try {
            status("A. ¿La casilla cambia el resultado?");
            out.tests.toggle = [await search("568", false, 0), await search("568", true, 0)];
            status("B. Paginación…");
            out.tests.paging = [await search("=43", true, 0), await search("=43", true, 1)];
            let i = 0;
            for (const p of PREFIXES) {
                status(`C. Prefijos: ${++i}/${PREFIXES.length} (${p})`);
                out.prefixes.push({ prefix: p, with: await search(p, true, 0), without: await search(p, false, 0) });
            }
            i = 0;
            for (const p of FULL) {
                const first = await search(p, true, 0);
                const n = Math.min(MAX_PAGES, Math.max(1, Math.ceil((first.total || 0) / 100)));
                const pages = [first];
                for (let pg = 1; pg < n; pg++) {
                    status(`D. ${p}: página ${pg + 1}/${n}`);
                    pages.push(await search(p, true, pg));
                }
                out.full.push({ prefix: p, pages });
                status(`D. ${++i}/${FULL.length} prefijos completos`);
            }
            await save();
            status(`Terminado en ${((Date.now() - t0) / 60000).toFixed(1)} min y guardado ` +
                   `(${out.cancelledRows.length} canceladas distintas). Ya puedes recargar la página.`);
        } catch (e) {
            out.errors.push(String(e));
            await save();
            status((e instanceof SessionExpired ? "La sesión caducó." : `Error: ${e.message}.`) + " Se guardó lo obtenido.");
        }
    };
    status(form ? "Listo. Pulsa 'Empezar'." : "Aviso: no veo el formulario de búsqueda; abre search.php y vuelve a pegarlo.");
})();
