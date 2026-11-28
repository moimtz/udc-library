import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../widgets/compact_dropdown.dart';
import '../widgets/item_tile.dart' show UnconfirmedMark;
import '../widgets/udc_breakdown.dart';
import '../widgets/udc_builder.dart';

enum AddOutcome { added, skipped, cancelAll }

enum _Kind { info, success, error, warning }

/// "Add files": pick one or several PDFs, then one floating window per file.
Future<void> addFilesFlow(BuildContext context) async {
  final state = context.read<AppState>();
  final res = await FilePicker.platform.pickFiles(
    allowMultiple: true,
    type: FileType.custom,
    allowedExtensions: ['pdf'],
  );
  if (res == null) return;
  final files = res.files.where((f) => f.path != null).toList();
  var added = 0;
  for (var i = 0; i < files.length; i++) {
    if (!context.mounted) return;
    final r = await showDialog<Object?>(
      context: context,
      barrierDismissible: false,
      builder: (_) => ItemFormDialog(file: files[i], index: i + 1, total: files.length),
    );
    if (r == AddOutcome.added) added++;
    if (r == AddOutcome.cancelAll || r == null) break;
  }
  if (added > 0) await state.refreshAfterChange();
}

Future<void> editItemDialog(BuildContext context, Item item) async {
  final r = await showDialog<Object?>(
    context: context,
    barrierDismissible: false,
    builder: (_) => ItemFormDialog(item: item),
  );
  if (r is Item && context.mounted) {
    final s = context.read<AppState>();
    s.itemUpdated(r);
    await s.refreshAfterChange(); // the UDC tree counts may have changed
  }
}

/// One creator in the form. The source of an automatic name is kept while the name is left as it was.
class _CreatorRow {
  String creatorType;
  int fieldMode;
  final TextEditingController first;
  final TextEditingController last;
  final String source;
  final double? confidence;
  final bool confirmed;
  final String origFirst;
  final String origLast;
  _CreatorRow(this.creatorType, String f, String l,
      {this.fieldMode = 0, this.source = manualSource, this.confidence, this.confirmed = true})
      : first = TextEditingController(text: f),
        last = TextEditingController(text: l),
        origFirst = f,
        origLast = l;

  factory _CreatorRow.from(Creator c) => _CreatorRow(c.creatorType, c.firstName, c.lastName,
      fieldMode: c.fieldMode, source: c.source, confidence: c.confidence, confirmed: c.confirmed);

  bool get isEmpty => first.text.trim().isEmpty && last.text.trim().isEmpty;
  bool get unchanged => first.text.trim() == origFirst && last.text.trim() == origLast;

  Map<String, dynamic> toJson() => {
        'creator_type': creatorType,
        'field_mode': fieldMode,
        'first_name': fieldMode == 1 ? '' : first.text.trim(),
        'last_name': last.text.trim(),
        if (unchanged && source != manualSource) ...{'source': source, 'confidence': confidence},
      };

  void dispose() {
    first.dispose();
    last.dispose();
  }
}

class ItemFormDialog extends StatefulWidget {
  final PlatformFile? file; // add mode
  final Item? item; // edit mode
  final int index;
  final int total;
  const ItemFormDialog({super.key, this.file, this.item, this.index = 1, this.total = 1});

  @override
  State<ItemFormDialog> createState() => _ItemFormDialogState();
}

class _ItemFormDialogState extends State<ItemFormDialog> {
  final Map<String, TextEditingController> _fields = {};
  // Value and provenance of each field as it came from the server, the PDF or a lookup. A value the person
  // leaves as it is keeps that source when saved; an edited one becomes 'manual'.
  final Map<String, FieldValue> _prov = {};
  final List<_CreatorRow> _creators = [];
  final _udc = TextEditingController();
  final _tags = TextEditingController();
  final Map<String, UdcValue> _udcProv = {};
  final Map<String, String> _tagSources = {};
  final _page = TextEditingController(text: '1');
  String _type = 'book';

  bool get _isEdit => widget.item != null;
  String _phase = 'ready'; // uploading | ready | error
  bool _busy = false;
  String? _checkedUdc; // UDC string already checked for cancelled notations (not asked again)
  String? _checkedForm; // UDC + type + Extra whose form warnings the user accepted (not asked again)
  String? _tempId;
  int _pages = 1;
  int _coverPage = 1;
  bool _regenKey = false;
  List<Map<String, dynamic>> _dups = [];
  String _dupAction = 'check';
  int? _replaceId;

  // Classifier (Analyze): availability on the server, the running job and what it suggested.
  bool _clsAvailable = false;
  bool _clsLoading = false;
  String? _job;
  bool _typeTouched = false; // the person chose the type: the analysis keeps it
  List<Map<String, dynamic>> _udcSugg = [];
  bool _lowConfidence = false;
  final List<_Suggestion> _pending = []; // values not applied because the field already had one

  String? _bannerText;
  _Kind _bannerKind = _Kind.info;
  int _bannerId = 0;

  TextEditingController _ctl(String code) => _fields.putIfAbsent(code, () => TextEditingController());

  TypeDef? get _typeDef => context.read<AppState>().schema.type(_type);

