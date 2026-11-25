import tempfile
import unittest
from pathlib import Path

import numpy as np

import config
from tests.synthetic import rdf_xml
from udcpoc import auxtables as aux, metadata as md
from udcpoc.classify import Classifier
from udcpoc.embed import Embedder, UDCIndex
from udcpoc.evaluate import evaluate
from udcpoc.feedback import FEATURES, Feedback, Reranker
from udcpoc.notation import components, compose, validate
from udcpoc.pdfio import Line, PdfDoc
from udcpoc.tree import Tree

TMP = Path(tempfile.mkdtemp())
RDF = TMP / "udc.rdf"
RDF.write_text(rdf_xml(), encoding="utf-8")


class TestTree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = Tree.load(RDF)

    def test_kinds(self):
        k = {n.notation: n.kind for n in self.tree.nodes.values()}
        self.assertEqual(k["94"], "main"); self.assertEqual(k["=134.2"], "lang")
        self.assertEqual(k["(02)"], "form"); self.assertEqual(k["(460)"], "place")
        self.assertEqual(k['"18"'], "time"); self.assertEqual(k["-05"], "common")

    def test_hierarchy_and_inference(self):
        t = self.tree
        self.assertEqual(t.parent_of(t.get("94")).notation, "9")
        self.assertEqual(t.parent_of(t.get("821")).notation, "82")      # inferido por prefijo
        self.assertEqual([n.notation for n in t.path(t.get("821"))], ["8", "82", "821"])
        self.assertEqual(t.parent_of(t.get("(460)")).notation, "(4)")

    def test_validate(self):
        t = self.tree
        self.assertEqual(validate('94(460)"18"=134.2', t), [])
        self.assertTrue(any(l == "error" for l, _ in validate("99", t)))
        self.assertTrue(any(l == "error" for l, _ in validate("94(460", t)))
        self.assertTrue(any(l == "error" for l, _ in validate("94:", t)))
        self.assertTrue(any(l == "warning" for l, _ in validate("94(999)", t)))
        c = components('94:34(460)"18"=134.2')
        self.assertEqual(c["main"], ["94", "34"]); self.assertEqual(c["place"], ["(460)"])
        # orden de cita estándar: lugar, tiempo, forma, idioma
        self.assertEqual(compose([{"code": "94"}], {"lang": "=134.2", "place": "(460)"}), "94(460)=134.2")


class TestPdfPages(unittest.TestCase):
    """Descarte de páginas vacías: guardas, portadas lisas, 'intentionally left blank', escaneos con tinta."""

    def _pdf(self):
        import pymupdf
        doc = pymupdf.open()
        body = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6
        doc.new_page()                                                    # 1 vacía
        p = doc.new_page(); p.draw_rect(p.rect, color=None, fill=(0.3, 0.3, 0.3))   # 2 portada lisa oscura
        doc.new_page().insert_text((72, 300), "This page intentionally left blank")  # 3
        doc.new_page().insert_text((72, 300), "TITULO DEL LIBRO", fontsize=30)       # 4 portada con poco texto
        p = doc.new_page()                                                # 5 "escaneada": tinta sin texto
        for y in range(100, 700, 14):
            p.draw_line((72, y), (520, y), width=4)
        for _ in range(12):
            doc.new_page().insert_textbox(pymupdf.Rect(72, 72, 520, 770), body)  # 6..17 texto
        doc.new_page()                                                    # 18 vacía al final
        path = TMP / "pages.pdf"
        doc.save(path)
        return path

    def test_kinds_and_pick(self):
        import pymupdf
        from udcpoc.pdfio import page_kind, read_pdf, text_quality
        path = self._pdf()
        doc = pymupdf.open(path)
        kinds = [page_kind(doc[i], doc[i].get_text("text")) for i in range(6)]
        self.assertEqual(kinds, ["blank", "blank", "blank", "text", "image", "text"])
        doc.close()
        d = read_pdf(path)
        self.assertEqual(d.pages_used, [3, 4, 5, 6, 7, 8, 14, 15, 16])   # salta 3 vacías al inicio y 1 al final
        self.assertEqual(d.blank_skipped, 4)
        self.assertFalse(d.scanned)                                # solo 1 de 6 páginas sin texto
        self.assertTrue(any("--ocr" in w for w in d.warnings))
        self.assertTrue(d.head_text[0].startswith("TITULO"))
        self.assertEqual(d.head_text[1], "")                       # la escaneada no aporta texto sin OCR
        self.assertGreater(text_quality("Discours de la méthode, pour bien conduire sa raison"), 0.9)
        self.assertLess(text_quality("; oi ) = / — ® Le 2e. ss x Es Ée . * Fr F è [44° st: % ñ }"), 0.5)


