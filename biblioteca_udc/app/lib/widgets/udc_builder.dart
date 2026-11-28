import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/theme.dart';
import '../core/udc_notation.dart';
import 'udc_breakdown.dart';
import 'udc_help.dart';
import 'udc_tree_view.dart';

/// "Number builder": a UDC number is put together by clicking classes of the tree and pressing the signs.
/// Returns the number built (or null on Cancel). Used by the search panel and by the item form.
///
/// Wide screens: a floating window. Phones: a full page that looks like the main screen (tree), with the
/// builder's box and signs on top instead of the search panel.
Future<String?> buildUdcNumber(BuildContext context, {String initial = '', String? doneLabel}) {
  final wide = MediaQuery.sizeOf(context).width >= kWideLayout;
  if (wide) {
    return showDialog<String>(
      context: context,
      builder: (_) => Dialog(
        insetPadding: const EdgeInsets.all(12),
        clipBehavior: Clip.antiAlias,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 760, maxHeight: 800),
          child: UdcBuilder(initial: initial, doneLabel: doneLabel),
        ),
      ),
    );
  }
  return Navigator.push<String>(
    context,
    MaterialPageRoute(builder: (_) => Scaffold(body: SafeArea(child: UdcBuilder(initial: initial, doneLabel: doneLabel)))),
  );
}

/// The signs offered as buttons. = ( ) " " -0 are not here: they come with the auxiliary classes of the tree.
const _signs = ['+', '/', ':', '::', '[', ']'];

class UdcBuilder extends StatefulWidget {
  final String initial;
  final String? doneLabel;
  const UdcBuilder({super.key, this.initial = '', this.doneLabel});

  @override
  State<UdcBuilder> createState() => _UdcBuilderState();
}

class _UdcBuilderState extends State<UdcBuilder> {
  late final TextEditingController _number;
  final _filter = TextEditingController();
  final Set<String> _expanded = {};
  String? _selected;
  bool _afterSign = false; // a sign was just pressed: the next class is added after it

  @override
  void initState() {
    super.initState();
    _number = TextEditingController(text: widget.initial.trim());
    _afterSign = _endsWithSign(_number.text);
    final s = context.read<AppState>();
    // open the tree at the last class of the initial number
    final parts = tokenizeUdc(_number.text).where((p) => !p.isSign).toList();
    if (parts.isNotEmpty) {
      final m = explainUdc(s.udc, parts.last.text, s.udcLang);
      final code = m.isEmpty ? '' : m.first.code;
      if (code.isNotEmpty) {
        _selected = code;
        String? p = s.udc.byCode[code]?.parent;
        while (p != null) {
          _expanded.add(p);
          p = s.udc.byCode[p]?.parent;
        }
      }
    }
  }

  @override
  void dispose() {
    _number.dispose();
    _filter.dispose();
    super.dispose();
  }

  static bool _endsWithSign(String t) {
    final parts = tokenizeUdc(t);
    return parts.isNotEmpty && parts.last.isSign;
  }

  void _set(String text) {
    _number.value = TextEditingValue(text: text, selection: TextSelection.collapsed(offset: text.length));
  }

  /// Start of the last "segment" (main number with its auxiliaries) of the text: after the last sign.
  int _segmentStart(String t) {
    final parts = tokenizeUdc(t);
    for (var i = parts.length - 1; i >= 0; i--) {
      if (parts[i].isSign) return parts[i].end;
    }
    return 0;
  }

  /// The rules of a click are explained in the help (udc_help.dart, "How the Number builder works").
  void _onClass(String code) {
    setState(() => _selected = code);
    final clicked = tokenizeUdc(code);
    if (clicked.isEmpty) return;
    if (clicked.length == 1 && clicked.first.isSign) return _onSign(code); // a sign node of the tree (':', '+')
    final t = _number.text.trimRight();
    if (t.isEmpty || _afterSign) {
      _set('$t$code');
      _afterSign = false;
      return;
    }
    final parts = tokenizeUdc(t);
    final last = parts.last;
    final first = clicked.first;
    if (first.kind == UdcKind.main) {
      // special auxiliary listed under its class ('62-1'): when the number already has that class (or a
      // subdivision), only the auxiliary is added
      final lastMain = parts.lastWhere((p) => p.kind == UdcKind.main, orElse: () => last);
      if (clicked.length > 1 && lastMain.kind == UdcKind.main && lastMain.text.startsWith(first.text)) {
        _set(t + code.substring(first.end));
      } else {
        _set(t.substring(0, _segmentStart(t)) + code); // replaces the last part
      }
    } else if (last.kind == first.kind && !last.isSign) {
      _set(t.substring(0, last.start) + code + t.substring(last.end)); // same table: (46) -> (460)
    } else {
      _set(t + code); // an auxiliary is added: 616 + (460) = 616(460)
    }
    _afterSign = false;
  }