  @override
  void initState() {
    super.initState();
    final s = context.read<AppState>();
    final enabled = s.schema.enabledTypes;
    _type = enabled.any((t) => t.code == 'book') ? 'book' : (enabled.isNotEmpty ? enabled.first.code : 'book');
    final it = widget.item;
    if (it != null) {
      _type = it.itemType;
      _setValues(it.fields);
      for (final c in it.creators) {
        _creators.add(_CreatorRow.from(c));
      }
      _setUdc(it.udc);
      _setTags(it.tags);
      _coverPage = it.coverPage;
      _pages = it.pages ?? 1;
      _page.text = '$_coverPage';
      if (it.warnings.isNotEmpty) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (mounted) _banner(it.warnings.join('\n'), _Kind.warning, seconds: 10);
        });
      }
    } else {
      _phase = 'uploading';
      WidgetsBinding.instance.addPostFrameCallback((_) => _upload());
    }
    if (_creators.isEmpty) _creators.add(_CreatorRow(_typeDef?.primaryCreator ?? 'author', '', ''));
    _checkClassifier();
  }

  @override
  void dispose() {
    for (final c in [..._fields.values, _udc, _tags, _page]) {
      c.dispose();
    }
    for (final c in _creators) {
      c.dispose();
    }
    super.dispose();
  }

  void _banner(String text, _Kind kind, {int seconds = 0}) {
    final id = ++_bannerId;
    setState(() {
      _bannerText = text;
      _bannerKind = kind;
    });
    if (seconds > 0) {
      Future.delayed(Duration(seconds: seconds), () {
        if (mounted && id == _bannerId) setState(() => _bannerText = null);
      });
    }
  }

  // ------------------------------------------------------------------ form values
  /// Replaces every field value (and its provenance).
  void _setValues(Map<String, FieldValue> values) {
    for (final c in _fields.values) {
      c.clear();
    }
    _prov.clear();
    for (final e in values.entries) {
      _ctl(e.key).text = e.value.value;
      _prov[e.key] = e.value;
    }
  }

  /// Sets some fields, keeping the others.
  void _mergeValues(Map<String, FieldValue> values) {
    for (final e in values.entries) {
      _ctl(e.key).text = e.value.value;
      _prov[e.key] = e.value;
    }
  }

  void _setCreators(List<Creator> list) {
    for (final c in _creators) {
      c.dispose();
    }
    _creators
      ..clear()
      ..addAll(list.map(_CreatorRow.from));
    if (_creators.isEmpty) _creators.add(_CreatorRow(_typeDef?.primaryCreator ?? 'author', '', ''));
  }

  void _setUdc(List<UdcValue> list) {
    _udcProv
      ..clear()
      ..addAll({for (final u in list) u.notation: u});
    _udc.text = list.map((u) => u.notation).join(' ; ');
  }

  void _setTags(List<TagValue> list) {
    _tagSources
      ..clear()
      ..addAll({for (final t in list) t.name.toLowerCase(): t.source});
    _tags.text = list.map((t) => t.name).join('; ');
  }

  void _addTags(List<TagValue> list) {
    final have = _splitTags(_tags.text);
    for (final t in list) {
      if (have.any((h) => h.toLowerCase() == t.name.toLowerCase())) continue;
      have.add(t.name);
      _tagSources[t.name.toLowerCase()] = t.source;
    }
    _tags.text = have.join('; ');
  }

  static List<String> _splitTags(String s) =>
      [for (final t in s.split(RegExp(r'[;\n]'))) if (t.trim().isNotEmpty) t.trim()];

  static List<String> _splitUdc(String s) =>
      [for (final t in s.split(RegExp(r'\s;\s|;|\n'))) if (t.trim().isNotEmpty) t.trim()];

  /// Field value as sent to the server: with its source while it is unchanged, plain text otherwise.
  dynamic _out(String code) {
    final text = _ctl(code).text.trim();
    final p = _prov[code];
    if (p != null && p.value.trim() == text && p.isAutomatic) return p.toJson();
    return text;
  }

  Map<String, dynamic> _currentFields() {
    final t = _typeDef;
    return {
      for (final f in t?.fields ?? const <FieldDef>[])
        if (!f.hidden && _ctl(f.code).text.trim().isNotEmpty) f.code: _out(f.code)
    };
  }

  List<Map<String, dynamic>> _currentCreators() => [for (final c in _creators) if (!c.isEmpty) c.toJson()];

  Map<String, dynamic> _itemJson() => {
        'item_type': _type,
        'fields': _currentFields(),
        'creators': _currentCreators(),
        'tags': [
          for (final t in _splitTags(_tags.text))
            {'name': t, 'source': _tagSources[t.toLowerCase()] ?? manualSource}
        ],
        'udc': [
          for (final n in _splitUdc(_udc.text))
            if (_udcProv[n] != null && _udcProv[n]!.source != manualSource) _udcProv[n]!.toJson() else n
        ],
      };

  // ------------------------------------------------------------------ type change
  /// Moves the form's values to another type (the server applies Zotero's base-field rules).
  Future<bool> _changeType(String to, {bool quiet = false}) async {
    if (to == _type) return true;
    final s = context.read<AppState>();
    final fields = _currentFields();
    final creators = _currentCreators();
    if (fields.isEmpty && creators.isEmpty) {
      setState(() {
        _type = to;
        for (final c in _creators) {
          if (!(_typeDef?.allowsCreator(c.creatorType) ?? true)) c.creatorType = _typeDef!.primaryCreator;
        }
      });
      return true;
    }
    setState(() => _busy = true);
    try {
      final r = await s.api.convertType(_type, to, fields, creators);
      if (!mounted) return false;
      final conv = Map<String, dynamic>.from(r['fields'] as Map);
      final report = Map<String, dynamic>.from(r['report'] as Map);
      setState(() {
        _type = to;
        _setValues({for (final e in conv.entries) e.key: FieldValue.fromJson(e.value)});
        _setCreators([
          for (final c in (r['creators'] as List)) Creator.fromJson(Map<String, dynamic>.from(c as Map))
        ]);
      });
      final toExtra = (report['to_extra'] as List?) ?? [];
      final moved = (report['moved'] as List?) ?? [];
      if (!quiet && toExtra.isNotEmpty) {
        _banner(tr('No field for {f} in this type: moved to Extra.',
            {'f': toExtra.map((x) => (x as Map)['label']).join(', ')}), _Kind.warning, seconds: 10);
      } else if (!quiet && moved.isNotEmpty) {
        _banner(tr('Values moved to the fields of the new type.'), _Kind.info, seconds: 5);
      }
      return true;
    } on ApiException catch (e) {
      if (mounted) _banner(tr('The type could not be changed: {e}', {'e': tr(e.message)}), _Kind.error, seconds: 8);
      return false;
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ------------------------------------------------------------------ upload
  Future<void> _upload() async {
    final s = context.read<AppState>();
    try {
      final r = await s.api.upload(widget.file!.path!, widget.file!.name);
      if (!mounted) return;
      setState(() {
        _tempId = r['temp_id'] as String;
        _pages = (r['pages'] as num).toInt();
        _applyGuess(Map<String, dynamic>.from(r['guess'] as Map));
        _dups = (r['duplicates'] as List).map((e) => Map<String, dynamic>.from(e as Map)).toList();
        _phase = 'ready';
      });
      if (_dups.isNotEmpty) _banner(tr('This file may already be in your library.'), _Kind.warning);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _phase = 'error');
      _banner(tr(e.message), _Kind.error);
    }
  }

  /// Title and authors from the PDF's metadata (or the file name).
  void _applyGuess(Map<String, dynamic> g) {
    final f = Map<String, dynamic>.from((g['fields'] as Map?) ?? {});
    final titleField = _typeDef?.titleField ?? 'title';
    if (f['title'] != null) {
      _mergeValues({titleField: FieldValue.fromJson(f['title'])});
    } else {
      final name = widget.file!.name.replaceAll(RegExp(r'\.pdf$', caseSensitive: false), '');
      _mergeValues({
        titleField: FieldValue(name.replaceAll(RegExp(r'[_\-]+'), ' ').trim(), source: 'filename', confidence: 0.2)
      });
    }
    final list = (g['creators'] as List?) ?? [];
    if (list.isNotEmpty) {
      _setCreators([for (final c in list) Creator.fromJson(Map<String, dynamic>.from(c as Map))]);
    }
  }

  // ------------------------------------------------------------------ autofill
  Future<void> _autofill() async {
    final s = context.read<AppState>();
    setState(() => _busy = true);
    _banner(tr('Looking up the bibliographic record...'), _Kind.info);
    String v(String code) => _ctl(code).text.trim();
    final extra = v('extra');
    final arxiv = RegExp(r'arXiv:\s*([\w.\-/]+)', caseSensitive: false).firstMatch('${v('archiveID')}\n$extra');
    try {
      final r = await s.api.autofill(
        tempId: _tempId,
        doi: v('DOI').isNotEmpty ? v('DOI') : RegExp(r'^DOI:\s*(\S+)', multiLine: true).firstMatch(extra)?.group(1),
        isbn: v('ISBN'),
        arxiv: arxiv?.group(1),
        itemType: _type,
      );
      if (!mounted) return;
      final type = r['item_type'] as String;
      if (type != _type && !await _changeType(type, quiet: true)) return;
      final ident = Map<String, dynamic>.from(r['identifier'] as Map);
      final fields = Map<String, dynamic>.from(r['fields'] as Map);
      final creators = (r['creators'] as List?) ?? [];
      setState(() {
        final extraNew = fields.remove('extra');
        _mergeValues({for (final e in fields.entries) e.key: FieldValue.fromJson(e.value)});
        if (extraNew != null) {
          // values with no field in this type: appended to Extra, never replacing what is there
          final add = FieldValue.fromJson(extraNew);
          final old = _ctl('extra').text.trim();
          _ctl('extra').text = [if (old.isNotEmpty) old, add.value].join('\n');
        }
        if (creators.isNotEmpty) {
          _setCreators([for (final c in creators) Creator.fromJson(Map<String, dynamic>.from(c as Map))]);
        }
        _addTags([for (final t in (r['tags'] as List?) ?? []) TagValue.fromJson(t)]);
      });
      _banner(tr('Filled from {id}. Check the fields before saving.',
          {'id': '${(ident['type'] as String).toUpperCase()} ${ident['value']}'}), _Kind.success, seconds: 6);
    } on ApiException catch (e) {
      if (mounted) _banner(tr(e.message), _Kind.error, seconds: 8);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  // ------------------------------------------------------------------ analyze (classifier)
  Future<void> _checkClassifier() async {
    final api = context.read<AppState>().api;
    try {
      final r = await api.classifierStatus();
      if (!mounted) return;
      setState(() {
        _clsAvailable = r['available'] == true;
        _clsLoading = r['loading'] == true;
      });
    } catch (_) {} // an older server or no connection: the button stays disabled
  }

  /// Queues the analysis and polls it every 2 s. The form stays editable meanwhile; closing it stops waiting.
  Future<void> _analyze() async {
    final s = context.read<AppState>();
    // the person's type is kept; otherwise the detected one is used (and the form switches to it)
    final itemType = _isEdit || _typeTouched ? _type : null;
    String job;
    try {
      job = _isEdit
          ? await s.api.analyze(itemId: widget.item!.id, itemType: itemType)
          : await s.api.analyze(tempId: _tempId, itemType: itemType);
    } on ApiException catch (e) {
      if (mounted) _banner(tr(e.message), _Kind.error, seconds: 8);
      if (e.status == 503) _checkClassifier();
      return;
    }
    if (!mounted) return;
    setState(() => _job = job);
    final t0 = DateTime.now();
    var last = '';
    var failures = 0; // a busy classifier may miss a poll: give up only after ~30 s without an answer
    try {
      while (mounted && _job == job) {
        final Map<String, dynamic> r;
        try {
          r = await s.api.analysis(job);
          failures = 0;
        } on ApiException catch (e) {
          if (e.status != 503 || ++failures >= 10) rethrow;
          await Future.delayed(const Duration(seconds: 3));
          continue;
        }
        if (!mounted) return;
        final st = r['status'] as String;
        if (st == 'done') {
          await _applyAnalysis(r, DateTime.now().difference(t0));
          break;
        }
        if (st == 'error') {
          _banner(tr('The analysis failed: {e}', {'e': r['error']}), _Kind.error, seconds: 10);
          break;
        }
        final ahead = ((r['position'] as num?)?.toInt() ?? 0) - 1;
        final text = st == 'queued' && ahead > 0
            ? tr('Waiting for the classifier ({n} ahead)... You can keep editing.', {'n': ahead})
            : r['loading'] == true
                ? tr('Loading the classifier model (about 1 min after a pause)... You can keep editing.')
                : tr('Analyzing the PDF (about 30 s, more if it needs OCR)... You can keep editing.');
        if (text != last) _banner(last = text, _Kind.info);
        await Future.delayed(const Duration(seconds: 2));
      }
    } on ApiException catch (e) {
      if (mounted) _banner(tr(e.message), _Kind.error, seconds: 8);
    } finally {
      if (mounted && _job == job) setState(() => _job = null);
    }
  }

  /// Fills empty fields (and automatic ones with less confidence); a value the person typed or confirmed is
  /// never replaced: the new one goes to the suggestions card. The UDC suggestions appear as chips.
  Future<void> _applyAnalysis(Map<String, dynamic> r, Duration took) async {
    final s = context.read<AppState>();
    final type = r['item_type'] as String;
    if (type != _type && !await _changeType(type, quiet: true)) return;
    if (!mounted) return;
    final fields = Map<String, dynamic>.from(r['fields'] as Map);
    final creators = [
      for (final c in (r['creators'] as List?) ?? []) Creator.fromJson(Map<String, dynamic>.from(c as Map))
    ];
    final udc = [for (final u in (r['udc'] as List?) ?? []) Map<String, dynamic>.from(u as Map)];
    final review = [for (final x in (r['review'] as List?) ?? []) '$x'];
    final td = _typeDef;
    var filled = 0;
    setState(() {
      _pending.clear();
      final extraNew = fields.remove('extra');
      for (final e in fields.entries) {
        final fv = FieldValue.fromJson(e.value);
        final f = td?.field(e.key);
        final cur = _ctl(e.key).text.trim();
        if (f == null || f.hidden || fv.value.trim().isEmpty || cur == fv.value.trim()) continue;
        final p = _prov[e.key];
        final weaker = p != null && p.isAutomatic && !p.confirmed && p.value.trim() == cur &&
            (p.confidence ?? 0) < (fv.confidence ?? 0);
        if (cur.isEmpty || weaker) {
          _mergeValues({e.key: fv});
          filled++;
        } else {
          _pending.add(_Suggestion(f.label, fv.value, () async => setState(() => _mergeValues({e.key: fv}))));
        }
      }
      if (extraNew != null) {
        // values with no field in this type: appended to Extra, never replacing what is there
        final add = FieldValue.fromJson(extraNew).value.trim();
        final old = _ctl('extra').text.trim();
        if (add.isNotEmpty && !old.contains(add)) _ctl('extra').text = [if (old.isNotEmpty) old, add].join('\n');
      }
      if (creators.isNotEmpty) {
        final names = creators.map(_creatorText).toList();
        final have = [for (final c in _creators) if (!c.isEmpty) _creatorText(Creator(firstName: c.first.text.trim(), lastName: c.last.text.trim()))];
        if (have.isEmpty) {
          _setCreators(creators);
          filled++;
        } else if (names.join('|').toLowerCase() != have.join('|').toLowerCase()) {
          _pending.add(_Suggestion(tr('Creators'), names.join('; '), () async => setState(() => _setCreators(creators))));
        }
      }
      _addTags([for (final t in (r['tags'] as List?) ?? []) TagValue.fromJson(t)]);
      final dt = (r['detected_type'] as Map?)?['value'] as String?;
      final dtDef = dt == null ? null : s.schema.type(dt);
      if (dtDef != null && dtDef.enabled && dt != _type) {
        _pending.add(_Suggestion(tr('Item type'), dtDef.label, () async {
          _typeTouched = true;
          await _changeType(dt!);
        }));
      }
      _udcSugg = udc;
      _lowConfidence = r['low_confidence'] == true;
      if (udc.isNotEmpty && _splitUdc(_udc.text).isEmpty) _useUdc(udc.first);
    });
    final secs = took.inSeconds;
    final parts = [
      tr('Analysis done in {s} s{ocr}: {n} field(s) filled.',
          {'s': secs, 'ocr': r['ocr'] == true ? tr(' (with OCR)') : '', 'n': filled}),
      if (_pending.isNotEmpty) tr('Other values are in the suggestions card.'),
      if (_lowConfidence) tr('Low confidence: check the UDC by hand.'),
      if (review.isNotEmpty) tr('Check: {x}.', {'x': review.join('; ')}),
      tr('Check the marked fields before saving.'),
    ];
    _banner(parts.join(' '), _lowConfidence || review.isNotEmpty ? _Kind.warning : _Kind.success, seconds: 15);
  }

  static String _creatorText(Creator c) =>
      c.firstName.trim().isEmpty ? c.lastName.trim() : '${c.lastName.trim()}, ${c.firstName.trim()}';

  /// A classifier suggestion becomes the main notation (the others, after ' ; ', are kept).
  void _useUdc(Map<String, dynamic> u) {
    final n = u['notation'] as String;
    final list = _splitUdc(_udc.text);
    if (list.isEmpty) {
      list.add(n);
    } else {
      list[0] = n;
    }
    _udcProv[n] = UdcValue(n, source: 'classifier', confidence: (u['confidence'] as num?)?.toDouble(), confirmed: false);
    _udc.text = list.join(' ; ');
  }

  String _udcTip(Map<String, dynamic> u) {
    final aux = [
      for (final a in (u['aux'] as List?) ?? [])
        if (a is Map) '${a['code']}  ${a['label'] ?? ''}${'${a['source']}'.contains('experimental') ? '  (${tr('experimental')})' : ''}'
    ];
    final broader = [for (final b in (u['broader'] as List?) ?? []) '$b'];
    return [
      if ('${u['label'] ?? ''}'.isNotEmpty) '${u['label']}',
      ...aux,
      if (broader.isNotEmpty) '${tr('Broader')}: ${broader.join(' > ')}',
    ].join('\n');
  }

  // ------------------------------------------------------------------ submit
  Future<void> _submit() async {
    final s = context.read<AppState>();
    final titleField = _typeDef?.titleField ?? 'title';
    if (_ctl(titleField).text.trim().isEmpty) {
      _banner(tr('{f} is required.', {'f': _typeDef?.field(titleField)?.label ?? tr('Title')}), _Kind.error, seconds: 5);
      return;
    }
    if (!await _checkUdc()) return;
    setState(() => _busy = true);
    try {
      if (_isEdit) {
        final it = await s.api.updateItem(widget.item!.id, {
          ..._itemJson(),
          'cover_page': _coverPage,
          'regen_citekey': _regenKey,
        });
        if (!mounted) return;
        _banner(tr('Saved.'), _Kind.success);
        await Future.delayed(const Duration(milliseconds: 900));
        if (mounted) Navigator.pop(context, it);
      } else {
        final it = await s.api.createItem({
          'temp_id': _tempId,
          'item': _itemJson(),
          'cover_page': _coverPage,
          'duplicate_action': _dupAction,
          if (_replaceId != null) 'replace_id': _replaceId,
        });
        if (!mounted) return;
        _banner(tr('Added: {f}', {'f': it.filename}), _Kind.success);
        await Future.delayed(const Duration(milliseconds: 1500));
        if (mounted) Navigator.pop(context, AddOutcome.added);
      }
    } on ApiException catch (e) {
      if (!mounted) return;
      final d = e.detail;
      if (e.status == 409 && d is Map && d['duplicates'] is List) {
        setState(() {
          _dups = (d['duplicates'] as List).map((x) => Map<String, dynamic>.from(x as Map)).toList();
          _dupAction = 'check';
        });
        _banner(tr('This looks like a duplicate. Choose what to do below.'), _Kind.warning);
      } else {
        _banner(tr(e.message), _Kind.error, seconds: 8);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Warns, without blocking, when the UDC uses cancelled notations (and offers their replacements) or when
  /// its form auxiliary does not fit the item type (a thesis without (043), a patent without (088.8)...).
  /// Returns false when the user goes back to editing. Offline (or an older server) never blocks saving.
  Future<bool> _checkUdc() async {
    final s = context.read<AppState>();
    for (var round = 0; round < 10; round++) {
      final udc = _udc.text.trim();
      final extra = _ctl('extra').text.trim();
      final formKey = '$udc|$_type|$extra';
      if (udc.isEmpty || (udc == _checkedUdc && formKey == _checkedForm)) return true;
      UdcCheckResult r;
      try {
        r = await s.api.udcCheck(udc, itemType: _type, extra: extra);
      } catch (_) {
        return true;
      }
      if (!mounted) return false;
      if (r.cancelled.isNotEmpty && udc != _checkedUdc) {
        final res = await showDialog<String>(
            context: context, builder: (_) => _CancelledUdcDialog(udc: udc, hits: r.cancelled, lang: s.udcLang));
        if (res == null || !mounted) return false; // back to editing
        if (res != udc) {
          setState(() => _udc.text = res); // one component replaced: check the new string
          continue;
        }
      }
      _checkedUdc = udc; // no cancelled notations, or saved as it is
      if (r.form.isEmpty || formKey == _checkedForm) {
        _checkedForm = formKey;
        return true;
      }
      final ok = await showDialog<bool>(context: context, builder: (_) => _FormUdcDialog(messages: r.form));
      if (ok != true || !mounted) return false;
      _checkedForm = formKey;
      return true;
    }
    return true;
  }

  void _resolveDuplicate(String action) {
    setState(() {
      _dupAction = action;
      _replaceId = action == 'replace' ? (_dups.first['id'] as num).toInt() : null;
    });
    _submit();
  }

  /// Number builder (UDC tree) on the main notation; the others, after ' ; ', are kept.
  Future<void> _pickUdc() async {
    final list = _splitUdc(_udc.text);
    final code = await buildUdcNumber(context, initial: list.isEmpty ? '' : list.first, doneLabel: tr('Use this number'));
    if (code == null || !mounted) return;
    setState(() {
      if (list.isEmpty) {
        if (code.isNotEmpty) list.add(code);
      } else if (code.isEmpty) {
        list.removeAt(0);
      } else {
        list[0] = code;
      }
      _udc.text = list.join(' ; ');
    });
  }

  void _goToPage(int p) {
    final page = p.clamp(1, _pages);
    setState(() {
      _coverPage = page;
      _page.text = '$page';
    });
  }

  // ------------------------------------------------------------------ build
  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final title = _isEdit
        ? tr('Edit fields')
        : (widget.total > 1 ? tr('Add file {i} of {n}', {'i': widget.index, 'n': widget.total}) : tr('Add file'));
    final subtitle = _isEdit ? widget.item!.filename : widget.file!.name;

    final body = _phase == 'uploading'
        ? Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text(tr('Uploading {f}...', {'f': subtitle}), textAlign: TextAlign.center),
              ),
            ]),
          )
        : _phase == 'error'
            ? Center(child: Text(tr('The file could not be uploaded.'), style: TextStyle(color: cs.error)))
            : LayoutBuilder(builder: (context, c) {
                final wide = c.maxWidth >= 720;
                if (wide) {
                  return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    SizedBox(width: 270, child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: _coverPicker(s))),
                    const VerticalDivider(width: 1),
                    Expanded(child: SingleChildScrollView(padding: const EdgeInsets.all(16), child: _form(s))),
                  ]);
                }
                return SingleChildScrollView(
                  padding: const EdgeInsets.all(16),
                  child: Column(children: [_coverPicker(s), const Divider(height: 28), _form(s)]),
                );
              });

    final ready = _phase == 'ready' && !_busy;
    final needsDupChoice = !_isEdit && _dups.isNotEmpty && _dupAction == 'check';

    return Dialog(
      insetPadding: const EdgeInsets.all(12),
      clipBehavior: Clip.antiAlias,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 980, maxHeight: 780),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          _BannerBar(text: _bannerText, kind: _bannerKind),
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 20, 8),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title, style: Theme.of(context).textTheme.titleLarge),
                  Text(subtitle, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(color: cs.onSurfaceVariant)),
                ]),
              ),
            ]),
          ),
          const Divider(height: 1),
          Flexible(child: SizedBox(height: 560, child: body)),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Wrap(spacing: 8, runSpacing: 8, alignment: WrapAlignment.end, crossAxisAlignment: WrapCrossAlignment.center, children: [
              if (_isEdit) ...[
                Row(mainAxisSize: MainAxisSize.min, children: [
                  Checkbox(value: _regenKey, onChanged: _busy ? null : (v) => setState(() => _regenKey = v ?? false)),
                  Tooltip(
                    message: tr('Renames the PDF files after the current author, year and title'),
                    child: Text(tr('Regenerate file names')),
                  ),
                ]),
                TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: Text(tr('Cancel'))),
              ] else ...[
                TextButton(onPressed: _busy ? null : () => Navigator.pop(context, AddOutcome.cancelAll), child: Text(tr('Cancel all'))),
                TextButton(onPressed: _busy ? null : () => Navigator.pop(context, AddOutcome.skipped), child: Text(tr('Skip file'))),
              ],
              Tooltip(
                message: _clsAvailable
                    ? tr('Suggest the type, the fields and the UDC from the PDF itself (local AI on the server)')
                    : (_clsLoading
                        ? tr('The classifier is starting on the server. Try again in a minute.')
                        : tr('Classifier not available on the server')),
                child: OutlinedButton.icon(
                  onPressed: ready && _clsAvailable && _job == null ? _analyze : null,
                  icon: _job != null
                      ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                      : const Icon(Icons.psychology_outlined, size: 18),
                  label: Text(_job != null ? tr('Analyzing...') : tr('Analyze')),
                ),
              ),
              OutlinedButton.icon(
                onPressed: ready ? _autofill : null,
                icon: const Icon(Icons.auto_fix_high, size: 18),
                label: Text(tr('Fill automatically')),
              ),
              FilledButton(
                onPressed: ready && !needsDupChoice ? _submit : null,
                child: Text(_isEdit ? tr('Save') : tr('Add')),
              ),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _coverPicker(AppState s) {
    final cs = Theme.of(context).colorScheme;
    final url = _isEdit
        ? s.api.itemPageUrl(widget.item!.id, _coverPage)
        : (_tempId == null ? null : s.api.uploadPageUrl(_tempId!, _coverPage));
    return Column(children: [
      Text(tr('Cover'), style: Theme.of(context).textTheme.titleSmall),
      const SizedBox(height: 8),
      ClipRRect(
        borderRadius: BorderRadius.circular(4),
        child: url == null
            ? SizedBox(height: 260, child: Center(child: Icon(Icons.picture_as_pdf, size: 48, color: cs.onSurfaceVariant)))
            : Image.network(url, key: ValueKey(url), headers: s.api.headers, width: 220, fit: BoxFit.fitWidth,
                errorBuilder: (_, __, ___) => SizedBox(height: 260, child: Center(child: Icon(Icons.broken_image_outlined, color: cs.onSurfaceVariant))),
                loadingBuilder: (_, child, p) => p == null ? child : const SizedBox(height: 260, child: Center(child: CircularProgressIndicator(strokeWidth: 2)))),
      ),
      const SizedBox(height: 8),
      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        IconButton(tooltip: tr('Previous page'), onPressed: _coverPage > 1 ? () => _goToPage(_coverPage - 1) : null, icon: const Icon(Icons.chevron_left)),
        SizedBox(
          width: 56,
          child: TextField(
            controller: _page,
            textAlign: TextAlign.center,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: const InputDecoration(isDense: true),
            onSubmitted: (v) => _goToPage(int.tryParse(v) ?? 1),
          ),
        ),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 6), child: Text(tr('of {n}', {'n': _pages}))),
        IconButton(tooltip: tr('Next page'), onPressed: _coverPage < _pages ? () => _goToPage(_coverPage + 1) : null, icon: const Icon(Icons.chevron_right)),
      ]),
      Text(tr('This page is used as the cover.'), style: TextStyle(color: cs.onSurfaceVariant, fontSize: kFsSmall)),
    ]);
  }

  Widget _dupCard() {
    final cs = Theme.of(context).colorScheme;
    return Card(
      color: cs.tertiaryContainer,
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.warning_amber_rounded, color: cs.onTertiaryContainer),
            const SizedBox(width: 8),
            Text(tr('Possible duplicate'), style: TextStyle(fontWeight: FontWeight.w600, color: cs.onTertiaryContainer)),
          ]),
          const SizedBox(height: 8),
          for (final d in _dups)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                '${tr('${d['reason']}')}: ${d['title']}'
                '${(d['creators_text'] ?? '').toString().isEmpty ? '' : ' - ${d['creators_text']}'}'
                '${d['year'] == null ? '' : ' (${d['year']})'}'
                '${d['in_trash'] == true ? '  [${tr('in trash')}]' : ''}',
                style: TextStyle(color: cs.onTertiaryContainer),
              ),
            ),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton(onPressed: _busy ? null : () => _resolveDuplicate('replace'), child: Text(tr('Replace existing'))),
            OutlinedButton(onPressed: _busy ? null : () => _resolveDuplicate('keep_both'), child: Text(tr('Keep both'))),
            if (!_isEdit)
              TextButton(onPressed: _busy ? null : () => Navigator.pop(context, AddOutcome.skipped), child: Text(tr('Skip this file'))),
          ]),
        ]),
      ),
    );
  }


  Widget _form(AppState s) {
    final t = s.schema.type(_type);
    const gap = SizedBox(height: 12);
    // A disabled type is offered only when the item already has it.
    final types = [...s.schema.enabledTypes, if (t != null && !t.enabled) t];
    final fields = [for (final f in t?.fields ?? const <FieldDef>[]) if (!f.hidden) f];
    final titleField = t?.titleField ?? 'title';
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (!_isEdit && _dups.isNotEmpty) _dupCard(),
      if (_pending.isNotEmpty) _pendingCard(),
      CompactDropdown<String>(
        value: t != null ? _type : null,
        label: tr('Item type'),
        suffix: t == null || t.help.isEmpty ? null : _help(t.help),
        options: [for (final x in types) Opt(x.code, x.label)],
        onChanged: _busy
            ? null
            : (v) {
                _typeTouched = true;
                _changeType(v);
              },
      ),
      for (final f in fields) ...[
        gap,
        _fieldEditor(f, required: f.code == titleField),
        // Zotero puts the creators right after the title
        if (f.code == titleField) ...[
          gap,
          Text(tr('Creators'), style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          for (var i = 0; i < _creators.length; i++) _creatorEditor(i, t),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              onPressed: () => setState(() => _creators.add(_CreatorRow(t?.primaryCreator ?? 'author', '', ''))),
              icon: const Icon(Icons.add, size: 18),
              label: Text(tr('Add creator')),
            ),
          ),
        ],
      ],
      const Divider(height: 32),
      Row(children: [
        Expanded(
          child: TextField(
            controller: _udc,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: tr('UDC notation'),
              hintText: tr('004.8:61   (several: 53 ; 62)'),
              prefixIcon: _udcUnconfirmed(),
            ),
          ),
        ),
        IconButton.outlined(tooltip: tr('Number builder (UDC tree)'), onPressed: _pickUdc, icon: const Icon(Icons.account_tree_outlined)),
      ]),
      if (_udc.text.trim().isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 6, left: 4),
          child: UdcBreakdown(_udc.text, compact: true),
        ),
      if (_udcSugg.isNotEmpty) _udcChips(),
      gap,
      TextField(
        controller: _tags,
        decoration: InputDecoration(labelText: tr('Tags'), hintText: tr('Separate tags with ;')),
      ),
    ]);
  }

  /// Values from the analysis that were not applied because the field already had one.
  Widget _pendingCard() {
    final cs = Theme.of(context).colorScheme;
    return Card(
      color: cs.secondaryContainer,
      margin: const EdgeInsets.only(bottom: 16),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 10, 4, 6),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(Icons.psychology_outlined, size: 18, color: cs.onSecondaryContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Text(tr('The classifier suggests other values'),
                  style: TextStyle(fontWeight: FontWeight.w600, color: cs.onSecondaryContainer)),
            ),
            TextButton(onPressed: () => setState(_pending.clear), child: Text(tr('Dismiss all'))),
          ]),
          for (final p in List.of(_pending))
            Row(children: [
              Expanded(
                child: Text('${p.label}: ${p.value}',
                    maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(color: cs.onSecondaryContainer)),
              ),
              TextButton(
                onPressed: _busy
                    ? null
                    : () async {
                        await p.apply();
                        if (mounted) setState(() => _pending.remove(p));
                      },
                child: Text(tr('Use')),
              ),
              IconButton(
                tooltip: tr('Dismiss'),
                onPressed: () => setState(() => _pending.remove(p)),
                icon: const Icon(Icons.close, size: 18),
              ),
            ]),
        ]),
      ),
    );
  }

  /// The classifier's UDC suggestions: tapping one makes it the main notation.
  Widget _udcChips() {
    final cs = Theme.of(context).colorScheme;
    final list = _splitUdc(_udc.text);
    final main = list.isEmpty ? '' : list.first;
    return Padding(
      padding: const EdgeInsets.only(top: 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(
          _lowConfidence ? tr('Classifier suggestions (low confidence: check them by hand)') : tr('Classifier suggestions'),
          style: TextStyle(fontSize: kFsSmall, color: _lowConfidence ? cs.error : cs.onSurfaceVariant),
        ),
        const SizedBox(height: 4),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final u in _udcSugg)
            Tooltip(
              message: _udcTip(u),
              child: ChoiceChip(
                label: Text('${u['notation']}   ${(((u['confidence'] as num?) ?? 0) * 100).round()}%'),
                selected: main == u['notation'],
                onSelected: (_) => setState(() => _useUdc(u)),
              ),
            ),
        ]),
      ]),
    );
  }

  Widget _help(String text) => Tooltip(
        message: text,
        preferBelow: false,
        triggerMode: TooltipTriggerMode.tap,
        child: const Padding(padding: EdgeInsets.all(12), child: Icon(Icons.help_outline, size: 18)),
      );

  Widget? _udcUnconfirmed() {
    for (final n in _splitUdc(_udc.text)) {
      final p = _udcProv[n];
      if (p != null && !p.confirmed && p.source != manualSource) {
        return SizedBox(width: 30, child: Center(child: UnconfirmedMark(p.source, p.confidence)));
      }
    }
    return null;
  }

  Widget _fieldEditor(FieldDef f, {bool required = false}) {
    final ctl = _ctl(f.code);
    final p = _prov[f.code];
    // marked while the automatic value is still there and nobody has confirmed it
    final automatic = p != null && p.isAutomatic && !p.confirmed && ctl.text.trim() == p.value.trim();
    final long = f.kind == 'longtext';
    return TextField(
      controller: ctl,
      readOnly: f.obsolete,
      onChanged: automatic ? (_) => setState(() {}) : null,
      minLines: long ? 3 : 1,
      maxLines: long ? 10 : (f.code == 'title' || required ? 3 : 1),
      keyboardType: f.kind == 'url' ? TextInputType.url : (long ? TextInputType.multiline : null),
      decoration: InputDecoration(
        labelText: '${f.label}${required ? ' *' : ''}${f.obsolete ? ' (${tr('no longer in Zotero')})' : ''}',
        hintText: switch (f.kind) {
          'date' => tr('e.g. 1998, March 1998, 1998-03-12'),
          'url' => 'https://...',
          _ => f.code == 'extra' ? tr('One "Name: value" per line, e.g. Type: musical_score') : null,
        },
        prefixIcon: automatic
            ? SizedBox(width: 30, child: Center(child: UnconfirmedMark(p.source, p.confidence)))
            : null,
        suffixIcon: f.help.isEmpty ? null : _help(f.help),
      ),
    );
  }

  Widget _creatorEditor(int i, TypeDef? t) {
    final c = _creators[i];
    final roles = t?.creatorTypes ?? const <CreatorTypeDef>[];
    final value = roles.any((r) => r.code == c.creatorType) ? c.creatorType : (roles.isEmpty ? null : roles.first.code);
    final single = c.fieldMode == 1;
    final automatic = !c.confirmed && c.source != manualSource && c.unchanged;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          if (automatic) UnconfirmedMark(c.source, c.confidence),
          Expanded(
              child: TextField(
                  controller: c.last,
                  onChanged: automatic ? (_) => setState(() {}) : null,
                  decoration: InputDecoration(
                      labelText: single ? tr('Name (organization)') : tr('Last name'), isDense: true))),
          if (!single) ...[
            const SizedBox(width: 8),
            Expanded(
                child: TextField(
                    controller: c.first,
                    onChanged: automatic ? (_) => setState(() {}) : null,
                    decoration: InputDecoration(labelText: tr('First name(s)'), isDense: true))),
          ],
          IconButton(
            tooltip: single ? tr('Switch to last name / first name') : tr('Switch to a single field (organizations)'),
            onPressed: () => setState(() {
              if (single) {
                c.fieldMode = 0;
              } else {
                final full = [c.first.text.trim(), c.last.text.trim()].where((x) => x.isNotEmpty).join(' ');
                c.fieldMode = 1;
                c.last.text = full;
                c.first.clear();
              }
            }),
            icon: Icon(single ? Icons.person_outline : Icons.business_outlined, size: 20),
          ),
          IconButton(
            tooltip: tr('Remove'),
            onPressed: _creators.length > 1
                ? () => setState(() => _creators.removeAt(i).dispose())
                : () => setState(() {
                      c.first.clear();
                      c.last.clear();
                    }),
            icon: const Icon(Icons.close, size: 20),
          ),
        ]),
        const SizedBox(height: 6),
        SizedBox(
          width: 220,
          child: CompactDropdown<String>(
            value: value,
            label: tr('Role'),
            options: [for (final r in roles) Opt(r.code, r.label, tip: r.help)],
            onChanged: (v) => setState(() => c.creatorType = v),
          ),
        ),
      ]),
    );
  }
}

