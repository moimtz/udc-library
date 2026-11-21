"""UDC helpers: notation parsing, tree walking, and item <-> node links."""
import json
import re


def extract_codes(udc: str) -> list[str]:
    """Pull main-table numbers out of a (possibly compound) UDC string.

    '004.8:61' -> ['004.8', '61'];  '54/55' -> ['54', '55'];  '94(460)"19"' -> ['94'].
    Auxiliary signs such as (460) or =134.2 are kept in the stored string but do
    not place the item in the tree.
    """
    codes: list[str] = []
    for part in re.split(r"[:+/]", udc or ""):
        m = re.match(r"\s*(\d+(?:\.\d+)*)", part)
        if m:
            codes.append(m.group(1))
    return list(dict.fromkeys(codes))


def resolve_node(code: str, known: set[str]) -> str | None:
    """Longest prefix of `code` that exists in the Summary (deep numbers fall back to a parent)."""
    c = code
    while c:
        if c in known:
            return c
        c = c[:-1].rstrip(".")
    return None


def natural_key(code: str):
    return [(0, int(t), t) if t.isdigit() else (1, 0, t) for t in re.findall(r"\d+|\D+", code)]


def load_parent_map(conn) -> tuple[dict[str, str | None], dict[str, list[str]]]:
    parent: dict[str, str | None] = {}
    children: dict[str, list[str]] = {}
    for r in conn.execute("SELECT code, parent FROM udc_nodes"):
        parent[r["code"]] = r["parent"]
        if r["parent"]:
            children.setdefault(r["parent"], []).append(r["code"])
    return parent, children


def descendants(conn, code: str) -> set[str]:
    _, children = load_parent_map(conn)
    out, stack = {code}, [code]
    while stack:
        for ch in children.get(stack.pop(), []):
            if ch not in out:
                out.add(ch)
                stack.append(ch)
    return out


def set_item_udc(conn, item_id: int, udc: str) -> None:
    known = {r["code"] for r in conn.execute("SELECT code FROM udc_nodes")}
    conn.execute("DELETE FROM item_udc WHERE item_id=?", (item_id,))
    for code in extract_codes(udc):
        conn.execute("INSERT OR IGNORE INTO item_udc(item_id, code, node_code) VALUES (?,?,?)",
                     (item_id, code, resolve_node(code, known)))


def rebuild_all_item_links(conn) -> None:
    """Call after importing a new UDC file."""
    for r in conn.execute("SELECT id, udc FROM items").fetchall():
        set_item_udc(conn, r["id"], r["udc"])


def tree_payload(conn) -> list[dict]:
    """All nodes with item counts (direct and including descendants)."""
    direct: dict[str, int] = {}
    for r in conn.execute(
            "SELECT iu.node_code AS c, COUNT(DISTINCT iu.item_id) AS n FROM item_udc iu "
            "JOIN items i ON i.id = iu.item_id WHERE i.deleted_at IS NULL AND iu.node_code IS NOT NULL "
            "GROUP BY iu.node_code"):
        direct[r["c"]] = r["n"]
    parent, children = load_parent_map(conn)

    # Items can sit in several branches, so count distinct items per subtree.
    item_nodes: dict[int, set[str]] = {}
    for r in conn.execute(
            "SELECT iu.item_id AS i, iu.node_code AS c FROM item_udc iu "
            "JOIN items it ON it.id = iu.item_id WHERE it.deleted_at IS NULL AND iu.node_code IS NOT NULL"):
        item_nodes.setdefault(r["i"], set()).add(r["c"])
    total: dict[str, set[int]] = {}
    for item_id, nodes in item_nodes.items():
        for n in nodes:
            c = n
            seen = set()
            while c and c not in seen:
                seen.add(c)
                total.setdefault(c, set()).add(item_id)
                c = parent.get(c)

    out = []
    for r in conn.execute("SELECT code, parent, labels, ord, node_type, notes IS NOT NULL AS has_notes "
                          "FROM udc_nodes ORDER BY ord"):
        node = {"code": r["code"], "parent": r["parent"], "labels": json.loads(r["labels"]),
                "ord": r["ord"], "direct": direct.get(r["code"], 0),
                "count": len(total.get(r["code"], ()))}
        # only when present, to keep the payload small (the full tree has ~72,000 classes)
        if r["node_type"]:
            node["type"] = r["node_type"]
        if r["has_notes"] or r["node_type"] == "info":
            node["has_info"] = True
        out.append(node)
    return out


def node_detail(conn, code: str) -> dict | None:
    """Everything the class information window shows: labels, path, type and notes.
    Notes: scope / app / including = {lang: [text]}, examples = {lang: [{code, label}]},
    related = [{code, labels}]."""
    r = conn.execute("SELECT code, parent, labels, node_type, notes FROM udc_nodes WHERE code=?",
                     (code,)).fetchone()
    if r is None:
        return None
    notes = json.loads(r["notes"]) if r["notes"] else {}
    labels_of = {}

    def labels(c):
        if c not in labels_of:
            row = conn.execute("SELECT labels FROM udc_nodes WHERE code=?", (c,)).fetchone()
            labels_of[c] = json.loads(row["labels"]) if row else {}
        return labels_of[c]

    path, p, seen = [], r["parent"], set()
    while p and p not in seen:
        seen.add(p)
        row = conn.execute("SELECT code, parent, labels FROM udc_nodes WHERE code=?", (p,)).fetchone()
        if row is None:
            break
        path.append({"code": row["code"], "labels": json.loads(row["labels"])})
        p = row["parent"]
    return {"code": r["code"], "labels": json.loads(r["labels"]), "type": r["node_type"],
            "path": path[::-1],
            "scope": notes.get("scope", {}), "app": notes.get("app", {}),
            "including": notes.get("including", {}), "examples": notes.get("examples", {}),
            "related": [{"code": c, "labels": labels(c)} for c in notes.get("related", [])]}


SEED = {
    "0": ("Science and knowledge. Organization. Computer science. Information. Documentation. Librarianship. Institutions. Publications",
          "Generalidades. Ciencia y conocimiento. Organización. Informática. Información. Documentación. Bibliotecología. Instituciones. Publicaciones"),
    "1": ("Philosophy. Psychology", "Filosofía. Psicología"),
    "2": ("Religion. Theology", "Religión. Teología"),
    "3": ("Social sciences", "Ciencias sociales"),
    "5": ("Mathematics. Natural sciences", "Matemáticas. Ciencias naturales"),
    "6": ("Applied sciences. Medicine. Technology", "Ciencias aplicadas. Medicina. Tecnología"),
    "7": ("The arts. Recreation. Entertainment. Sport", "Arte. Recreación. Entretenimiento. Deportes"),
    "8": ("Language. Linguistics. Literature", "Lengua. Lingüística. Literatura"),
    "9": ("Geography. Biography. History", "Geografía. Biografía. Historia"),
}


def seed_minimal(conn) -> None:
    """Ten main classes so the app works before the full Summary is imported."""
    if conn.execute("SELECT 1 FROM udc_nodes LIMIT 1").fetchone():
        return
    for i, (code, (en, es)) in enumerate(SEED.items()):
        conn.execute("INSERT INTO udc_nodes(code, parent, labels, ord) VALUES (?,?,?,?)",
                     (code, None, json.dumps({"en": en, "es": es}, ensure_ascii=False), i))
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('udc_source', 'seed')")
    conn.commit()
