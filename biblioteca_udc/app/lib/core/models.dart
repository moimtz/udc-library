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

double? _d(dynamic v) => (v as num?)?.toDouble();

/// Where a value came from. 'manual' = typed by a person; anything else is automatic.
const manualSource = 'manual';

/// One field value with its provenance (item_fields row).
class FieldValue {
  final String value;
  final String source;
  final double? confidence;
  final bool confirmed;
  const FieldValue(this.value, {this.source = manualSource, this.confidence, this.confirmed = true});

  factory FieldValue.fromJson(dynamic j) {
    if (j is Map) {
      return FieldValue(_s(j['value']),
          source: _s(j['source']).isEmpty ? manualSource : _s(j['source']),
          confidence: _d(j['confidence']),
          confirmed: j['confirmed'] == true);
    }
    return FieldValue(_s(j));
  }

  bool get isAutomatic => source != manualSource;

  Map<String, dynamic> toJson() =>
      {'value': value, 'source': source, if (confidence != null) 'confidence': confidence};
}

class Creator {
  String creatorType;
  String firstName;
  String lastName;
  int fieldMode; // 0 = last + first, 1 = one field (institutions)
  String source;
  double? confidence;
  bool confirmed;
  Creator({
    this.creatorType = 'author',
    this.firstName = '',
    this.lastName = '',
    this.fieldMode = 0,
    this.source = manualSource,
    this.confidence,
    this.confirmed = true,
  });

  factory Creator.fromJson(Map<String, dynamic> j) => Creator(
        creatorType: _s(j['creator_type']).isEmpty ? 'author' : _s(j['creator_type']),
        firstName: _s(j['first_name']),
        lastName: _s(j['last_name']),
        fieldMode: (j['field_mode'] as num?)?.toInt() ?? 0,
        source: _s(j['source']).isEmpty ? manualSource : _s(j['source']),
        confidence: _d(j['confidence']),
        confirmed: j['confirmed'] == true,
      );

  Map<String, dynamic> toJson() => {
        'creator_type': creatorType,
        'first_name': firstName,
        'last_name': lastName,
        'field_mode': fieldMode,
        'source': source,
        if (confidence != null) 'confidence': confidence,
      };
}

/// A UDC notation of an item (item_udc row).
class UdcValue {
  final String notation;
  final String source;
  final double? confidence;
  final bool confirmed;
  const UdcValue(this.notation, {this.source = manualSource, this.confidence, this.confirmed = true});
  factory UdcValue.fromJson(Map<String, dynamic> j) => UdcValue(_s(j['notation']),
      source: _s(j['source']).isEmpty ? manualSource : _s(j['source']),
      confidence: _d(j['confidence']),
      confirmed: j['confirmed'] == true);
  Map<String, dynamic> toJson() =>
      {'notation': notation, 'source': source, if (confidence != null) 'confidence': confidence};
}

class TagValue {
  final String name;
  final String source;
  const TagValue(this.name, {this.source = manualSource});
  factory TagValue.fromJson(dynamic j) => j is Map
      ? TagValue(_s(j['name']), source: _s(j['source']).isEmpty ? manualSource : _s(j['source']))
      : TagValue(_s(j));
  Map<String, dynamic> toJson() => {'name': name, 'source': source};
}

class Attachment {
  final int id;
  final String role; // main | supplementary
  final String label;
  final int position;
  final String filename;
  final String sha256;
  final int size;
  final String mime;
  final int? pages;
  final int? coverPage;
  final String? deletedAt;
  Attachment.fromJson(Map<String, dynamic> j)
      : id = (j['id'] as num).toInt(),
        role = _s(j['role']),
        label = _s(j['label']),
        position = (j['position'] as num?)?.toInt() ?? 0,
        filename = _s(j['filename']),
        sha256 = _s(j['sha256']),
        size = (j['size'] as num?)?.toInt() ?? 0,
        mime = _s(j['mime']),
        pages = (j['pages'] as num?)?.toInt(),
        coverPage = (j['cover_page'] as num?)?.toInt(),
        deletedAt = j['deleted_at'] as String?;

  bool get isMain => role == 'main';
}

class ItemNote {
  final int id;
  final String body;
  final String modifiedAt;
  ItemNote.fromJson(Map<String, dynamic> j)
      : id = (j['id'] as num).toInt(),
        body = _s(j['body']),
        modifiedAt = _s(j['modified_at']);
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
  final Map<String, FieldValue> fields;
  final List<Creator> creators;
  final List<TagValue> tags;
  final List<UdcValue> udc;
  final List<Attachment> attachments;
  final List<ItemNote> notes;
  final String addedAt;
  final String? deletedAt;
  final String creatorsText;
  final String udcText;
  final Map<String, Spans> matches;