/// A value from the analysis that the person may apply ("Use") or dismiss.
class _Suggestion {
  final String label;
  final String value;
  final Future<void> Function() apply;
  _Suggestion(this.label, this.value, this.apply);
}

/// component replaced, the same string ("Save as it is") or null ("Back to editing").
class _CancelledUdcDialog extends StatelessWidget {
  final String udc;
  final List<UdcCancelledHit> hits;
  final String lang;
  const _CancelledUdcDialog({required this.udc, required this.hits, required this.lang});

  String _replace(UdcCancelledHit h, String code) => udc.substring(0, h.start) + code + udc.substring(h.end);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return AlertDialog(
      icon: Icon(Icons.history, color: cs.tertiary),
      title: Text(tr('Cancelled UDC notation')),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(hits.length == 1
                ? tr('This UDC number uses a notation that was cancelled in the UDC. You can replace it or save it as it is.')
                : tr('This UDC number uses notations that were cancelled in the UDC. You can replace them or save it as it is.')),
            const SizedBox(height: 12),
            for (final h in hits)
              for (final c in h.cancellations)
                Padding(
                  padding: const EdgeInsets.only(bottom: 14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text.rich(TextSpan(children: [
                      TextSpan(
                          text: h.component,
                          style: TextStyle(fontWeight: FontWeight.w700, decoration: TextDecoration.lineThrough)),
                      TextSpan(text: '  ${tr('cancelled')} ${c.when}  ', style: TextStyle(color: cs.onSurfaceVariant)),
                      TextSpan(text: c.label),
                    ])),
                    const SizedBox(height: 6),
                    if (c.replacedBy.isEmpty)
                      Text(c.note.isEmpty ? tr('No replacement.') : tr(c.note), style: TextStyle(color: cs.onSurfaceVariant))
                    else
                      Wrap(spacing: 8, runSpacing: 8, children: [
                        for (final r in c.replacedBy)
                          OutlinedButton(
                            onPressed: () => Navigator.pop(context, _replace(h, r.code)),
                            child: Text(r.exists ? '${tr('Use')} ${r.code}  ${r.label(lang)}' : '${tr('Use')} ${r.code}',
                                overflow: TextOverflow.ellipsis),
                          ),
                      ]),
                  ]),
                ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Back to editing'))),
        FilledButton.tonal(onPressed: () => Navigator.pop(context, udc), child: Text(tr('Save as it is'))),
      ],
    );
  }
}

