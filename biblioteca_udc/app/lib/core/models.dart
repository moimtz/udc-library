/// Plain data classes shared by the whole app.

String _s(dynamic v) => v == null ? '' : v.toString();

/// Lower-case + accent-free text, used for filtering (not for display).
String foldText(String s) {
  const from = 'áàäâãéèëêíìïîóòöôõúùüûñçÁÀÄÂÃÉÈËÊÍÌÏÎÓÒÖÔÕÚÙÜÛÑÇ';
  const to = 'aaaaaeeeeiiiiooooouuuuncAAAAAEEEEIIIIOOOOOUUUUNC';
  final b = StringBuffer();
  for (final r in s.runes) {
    final ch = String.fromCharCode(r);
    final i = from.indexOf(ch);
    b.write(i >= 0 ? to[i] : ch);
  }
  return b.toString().toLowerCase();
}

String formatBytes(int n) {
  if (n < 1024) return '$n B';
  const units = ['KB', 'MB', 'GB', 'TB'];
  double v = n / 1024;
  int u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  return '${v.toStringAsFixed(v >= 100 ? 0 : 1)} ${units[u]}';
}

class Creator {
  String role;
  String first;
  String last;
  Creator({this.role = 'author', this.first = '', this.last = ''});

  factory Creator.fromJson(Map<String, dynamic> j) => Creator(
        role: _s(j['role']).isEmpty ? 'author' : _s(j['role']),
        first: _s(j['first']),
        last: _s(j['last']),
      );

  Map<String, dynamic> toJson() => {'role': role, 'first': first, 'last': last};
}

typedef Spans = List<List<int>>;

class Item {
  final Map<String, dynamic> raw;
  final int id;
  final String citekey;
  final String itemType;
  final String title;
  final int? year;
  final String language;
  final String udc;
  final List<Creator> creators;
  final Map<String, String> data;
  final String filename;
  final String sha256;
  final int size;
  final int? pages;
  final int coverPage;
  final String addedAt;
  final String? deletedAt;
  final String creatorsText;
  final Map<String, Spans> matches;

  Item.fromJson(Map<String, dynamic> j)
      : raw = j,
        id = (j['id'] as num).toInt(),
        citekey = _s(j['citekey']),
        itemType = _s(j['item_type']),
        title = _s(j['title']),
        year = (j['year'] as num?)?.toInt(),
        language = _s(j['language']),
        udc = _s(j['udc']),
        creators = ((j['creators'] as List?) ?? [])
            .map((e) => Creator.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList(),
        data = {
          for (final e in ((j['data'] as Map?) ?? {}).entries)
            e.key.toString(): _s(e.value)
        },
        filename = _s(j['filename']),
        sha256 = _s(j['sha256']),
        size = (j['size'] as num?)?.toInt() ?? 0,
        pages = (j['pages'] as num?)?.toInt(),
        coverPage = (j['cover_page'] as num?)?.toInt() ?? 1,
        addedAt = _s(j['added_at']),
        deletedAt = j['deleted_at'] as String?,
        creatorsText = _s(j['creators_text']),
        matches = _parseMatches(j['matches']);

  static Map<String, Spans> _parseMatches(dynamic m) {
    final out = <String, Spans>{};
    if (m is Map) {
      m.forEach((k, v) {
        out[k.toString()] = (v as List)
            .map((e) => (e as List).map((n) => (n as num).toInt()).toList())
            .toList();
      });
    }
    return out;
  }
}

class FieldDef {
  final String key;
  final String label;
  final String kind;
  const FieldDef(this.key, this.label, this.kind);
}

class TypeDef {
  final String code;
  final String label;
  final List<String> fields;
  const TypeDef(this.code, this.label, this.fields);
}

class SchemaInfo {
  final List<TypeDef> types;
  final Map<String, FieldDef> fields;
  final List<String> roles;
  SchemaInfo(this.types, this.fields, this.roles);

