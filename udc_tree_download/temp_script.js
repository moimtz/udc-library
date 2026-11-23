/*
 * Sondeo exploratorio de UDC Online (~15 min). No descarga el árbol: busca información que todavía
 * no aprovechamos (canceladas, Number Builder, vistas y parámetros desconocidos).
 *
 * Uso: con la sesión iniciada en UDC Online, pegar este archivo en la consola (F12). Aparece un panel.
 *   1. "Sondeo automático" (~5 min):
 *      a) inventario de la página: funciones propias del sitio (con su código), scripts, rutas .php,
 *         formularios y opciones;
 *      b) unas 30 clases de muestra pedidas con los parámetros actuales y con cada parámetro cambiado;
 *      c) búsquedas con "Include cancelled" / "Include examples" (incluye notaciones que el Summary
 *         daba como obsoletas: 568, =43, 54-1/-4).
 *   2. Exploración manual (lo que quieras, ~5-10 min). TODO el tráfico de la página queda grabado:
 *      - Number Builder: añade 2-3 clases con el lápiz, construye/analiza un número compuesto,
 *        prueba sus botones (si los hay: validar, copiar, explicar...);
 *      - abre "open full record" de alguna clase; busca algo con "Include cancelled";
 *      - cualquier menú u opción que no conozcamos (historial, exportar, ediciones...).
 *   3. "Terminar y guardar": descarga udc_probe.json.gz (pásamelo).
 *
 * No guarda cookies ni contraseñas. Hace pocas peticiones y despacio.
 */