  Item.fromJson(Map<String, dynamic> j)
      : raw = j,
        id = (j['id'] as num).toInt(),
        citekey = _s(j['citekey']),
        itemType = _s(j['item_type']),
        title = _s(j['title']),
        year = (j['year'] as num?)?.toInt(),
        language = _s(j['language']),
        fields = {
          for (final e in ((j['fields'] as Map?) ?? {}).entries) e.key.toString(): FieldValue.fromJson(e.value)
        },
        creators = [
          for (final e in (j['creators'] as List?) ?? []) Creator.fromJson(Map<String, dynamic>.from(e as Map))
        ],
        tags = [for (final e in (j['tags'] as List?) ?? []) TagValue.fromJson(e)],
        udc = [for (final e in (j['udc'] as List?) ?? []) UdcValue.fromJson(Map<String, dynamic>.from(e as Map))],
        attachments = [
          for (final e in (j['attachments'] as List?) ?? []) Attachment.fromJson(Map<String, dynamic>.from(e as Map))
        ],
        notes = [for (final e in (j['notes'] as List?) ?? []) ItemNote.fromJson(Map<String, dynamic>.from(e as Map))],
        addedAt = _s(j['added_at']),
        deletedAt = j['deleted_at'] as String?,
        creatorsText = _s(j['creators_text']),
        udcText = _s(j['udc_text']),
        matches = _parseMatches(j['matches']);

  /// Coherence warnings between the type and the UDC form (full item only; GET /api/items/{id}).
  List<String> get warnings => [
        for (final w in (raw['warnings'] as List?) ?? const []) _s((w as Map)['message'])
      ];

  Attachment? get main {
    for (final a in attachments) {
      if (a.isMain) return a;
    }
    return null;
  }

  /// Supplementary files not in the trash, in their order.
  List<Attachment> get supplementary =>
      [for (final a in attachments) if (!a.isMain && a.deletedAt == null) a]
        ..sort((a, b) => a.position.compareTo(b.position));

  // main file shortcuts (cache, list rows)
  String get filename => main?.filename ?? '';
  String get sha256 => main?.sha256 ?? '';
  int get size => main?.size ?? 0;
  int? get pages => main?.pages;
  int get coverPage => main?.coverPage ?? 1;

  String value(String field) => fields[field]?.value ?? '';

  /// Values written by an automatic process that no person has confirmed yet.
  bool get hasUnconfirmed =>
      fields.values.any((v) => !v.confirmed) || creators.any((c) => !c.confirmed) || udc.any((u) => !u.confirmed);

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
  final String code;
  final String label;
  final String kind; // text | longtext | date | url
  final String help;
  final String? base; // base field when this is a variant (university -> publisher)
  final bool hidden;
  final bool obsolete;
  const FieldDef(this.code, this.label, this.kind,
      {this.help = '', this.base, this.hidden = false, this.obsolete = false});

  factory FieldDef.fromJson(Map<String, dynamic> j) => FieldDef(_s(j['code']), _s(j['label']), _s(j['kind']),
      help: _s(j['help']), base: j['base'] as String?, hidden: j['hidden'] == true, obsolete: j['obsolete'] == true);
}

class CreatorTypeDef {
  final String code;
  final String label;
  final bool primary;
  final String help;
  const CreatorTypeDef(this.code, this.label, {this.primary = false, this.help = ''});
  factory CreatorTypeDef.fromJson(Map<String, dynamic> j) =>
      CreatorTypeDef(_s(j['code']), _s(j['label']), primary: j['primary'] == true, help: _s(j['help']));
}

class TypeDef {
  final String code;
  final String label;
  final String help;
  final bool enabled;
  final List<FieldDef> fields; // Zotero's form order
  final List<CreatorTypeDef> creatorTypes;
  const TypeDef(this.code, this.label, this.fields, this.creatorTypes, {this.help = '', this.enabled = true});

  factory TypeDef.fromJson(Map<String, dynamic> j) => TypeDef(
        _s(j['code']),
        _s(j['label']),
        [for (final f in (j['fields'] as List? ?? [])) FieldDef.fromJson(Map<String, dynamic>.from(f as Map))],
        [
          for (final c in (j['creator_types'] as List? ?? []))
            CreatorTypeDef.fromJson(Map<String, dynamic>.from(c as Map))
        ],
        help: _s(j['help']),
        enabled: j['enabled'] == true,
      );

  /// The type's own field for a base field: thesis + 'publisher' -> 'university'.
  String? fieldFor(String base) {
    for (final f in fields) {
      if (f.code == base && f.base == null) return f.code;
    }
    for (final f in fields) {
      if (f.base == base) return f.code;
    }
    return null;
  }

  FieldDef? field(String code) {
    for (final f in fields) {
      if (f.code == code) return f;
    }
    return null;
  }