  void _onSign(String sign) {
    var t = _number.text.trimRight();
    if (t.isEmpty && sign != '[') return;
    final parts = tokenizeUdc(t);
    if (parts.isNotEmpty && parts.last.isSign && parts.last.text != ']' && sign != '[') {
      t = t.substring(0, parts.last.start); // a sign right after another one replaces it
    }
    setState(() {
      _set(t + sign);
      _afterSign = sign != ']';
    });
  }

  void _backspace() {
    final t = _number.text.trimRight();
    final parts = tokenizeUdc(t);
    setState(() {
      if (parts.isEmpty) {
        _set('');
      } else {
        _set(t.substring(0, parts.last.start));
      }
      _afterSign = _endsWithSign(_number.text);
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final done = widget.doneLabel ?? tr('Done');

    final header = Container(
      color: cs.surfaceContainer,
      padding: const EdgeInsets.fromLTRB(12, 10, 8, 8),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Row(children: [
          Icon(Icons.construction_outlined, size: 20, color: cs.primary),
          const SizedBox(width: 8),
          Expanded(child: Text(tr('Number builder'), style: Theme.of(context).textTheme.titleMedium)),
          SmallIconButton(icon: Icons.help_outline, tooltip: tr('Help'), onPressed: () => showUdcHelp(context)),
          const SizedBox(width: 4),
          IconButton(tooltip: tr('Close'), icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
        ]),
        const SizedBox(height: 6),
        TextField(
          controller: _number,
          onChanged: (v) => setState(() => _afterSign = _endsWithSign(v)),
          style: const TextStyle(fontFamily: 'monospace', fontSize: kFsSection + 1, fontWeight: FontWeight.w700),
          decoration: InputDecoration(
            hintText: tr('Click classes of the tree, or type'),
            filled: true,
            fillColor: cs.surface,
            suffixIcon: _number.text.isEmpty
                ? null
                : IconButton(
                    tooltip: tr('Clear'),
                    icon: const Icon(Icons.clear),
                    onPressed: () => setState(() {
                          _set('');
                          _afterSign = false;
                        })),
          ),
        ),
        const SizedBox(height: kGap),
        Wrap(spacing: 4, runSpacing: 4, crossAxisAlignment: WrapCrossAlignment.center, children: [
          for (final sign in _signs)
            Tooltip(
              message: udcSignName(sign),
              child: OutlinedButton(
                style: OutlinedButton.styleFrom(minimumSize: const Size(40, 32), padding: EdgeInsets.zero),
                onPressed: () => _onSign(sign),
                child: Text(sign, style: const TextStyle(fontFamily: 'monospace', fontWeight: FontWeight.w700, fontSize: kFsSection)),
              ),
            ),
          Tooltip(
            message: tr('Remove the last part'),
            child: OutlinedButton(
              style: OutlinedButton.styleFrom(minimumSize: const Size(40, 32), padding: EdgeInsets.zero),
              onPressed: _number.text.isEmpty ? null : _backspace,
              child: const Icon(Icons.backspace_outlined, size: 17),
            ),
          ),
          if (_afterSign)
            Padding(
              padding: const EdgeInsets.only(left: 6),
              child: Text(tr('Now click the class to add'),
                  style: TextStyle(fontSize: kFsSmall, color: cs.primary, fontStyle: FontStyle.italic)),
            ),
        ]),
        if (_number.text.trim().isNotEmpty) ...[
          const SizedBox(height: kGap),
          ConstrainedBox(
            constraints: const BoxConstraints(maxHeight: 96),
            child: SingleChildScrollView(child: UdcBreakdown(_number.text, compact: true)),
          ),
        ],
      ]),
    );

    return Column(children: [
      header,
      Padding(
        padding: const EdgeInsets.fromLTRB(10, 8, 10, 4),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: _filter,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search, size: 18),
                hintText: tr('Find in the tree (number or name)'),
                suffixIcon: _filter.text.isEmpty
                    ? null
                    : IconButton(icon: const Icon(Icons.clear, size: 18), onPressed: () => setState(_filter.clear)),
              ),
            ),
          ),
          IconButton(
            tooltip: tr('Collapse all'),
            icon: const Icon(Icons.unfold_less),
            onPressed: () => setState(_expanded.clear),
          ),
        ]),
      ),
      const Divider(height: 1),
      Expanded(
        child: Container(
          color: cs.surfaceContainerLowest,
          child: UdcTreeView(
            index: s.udc,
            expanded: _expanded,
            selected: _selected,
            lang: s.udcLang,
            filter: _filter.text,
            showUnclassified: false,
            onSelect: _onClass,
            onToggle: (c) => setState(() {
              if (!_expanded.remove(c)) _expanded.add(c);
            }),
          ),
        ),
      ),
      const Divider(height: 1),
      Padding(
        padding: const EdgeInsets.all(10),
        child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
          TextButton(onPressed: () => Navigator.pop(context), child: Text(tr('Cancel'))),
          const SizedBox(width: 8),
          FilledButton.icon(
            icon: const Icon(Icons.check, size: 18),
            onPressed: () => Navigator.pop(context, _number.text.trim()),
            label: Text(done),
          ),
        ]),
      ),
    ]);
  }
}