class TestMusic(unittest.TestCase):
    """Partituras: pentagramas dibujados, plantilla por sistema y clasificación dentro de 78."""

    @staticmethod
    def _score_pdf(per_system=2, systems=5, pages=4, text=""):
        import pymupdf
        doc = pymupdf.open()
        for _ in range(pages):
            p = doc.new_page()
            y = 80
            for _s in range(systems):
                for _k in range(per_system):
                    for ln in range(5):                       # 5 líneas a 5 pt
                        p.draw_line((60, y + 5 * ln), (540, y + 5 * ln), width=0.6)
                    y += 20 + 22                              # pentagrama + hueco dentro del sistema
                y += 40                                       # hueco entre sistemas (mayor)
            if text:
                p.insert_text((60, 40), text)
        path = TMP / f"score_{per_system}_{systems}.pdf"
        doc.save(path)
        return path

    def test_detect_and_template(self):
        import pymupdf
        from udcpoc import music
        d = pymupdf.open(self._score_pdf(2, 5))
        info = music.detect(d)
        self.assertTrue(info.is_score)
        self.assertEqual(info.per_system, 2)
        d = pymupdf.open(self._score_pdf(3, 3))
        self.assertEqual(music.detect(d).per_system, 3)

    def test_text_page_is_not_score(self):
        import pymupdf
        from udcpoc import music
        doc = pymupdf.open()
        for _ in range(4):
            doc.new_page().insert_textbox(pymupdf.Rect(60, 60, 540, 780), "Lorem ipsum dolor sit amet. " * 120)
        self.assertEqual(music.detect(doc).score_pages, 0)

    def test_decide_and_classify(self):
        from udcpoc import music
        info = music.StaffInfo(pages_checked=6, score_pages=5, per_system=2)
        self.assertTrue(music.decide(info, "Sobre las olas", "Rosas_SobrelasOlas")[0])
        self.assertFalse(music.decide(info, "Tonal Harmony", "Tonal Harmony - Kostka")[0])   # libro SOBRE música
        weak = music.StaffInfo(pages_checked=6, score_pages=2)
        self.assertFalse(music.decide(weak, "", "variaciones")[0])
        self.assertTrue(music.decide(weak, "", "IMSLP302161-bach")[0])                       # fuente de partituras
        c = lambda txt, ps=0: music.classify(txt, music.StaffInfo(per_system=ps))["mains"]
        self.assertEqual(c("Toccatina, Alkan, Op. 75", 2), ["780.8", "780.616.433", "78.083.3"])
        self.assertEqual(c("Sobre las olas. Vals para piano"), ["780.8", "780.616.433", "78.085.2"])
        self.assertEqual(c("Estrellita (Little Star)", 3), ["784.3"])
        self.assertEqual(c("Streichquartett Nr. 14"), ["785.74"])
        self.assertEqual(c("Symphonie Nr. 5 c-moll", 1), ["785.11"])
        self.assertEqual(c("Konzert für Violine und Orchester"), ["785.6", "780.614.332"])
        self.assertEqual(c("La Traviata. Opera in tre atti"), ["782"])
        self.assertEqual(c("Missa solemnis"), ["783"])


