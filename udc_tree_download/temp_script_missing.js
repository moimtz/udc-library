/*
 * Descarga las fichas de las 19 notaciones vigentes que faltan en UDC_hierarchy.txt (~1 min).
 * Uso: con la sesión iniciada en UDC Online, pegar en la consola (F12). Guarda udc_records_part_0037.jsonl.gz
 * (mismo formato que record_download.js): moverlo a udc_tree_download/records/.
 */
(async () => {
    const NOTATIONS = [
        "66.047.4/.5", "66.047.41", "66.047.44", "66.047.45", "66.047.46", "66.047.47", "66.047.49",
        "66.047.54", "66.047.55", "66.047.56", "66.047.57",
        "598.141/.143", "598.141", "598.142", "598.143", "599.63",
        "622.01/.06", "629.3.01/.08", "681.7.01/.08",
    ];
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    function trimRecord(html) {   // igual que record_download.js
        const doc = new DOMParser().parseFromString(html, "text/html");
        doc.querySelectorAll("#searchbox, script, style, form").forEach(e => e.remove());
        doc.querySelectorAll("[style]").forEach(e => e.removeAttribute("style"));
        return doc.body.innerHTML.replace(/\s+/g, " ").trim();
    }
    const lines = [];
    for (const nt of NOTATIONS) {
        try {
            const r = await fetch(`/ajaxbrowse.php?n=${encodeURIComponent(nt)}&x=1&z=-1&cs=1&ix=-1`,
                                  { credentials: "same-origin", cache: "no-store" });
            const text = await r.text();
            if (text.trim() === "XP") { console.log("La sesión caducó: inicia sesión y vuelve a pegarlo."); return; }
            lines.push(JSON.stringify({ n: nt, h: trimRecord(text) }));
            console.log(`[faltantes] ${nt}: ${/No results were returned/.test(text) ? "SIN RESULTADOS" : "ok"}`);
        } catch (e) {
            lines.push(JSON.stringify({ n: nt, error: e.message }));
            console.log(`[faltantes] ${nt}: error ${e.message}`);
        }
        await sleep(200);
    }
    const blob = await new Response(new Blob([lines.join("\n") + "\n"]).stream()
        .pipeThrough(new CompressionStream("gzip"))).blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "udc_records_part_0037.jsonl.gz";
    document.body.appendChild(a); a.click(); a.remove();
    console.log("[faltantes] Guardado udc_records_part_0037.jsonl.gz");
})();
