import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../core/models.dart';
import 'udc_picker.dart';

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
  if (r is Item && context.mounted) context.read<AppState>().itemUpdated(r);
}

class _CreatorRow {
  String role;
  final TextEditingController first;
  final TextEditingController last;
  _CreatorRow(this.role, String f, String l)
      : first = TextEditingController(text: f),
        last = TextEditingController(text: l);
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
  final _title = TextEditingController();
  final _year = TextEditingController();
  final _language = TextEditingController();
  final _udc = TextEditingController();
  final _page = TextEditingController(text: '1');
  final Map<String, TextEditingController> _data = {};
  final List<_CreatorRow> _creators = [];
  String _type = 'book';

  bool get _isEdit => widget.item != null;
  String _phase = 'ready'; // uploading | ready | error
  bool _busy = false;
  String? _checkedUdc; // UDC string already checked for cancelled notations (not asked again)
  String? _tempId;
  int _pages = 1;
  int _coverPage = 1;
  bool _regenKey = false;
  List<Map<String, dynamic>> _dups = [];
  String _dupAction = 'check';
  int? _replaceId;

  String? _bannerText;
  _Kind _bannerKind = _Kind.info;
  int _bannerId = 0;

  TextEditingController _ctl(String key) => _data.putIfAbsent(key, () => TextEditingController());

  @override
  void initState() {
    super.initState();
    final s = context.read<AppState>();
    _type = s.schema.types.isNotEmpty ? s.schema.types.first.code : 'other';
    final it = widget.item;
    if (it != null) {
      _type = s.schema.type(it.itemType) != null ? it.itemType : 'other';
      _title.text = it.title;
      _year.text = it.year?.toString() ?? '';
      _language.text = it.language;
      _udc.text = it.udc;
      _coverPage = it.coverPage;
      _pages = it.pages ?? 1;
      _page.text = '$_coverPage';
      for (final e in it.data.entries) {
        _ctl(e.key).text = e.value;
      }
      for (final c in it.creators) {
        _creators.add(_CreatorRow(c.role, c.first, c.last));
      }
    } else {
      _phase = 'uploading';
      WidgetsBinding.instance.addPostFrameCallback((_) => _upload());
    }
    if (_creators.isEmpty) _creators.add(_CreatorRow('author', '', ''));
  }

