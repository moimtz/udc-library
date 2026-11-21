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
        self.assertEqual(compose([{"code": "94"}], {"lang": "=134.2", "place": "(460)"}), "94=134.2(460)")


class TestMetadata(unittest.TestCase):
    def test_identifiers(self):
        ids = md.find_identifiers("see 10.1000/xyz123. ISBN 978-0-306-40615-7 arXiv:2101.01234v2 ISSN 1234-5679")
        self.assertEqual(ids["doi"], "10.1000/xyz123"); self.assertEqual(ids["isbn"], "978-0-306-40615-7")
        self.assertEqual(ids["arxiv"], "2101.01234"); self.assertNotIn("isbn", md.find_identifiers("ISBN 978-0-306-40615-8"))

    def test_dates_and_names(self):
        self.assertEqual(md.norm_date("Filed: Mar. 5, 2019"), "2019-03-05")
        self.assertEqual(md.norm_date("12 de mayo de 2001"), "2001-05-12")
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
        self.assertEqual(aux.time_aux("La España del siglo XIX y la crisis de 1808", t)["code"], '"18"')
        self.assertIsNone(aux.time_aux("Un texto sin fechas", t))

    def test_place(self):
        pf = aux.PlaceFinder(self.tree)
        self.assertEqual(pf.find([("Historia de España", 5.0)])["code"], "(460)")
        self.assertIsNone(pf.find([("Un libro sobre cosas", 5.0)]))

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

    def test_evaluate(self):
        r = self.clf().suggest({"front": "history of Spain revolutions", "toc": "", "body": "", "tail": ""}, {"lang": ("es", .9), "item_type": "book"})
        res = [{"file": "/a/x.pdf", "classification": r, "fields": {"title": {"value": "T"}}, "item_type": {"value": "book"}}]
        m = evaluate(res, {"x.pdf": {"file": "x.pdf", "udc": "94(460)", "title": "T"}}, self.tree)
        self.assertEqual(m["documentos_evaluados"], 1); self.assertEqual(m["clase_principal_top1"], 1.0)
        self.assertIn("nivel_1", m["acierto_por_nivel"])


if __name__ == "__main__":
    unittest.main()