/// Type <-> UDC form mismatch: true = "Save as it is", null = "Back to editing". A warning, never a rule.
class _FormUdcDialog extends StatelessWidget {
  final List<String> messages;
  const _FormUdcDialog({required this.messages});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return AlertDialog(
      icon: Icon(Icons.rule, color: cs.tertiary),
      title: Text(tr('Type and UDC form do not match')),
      content: SizedBox(
        width: 520,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
          for (final m in messages) Padding(padding: const EdgeInsets.only(bottom: 10), child: Text(tr(m))),
          Text(tr('Often one of the two was mistyped: change the item type or the UDC, or keep both if they are right.'),
              style: TextStyle(color: cs.onSurfaceVariant)),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Back to editing'))),
        FilledButton.tonal(onPressed: () => Navigator.pop(context, true), child: Text(tr('Save as it is'))),
      ],
    );
  }
}

class _BannerBar extends StatelessWidget {
  final String? text;
  final _Kind kind;
  const _BannerBar({required this.text, required this.kind});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final color = switch (kind) {
      _Kind.success => paletteOf(context).action,
      _Kind.error => cs.error,
      _Kind.warning => paletteOf(context).warning,
      _Kind.info => cs.primary,
    };
    return AnimatedSize(
      duration: const Duration(milliseconds: 150),
      child: text == null
          ? const SizedBox(width: double.infinity)
          : Container(
              width: double.infinity,
              color: color,
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
              child: Text(text!, style: const TextStyle(color: Colors.white)),
            ),
    );
  }
}