  @override
  void dispose() {
    for (final c in [_title, _year, _language, _udc, _page, ..._data.values]) {
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
      if (_dups.isNotEmpty) _banner('This file may already be in your library.', _Kind.warning);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _phase = 'error');
      _banner(e.message, _Kind.error);
    }
  }

  void _applyGuess(Map<String, dynamic> g) {
    final t = (g['title'] as String?) ?? '';
    if (t.isNotEmpty) {
      _title.text = t;
    } else {
      final name = widget.file!.name.replaceAll(RegExp(r'\.pdf$', caseSensitive: false), '');
      _title.text = name.replaceAll(RegExp(r'[_\-]+'), ' ').trim();
    }
    final list = (g['creators'] as List?) ?? [];
    if (list.isNotEmpty) {
      _creators
        ..forEach((c) => c.dispose())
        ..clear();
      for (final c in list) {
        final m = Map<String, dynamic>.from(c as Map);
        _creators.add(_CreatorRow((m['role'] ?? 'author').toString(), (m['first'] ?? '').toString(), (m['last'] ?? '').toString()));
      }
    }
  }

  // ------------------------------------------------------------------ autofill
  Future<void> _autofill() async {
    final s = context.read<AppState>();
    setState(() => _busy = true);
    _banner('Looking up the bibliographic record...', _Kind.info);
    try {
      final r = await s.api.autofill(
        tempId: _tempId,
        doi: _data['doi']?.text.trim(),
        isbn: _data['isbn']?.text.trim(),
        arxiv: _data['arxiv']?.text.trim(),
      );
      if (!mounted) return;
      final ident = Map<String, dynamic>.from(r['identifier'] as Map);
      setState(() => _applyFilled(Map<String, dynamic>.from(r['fields'] as Map)));
      _banner('Filled from ${(ident['type'] as String).toUpperCase()} ${ident['value']}. Check the fields before saving.',
          _Kind.success, seconds: 6);
    } on ApiException catch (e) {
      if (mounted) _banner(e.message, _Kind.error, seconds: 8);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _applyFilled(Map<String, dynamic> f) {
    final s = context.read<AppState>();
    final t = f['item_type'] as String?;
    if (t != null && s.schema.type(t) != null) _type = t;
    if ((f['title'] ?? '').toString().isNotEmpty) _title.text = f['title'].toString();
    if (f['year'] != null) _year.text = f['year'].toString();
    if ((f['language'] ?? '').toString().isNotEmpty) _language.text = f['language'].toString();
    final list = (f['creators'] as List?) ?? [];
    if (list.isNotEmpty) {
      for (final c in _creators) {
        c.dispose();
      }
      _creators.clear();
      for (final c in list) {
        final m = Map<String, dynamic>.from(c as Map);
        _creators.add(_CreatorRow((m['role'] ?? 'author').toString(), (m['first'] ?? '').toString(), (m['last'] ?? '').toString()));
      }
    }
    final data = Map<String, dynamic>.from((f['data'] as Map?) ?? {});
    for (final e in data.entries) {
      _ctl(e.key).text = e.value.toString();
    }
  }

  // ------------------------------------------------------------------ submit
  Map<String, dynamic> _fields() {
    final s = context.read<AppState>();
    final keys = s.schema.type(_type)?.fields ?? <String>[];
    return {
      'item_type': _type,
      'title': _title.text.trim(),
      'year': int.tryParse(_year.text.trim()),
      'language': _language.text.trim(),
      'udc': _udc.text.trim(),
      'creators': [
        for (final c in _creators)
          if (c.first.text.trim().isNotEmpty || c.last.text.trim().isNotEmpty)
            {'role': c.role, 'first': c.first.text.trim(), 'last': c.last.text.trim()}
      ],
      'data': {
        for (final k in keys)
          if (_ctl(k).text.trim().isNotEmpty) k: _ctl(k).text.trim()
      },
    };
  }

  Future<void> _submit() async {
    final s = context.read<AppState>();
    if (_title.text.trim().isEmpty) {
      _banner('Title is required.', _Kind.error, seconds: 5);
      return;
    }
    if (_year.text.trim().isNotEmpty && int.tryParse(_year.text.trim()) == null) {
      _banner('Year must be a number, for example 1998.', _Kind.error, seconds: 5);
      return;
    }
    if (!await _checkCancelledUdc()) return;
    setState(() => _busy = true);
    try {
      if (_isEdit) {
        final it = await s.api.updateItem(widget.item!.id, {
          ..._fields(),
          'cover_page': _coverPage,
          'regen_citekey': _regenKey,
        });
        if (!mounted) return;
        _banner('Saved.', _Kind.success);
        await Future.delayed(const Duration(milliseconds: 900));
        if (mounted) Navigator.pop(context, it);
      } else {
        final it = await s.api.createItem({
          'temp_id': _tempId,
          'fields': _fields(),
          'cover_page': _coverPage,
          'duplicate_action': _dupAction,
          if (_replaceId != null) 'replace_id': _replaceId,
        });
        if (!mounted) return;
        _banner('Added: ${it.citekey}', _Kind.success);
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
        _banner('This looks like a duplicate. Choose what to do below.', _Kind.warning);
      } else {
        _banner(e.message, _Kind.error, seconds: 8);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Warns, without blocking, when the UDC uses cancelled notations and offers their replacements.
  /// Returns false when the user goes back to editing. Offline (or an older server) never blocks saving.
  Future<bool> _checkCancelledUdc() async {
    final s = context.read<AppState>();
    for (var round = 0; round < 10; round++) {
      final udc = _udc.text.trim();
      if (udc.isEmpty || udc == _checkedUdc) return true;
      List<UdcCancelledHit> hits;
      try {
        hits = await s.api.udcCheck(udc);
      } catch (_) {
        return true;
      }
      if (!mounted) return false;
      if (hits.isEmpty) {
        _checkedUdc = udc;
        return true;
      }
      final res = await showDialog<String>(
          context: context, builder: (_) => _CancelledUdcDialog(udc: udc, hits: hits, lang: s.udcLang));
      if (res == null || !mounted) return false; // back to editing
      if (res == udc) {
        _checkedUdc = udc; // save as it is
        return true;
      }
      setState(() => _udc.text = res); // one component replaced: check the new string
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

  Future<void> _pickUdc() async {
    final code = await pickUdc(context);
    if (code != null && mounted) {
      setState(() => _udc.text = _udc.text.trim().isEmpty ? code : '${_udc.text.trim()}:$code');
    }
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
        ? 'Edit fields'
        : (widget.total > 1 ? 'Add file ${widget.index} of ${widget.total}' : 'Add file');
    final subtitle = _isEdit ? widget.item!.filename : widget.file!.name;

    final body = _phase == 'uploading'
        ? Center(
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 24),
                child: Text('Uploading $subtitle...', textAlign: TextAlign.center),
              ),
            ]),
          )
        : _phase == 'error'
            ? Center(child: Text('The file could not be uploaded.', style: TextStyle(color: cs.error)))
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
                  const Text('Regenerate citation key and file name'),
                ]),
                TextButton(onPressed: _busy ? null : () => Navigator.pop(context), child: const Text('Cancel')),
              ] else ...[
                TextButton(onPressed: _busy ? null : () => Navigator.pop(context, AddOutcome.cancelAll), child: const Text('Cancel all')),
                TextButton(onPressed: _busy ? null : () => Navigator.pop(context, AddOutcome.skipped), child: const Text('Skip file')),
              ],
              OutlinedButton.icon(
                onPressed: ready ? _autofill : null,
                icon: const Icon(Icons.auto_fix_high, size: 18),
                label: const Text('Fill automatically'),
              ),
              FilledButton(
                onPressed: ready && !needsDupChoice ? _submit : null,
                child: Text(_isEdit ? 'Save' : 'Add'),
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
      Text('Cover', style: Theme.of(context).textTheme.titleSmall),
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
        IconButton(tooltip: 'Previous page', onPressed: _coverPage > 1 ? () => _goToPage(_coverPage - 1) : null, icon: const Icon(Icons.chevron_left)),
        SizedBox(
          width: 56,
          child: TextField(
            controller: _page,
            textAlign: TextAlign.center,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
            decoration: const InputDecoration(isDense: true, border: OutlineInputBorder()),
            onSubmitted: (v) => _goToPage(int.tryParse(v) ?? 1),
          ),
        ),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 6), child: Text('of $_pages')),
        IconButton(tooltip: 'Next page', onPressed: _coverPage < _pages ? () => _goToPage(_coverPage + 1) : null, icon: const Icon(Icons.chevron_right)),
      ]),
      Text('This page is used as the cover.', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
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
            Text('Possible duplicate', style: TextStyle(fontWeight: FontWeight.w600, color: cs.onTertiaryContainer)),
          ]),
          const SizedBox(height: 8),
          for (final d in _dups)
            Padding(
              padding: const EdgeInsets.only(bottom: 4),
              child: Text(
                '${d['reason']}: ${d['title']}'
                '${(d['creators_text'] ?? '').toString().isEmpty ? '' : ' - ${d['creators_text']}'}'
                '${d['year'] == null ? '' : ' (${d['year']})'}'
                '${d['in_trash'] == true ? '  [in trash]' : ''}',
                style: TextStyle(color: cs.onTertiaryContainer),
              ),
            ),
          const SizedBox(height: 8),
          Wrap(spacing: 8, runSpacing: 8, children: [
            FilledButton(onPressed: _busy ? null : () => _resolveDuplicate('replace'), child: const Text('Replace existing')),
            OutlinedButton(onPressed: _busy ? null : () => _resolveDuplicate('keep_both'), child: const Text('Keep both')),
            if (!_isEdit)
              TextButton(onPressed: _busy ? null : () => Navigator.pop(context, AddOutcome.skipped), child: const Text('Skip this file')),
          ]),
        ]),
      ),
    );
  }

  Widget _form(AppState s) {
    final typeDef = s.schema.type(_type);
    final udcText = s.udc.describe(_udc.text, s.udcLang);
    const gap = SizedBox(height: 12);
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      if (!_isEdit && _dups.isNotEmpty) _dupCard(),
      DropdownButtonFormField<String>(
        value: s.schema.type(_type) != null ? _type : null,
        decoration: const InputDecoration(labelText: 'Resource type', border: OutlineInputBorder()),
        items: [for (final t in s.schema.types) DropdownMenuItem(value: t.code, child: Text(t.label))],
        onChanged: (v) => setState(() => _type = v ?? _type),
      ),
      gap,
      TextField(
        controller: _title,
        minLines: 1,
        maxLines: 3,
        decoration: const InputDecoration(labelText: 'Title *', border: OutlineInputBorder()),
      ),
      gap,
      Text('Creators', style: Theme.of(context).textTheme.titleSmall),
      const SizedBox(height: 6),
      for (var i = 0; i < _creators.length; i++) _creatorEditor(i, s),
      Align(
        alignment: Alignment.centerLeft,
        child: TextButton.icon(
          onPressed: () => setState(() => _creators.add(_CreatorRow('author', '', ''))),
          icon: const Icon(Icons.add, size: 18),
          label: const Text('Add creator'),
        ),
      ),
      gap,
      Row(children: [
        Expanded(
          child: TextField(
            controller: _year,
            keyboardType: TextInputType.number,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)],
            decoration: const InputDecoration(labelText: 'Year', border: OutlineInputBorder()),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(
          child: TextField(
            controller: _language,
            decoration: const InputDecoration(labelText: 'Language', hintText: 'es, en, fr...', border: OutlineInputBorder()),
          ),
        ),
      ]),
      gap,
      Row(children: [
        Expanded(
          child: TextField(
            controller: _udc,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(labelText: 'UDC notation', hintText: '004.8:61', border: OutlineInputBorder()),
          ),
        ),
        IconButton(tooltip: 'Pick from the UDC tree', onPressed: _pickUdc, icon: const Icon(Icons.account_tree_outlined)),
      ]),
      if (udcText.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(top: 4),
          child: Text(udcText, style: TextStyle(fontSize: 12, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ),
      for (final key in typeDef?.fields ?? <String>[]) ...[
        gap,
        TextField(
          controller: _ctl(key),
          minLines: s.schema.fields[key]?.kind == 'area' ? 3 : 1,
          maxLines: s.schema.fields[key]?.kind == 'area' ? 8 : 1,
          decoration: InputDecoration(labelText: s.schema.fields[key]?.label ?? key, border: const OutlineInputBorder()),
        ),
      ],
    ]);
  }

  Widget _creatorEditor(int i, AppState s) {
    final c = _creators[i];
    final roles = s.schema.roles.isEmpty ? ['author'] : s.schema.roles;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: TextField(controller: c.last, decoration: const InputDecoration(labelText: 'Last name', isDense: true, border: OutlineInputBorder()))),
          const SizedBox(width: 8),
          Expanded(child: TextField(controller: c.first, decoration: const InputDecoration(labelText: 'First name(s)', isDense: true, border: OutlineInputBorder()))),
          IconButton(
            tooltip: 'Remove',
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
          width: 180,
          child: DropdownButtonFormField<String>(
            value: roles.contains(c.role) ? c.role : roles.first,
            isDense: true,
            decoration: const InputDecoration(labelText: 'Role', isDense: true, border: OutlineInputBorder()),
            items: [for (final r in roles) DropdownMenuItem(value: r, child: Text(r))],
            onChanged: (v) => setState(() => c.role = v ?? c.role),
          ),
        ),
      ]),
    );
  }
}