  String get titleField => fieldFor('title') ?? 'title';

  String get primaryCreator {
    for (final c in creatorTypes) {
      if (c.primary) return c.code;
    }
    return creatorTypes.isEmpty ? 'author' : creatorTypes.first.code;
  }

  bool allowsCreator(String code) => creatorTypes.any((c) => c.code == code);
}

class SchemaInfo {
  final List<TypeDef> types;
  SchemaInfo(this.types);

  factory SchemaInfo.fromJson(Map<String, dynamic> j) =>
      SchemaInfo([for (final t in (j['types'] as List)) TypeDef.fromJson(Map<String, dynamic>.from(t as Map))]);

  factory SchemaInfo.empty() => SchemaInfo([]);

  /// Types that can be chosen for a new item, alphabetical (as in Zotero's menu).
  List<TypeDef> get enabledTypes =>
      [for (final t in types) if (t.enabled) t]..sort((a, b) => a.label.compareTo(b.label));

  TypeDef? type(String code) {
    for (final t in types) {
      if (t.code == code) return t;
    }
    return null;
  }

  String typeLabel(String code) => type(code)?.label ?? code;

  String fieldLabel(String code) {
    for (final t in types) {
      final f = t.field(code);
      if (f != null) return f.label;
    }
    return code;
  }

  String creatorLabel(String code) {
    for (final t in types) {
      for (final c in t.creatorTypes) {
        if (c.code == code) return c.label;
      }
    }
    return code;
  }

  /// Fields offered by the search box: a base field stands for its variants (Publisher also finds
  /// University, Label, Institution...). Only fields of enabled types; hidden ones are left out.
  List<(String, String)> get searchFields {
    final seen = <String, String>{};
    for (final t in enabledTypes) {
      for (final f in t.fields) {
        if (f.hidden) continue;
        final code = f.base ?? f.code;
        seen.putIfAbsent(code, () {
          final l = fieldLabel(code); // 'authority' and 'medium' are only base fields: use the variant's label
          return l == code ? f.label : l;
        });
      }
    }
    return [for (final e in seen.entries) (e.key, e.value)]..sort((a, b) => a.$2.compareTo(b.$2));
  }
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
  final Map<String, String> including; // "Including ..." shown after the label, per language
  UdcNode(this.code, this.parent, this.labels, this.ord, this.count, this.direct,
      {this.type, this.hasInfo = false, this.including = const {}});

  factory UdcNode.fromJson(Map<String, dynamic> j) => UdcNode(
        _s(j['code']),
        j['parent'] as String?,
        {for (final e in (j['labels'] as Map).entries) e.key.toString(): _s(e.value)},
        (j['ord'] as num).toInt(),
        (j['count'] as num?)?.toInt() ?? 0,
        (j['direct'] as num?)?.toInt() ?? 0,
        type: j['type'] as String?,
        hasInfo: j['has_info'] == true,
        including: _labels(j['incl']),
      );

  bool get isInfo => type == 'info';
  bool get isHeading => type == 'heading';

  /// Headings ('heading-1'...) have no notation to show.
  String get displayCode => isHeading ? '' : code;

  String label(String lang) =>
      labels[lang] ?? labels['en'] ?? (labels.isEmpty ? '' : labels.values.first);

  String includingIn(String lang) => _pickLang(including, lang);
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
  final Map<String, List<String>> info; // information note
  final Map<String, List<String>> including;
  final Map<String, List<UdcExample>> examples;
  final List<UdcRef> related;
  final List<UdcCancelledRef> replaces; // cancelled classes now classed here
  final List<UdcCancellation> earlier; // earlier meanings of this same notation (cancelled, then reused)

  UdcNodeInfo(this.code, this.labels, this.type, this.path, this.scope, this.app, this.info, this.including,
      this.examples, this.related, this.replaces, this.earlier);

  factory UdcNodeInfo.fromJson(Map<String, dynamic> j) => UdcNodeInfo(
        _s(j['code']),
        _labels(j['labels']),
        j['type'] as String?,
        [for (final p in (j['path'] as List? ?? const [])) UdcRef.fromJson(Map<String, dynamic>.from(p as Map))],
        _texts(j['scope']),
        _texts(j['app']),
        _texts(j['info']),
        _texts(j['including']),
        {
          for (final e in ((j['examples'] ?? const {}) as Map).entries)
            e.key.toString(): [
              for (final x in (e.value as List))
                UdcExample(_s((x as Map)['code']), _s(x['label']))
            ]
        },
        [for (final r in (j['related'] as List? ?? const [])) UdcRef.fromJson(Map<String, dynamic>.from(r as Map))],
        [
          for (final r in (j['replaces'] as List? ?? const []))
            UdcCancelledRef.fromJson(Map<String, dynamic>.from(r as Map))
        ],
        [
          for (final r in (j['earlier'] as List? ?? const []))
            UdcCancellation.fromJson(Map<String, dynamic>.from(r as Map))
        ],
      );

