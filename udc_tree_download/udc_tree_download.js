/*
 * udc_tree_download.js — descarga universal de UDC Online en un solo archivo (udc_snapshot_AAAA-MM-DD.json.gz).
 * Luego: python udc_to_rdf_conversion/udc_main_tree_fusion.py <snapshot>  (lo fusiona con udcs-skos.rdf).
 *
 * Uso: con la sesión iniciada, en la página de búsqueda/árbol de UDC Online (search.php), pegar este archivo
 * en la consola (F12) y pulsar "Empezar". Al terminar descarga el snapshot solo.
 * - El avance se guarda en el navegador (IndexedDB): si se recarga la página o caduca la sesión, volver a
 *   iniciar sesión, pegar el script y pulsar "Continuar".
 * - "Exportar ahora" descarga lo que lleve (sirve para revisar); "Borrar datos" empieza de cero.
 *
 * Fases (todo lo que hemos ido extrayendo):
 *   1. Árbol: jerarquía, orden y etiquetas (getTreeData.php, rama por rama; ~10 000 peticiones).
 *   2. Fichas: notas, Including, ejemplos ◇, See also y tipo de auxiliar. La ficha de una clase lista TODAS sus
 *      subdivisiones (100 por página), así que solo se pide la de las clases que aún no estén cubiertas
 *      (~1 000-2 000 peticiones en lugar de 72 000). Los dígitos sueltos ("0", "5") solo devuelven una fila:
 *      se bajan sus hijos.
 *   3. Búsqueda con "Include cancelled": clases canceladas (año, E&C, reemplazos) y lista de notaciones
 *      vigentes, para detectar las que faltan en el árbol (~1 000 peticiones).
 *   4. Huecos: ficha propia de las notaciones vigentes que no aparecieron en ninguna ficha.
 *   5. Exportación del snapshot.
 * El HTML se guarda casi crudo: la interpretación la hace Python, y se puede corregir sin volver a descargar.
 */