class TestEnrich(unittest.TestCase):
    """Enriquecimiento por identificador (sin red: solo las partes deterministas)."""

    def test_helpers(self):
        from udcpoc import enrich as en
        self.assertEqual(en.isbn13("0-393-92516-1"), "9780393925166")
        self.assertEqual(en.lcc_label("QA433 .S28 2005"), "Mathematics")
        self.assertEqual(en.lcc_label("MT50.P455 T9"), "Musical instruction and study")
        self.assertEqual(en.ddc_label("515/.63"), "Mathematics")
        v = en.subjects_view({"subjects": ["Vector analysis", "Qa433 .s28 2005", "515/.63"],
                              "lcc": ["QA433 .S28 2005"], "ddc": ["515/.63"]})
        self.assertEqual(v, "Vector analysis; Mathematics")         # sin códigos sueltos ni duplicados

    def test_offline_cache_and_no_ids(self):
        from udcpoc import enrich as en
        self.assertIsNone(en.enrich({}))
        en._cache = {"ol:9780393925166": {"fields": {"title": "Div, grad, curl"}, "subjects": ["Vector analysis"]},
                     "bnpl:9780393925166": {"udc": ["514.742(075.8)"]}}
        try:
            e = en.enrich({"isbn": "0393925161"})                   # todo sale de la caché: sin red
            self.assertEqual(e["sources"], ["openlibrary", "bn.org.pl"])
            self.assertEqual(e["udc"], ["514.742(075.8)"])
        finally:
            en._cache = None

    def test_catalog_udc_goes_first(self):
        tree = Tree.load(RDF)
        emb = Embedder("dummy")
        clf = Classifier(tree, UDCIndex.load_or_build(tree, emb, TMP / "idx_cat", progress=False), emb)
        views = {"front": "A history of Spain", "toc": "", "body": "", "tail": ""}
        r = clf.suggest(views, {"item_type": "book", "external_udc": {"codes": ["[94(460)]"], "source": "bn.org.pl"}})
        self.assertEqual(r["suggestions"][0]["udc"], "94(460)")
        self.assertIn("catálogo", r["suggestions"][0]["explain"]["origen"])
        self.assertLessEqual(len(r["suggestions"]), 3)