  String label(String lang) => _pickLang(labels, lang);

  /// Texts in the chosen language, falling back to English, then to any language.
  static List<T> inLang<T>(Map<String, List<T>> m, String lang) =>
      m[lang] ?? m['en'] ?? (m.isEmpty ? <T>[] : m.values.first);

  bool get isEmpty =>
      scope.isEmpty && app.isEmpty && info.isEmpty && including.isEmpty && examples.isEmpty && related.isEmpty &&
      replaces.isEmpty && earlier.isEmpty;

  bool get hasNotes =>
      scope.isNotEmpty || app.isNotEmpty || info.isNotEmpty || including.isNotEmpty || examples.isNotEmpty ||
      related.isNotEmpty;
}

/// "[2011, E&C33]" (the E&C issue is missing in a few records).
String cancelledWhen(int? year, String? ec) =>
    '[${year ?? '?'}${(ec ?? '').isEmpty ? '' : ', $ec'}]';

/// A cancelled class that points to the current one (GET /api/udc/node -> replaces).
class UdcCancelledRef {
  final String code;
  final int? year;
  final String ec;
  final String label;
  UdcCancelledRef(this.code, this.year, this.ec, this.label);
  factory UdcCancelledRef.fromJson(Map<String, dynamic> j) =>
      UdcCancelledRef(_s(j['code']), (j['year'] as num?)?.toInt(), _s(j['ec']), _s(j['label']));
}

class UdcReplacement {
  final String code;
  final Map<String, String> labels;
  final bool exists; // false = not a class of the current tree (e.g. a combination such as 94(4/9))
  UdcReplacement(this.code, this.labels, this.exists);
  String label(String lang) => _pickLang(labels, lang);
}

/// One cancellation of a notation: when, old label and the classes that replace it.
class UdcCancellation {
  final String code;
  final int? year;
  final String ec;
  final String label;
  final String including;
  final String note; // e.g. 'No replacement'
  final List<UdcReplacement> replacedBy;
  UdcCancellation(this.code, this.year, this.ec, this.label, this.including, this.note, this.replacedBy);

  factory UdcCancellation.fromJson(Map<String, dynamic> j) => UdcCancellation(
        _s(j['code']),
        (j['year'] as num?)?.toInt(),
        _s(j['ec']),
        _s(j['label']),
        _s(j['including']),
        _s(j['note']),
        [
          for (final r in (j['replaced_by'] as List? ?? const []))
            UdcReplacement(_s((r as Map)['code']), _labels(r['labels']), r['exists'] == true)
        ],
      );

  String get when => cancelledWhen(year, ec);
}

/// Compact entry of GET /api/udc/cancelled-index (cancelled notations not in the current tree).
class CancelledEntry {
  final String code;
  final int? year;
  final String label;
  final List<String> replacedBy;
  CancelledEntry(this.code, this.year, this.label, this.replacedBy);
  factory CancelledEntry.fromJson(List j) => CancelledEntry(_s(j[0]), (j[1] as num?)?.toInt(), _s(j[2]),
      [for (final t in (j[3] as List? ?? const [])) _s(t)]);
}

/// A cancelled notation found inside a UDC string (GET /api/udc/check).
class UdcCancelledHit {
  final int start;
  final int end;
  final String component;
  final List<UdcCancellation> cancellations;
  UdcCancelledHit(this.start, this.end, this.component, this.cancellations);
  factory UdcCancelledHit.fromJson(Map<String, dynamic> j) => UdcCancelledHit(
        (j['start'] as num).toInt(),
        (j['end'] as num).toInt(),
        _s(j['component']),
        [
          for (final c in (j['cancelled'] as List? ?? const []))
            UdcCancellation.fromJson(Map<String, dynamic>.from(c as Map))
        ],
      );
}

/// GET /api/udc/check: cancelled notations, and type <-> UDC form warnings when the type was sent.
class UdcCheckResult {
  final List<UdcCancelledHit> cancelled;
  final List<String> form;
  UdcCheckResult(this.cancelled, this.form);
  factory UdcCheckResult.fromJson(Map<String, dynamic> j) => UdcCheckResult(
        [
          for (final h in (j['cancelled'] as List? ?? const []))
            UdcCancelledHit.fromJson(Map<String, dynamic>.from(h as Map))
        ],
        [for (final w in (j['form'] as List? ?? const [])) _s((w as Map)['message'])], // older servers: none
      );
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
      if (foldText(n.displayCode).startsWith(f) ||
          foldText(n.label(lang)).contains(f) ||
          foldText(n.includingIn(lang)).contains(f)) {
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