(async () => {
    const VERSION = "udc_tree_download.js 1.0";
    const CONC = 4;            // peticiones simultáneas (árbol y páginas de una ficha)
    const DELAY_MS = 80;       // pausa entre tandas
    const RETRIES = 3;
    const PAGE = 100;          // filas por página (fichas y búsqueda)
    const COMMA_NOTATIONS = ["-1/-9,.01/.09, `0/`9", ":, ::, []", "+, /", "*, A/Z"];
    const SEARCH_TOP = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
                        "=", "(", "\"", "-", ".", "'", "`", "+", "*", ":", "["];
    const SEARCH_NEXT = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "-", "`", "'", "(", "\"", "=", ":",
                         "/", "+", "*", "["];
    const SEARCH_MAX_DEPTH = 6;
    const CHECK = { notation: "330.322", text: "330.322.014.3" };   // validación: la ficha trae su ejemplo ◇ (cualquier idioma)

    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const clean = s => (s || "").replace(/[‐‑−]/g, "-").replace(/\s+/g, " ").trim();
    let stopRequested = false;

    // ------------------------------------------------------------------ IndexedDB
    const db = await new Promise((res, rej) => {
        const rq = indexedDB.open("udcTreeDownload", 1);
        rq.onupgradeneeded = () => {
            const d = rq.result;
            d.createObjectStore("kv");
            d.createObjectStore("tree", { keyPath: "k" });
            d.createObjectStore("rec", { autoIncrement: true });
            d.createObjectStore("srch", { keyPath: "top" });
            d.createObjectStore("err", { autoIncrement: true });
        };
        rq.onsuccess = () => res(rq.result);
        rq.onerror = () => rej(rq.error);
    });
    const tx = (store, mode, fn) => new Promise((res, rej) => {
        const t = db.transaction(store, mode);
        const out = fn(t.objectStore(store));
        t.oncomplete = () => res(out && "result" in out ? out.result : out);
        t.onerror = () => rej(t.error);
    });
    const kvGet = k => tx("kv", "readonly", s => s.get(k));
    const kvSet = (k, v) => tx("kv", "readwrite", s => s.put(v, k));
    const getAll = store => tx(store, "readonly", s => s.getAll());
    const putMany = (store, vals) => tx(store, "readwrite", s => { for (const v of vals) s.put(v); });
    const addErr = e => tx("err", "readwrite", s => s.add({ t: new Date().toISOString(), ...e }));
    async function clearAll() {
        for (const s of ["kv", "tree", "rec", "srch", "err"]) await tx(s, "readwrite", st => st.clear());
    }

    // ------------------------------------------------------------------ panel
    const panel = document.createElement("div");
    panel.style.cssText = "position:fixed;top:10px;right:10px;z-index:99999;background:#fff;border:2px solid #333;" +
        "padding:10px;font:13px sans-serif;width:400px;box-shadow:0 2px 8px #0005";
    panel.innerHTML = `<b>UDC Online → snapshot</b> <small>(${VERSION})</small><br>` +
        '<button id="udcUtRun">Empezar / Continuar</button> <button id="udcUtStop">Pausar</button> ' +
        '<button id="udcUtExport">Exportar ahora</button> <button id="udcUtClear">Borrar datos</button>' +
        '<div id="udcUtStatus" style="margin-top:6px;white-space:pre-wrap"></div>';
    document.body.appendChild(panel);
    setInterval(() => { if (!document.body.contains(panel)) document.body.appendChild(panel); }, 1000);
    const status = msg => { panel.querySelector("#udcUtStatus").textContent = msg; console.log("[udc]", msg); };

    // ------------------------------------------------------------------ red
    class SessionExpired extends Error {}
    class Stopped extends Error {}
    async function get(url, init = {}) {
        let last;
        for (let i = 0; i < RETRIES; i++) {
            if (stopRequested) throw new Stopped();
            try {
                const r = await fetch(url, { credentials: "same-origin", cache: "no-store", ...init });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const text = await r.text();
                if (text.trim() === "XP" || /name="password"/i.test(text)) throw new SessionExpired();
                return text;
            } catch (e) {
                if (e instanceof SessionExpired || e instanceof Stopped) throw e;
                last = e;
                await sleep(800 * (i + 1));
            }
        }
        throw last;
    }
    function trimHtml(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        doc.querySelectorAll("#searchbox, script, style, form").forEach(e => e.remove());
        doc.querySelectorAll("[style]").forEach(e => e.removeAttribute("style"));
        return doc.body.innerHTML.replace(/\s+/g, " ").trim();
    }
    // "330.322 Investments..." -> "330.322"; encabezados ("- AUXILIARY TABLES") -> null
    function notationOf(title) {
        if (/^-+(\s|$)/.test(title)) return null;
        for (const nt of COMMA_NOTATIONS) if (title === nt || title.startsWith(nt + " ")) return nt;
        return title.split(" ")[0];
    }

    // ------------------------------------------------------------------ 1. árbol
    function nodeFrom(raw, parent, index) {
        const div = document.createElement("div");
        div.innerHTML = raw.title || "";
        const m = (raw.title || "").match(/fetchAndClearRecord\('([^']*)'\)/);
        return { k: String(raw.key), t: clean(div.textContent), rk: m ? m[1] : null, p: parent, i: index,
                 lazy: !!raw.lazy, done: !raw.lazy };
    }
    async function phaseTree() {
        let nodes = await getAll("tree");
        if (!nodes.length) {
            const ft = window.$ && $.ui && $.ui.fancytree && $.ui.fancytree.getTree("#tree");
            if (!ft) throw new Error("No encuentro el árbol de la página: abre search.php (Search/Browse) y vuelve a pegar el script.");
            const init = [];
            const walk = (ftNode, parentKey) => (ftNode.children || []).forEach((ch, i) => {
                const n = nodeFrom({ title: ch.title, key: ch.key, lazy: ch.isLazy() && !ch.children }, parentKey, i);
                init.push(n);
                walk(ch, n.k);
            });
            walk(ft.getRootNode(), null);
            await putMany("tree", init);
            nodes = init;
        }
        const byKey = new Map(nodes.map(n => [n.k, n]));
        let pending = nodes.filter(n => !n.done);
        const t0 = Date.now();
        let doneCount = 0;
        while (pending.length) {
            const next = [];
            for (let i = 0; i < pending.length; i += CONC) {
                const batch = pending.slice(i, i + CONC);
                await Promise.all(batch.map(async parent => {
                    let data;
                    try {
                        const text = await get(`getTreeData.php?mode=children&parent=${encodeURIComponent(parent.k)}`);
                        data = JSON.parse(text);
                        if (!Array.isArray(data)) throw new Error("respuesta no es una lista");
                    } catch (e) {
                        if (e instanceof SessionExpired || e instanceof Stopped) throw e;
                        await addErr({ phase: "tree", key: parent.k, title: parent.t, error: e.message });
                        data = [];
                    }
                    const kids = [];
                    data.forEach((raw, idx) => {
                        const ch = nodeFrom(raw, parent.k, idx);
                        if (!byKey.has(ch.k)) { byKey.set(ch.k, ch); kids.push(ch); if (!ch.done) next.push(ch); }
                    });
                    parent.done = true;
                    await putMany("tree", [...kids, parent]);
                    doneCount++;
                }));
                const mins = (Date.now() - t0) / 60000;
                status(`1/4 Árbol: ${byKey.size} nodos, ${doneCount} ramas abiertas, ${pending.length - i - batch.length + next.length} pendientes ` +
                       `(${mins.toFixed(1)} min)`);
                await sleep(DELAY_MS);
            }
            pending = next;
        }
        return byKey;
    }

    // orden de lectura: raíces y luego hijos en el orden del sitio (recorrido en profundidad)
    function dfs(byKey) {
        const kids = new Map();
        for (const n of byKey.values()) {
            if (!kids.has(n.p)) kids.set(n.p, []);
            kids.get(n.p).push(n);
        }
        for (const l of kids.values()) l.sort((a, b) => a.i - b.i);
        const out = [], stack = [...(kids.get(null) || [])].reverse(), seen = new Set();
        while (stack.length) {
            const n = stack.pop();
            if (seen.has(n.k)) continue;
            seen.add(n.k);
            out.push(n);
            stack.push(...[...(kids.get(n.k) || [])].reverse());
        }
        return out;
    }

    // ------------------------------------------------------------------ 2. fichas
    // Sin depender del idioma de la interfaz: filas por su enlace de notación y número de páginas por el selector
    // de páginas del sitio (sus opciones llevan "p=1", "p=2"...).
    function rowsOf(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        const ns = [...doc.querySelectorAll("a.notation-main")].map(a => clean(a.textContent));
        let pages = 1;
        for (const o of doc.querySelectorAll("#page_number option")) {
            const m = (o.getAttribute("value") || "").match(/(?:^|&)p=(\d+)/);
            if (m) pages = Math.max(pages, +m[1] + 1);
        }
        return { ns, pages };
    }
    async function fetchRecord(nq, covered, label) {
        // página 1 (como la página: x=1&z=-1&cs=1&ix=-1); las demás, como su selector de páginas.
        // Los dígitos sueltos ("0", "5") muestran una fila y ningún selector: no se paginan y sus hijos,
        // que quedan sin cubrir, se piden aparte.
        const first = await get(`/ajaxbrowse.php?n=${nq}&x=1&z=-1&cs=1&ix=-1`);
        const r0 = rowsOf(first);
        const recs = [{ q: nq, pg: 0, ns: r0.ns, h: trimHtml(first) }];
        if (r0.pages > 1) {
            const pages = r0.pages;
            for (let p = 1; p < pages; p += CONC) {
                const batch = [];
                for (let k = p; k < Math.min(pages, p + CONC); k++) batch.push(k);
                const got = await Promise.all(batch.map(async k => {
                    const h = await get(`/ajaxbrowse.php?n=${nq}&p=${k}&x=1&cs=0&z=-2`);
                    return { q: nq, pg: k, ns: rowsOf(h).ns, h: trimHtml(h) };
                }));
                recs.push(...got);
                status(`2/4 Fichas: ${label} página ${Math.min(pages, p + CONC)}/${pages}`);
                await sleep(DELAY_MS);
            }
        }
        await putMany("rec", recs);
        for (const r of recs) for (const n of r.ns) covered.add(n);
        return recs;
    }
    async function loadCovered() {
        const covered = new Set(), asked = new Set();
        for (const r of await getAll("rec")) { asked.add(r.q); for (const n of r.ns) covered.add(n); }
        return { covered, asked };
    }
    async function phaseRecords(order) {
        const { covered, asked } = await loadCovered();
        const t0 = Date.now();
        let i = 0, requests = 0;
        for (const n of order) {
            i++;
            const nt = notationOf(n.t);
            if (!nt || covered.has(nt)) continue;
            const nq = n.rk || encodeURIComponent(nt);
            if (asked.has(nq)) { covered.add(nt); continue; }
            try {
                const recs = await fetchRecord(nq, covered, nt);
                requests += recs.length;
            } catch (e) {
                if (e instanceof SessionExpired || e instanceof Stopped) throw e;
                await addErr({ phase: "records", notation: nt, error: e.message });
            }
            asked.add(nq);
            covered.add(nt);   // aunque el sitio no devuelva nada, no se vuelve a pedir
            if (requests % 20 === 0 || i % 500 === 0) {
                status(`2/4 Fichas: nodo ${i}/${order.length}, ${covered.size} clases cubiertas, ${requests} peticiones ` +
                       `(${((Date.now() - t0) / 60000).toFixed(1)} min)`);
            }
            await sleep(DELAY_MS);
        }
    }

    // ------------------------------------------------------------------ 3. búsqueda (canceladas + vigentes)
    function searchBody(notation, page) {
        const form = document.getElementById("searchform");
        const fd = new URLSearchParams();
        if (form) for (const e of form.elements) {
            if (!e.name || e.type === "submit" || e.type === "button") continue;
            if (e.type === "checkbox") { if (e.checked) fd.set(e.name, e.value); } else fd.set(e.name, "");
        }
        for (const f of ["caption", "including", "scopenote", "appnote", "infonote", "examples"]) fd.set(f, f);
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
    async function search(notation, page) {
        const text = await get("/search.php", { method: "POST", body: searchBody(notation, page),
                                                headers: { "Content-Type": "application/x-www-form-urlencoded" } });
        const doc = new DOMParser().parseFromString(text, "text/html");
        // recuento: el número del recuadro de resultados ("1994 matching records found", en cualquier idioma)
        const box = doc.querySelector(".totalline > div") || doc.querySelector(".totalline");
        const m = box ? box.textContent.match(/\d+/) : null;
        let total = m ? +m[0] : null;
        const cancelled = [], live = [];
        for (const tr of doc.querySelectorAll("table.table-condensed > tbody > tr, table.table-condensed > tr")) {
            const ntd = tr.querySelector("td.table-notation");
            if (!ntd) continue;
            const n = ntd.textContent.trim();
            if (ntd.classList.contains("cancelled_text")) {
                const note = tr.querySelector("td.notefield");
                cancelled.push({ n, h: note ? note.innerHTML.replace(/\s+/g, " ").trim() : "" });
            } else live.push(n);
        }
        const table = doc.querySelector("table.table-condensed");
        const rows = cancelled.length + live.length;
        if (total === null) {
            // sin recuadro de recuento: "sin resultados" si no hay filas; si las hay, el formato cambió
            if (rows) throw new Error("respuesta de búsqueda sin recuento");
            total = 0;
        }
        await sleep(DELAY_MS);
        return { total, cancelled, live, rows, table: table ? table.outerHTML : "" };
    }
    async function crawl(prefix, lines, counter) {
        const emit = (p, res) => {
            for (const c of res.cancelled) lines.push({ q: prefix, p, n: c.n, h: c.h });
            if (res.live.length) lines.push({ q: prefix, live: res.live });
        };
        const first = await search(prefix, 0); counter.n++;
        const expect = p => Math.min(PAGE, first.total - p * PAGE);
        if (first.total > 0 && first.rows < expect(0) / 2) {        // página casi vacía: dividir el prefijo
            if (prefix.length >= SEARCH_MAX_DEPTH) {
                lines.push({ check: { prefix, total: first.total, rows: first.rows, problem: "incompleto y sin poder dividir" } });
                emit(0, first);
                return;
            }
            for (const c of SEARCH_NEXT) await crawl(prefix + c, lines, counter);
            lines.push({ check: { prefix, total: first.total, split: true } });
            emit(0, first);
            return;
        }
        emit(0, first);
        if (first.rows < expect(0)) lines.push({ diag: { prefix, page: 0, expected: expect(0), rows: first.rows, html: first.table } });
        let got = first.rows;
        const pages = Math.ceil(first.total / PAGE);
        for (let p = 1; p < pages; p++) {
            let r = await search(prefix, p); counter.n++;
            if (r.rows < expect(p)) { r = await search(prefix, p); counter.n++; }
            emit(p, r);
            if (r.rows < expect(p)) lines.push({ diag: { prefix, page: p, expected: expect(p), rows: r.rows, html: r.table } });
            got += r.rows;
            if (p % 10 === 0) status(`3/4 Búsqueda: ${prefix} página ${p + 1}/${pages} (${counter.n} búsquedas)`);
        }
        lines.push({ check: { prefix, total: first.total, rows: got, pages } });
    }
    async function phaseSearch() {
        const done = new Set((await getAll("srch")).map(x => x.top));
        const counter = { n: 0 };
        for (const top of SEARCH_TOP) {
            if (done.has(top)) continue;
            status(`3/4 Búsqueda (canceladas y vigentes): prefijo ${top} (${SEARCH_TOP.indexOf(top) + 1}/${SEARCH_TOP.length})`);
            const lines = [];
            await crawl(top, lines, counter);
            await putMany("srch", [{ top, lines }]);
        }
    }

    // ------------------------------------------------------------------ 4. huecos
    async function phaseGaps(order) {
        const treeNts = new Set(order.map(n => notationOf(n.t)).filter(Boolean));
        const { covered, asked } = await loadCovered();
        const live = new Set();
        for (const s of await getAll("srch")) for (const l of s.lines) if (l.live) l.live.forEach(n => live.add(clean(n)));
        const gaps = [...live].filter(n => !treeNts.has(n) && !covered.has(n) && !/^-+$/.test(n));
        let i = 0;
        for (const nt of gaps) {
            const nq = encodeURIComponent(nt);
            if (asked.has(nq)) continue;
            status(`4/4 Huecos: ficha de ${nt} (${++i}/${gaps.length})`);
            try { await fetchRecord(nq, covered, nt); } catch (e) {
                if (e instanceof SessionExpired || e instanceof Stopped) throw e;
                await addErr({ phase: "gaps", notation: nt, error: e.message });
            }
            await sleep(DELAY_MS);
        }
        await kvSet("gaps", gaps);
    }

    // ------------------------------------------------------------------ 5. exportación
    async function exportSnapshot(partial) {
        status("Preparando el snapshot…");
        const byKey = new Map((await getAll("tree")).map(n => [n.k, n]));
        const order = dfs(byKey);
        const recs = await getAll("rec");
        const srch = await getAll("srch");
        const errs = await getAll("err");
        const st = (await kvGet("state")) || {};
        const check = recs.some(r => r.h.includes(CHECK.text));
        // nombres de los campos en el idioma de la interfaz (los mismos que usan las fichas: "Scope Note"...)
        const ui = {};
        const form = document.getElementById("searchform");
        if (form) for (const e of form.querySelectorAll("input[name]")) {
            const lab = e.closest("label");
            if (lab && e.type === "checkbox") ui[e.name] = lab.textContent.replace(/\s+/g, " ").trim();
        }
        const stats = { nodes: byKey.size, records: recs.length, searchPrefixes: srch.length, errors: errs.length,
                        partial: !!partial, checkExample: check, gaps: (await kvGet("gaps")) || [] };
        const parts = [JSON.stringify({ format: "udc-snapshot/1", created: new Date().toISOString(), site: location.host,
                                        tool: VERSION, started: st.started || null, lang: document.documentElement.lang || null,
                                        ui, stats }).slice(0, -1)];
        parts.push(',"tree":[');
        order.forEach((n, i) => parts.push((i ? "," : "") + JSON.stringify({ k: n.k, t: n.t, p: n.p, i: n.i, rk: n.rk })));
        parts.push('],"records":[');
        recs.forEach((r, i) => parts.push((i ? "," : "") + JSON.stringify({ q: r.q, pg: r.pg, h: r.h })));
        parts.push('],"search":[');
        let first = true;
        for (const s of srch) for (const l of s.lines) { parts.push((first ? "" : ",") + JSON.stringify(l)); first = false; }
        parts.push('],"errors":' + JSON.stringify(errs) + "}");
        const blob = await new Response(new Blob(parts).stream().pipeThrough(new CompressionStream("gzip"))).blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = `udc_snapshot_${new Date().toISOString().slice(0, 10)}${partial ? "_parcial" : ""}.json.gz`;
        document.body.appendChild(a); a.click(); a.remove();
        return { size: blob.size, stats };
    }

    // ------------------------------------------------------------------ botones
    let running = false;
    panel.querySelector("#udcUtRun").onclick = async () => {
        if (running) return;
        running = true; stopRequested = false;
        const st = (await kvGet("state")) || { phase: "tree", started: new Date().toISOString() };
        await kvSet("state", st);
        const t0 = Date.now();
        try {
            if (st.phase === "tree") { await phaseTree(); st.phase = "records"; await kvSet("state", st); }
            const order = dfs(new Map((await getAll("tree")).map(n => [n.k, n])));
            if (st.phase === "records") {
                // validación temprana: la ficha de prueba debe traer sus ejemplos ◇
                const probe = await get(`/ajaxbrowse.php?n=${encodeURIComponent(CHECK.notation)}&x=1&z=-1&cs=1&ix=-1`);
                if (!probe.includes(CHECK.text)) throw new Error(`la ficha de ${CHECK.notation} no trae "${CHECK.text}": el formato del sitio cambió`);
                await phaseRecords(order); st.phase = "search"; await kvSet("state", st);
            }
            if (st.phase === "search") { await phaseSearch(); st.phase = "gaps"; await kvSet("state", st); }
            if (st.phase === "gaps") { await phaseGaps(order); st.phase = "done"; await kvSet("state", st); }
            const r = await exportSnapshot(false);
            status(`TERMINADO (${((Date.now() - t0) / 60000).toFixed(1)} min en esta sesión). Snapshot de ${(r.size / 1048576).toFixed(1)} MB: ` +
                   `${r.stats.nodes} nodos, ${r.stats.records} páginas de fichas, ${r.stats.errors} errores.\n` +
                   `Muévelo a udc_tree_download/snapshots/ y ejecuta udc_main_tree_fusion.py.\n` +
                   `Para una descarga nueva más adelante: "Borrar datos".`);
        } catch (e) {
            if (e instanceof SessionExpired) status("La sesión caducó. Inicia sesión, abre search.php, pega el script y pulsa 'Empezar / Continuar'.");
            else if (e instanceof Stopped) status("En pausa. 'Empezar / Continuar' sigue donde quedó.");
            else { status(`Error: ${e.message}. Se puede continuar; lo descargado está guardado.`); console.error(e); }
        }
        running = false;
    };
    panel.querySelector("#udcUtStop").onclick = () => { stopRequested = true; status("Pausando…"); };
    panel.querySelector("#udcUtExport").onclick = async () => {
        const r = await exportSnapshot(true);
        status(`Exportado (parcial): ${(r.size / 1048576).toFixed(1)} MB, ${r.stats.nodes} nodos, ${r.stats.records} páginas de fichas.`);
    };
    panel.querySelector("#udcUtClear").onclick = async () => {
        if (running) { status("Primero pausa la descarga."); return; }
        if (!confirm("¿Borrar todo lo descargado y empezar de cero?")) return;
        await clearAll();
        status("Datos borrados. Pulsa 'Empezar / Continuar' para una descarga nueva.");
    };
    const st = await kvGet("state");
    status(st ? `Descarga guardada en fase "${st.phase}" (desde ${st.started}). Pulsa 'Empezar / Continuar'.`
              : "Listo. Pulsa 'Empezar / Continuar'. Tarda ~1-2 h; puedes pausar y seguir otro día.");
})();