class TestMetadata(unittest.TestCase):
    def test_identifiers(self):
        ids = md.find_identifiers("see 10.1000/xyz123. ISBN 978-0-306-40615-7 arXiv:2101.01234v2 ISSN 1234-5679")
        self.assertEqual(ids["doi"], "10.1000/xyz123"); self.assertEqual(ids["isbn"], "978-0-306-40615-7")
        self.assertEqual(ids["arxiv"], "2101.01234"); self.assertNotIn("isbn", md.find_identifiers("ISBN 978-0-306-40615-8"))

    def test_dates_and_names(self):
        self.assertEqual(md.norm_date("Filed: Mar. 5, 2019"), "2019-03-05")
        self.assertEqual(md.norm_date("12 de mayo de 2001"), "2001-05-12")
        self.assertEqual(md.norm_date("3. März 1999"), "1999-03-03")                # sin idioma: no ambiguo
        self.assertEqual(md.norm_date("14 juillet 1789"), "1789-07-14")
        self.assertEqual(md.norm_date("12 de octubre de 1492", "es"), "1492-10-12")
        self.assertEqual(md.norm_date("5 listopada 2010", "pl"), "2010-11-05")      # ambiguo: necesita idioma
        self.assertEqual(md.norm_date("5 listopada 2010", "hr"), "2010-10-05")
        self.assertEqual(md.norm_date("12 мая 2001", "ru"), "2001-05-12")
        self.assertEqual(md.parse_names("Иван Петров, Анна Смирнова"), ["Иван Петров", "Анна Смирнова"])
        self.assertEqual(md.parse_names("Jean-Paul Sartre et Simone de Beauvoir"),
                         ["Jean-Paul Sartre", "Simone de Beauvoir"])
        self.assertEqual(md.split_title_extras("Analyse, 2e édition")[1], "2")
        self.assertEqual(md.split_title_extras("Mechanik (3. Auflage)")[1], "3")
        self.assertEqual(md.pick_keywords("Mots-clés : histoire, chimie\n\nIntro"), ["histoire", "chimie"])
        self.assertEqual(md.detect_doctype("thèse de doctorat, université de paris, directeur", {}, 200)[0],
                         "thesis")
        self.assertEqual(md.detect_doctype("dissertation zur erlangung des doktorgrades, universität, betreuer",
                                           {}, 200)[0], "thesis")
        # créditos de revisores en la contraportada de un libro largo: empate tesis/libro -> libro
        self.assertEqual(md.detect_doctype("revisores: maestría en sistemas, university of texas", {}, 348)[0],
                         "book")
        # falsos amigos entre idiomas: palabras corrientes que no deben disparar un tipo
        for txt in ("these results show attention, university of toronto", "un largo camino lento",
                    "the partition function", "querido amigo, el precio es caro"):
            self.assertNotIn(md.detect_doctype(txt, {}, 10)[0], ("thesis", "score", "letter"), txt)
        self.assertEqual(md.parse_names("Juan Pérez, María de la Cruz y Ana López"), ["Juan Pérez", "María de la Cruz", "Ana López"])
        self.assertEqual(md.parse_names("Pérez, Juan"), ["Juan Pérez"])
        self.assertEqual(md.parse_names("Universidad Nacional Autónoma"), [])
        self.assertEqual(md.name_to_creator("María de la Cruz")["lastName"], "de la Cruz")

    def test_title_layout(self):
        L = lambda t, s, y: Line(t, s, 0, y)
        lines = [L("UNIVERSIDAD DE EJEMPLO", 18, 40), L("Modelos de aprendizaje profundo para", 22, 120),
                 L("la clasificación de documentos", 22, 148), L("Juan Pérez Gómez", 12, 220), L("María López", 12, 240),
                 L("Resumen del trabajo presentado en 2020 para optar al título", 10, 300), L("otro texto de relleno aquí", 10, 320)]
        title, conf, after, size = md.pick_title(lines)
        self.assertEqual(title, "Modelos de aprendizaje profundo para la clasificación de documentos")
        self.assertEqual(md.pick_creators(after, size), ["Juan Pérez Gómez", "María López"])

    def test_doctype_and_patent(self):
        pat = ("(19) United States\n(12) Patent Application Publication\n(11) Patent No.: US 7,123,456 B2\n"
               "(54) WIDGET FOR TESTING THINGS\n(72) Inventors: John Smith, Boston, MA (US);\nJane Doe, Austin, TX (US)\n"
               "(73) Assignee: ACME Corp.\n(21) Appl. No.: 10/123,456\n(22) Filed: Mar. 5, 2019\n(45) Date of Patent: Jun. 7, 2021\n"
               "(57) ABSTRACT\nA widget that tests things " + "x" * 50)
        self.assertEqual(md.detect_doctype(pat, {}, 20)[0], "patent")
        p = md.parse_patent(pat)
        self.assertEqual(p["patentNumber"], "US 7,123,456 B2"); self.assertEqual(p["country"], "US")
        self.assertEqual(p["title"], "Widget For Testing Things"); self.assertEqual(p["filingDate"], "2019-03-05")
        self.assertEqual(md.detect_doctype("Tesis doctoral. Universidad de X. Director: ...", {}, 200)[0], "thesis")
        self.assertEqual(md.detect_language("El análisis de los datos que se presentan en este trabajo es para los lectores " * 3)[0], "es")

    def test_filename(self):
        p = md.parse_filename(r"C:\x\Análisis de Circuitos en Ingeniería - Hayt Jr., Kemmerly, Durbin (8th).pdf")
        self.assertEqual(p["title"], "Análisis de Circuitos en Ingeniería")
        self.assertEqual(p["authors"], ["Hayt Jr", "Kemmerly", "Durbin"]); self.assertEqual(p["edition"], "8")
        p = md.parse_filename("IMSLP755791-PMLP1199200-Arensky_-_1000_Aufgaben.pdf")
        self.assertEqual((p["title"], p["authors"]), ("1000 Aufgaben", ["Arensky"]))
        p = md.parse_filename("Köhler's Medizinal-Pflanzen I.pdf")
        self.assertEqual((p["title"], p["authors"]), ("Köhler's Medizinal-Pflanzen I", []))
        self.assertEqual(md.parse_filename("a3f9c2e81b7d4e6fa0c1.pdf"), {})
        self.assertEqual(md.parse_filename("document(3).pdf"), {})
        self.assertEqual(md.split_title_extras("A First Course in the Finite Element Method, 6th edition (2017)"),
                         ("A First Course in the Finite Element Method", "6", "2017"))

    def test_build_record_end_to_end(self):
        L = lambda t, s, y: Line(t, s, 0, y)
        pdf = PdfDoc(path="x.pdf", n_pages=300, head_text=["Historia de España en el siglo XIX\nJuan Pérez\n© 1998 Editorial Alianza\n" + "texto " * 80, "más texto " * 50],
                     tail_text=["ISBN 978-0-306-40615-7"],
                     lines=[L("Historia de España en el siglo XIX", 24, 100), L("Juan Pérez", 12, 160), L("Editorial Alianza", 10, 700), L("otra línea de texto normal", 10, 720)])
        rec = md.build_record(pdf)
        self.assertEqual(rec["item_type"]["value"], "book")
        f = rec["fields"]
        self.assertEqual(f["title"]["value"], "Historia de España en el siglo XIX")
        self.assertEqual(f["date"]["value"], "1998"); self.assertEqual(f["ISBN"]["value"], "978-0-306-40615-7")
        self.assertEqual(f["creators"]["value"][0]["lastName"], "Pérez")
        self.assertIn("publisher", f)