/// "568 was cancelled in 2011 (E&C33)..." with one button per replacing class. Returns the UDC string with that
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
      title: const Text('Cancelled UDC notation'),
      content: SizedBox(
        width: 560,
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('This UDC number uses ${hits.length == 1 ? 'a notation that was' : 'notations that were'} '
                'cancelled in the UDC. You can replace ${hits.length == 1 ? 'it' : 'them'} or save it as it is.'),
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
                      TextSpan(text: '  cancelled ${c.when}  ', style: TextStyle(color: cs.onSurfaceVariant)),
                      TextSpan(text: c.label),
                    ])),
                    const SizedBox(height: 6),
                    if (c.replacedBy.isEmpty)
                      Text(c.note.isEmpty ? 'No replacement.' : c.note, style: TextStyle(color: cs.onSurfaceVariant))
                    else
                      Wrap(spacing: 8, runSpacing: 8, children: [
                        for (final r in c.replacedBy)
                          OutlinedButton(
                            onPressed: () => Navigator.pop(context, _replace(h, r.code)),
                            child: Text(r.exists ? 'Use ${r.code}  ${r.label(lang)}' : 'Use ${r.code}',
                                overflow: TextOverflow.ellipsis),
                          ),
                      ]),
                  ]),
                ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Back to editing')),
        FilledButton.tonal(onPressed: () => Navigator.pop(context, udc), child: const Text('Save as it is')),
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
      _Kind.success => const Color(0xFF2E7D32),
      _Kind.error => cs.error,
      _Kind.warning => const Color(0xFFB26A00),
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