  factory SchemaInfo.fromJson(Map<String, dynamic> j) => SchemaInfo(
        (j['types'] as List)
            .map((t) => TypeDef(_s(t['code']), _s(t['label']),
                (t['fields'] as List).map((e) => e.toString()).toList()))
            .toList(),
        {
          for (final e in (j['fields'] as Map).entries)
            e.key.toString(): FieldDef(
                e.key.toString(), _s(e.value['label']), _s(e.value['kind']))
        },
        (j['roles'] as List).map((e) => e.toString()).toList(),
      );

  factory SchemaInfo.empty() =>
      SchemaInfo([const TypeDef('other', 'Other', [])], {}, ['author']);

  TypeDef? type(String code) {
    for (final t in types) {
      if (t.code == code) return t;
    }
    return null;
  }

  String typeLabel(String code) => type(code)?.label ?? code;
}

class UdcNode {
  final String code;
  final String? parent;
  final Map<String, String> labels;
  final int ord;
  final int count;
  final int direct;
  final String? type; // null = normal class, 'heading' (group without notation), 'info' (informative)
  final bool hasInfo; // has notes for the information window
  UdcNode(this.code, this.parent, this.labels, this.ord, this.count, this.direct,
      {this.type, this.hasInfo = false});

  factory UdcNode.fromJson(Map<String, dynamic> j) => UdcNode(
        _s(j['code']),
        j['parent'] as String?,
        {for (final e in (j['labels'] as Map).entries) e.key.toString(): _s(e.value)},
        (j['ord'] as num).toInt(),
        (j['count'] as num?)?.toInt() ?? 0,
        (j['direct'] as num?)?.toInt() ?? 0,
        type: j['type'] as String?,
        hasInfo: j['has_info'] == true,
      );

  bool get isInfo => type == 'info';
  bool get isHeading => type == 'heading';

  /// Headings ('heading-1'...) have no notation to show.
  String get displayCode => isHeading ? '' : code;

  String label(String lang) =>
      labels[lang] ?? labels['en'] ?? (labels.isEmpty ? '' : labels.values.first);
}

String _pickLang(Map<String, String> labels, String lang) =>
    labels[lang] ?? labels['en'] ?? (labels.isEmpty ? '' : labels.values.first);

Map<String, String> _labels(dynamic m) =>
    {for (final e in ((m ?? const {}) as Map).entries) e.key.toString(): _s(e.value)};

/// Notes per language: {lang: [text]}.
Map<String, List<String>> _texts(dynamic m) => {
      for (final e in ((m ?? const {}) as Map).entries)
        e.key.toString(): [for (final t in (e.value as List)) _s(t)]
    };

class UdcRef {
  final String code;
  final Map<String, String> labels;
  UdcRef(this.code, this.labels);
  factory UdcRef.fromJson(Map<String, dynamic> j) => UdcRef(_s(j['code']), _labels(j['labels']));
  String label(String lang) => _pickLang(labels, lang);
}

class UdcExample {
  final String code;
  final String label;
  UdcExample(this.code, this.label);
}

/// Contents of the class information window (GET /api/udc/node).
class UdcNodeInfo {
  final String code;
  final Map<String, String> labels;
  final String? type;
  final List<UdcRef> path; // ancestors, root first
  final Map<String, List<String>> scope;
  final Map<String, List<String>> app;
  final Map<String, List<String>> including;
  final Map<String, List<UdcExample>> examples;
  final List<UdcRef> related;

  UdcNodeInfo(this.code, this.labels, this.type, this.path, this.scope, this.app, this.including,
      this.examples, this.related);

  factory UdcNodeInfo.fromJson(Map<String, dynamic> j) => UdcNodeInfo(
        _s(j['code']),
        _labels(j['labels']),
        j['type'] as String?,
        [for (final p in (j['path'] as List? ?? const [])) UdcRef.fromJson(Map<String, dynamic>.from(p as Map))],
        _texts(j['scope']),
        _texts(j['app']),
        _texts(j['including']),
        {
          for (final e in ((j['examples'] ?? const {}) as Map).entries)
            e.key.toString(): [
              for (final x in (e.value as List))
                UdcExample(_s((x as Map)['code']), _s(x['label']))
            ]
        },
        [for (final r in (j['related'] as List? ?? const [])) UdcRef.fromJson(Map<String, dynamic>.from(r as Map))],
      );

