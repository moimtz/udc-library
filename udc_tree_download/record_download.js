/*
 * Descarga las fichas completas de UDC Online (notas, ejemplos de combinación, referencias).
 *
 * Uso: con la sesión iniciada en UDC Online, pegar este archivo en la consola (F12).
 * Aparece un panel arriba a la derecha: pulsar el botón y elegir UDC_hierarchy.txt.
 *
 * 1. Primero descarga la ficha de 330.322 completa (udc_record_sample_330.322.html) y comprueba
 *    que contiene "Net investment". Si no, se detiene.
 * 2. Luego descarga todas las notaciones en partes de PART_SIZE fichas:
 *    udc_records_part_0001.jsonl.gz, ...  (una línea JSON por ficha: {"n": notación, "h": html})
 *    El HTML se guarda casi crudo; se interpreta después con udc_records.py.
 * 3. Si se cierra la pestaña o caduca la sesión, volver a pegar el script: continúa en la
 *    parte siguiente a la última descargada (se guarda en localStorage).
 *    Para empezar de cero: localStorage.removeItem("udcRecNext")
 *
 * Chrome pedirá permiso para "descargar varios archivos": aceptarlo.
 */
(async () => {
    const MAX_CONCURRENT = 4;
    const PART_SIZE = 2000;
    const RETRIES = 3;
    const DELAY_MS = 40;
    const CHECK_NOTATION = "330.322";
    const CHECK_TEXT = "Net investment";
    // Notaciones con coma: en el sitio usan claves internas ('$$1$, /'); son nodos informativos
    // y se cubren a mano en extra_notes.json.
    const COMMA_NOTATIONS = ["-1/-9,.01/.09, `0/`9", ":, ::, []", "+, /", "*, A/Z"];

    const sleep = ms => new Promise(r => setTimeout(r, ms));

    function recordUrl(notation) {
        // Igual que fetchAndClearRecord() de la página: n=<notación>&x=1&z=-1&cs=1&ix=-1
        return `/ajaxbrowse.php?n=${encodeURIComponent(notation)}&x=1&z=-1&cs=1&ix=-1`;
    }

    function saveBlob(blob, name) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
    }

    async function gzip(text) {
        const stream = new Blob([text]).stream().pipeThrough(new CompressionStream("gzip"));
        return await new Response(stream).blob();
    }

    // Quita el formulario de búsqueda, scripts y estilos; conserva el resto del HTML.
    function trimRecord(html) {
        const doc = new DOMParser().parseFromString(html, "text/html");
        doc.querySelectorAll("#searchbox, script, style, form").forEach(e => e.remove());
        doc.querySelectorAll("[style]").forEach(e => e.removeAttribute("style"));
        return doc.body.innerHTML.replace(/\s+/g, " ").trim();
    }

    class SessionExpired extends Error {}

    async function fetchRecord(notation) {
        let lastErr;
        for (let i = 0; i < RETRIES; i++) {
            try {
                const r = await fetch(recordUrl(notation), { credentials: "same-origin", cache: "no-store" });
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                const text = await r.text();
                if (text.trim() === "XP" || /logout\.php|name="password"/i.test(text.slice(0, 2000))) {
                    throw new SessionExpired("sesión caducada");
                }
                return text;
            } catch (e) {
                if (e instanceof SessionExpired) throw e;
                lastErr = e;
                await sleep(500 * (i + 1));
            }
        }
        throw lastErr;
    }

    function readNotations(txt) {
        const out = [];
        for (const raw of txt.replace(/^﻿/, "").split(/\r?\n/)) {
            const s = raw.trim();
            if (!s) continue;
            const head = s.split(" ")[0];
            if (/^-+$/.test(head)) continue;                       // encabezado de grupo
            if (COMMA_NOTATIONS.some(nt => s === nt || s.startsWith(nt + " "))) continue;
            out.push(head);
        }
        return out;
    }

    // ---------------------------------------------------------------- panel
    const panel = document.createElement("div");
    panel.style.cssText = "position:fixed;top:10px;right:10px;z-index:99999;background:#fff;" +
        "border:2px solid #333;padding:10px;font:13px sans-serif;max-width:360px;box-shadow:0 2px 8px #0005";
    panel.innerHTML = '<b>Descarga de fichas UDC</b><br><button id="udcRecBtn">Elegir UDC_hierarchy.txt</button>' +
        '<div id="udcRecStatus" style="margin-top:6px;white-space:pre-wrap"></div>';
    document.body.appendChild(panel);
    const status = msg => { panel.querySelector("#udcRecStatus").textContent = msg; console.log(msg); };

    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".txt";
    panel.querySelector("#udcRecBtn").onclick = () => input.click();
    const file = await new Promise(res => { input.onchange = () => res(input.files[0]); });
    const notations = readNotations(await file.text());
    status(`${notations.length} notaciones leídas.`);

    // ---------------------------------------------------------------- 1. validación
    try {
        const sample = await fetchRecord(CHECK_NOTATION);
        saveBlob(new Blob([sample], { type: "text/html;charset=utf-8" }), `udc_record_sample_${CHECK_NOTATION}.html`);
        if (!sample.includes(CHECK_TEXT)) {
            status(`La ficha de ${CHECK_NOTATION} no contiene "${CHECK_TEXT}". Se guardó la muestra; me detengo.`);
            return;
        }
    } catch (e) {
        status(`No se pudo descargar la ficha de prueba: ${e.message}`);
        return;
    }
    status(`Ficha de prueba correcta (${CHECK_NOTATION}).`);

    // ---------------------------------------------------------------- 2. descarga por partes
    const parts = Math.ceil(notations.length / PART_SIZE);
    let next = parseInt(localStorage.getItem("udcRecNext") || "0", 10);
    const failures = [];
    const t0 = Date.now();

    for (let p = next; p < parts; p++) {
        const slice = notations.slice(p * PART_SIZE, (p + 1) * PART_SIZE);
        const lines = new Array(slice.length);
        let done = 0;
        try {
            for (let i = 0; i < slice.length; i += MAX_CONCURRENT) {
                await Promise.all(slice.slice(i, i + MAX_CONCURRENT).map(async (nt, j) => {
                    try {
                        const html = await fetchRecord(nt);
                        lines[i + j] = JSON.stringify({ n: nt, h: trimRecord(html) });
                    } catch (e) {
                        if (e instanceof SessionExpired) throw e;
                        failures.push({ n: nt, error: e.message });
                        lines[i + j] = JSON.stringify({ n: nt, error: e.message });
                    }
                    done++;
                }));
                if (i % 200 === 0) {
                    const mins = ((Date.now() - t0) / 60000).toFixed(1);
                    status(`Parte ${p + 1}/${parts}: ${done}/${slice.length}  (${mins} min, ${failures.length} errores)`);
                }
                await sleep(DELAY_MS);
            }
        } catch (e) {
            status(`Sesión caducada en la parte ${p + 1}. Inicia sesión de nuevo y vuelve a pegar el script: ` +
                   `continuará en esa parte.`);
            return;
        }
        const name = `udc_records_part_${String(p + 1).padStart(4, "0")}.jsonl.gz`;
        saveBlob(await gzip(lines.join("\n") + "\n"), name);
        localStorage.setItem("udcRecNext", String(p + 1));
        status(`Guardada ${name}`);
    }

    if (failures.length) {
        saveBlob(new Blob([JSON.stringify(failures, null, 1)], { type: "application/json" }), "udc_records_failures.json");
    }
    status(`TERMINADO: ${notations.length} fichas en ${parts} partes, ${failures.length} errores.\n` +
           `Para repetir desde cero: localStorage.removeItem("udcRecNext")`);
})();