(async () => {
    const DELAY_MS = 120;
    const MAX_HTML = 200000;       // tope por respuesta guardada
    const t0 = Date.now();

    // Muestra: tipos de clase distintos, notaciones compuestas y obsoletas del Summary.
    const SAMPLE = [
        "330.322", "/", "903", "903.36", "903.01/.08", "903`1", "661.187.047", "621.039",
        "(460)", "=112.35", "=...`276", "\"19\"", "-05", "-021.475.2", "(1-1)", "(0.023.552)",
        "(729.741)", "(729.732.1)", "2-533", "598.192.162", "004.8", "821.111", "512.666.1",
        "568", "=43", "54-1/-4",                          // obsoletas en el Summary: ¿canceladas?
        "330.322:37", "94(460)\"19\"", "004.8:61",        // compuestas: ¿las analiza el sitio?
    ];
    const BASE = { x: "1", z: "-1", cs: "1", ix: "-1" };
    const VARIANTS = [
        { x: "0" }, { x: "2" }, { z: "0" }, { z: "1" }, { cs: "0" }, { ix: "0" }, { ix: "1" },
    ];
    const SEARCHES = [
        { term: "investment" },
        { term: "investment", include_examples: true },
        { term: "investment", includecancelled: true },
        { notation: "568", includecancelled: true },
        { notation: "=43", includecancelled: true },
        { notation: "54-1", includecancelled: true },
        { notation: "330.322", exactnotation: true, include_examples: true, includecancelled: true },
    ];

    const out = {
        meta: { started: new Date().toISOString(), url: location.href, userAgent: navigator.userAgent },
        inventory: null, variants: [], variantSummary: null, searches: [], traffic: [], errors: [],
    };
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const cut = s => (s && s.length > MAX_HTML ? s.slice(0, MAX_HTML) + "…[cortado]" : s);

    // ------------------------------------------------------------ panel
    const panel = document.createElement("div");
    panel.style.cssText = "position:fixed;top:10px;right:10px;z-index:99999;background:#fff;border:2px solid #333;" +
        "padding:10px;font:13px sans-serif;max-width:380px;box-shadow:0 2px 8px #0005";
    panel.innerHTML = '<b>Sondeo UDC Online</b> <span style="color:#c00">● grabando tráfico</span><br>' +
        '<button id="udcPrAuto">1. Sondeo automático</button> ' +
        '<button id="udcPrSave">3. Terminar y guardar</button>' +
        '<div id="udcPrStatus" style="margin-top:6px;white-space:pre-wrap"></div>';
    document.body.appendChild(panel);
    // si la página rehace su contenido y el panel desaparece, se vuelve a poner
    setInterval(() => { if (!document.body.contains(panel)) document.body.appendChild(panel); }, 1000);
    const status = msg => { panel.querySelector("#udcPrStatus").textContent = msg; console.log("[sondeo]", msg); };

    // ------------------------------------------------------------ grabación de tráfico (fetch + XHR)
    let ownRequest = false;   // las peticiones del sondeo automático ya se guardan aparte
    const record = (kind, method, url, body, statusCode, text) => {
        if (ownRequest) return;
        out.traffic.push({ t: ((Date.now() - t0) / 1000).toFixed(1), kind, method, url: String(url),
                           body: body == null ? null : cut(String(body)), status: statusCode, response: cut(text) });
        status(`Tráfico grabado: ${out.traffic.length} peticiones`);
    };
    const bodyToText = b => {
        if (b == null) return null;
        if (typeof b === "string") return b;
        if (b instanceof URLSearchParams) return b.toString();
        if (b instanceof FormData) return [...b.entries()].map(([k, v]) => `${k}=${v}`).join("&");
        return `[${Object.prototype.toString.call(b)}]`;
    };
    const origFetch = window.fetch.bind(window);
    window.fetch = async (input, init = {}) => {
        const resp = await origFetch(input, init);
        try {
            const url = typeof input === "string" ? input : input.url;
            resp.clone().text().then(t => record("fetch", init.method || "GET", url, bodyToText(init.body), resp.status, t));
        } catch (e) { /* sin grabar */ }
        return resp;
    };
    const XO = XMLHttpRequest.prototype.open, XS = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__pr = { m, u }; return XO.call(this, m, u, ...rest); };
    XMLHttpRequest.prototype.send = function (body) {
        this.addEventListener("loadend", () => {
            let text = "";
            try { text = this.responseType === "" || this.responseType === "text" ? this.responseText : `[${this.responseType}]`; } catch (e) { }
            record("xhr", this.__pr?.m, this.__pr?.u, bodyToText(body), this.status, text);
        });
        return XS.call(this, body);
    };
    // formularios enviados de forma clásica (recargan la página): al menos queda qué se envió
    document.addEventListener("submit", ev => {
        const f = ev.target;
        try { record("form-submit", f.method || "GET", f.action, bodyToText(new FormData(f)), null, "(navegación)"); } catch (e) { }
    }, true);

    // ------------------------------------------------------------ utilidades
    class SessionExpired extends Error {}
    async function getText(url, init = {}) {
        ownRequest = true;
        try {
            const r = await origFetch(url, { credentials: "same-origin", cache: "no-store", ...init });
            const text = await r.text();
            if (text.trim() === "XP" || /logout\.php|name="password"/i.test(text.slice(0, 2000))) {
                throw new SessionExpired("sesión caducada");
            }
            return { status: r.status, text };
        } finally {
            ownRequest = false;
        }
    }
    function trim(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        doc.querySelectorAll("script, style").forEach(e => e.remove());
        doc.querySelectorAll("input[type=password]").forEach(e => e.removeAttribute("value"));
        return doc.body.innerHTML.replace(/\s+/g, " ").trim();
    }
    // Huella estructural: qué tipos de cosas aparecen (no el texto).
    function markers(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        const m = new Set();
        doc.querySelectorAll("#searchbox").forEach(e => e.remove());
        for (const el of doc.body.querySelectorAll("*")) {
            const tag = el.tagName.toLowerCase();
            m.add(`tag:${tag}`);
            el.classList.forEach(c => m.add(`class:${c}`));
            if (el.title) m.add(`title:${el.title}`);
            if (el.id) m.add(`id:${el.id.replace(/\d+/g, "#")}`);
            if (tag === "img") m.add(`img:${el.getAttribute("src")}`);
            const oc = el.getAttribute("onclick");
            if (oc) (oc.match(/[A-Za-z_]\w*(?=\()/g) || []).forEach(f => m.add(`fn:${f}`));
            if (["strong", "b", "th", "label", "h1", "h2", "h3", "h4", "legend"].includes(tag)) {
                const t = el.textContent.trim();
                if (t && t.length <= 40 && !/^[\d.\-()=:"`'\/+]+$/.test(t)) m.add(`${tag}:${t}`);
            }
        }
        const tl = doc.body.textContent.replace(/\s+/g, " ");
        for (const w of ["cancel", "replaced", "introduced", "revision", "revised", "edition", "derived",
                         "divide as", "parallel", "see also", "deprecated", "obsolete", "history", "date"]) {
            if (tl.toLowerCase().includes(w)) m.add(`word:${w}`);
        }
        return m;
    }
    const browseUrl = (n, p) => `/ajaxbrowse.php?n=${encodeURIComponent(n)}&` + new URLSearchParams(p).toString();

    // ------------------------------------------------------------ 1a. inventario
    async function inventory() {
        status("Inventario de la página…");
        const inv = { functions: {}, scripts: [], endpoints: [], forms: [], onclickFunctions: [], links: [] };
        // funciones propias del sitio (no nativas, no de librerías conocidas)
        for (const k of Object.keys(window)) {
            let v;
            try { v = window[k]; } catch (e) { continue; }
            if (typeof v !== "function" || /^(\$|jQuery|webkit|on)/.test(k)) continue;
            const src = Function.prototype.toString.call(v);
            if (src.includes("[native code]")) continue;
            inv.functions[k] = src.length > 20000 ? src.slice(0, 20000) + "…" : src;
        }
        const allJs = [];
        for (const s of document.scripts) {
            if (s.src) {
                const entry = { src: s.src };
                const sameOrigin = new URL(s.src, location.href).origin === location.origin;
                if (sameOrigin && !/jquery|bootstrap|analytics|gtag|recaptcha/i.test(s.src)) {
                    try { entry.text = cut((await getText(s.src)).text); allJs.push(entry.text); } catch (e) { entry.error = e.message; }
                }
                inv.scripts.push(entry);
            } else {
                inv.scripts.push({ inline: cut(s.textContent) });
                allJs.push(s.textContent);
            }
        }
        const html = document.documentElement.outerHTML;
        allJs.push(html, ...Object.values(inv.functions));
        const eps = new Set();
        for (const t of allJs) (t.match(/[\w\/.\-]+\.php(?:\?[^'"\s<>)]*)?/g) || []).forEach(e => eps.add(e));
        inv.endpoints = [...eps].sort();
        for (const f of document.forms) {
            inv.forms.push({
                id: f.id, action: f.getAttribute("action"), method: f.method,
                fields: [...f.elements].map(e => ({ name: e.name, id: e.id, type: e.type, value: e.type === "password" ? "" : e.value,
                    checked: e.checked, options: e.options ? [...e.options].map(o => [o.value, o.text]) : undefined })),
            });
        }
        const fns = new Set();
        document.querySelectorAll("[onclick]").forEach(e => (e.getAttribute("onclick").match(/[A-Za-z_]\w*(?=\()/g) || []).forEach(f => fns.add(f)));
        inv.onclickFunctions = [...fns].sort();
        inv.links = [...new Set([...document.querySelectorAll("a[href]")].map(a => a.getAttribute("href")))].slice(0, 400);
        inv.page = cut(trim(html));
        out.inventory = inv;
        status(`Inventario: ${Object.keys(inv.functions).length} funciones, ${inv.endpoints.length} rutas .php, ${inv.forms.length} formularios.`);
    }

    // ------------------------------------------------------------ 1b. variantes de parámetros
    async function variants() {
        const known = new Set();
        const summary = {};   // variante -> {nuevas: {marca: [notaciones]}, faltan: {...}, cambioTamano: [...]}
        let done = 0;
        const total = SAMPLE.length * (VARIANTS.length + 1);
        for (const n of SAMPLE) {
            let base;
            for (const v of [{}, ...VARIANTS]) {
                const params = { ...BASE, ...v };
                const key = Object.keys(v).length ? Object.entries(v).map(([a, b]) => `${a}=${b}`).join("&") : "base";
                const rec = { n, variant: key, url: browseUrl(n, params) };
                try {
                    const r = await getText(rec.url);
                    rec.status = r.status;
                    rec.length = r.text.length;
                    rec.html = cut(trim(r.text));
                    const mk = markers(r.text);
                    if (key === "base") {
                        base = { mk, len: r.text.length };
                        mk.forEach(x => known.add(x));
                    } else if (base) {
                        const s = (summary[key] ||= { nuevas: {}, faltan: {}, cambioTamano: [] });
                        for (const x of mk) if (!base.mk.has(x)) (s.nuevas[x] ||= []).push(n);
                        for (const x of base.mk) if (!mk.has(x)) (s.faltan[x] ||= []).push(n);
                        if (Math.abs(r.text.length - base.len) > 50) s.cambioTamano.push(`${n}: ${base.len} -> ${r.text.length}`);
                    }
                } catch (e) {
                    if (e instanceof SessionExpired) throw e;
                    rec.error = e.message;
                    out.errors.push(`${rec.url}: ${e.message}`);
                }
                out.variants.push(rec);
                done++;
                if (done % 10 === 0) status(`Variantes: ${done}/${total}`);
                await sleep(DELAY_MS);
            }
        }
        out.variantSummary = { marcasBase: [...known].sort(), porVariante: summary };
    }

    // ------------------------------------------------------------ 1c. búsquedas
    async function searches() {
        const form = document.getElementById("searchform");
        const action = form?.getAttribute("action") || "search.php";
        for (const q of SEARCHES) {
            const fd = new URLSearchParams();
            // mismos campos que el formulario de la página (casillas de campos marcadas por defecto)
            if (form) for (const e of form.elements) {
                if (!e.name || e.type === "submit" || e.type === "button") continue;
                if (e.type === "checkbox") { if (e.checked) fd.set(e.name, e.value); }
                else fd.set(e.name, "");
            }
            for (const [k, v] of Object.entries(q)) {
                if (v === true) fd.set(k, k); else fd.set(k, v);
            }
            fd.set("search", "");
            const rec = { query: q, action, body: fd.toString() };
            try {
                const r = await getText(action, { method: "POST", body: fd, headers: { "Content-Type": "application/x-www-form-urlencoded" } });
                rec.status = r.status;
                rec.length = r.text.length;
                rec.html = cut(trim(r.text));
                rec.markers = [...markers(r.text)].sort();
            } catch (e) {
                if (e instanceof SessionExpired) throw e;
                rec.error = e.message;
            }
            out.searches.push(rec);
            status(`Búsquedas: ${out.searches.length}/${SEARCHES.length}`);
            await sleep(DELAY_MS * 3);
        }
    }

    // ------------------------------------------------------------ botones
    let running = false;
    panel.querySelector("#udcPrAuto").onclick = async () => {
        if (running) return;
        running = true;
        try {
            await inventory();
            await variants();
            await searches();
            const novedades = Object.entries(out.variantSummary.porVariante)
                .map(([k, s]) => `${k}: +${Object.keys(s.nuevas).length} marcas, ${s.cambioTamano.length} cambios de tamaño`).join("\n");
            await save();
            status(`Sondeo automático terminado y guardado en udc_probe.json.gz ` +
                   `(${((Date.now() - t0) / 60000).toFixed(1)} min).\n${novedades}\n\nYa puedes recargar la página (F5).`);
        } catch (e) {
            out.errors.push(String(e));
            await save();
            status((e instanceof SessionExpired ? "La sesión caducó." : `Error: ${e.message}.`) +
                   " Se guardó lo obtenido en udc_probe.json.gz.");
        }
        running = false;
    };
    const save = async () => {
        out.meta.finished = new Date().toISOString();
        if (!out.inventory) { try { await inventory(); } catch (e) { out.errors.push(String(e)); } }
        const text = JSON.stringify(out);
        const blob = await new Response(new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"))).blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = "udc_probe.json.gz";
        document.body.appendChild(a);
        a.click();
        a.remove();
        status(`Guardado udc_probe.json.gz (${(blob.size / 1024).toFixed(0)} KB; ${out.variants.length} variantes, ` +
               `${out.searches.length} búsquedas, ${out.traffic.length} peticiones grabadas). Puedes seguir y volver a guardar.`);
    };
    panel.querySelector("#udcPrSave").onclick = save;
    // Desde la consola: udcProbe.save() guarda; udcProbe.resumen() muestra el avance.
    window.udcProbe = {
        save, out,
        resumen: () => `${out.variants.length} variantes, ${out.searches.length} búsquedas, ${out.traffic.length} peticiones grabadas`,
    };
    status("Listo. Pulsa '1. Sondeo automático'. El tráfico ya se está grabando.");
})();