  String label(String lang) => _pickLang(labels, lang);

  /// Texts in the chosen language, falling back to English, then to any language.
  static List<T> inLang<T>(Map<String, List<T>> m, String lang) =>
      m[lang] ?? m['en'] ?? (m.isEmpty ? <T>[] : m.values.first);

  bool get isEmpty =>
      scope.isEmpty && app.isEmpty && including.isEmpty && examples.isEmpty && related.isEmpty;
}

class TreeRow {
  final UdcNode node;
  final int depth;
  final bool hasChildren;
  TreeRow(this.node, this.depth, this.hasChildren);
}

class UdcIndex {
  final Map<String, UdcNode> byCode = {};
  final Map<String?, List<UdcNode>> children = {};
  final int unclassified;

  UdcIndex(List<UdcNode> nodes, {this.unclassified = 0}) {
    final sorted = [...nodes]..sort((a, b) => a.ord.compareTo(b.ord));
    for (final n in sorted) {
      byCode[n.code] = n;
    }
    for (final n in sorted) {
      final p = (n.parent != null && byCode.containsKey(n.parent)) ? n.parent : null;
      children.putIfAbsent(p, () => []).add(n);
    }
  }

  factory UdcIndex.empty() => UdcIndex([]);

  bool get isEmpty => byCode.isEmpty;
  bool hasChildren(String code) => (children[code]?.isNotEmpty) ?? false;

  Set<String> get expandable => {
        for (final e in children.entries)
          if (e.key != null && e.value.isNotEmpty) e.key!
      };

  /// Rows to draw. With a filter, matching classes and their ancestors are
  /// shown, all open.
  List<TreeRow> rows(Set<String> expanded, {String filter = '', String lang = 'en'}) {
    final f = foldText(filter.trim());
    final Set<String>? vis = f.isEmpty ? null : _matching(f, lang);
    final out = <TreeRow>[];
    void walk(String? parent, int depth) {
      for (final n in children[parent] ?? const <UdcNode>[]) {
        if (vis != null && !vis.contains(n.code)) continue;
        final kids = hasChildren(n.code);
        out.add(TreeRow(n, depth, kids));
        final open = vis != null ? true : expanded.contains(n.code);
        if (kids && open) walk(n.code, depth + 1);
      }
    }

    walk(null, 0);
    return out;
  }

  Set<String> _matching(String f, String lang) {
    final vis = <String>{};
    for (final n in byCode.values) {
      if (foldText(n.displayCode).startsWith(f) || foldText(n.label(lang)).contains(f)) {
        String? c = n.code;
        while (c != null && vis.add(c)) {
          c = byCode[c]?.parent;
        }
      }
    }
    return vis;
  }

  /// "004.8 Artificial intelligence; 61 Medical sciences" for a UDC string.
  String describe(String udc, String lang) {
    final parts = <String>[];
    for (final p in udc.split(RegExp(r'[:+/]'))) {
      final m = RegExp(r'^\s*(\d+(?:\.\d+)*)').firstMatch(p);
      if (m == null) continue;
      String c = m.group(1)!;
      while (c.isNotEmpty && !byCode.containsKey(c)) {
        c = c.substring(0, c.length - 1);
        if (c.endsWith('.')) c = c.substring(0, c.length - 1);
      }
      if (c.isNotEmpty) parts.add('$c ${byCode[c]!.label(lang)}');
    }
    return parts.join('; ');
  }
}

class ItemsPage {
  final int total;
  final List<Item> items;
  ItemsPage(this.total, this.items);
}

class UserInfo {
  final int id;
  final String username;
  final String role;
  final bool disabled;
  UserInfo(this.id, this.username, this.role, this.disabled);

  factory UserInfo.fromJson(Map<String, dynamic> j) => UserInfo(
        (j['id'] as num).toInt(),
        _s(j['username']),
        _s(j['role']),
        j['disabled'] == true,
      );

  bool get canEdit => role == 'admin' || role == 'editor';
  bool get isAdmin => role == 'admin';
}