class TestClassify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = Tree.load(RDF)
        cls.emb = Embedder("dummy")
        cls.idx = UDCIndex.load_or_build(cls.tree, cls.emb, TMP / "idx", progress=False)
        cls.fb = Feedback(TMP / "fb.db")

    def clf(self, **kw):
        return Classifier(self.tree, self.idx, self.emb, **kw)

    def test_aux_pieces(self):
        t = self.tree
        self.assertEqual(aux.lang_aux("es", 0.9, t)["code"], "=134.2")
        self.assertEqual(aux.form_aux("thesis", None, "", t)["code"], "(043.2)")
        self.assertIsNone(aux.form_aux("book", None, "", t))  # un libro normal no lleva forma
        self.assertEqual(aux.form_aux("book", None, "A First Course in Calculus", t)["code"], "(075)")
        self.assertEqual(aux.form_aux("book", None, "CRC Handbook of Chemistry", t)["code"], "(035)")
        self.assertEqual(aux.time_aux("", t, title="La España del siglo XIX y la crisis de 1808")["code"], '"18"')
        self.assertIsNone(aux.time_aux("Un texto sin fechas", t))
        self.assertEqual(aux.time_aux("", t, title="Twentieth-century Harmony")["code"], '"19"')
        # años sueltos (edición, informes, citas) ya no dan periodo
        self.assertIsNone(aux.time_aux("Informe 2021. Datos de 2019, 2020 y 2022. Publicado en 2023.", t))
        self.assertEqual(aux.form_aux("book", None, "A First Course in Calculus, 9th edition", t)["code"], "(075.8)")
        self.assertEqual(aux.form_aux("journalArticle", None, "", t)["code"], "(045)")
        self.assertEqual(aux.form_aux("book", None, "LM317 datasheet. Absolute maximum ratings", t)["code"], "(085)")

    def test_place(self):
        pf = aux.PlaceFinder(self.tree)
        self.assertEqual(pf.find([("Historia de España", 5.0)], "es")["code"], "(460)")
        self.assertIsNone(pf.find([("Un libro sobre cosas", 5.0)], "es"))
        # cualquier idioma: nombres CLDR en el idioma del documento
        self.assertEqual(pf.find([("Geschichte Mexikos und Spaniens: Mexiko", 5.0)], "de")["code"], "(72)")
        self.assertEqual(pf.find([("История Испании", 5.0)], "ru")["code"], "(460)")
        self.assertEqual(pf.find([("スペインの歴史", 5.0)], "ja")["code"], "(460)")
        self.assertEqual(pf.find([("A history of Spain", 5.0)], "fr")["code"], "(460)")   # inglés siempre
        self.assertEqual(pf.find([("Historia de EE. UU. y México", 5.0)], "es")["code"], "(72)")  # alias

    def test_index_incremental_and_deterministic(self):
        import json
        d = TMP / "idx_inc"
        t1 = Tree.load(RDF)
        self.assertEqual(t1.fingerprint(), Tree.load(RDF).fingerprint())       # misma entrada, misma huella
        emb = Embedder("dummy")
        calls = []
        orig = emb.encode
        emb.encode = lambda texts, **k: (calls.append(len(texts)), orig(texts, **k))[1]
        i1 = UDCIndex.load_or_build(t1, emb, d, progress=False)
        UDCIndex.load_or_build(Tree.load(RDF), emb, d, progress=False)          # nada que hacer
        self.assertEqual(calls, [len(i1.uris)])
        rdf2 = TMP / "udc2.rdf"
        rdf2.write_text(RDF.read_text(encoding="utf-8").replace(">Spain<", ">Kingdom of Spain<"), encoding="utf-8")
        t2 = Tree.load(rdf2)
        i2 = UDCIndex.load_or_build(t2, emb, d, progress=False)
        self.assertEqual(calls[-1], sum(1 for n in t2.indexable() if "Kingdom of Spain" in t2.node_text(n)))
        self.assertLess(calls[-1], len(i2.uris))                                # solo lo que cambió
        u = next(n.uri for n in t2.indexable() if n.notation == "94")
        np.testing.assert_allclose(i2.emb[i2.pos[u]], i1.emb[i1.pos[u]])        # reutilizado tal cual
        self.assertIn("texts", json.loads((d / "dummy" / "meta.json").read_text(encoding="utf-8")))

    def test_lang_any(self):
        for iso, code in (("es", "=134.2"), ("en", "=111")):
            self.assertEqual(aux.lang_aux(iso, 0.9, self.tree)["code"], code)
        self.assertIsNone(aux.lang_aux("zxx", 0.9, self.tree))

    def test_time_multilingual(self):
        for txt in ("Histoire de la France au XIXe siècle", "Deutschland im 19. Jahrhundert",
                    "Storia d'Italia nel XIX secolo", "História do Brasil no século XIX",
                    "Spain in the 19th century", "Россия в XIX веке"):
            r = aux.time_aux(txt + ". " + txt, self.tree)
            self.assertIsNotNone(r, txt)
            self.assertEqual(r["code"], '"18"', txt)

    def test_full_suggestion(self):
        views = {"front": "A history of Spain in the nineteenth century: monarchy and revolutions. History",
                 "toc": "", "body": "", "tail": ""}
        ctx = {"item_type": "book", "lang": ("es", 0.9), "title": "Historia de España en el siglo XIX",
               "abstract": "Historia de España desde 1808 hasta 1898", "tags": ""}
        r = self.clf().suggest(views, ctx)
        s = r["suggestions"][0]
        self.assertEqual(s["main"][0]["code"], "94")
        for piece in ("(460)", '"18"', "=134.2"):
            self.assertIn(piece, s["udc"])
        self.assertEqual(validate(s["udc"], self.tree), [])
        self.assertLessEqual(len(r["suggestions"]), 3)
        self.assertTrue(all(not self.tree.is_related(self.tree.get(a["main"][0]["code"]), self.tree.get(b["main"][0]["code"]))
                            for i, a in enumerate(r["suggestions"]) for b in r["suggestions"][i + 1:]))

    def test_official_aux_type(self):
        """udcx:auxType (UDC Online) decide entre principal y especial; sin la marca manda la notación."""
        extra = [("004.052", "Fault tolerance", "004"), ("53-1", "Hypothetical special-looking class", "53")]
        plain, marked = TMP / "aux_plain.rdf", TMP / "aux_marked.rdf"
        plain.write_text(rdf_xml(extra), encoding="utf-8")
        marked.write_text(rdf_xml(extra, aux={"004.052": "special", "-05": "common"}), encoding="utf-8")
        t0, t1 = Tree.load(plain), Tree.load(marked)
        self.assertFalse(t0.official_aux)
        self.assertEqual((t0.get("004.052").kind, t0.get("53-1").kind), ("main", "special"))
        self.assertTrue(t1.official_aux)
        self.assertEqual((t1.get("004.052").kind, t1.get("53-1").kind), ("special", "main"))
        self.assertEqual(t1.get("-05").kind, "common")      # las tablas comunes conservan su tipo fino
        self.assertEqual(t1.get("(460)").kind, "place")

    def test_see_also_links(self):
        t = self.tree
        self.assertEqual([n.notation for n in t.see_also(t.get("903.26"))], ["2-533"])
        self.assertEqual([n.notation for n in t.see_also(t.get("2-533"))], ["903.26"])   # sentido inverso
        self.assertEqual([n.notation for n in t.see_also(t.get("681.3"))], ["004"])
        self.assertEqual(t.get("2-533").kind, "special")
        self.assertEqual(t.stats()["con_see_also"], 4)

    def test_see_also_candidates(self):
        """Con un haz estrecho, 681.3 (otra rama) solo entra como candidata por el "See also" de 004."""
        views = {"front": "Computer science and technology. Computing. Data processing", "toc": "", "body": "", "tail": ""}
        old = (config.K_FLAT, config.BEAM_WIDTH, config.SEE_ALSO_FROM)
        try:
            config.K_FLAT, config.BEAM_WIDTH = 1, 1
            config.SEE_ALSO_FROM = 0
            r0 = self.clf().suggest(views, {})
            self.assertNotIn("681.3", [c["code"] for c in r0["_candidates"]])
            config.SEE_ALSO_FROM = 10
            r1 = self.clf().suggest(views, {})
            cand = {c["code"]: c["feats"] for c in r1["_candidates"]}
            self.assertIn("681.3", cand)
            self.assertEqual(cand["681.3"]["see_also"], 1.0)
            self.assertEqual(cand["004"]["see_also"], 0.0)
            s = r1["suggestions"][0]
            self.assertEqual(s["main"][0]["code"], "004")            # no desplaza a la principal
            self.assertEqual([x["code"] for x in s["ver_tambien"]], ["681.3"])
            self.assertIsNone(s["explain"]["via_see_also"])
            alt = [x for x in r1["suggestions"] if x["main"][0]["code"] == "681.3"]
            if alt:
                self.assertTrue(alt[0]["explain"]["via_see_also"].startswith("004 "))
        finally:
            config.K_FLAT, config.BEAM_WIDTH, config.SEE_ALSO_FROM = old

    def test_see_also_list_includes_aux(self):
        """Un auxiliar especial enlazado (2-533) no compite como candidato, pero sí se muestra en ver_tambien."""
        c = self.clf()
        t = self.tree
        sim_of = lambda n: 0.5
        self.assertEqual([x["code"] for x in c._see_also_list(t.get("903.26"), sim_of)], ["2-533"])
        self.assertEqual(c._see_also_candidates({t.get("903.26").uri}, sim_of), {})
        via = c._see_also_candidates({t.get("004").uri}, sim_of)
        self.assertEqual([t.nodes[u].notation for u in via], ["681.3"])

    def test_cancelled(self):
        t = self.tree
        self.assertIsNone(t.get("568.1"))                       # no es un nodo del árbol
        self.assertEqual(t.cancellation("568.1")["replaced_by"], ["53"])
        self.assertIsNone(t.cancellation("94"))                 # reutilizada: hoy es una clase válida
        self.assertEqual(t.stats()["notaciones_canceladas"], 3)
        issues = validate("568.1", t)
        self.assertTrue(any(lv == "error" and "cancelada" in msg and "53" in msg for lv, msg in issues), issues)
        issues = validate("94(1-73)", t)
        self.assertTrue(any(lv == "warning" and "(1-73)" in msg and "cancelada" in msg for lv, msg in issues), issues)
        self.assertEqual(validate("94", t), [])

    def test_example_nodes(self):
        t = self.tree
        host = t.get("330.322")
        self.assertEqual(len(host.examples), 7)
        # el anfitrión solo lleva los ejemplos que no son nodo propio (la combinación con ':')
        self.assertIn("History of investments", t.node_text(host))
        self.assertNotIn("Net investment", t.node_text(host))
        self.assertIn("Capital formation > Investment theory > Volume of investment > Net investment",
                      t.node_text(t.get("330.322.014.3")))
        made = sorted(n.notation for n in t.nodes.values() if n.origin == "example")
        self.assertEqual(made, ["330.322.01", "330.322.011", "330.322.014", "330.322.014.3",
                                "330.322.014.4", "330.322.014.6"])   # sin "330.322:94"
        net = t.get("330.322.014.3")
        self.assertEqual(t.nodes[net.parent].notation, "330.322.014")
        self.assertEqual(t.nodes[t.get("330.322.014").parent].notation, "330.322.01")
        self.assertEqual(net.host, host.uri)
        self.assertEqual(net.kind, "main")
        self.assertEqual(validate("330.322.014.3", t), [])

    def test_example_suggestion(self):
        views = {"front": "Net investment", "toc": "", "body": "", "tail": ""}
        r = self.clf().suggest(views, {"title_only": True})
        s = r["suggestions"][0]
        self.assertEqual(s["main"][0]["code"], "330.322.014.3")
        self.assertEqual(s["main"][0]["origin"], "example")
        self.assertTrue(s["explain"]["origen"].startswith("ejemplo de combinación de 330.322"))
        self.assertIn("330.322 Investments. Capital formation", s["explain"]["retroceder_a"])
        old = config.EXAMPLE_MARGIN
        config.EXAMPLE_MARGIN = 9.0   # con un margen imposible nunca se propone un ejemplo
        try:
            r = self.clf().suggest(views, {"title_only": True})
            self.assertTrue(all(x["main"][0]["origin"] == "class" for x in r["suggestions"]))
        finally:
            config.EXAMPLE_MARGIN = old

    def test_empty_doc(self):
        r = self.clf().suggest({"front": "", "toc": "", "body": "", "tail": ""}, {})
        self.assertTrue(r["low_confidence"]); self.assertEqual(r["suggestions"], [])

    def test_feedback_and_reranker(self):
        fb = Feedback(TMP / "fb2.db")
        config.RERANKER_PATH = TMP / "rr.pkl"
        c = self.clf(feedback=fb)
        rng = np.random.default_rng(0)
        topics = [("music score for piano concerto symphony", "78"), ("mathematics algebra theorem proof", "51"),
                  ("law jurisprudence court legal", "34"), ("physics quantum energy mechanics", "53")]
        for i in range(40):
            text, code = topics[i % 4]
            views = {"front": text + f" doc{i}", "toc": "", "body": "", "tail": ""}
            r = c.suggest(views, {}, sha=f"s{i}")
            fb.add(f"s{i}", f"f{i}.pdf", "t", np.frombuffer(__import__("base64").b64decode(r["_doc_embedding"]), dtype=np.float32),
                   code, [code], {}, r["_candidates"], [s["udc"] for s in r["suggestions"]], 0)
        info = fb.train_reranker()
        self.assertTrue(info["trained"], info)
        rr = Reranker.load()
        self.assertIsNotNone(rr)
        r = self.clf(feedback=fb, reranker=rr).suggest({"front": "algebra theorem proof mathematics", "toc": "", "body": "", "tail": ""}, {})
        self.assertEqual(r["mode"], "reranker"); self.assertEqual(r["suggestions"][0]["main"][0]["code"], "51")
        self.assertGreater(r["neighbors_used"], 0)

    def test_evaluate_cancelled_gold(self):
        """Gold con una clase cancelada de un solo reemplazo: acertar el reemplazo cuenta en las métricas aparte."""
        res = [{"file": "c.pdf", "fields": {}, "item_type": {"value": "book"},
                "classification": {"suggestions": [{"udc": "53"}]}}]
        m = evaluate(res, {"c.pdf": {"file": "c.pdf", "udc": "568.1"}}, self.tree)
        self.assertEqual(m["clase_principal_top1"], 0.0)
        self.assertEqual(m["clase_principal_top1_con_reemplazos"], 1.0)
        self.assertEqual(m["gold_con_notaciones_canceladas"], 1)

    def test_evaluate(self):
        r = self.clf().suggest({"front": "history of Spain revolutions", "toc": "", "body": "", "tail": ""}, {"lang": ("es", .9), "item_type": "book"})
        res = [{"file": "/a/x.pdf", "classification": r, "fields": {"title": {"value": "T"}}, "item_type": {"value": "book"}}]
        m = evaluate(res, {"x.pdf": {"file": "x.pdf", "udc": "94(460)", "title": "T"}}, self.tree)
        self.assertEqual(m["documentos_evaluados"], 1); self.assertEqual(m["clase_principal_top1"], 1.0)
        self.assertIn("nivel_1", m["acierto_por_nivel"])


if __name__ == "__main__":
    unittest.main()
