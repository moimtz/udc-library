import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';
import 'rich_note.dart';

/// Information window of a UDC class: scope note, application note, information note, including,
/// examples of combination and "see also". Also used for informative nodes
/// (e.g. "INFORMATION ON SPECIAL AUXILIARY TABLES").
Future<void> showUdcInfo(BuildContext context, String code) {
  return showDialog<void>(context: context, builder: (_) => _UdcInfoDialog(code: code));
}

/// Window of a cancelled notation: when it was cancelled, its old label and the classes that replace it.
Future<void> showCancelledInfo(BuildContext context, String code) {
  return showDialog<void>(context: context, builder: (_) => _CancelledDialog(code: code));
}

class _UdcInfoDialog extends StatefulWidget {
  final String code;
  const _UdcInfoDialog({required this.code});

  @override
  State<_UdcInfoDialog> createState() => _UdcInfoDialogState();
}

class _UdcInfoDialogState extends State<_UdcInfoDialog> {
  final List<String> _history = []; // classes visited through "See also"
  late String _code;
  late Future<UdcNodeInfo> _future;

  @override
  void initState() {
    super.initState();
    _code = widget.code;
    _load();
  }

  void _load() => _future = context.read<AppState>().api.udcNode(_code);

  void _open(String code) => setState(() {
        _history.add(_code);
        _code = code;
        _load();
      });

  void _back() => setState(() {
        _code = _history.removeLast();
        _load();
      });

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final lang = s.udcLang;
    final cs = Theme.of(context).colorScheme;
    final node = s.udc.byCode[_code];
    return Dialog(
      insetPadding: const EdgeInsets.all(12),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640, maxHeight: 720),
        child: FutureBuilder<UdcNodeInfo>(
          future: _future,
          builder: (context, snap) {
            final info = snap.data;
            final code = info == null ? (node?.displayCode ?? _code) : (info.type == 'heading' ? '' : info.code);
            final title = info?.label(lang) ?? node?.label(lang) ?? '';
            return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Padding(
                padding: const EdgeInsets.fromLTRB(8, 10, 8, 0),
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  if (_history.isNotEmpty)
                    IconButton(tooltip: tr('Back'), icon: const Icon(Icons.arrow_back), onPressed: _back)
                  else
                    const Padding(
                      padding: EdgeInsets.fromLTRB(12, 12, 4, 0),
                      child: Icon(Icons.info_outline),
                    ),
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(8, 10, 8, 4),
                      child: Text.rich(
                        TextSpan(children: [
                          if (code.isNotEmpty)
                            TextSpan(
                                text: '$code  ',
                                style: TextStyle(fontWeight: FontWeight.w700, color: cs.primary)),
                          TextSpan(text: title),
                        ]),
                        style: Theme.of(context).textTheme.titleMedium,
                      ),
                    ),
                  ),
                  IconButton(
                      tooltip: tr('Close'), icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
                ]),
              ),
              if (info != null && info.path.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 6),
                  child: Text(
                    info.path.map((p) => p.label(lang)).join(' › '),
                    style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant),
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
              const Divider(height: 1),
              Flexible(child: _body(context, snap, lang)),
            ]);
          },
        ),
      ),
    );
  }

  Widget _body(BuildContext context, AsyncSnapshot<UdcNodeInfo> snap, String lang) {
    if (snap.connectionState != ConnectionState.done) {
      return const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()));
    }
    if (snap.hasError) {
      final e = snap.error;
      final msg = e is ApiException && e.isNetwork
          ? tr('The server cannot be reached. Class notes are only available online.')
          : tr('$e');
      return Padding(padding: const EdgeInsets.all(24), child: Text(msg));
    }
    final info = snap.data!;
    if (info.isEmpty) {
      return Padding(
          padding: const EdgeInsets.all(24), child: Text(tr('There is no additional information for this class.')));
    }
    final scope = UdcNodeInfo.inLang(info.scope, lang);
    final app = UdcNodeInfo.inLang(info.app, lang);
    final infoNote = UdcNodeInfo.inLang(info.info, lang);
    final including = UdcNodeInfo.inLang(info.including, lang);
    final examples = UdcNodeInfo.inLang(info.examples, lang);
    return SelectionArea(
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(24, 12, 24, 20),
        children: [
          if (scope.isNotEmpty) _Section(tr('Scope note'), Icons.crop_free, [for (final t in scope) _Para(t, _open)]),
          if (app.isNotEmpty)
            _Section(tr('Application note'), Icons.build_outlined, [for (final t in app) _Para(t, _open)]),
          if (infoNote.isNotEmpty)
            _Section(tr('Information note'), Icons.lightbulb_outline, [for (final t in infoNote) _Para(t, _open)]),
          if (including.isNotEmpty)
            _Section(tr('Including'), Icons.crop_square, [for (final t in including) _Para(t, _open)]),
          if (examples.isNotEmpty)
            _Section(tr('Examples of combination'), Icons.join_inner, [for (final x in examples) _ExampleRow(x)]),
          if (info.replaces.isNotEmpty || info.earlier.isNotEmpty) _moreInfo(context, info, lang),
          if (info.related.isNotEmpty)
            _Section(tr('See also'), Icons.arrow_forward, [
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final r in info.related)
                  ActionChip(
                    label: Text('${r.code}  ${r.label(lang)}', overflow: TextOverflow.ellipsis),
                    tooltip: tr('Show the information of {c}', {'c': r.code}),
                    onPressed: () => _open(r.code),
                  ),
              ]),
            ]),
        ],
      ),
    );
  }

  /// "More info": cancelled classes now classed here and earlier meanings of this notation. Collapsed unless
  /// it is the only information of the class.
  Widget _moreInfo(BuildContext context, UdcNodeInfo info, String lang) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          initiallyExpanded: !info.hasNotes,
          tilePadding: EdgeInsets.zero,
          childrenPadding: const EdgeInsets.only(left: 4),
          expandedCrossAxisAlignment: CrossAxisAlignment.start,
          title: Text(tr('More info'), style: TextStyle(fontWeight: FontWeight.w700, color: cs.primary)),
          subtitle: Text(
            [
              if (info.replaces.isNotEmpty) tr('{n} cancelled class(es) now classed here', {'n': info.replaces.length}),
              if (info.earlier.isNotEmpty) tr('notation used before with another meaning'),
            ].join(' · '),
            style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant),
          ),
          children: [
            if (info.earlier.isNotEmpty)
              _Section(tr('Earlier meaning of this notation'), Icons.history, [
                for (final c in info.earlier)
                  _CancellationView(c, lang: lang, onOpen: (code) => _open(code), showCode: false),
              ]),
            if (info.replaces.isNotEmpty)
              _Section(tr('Replaces cancelled classes'), Icons.history_toggle_off, [
                for (final r in info.replaces)
                  InkWell(
                    onTap: () => showCancelledInfo(context, r.code),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 3),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        ConstrainedBox(
                          constraints: const BoxConstraints(minWidth: 150),
                          child: Padding(
                            padding: const EdgeInsets.only(right: 12),
                            child: Text(r.code,
                                style: TextStyle(
                                    fontWeight: FontWeight.w600,
                                    color: cs.onSurfaceVariant,
                                    decoration: TextDecoration.lineThrough)),
                          ),
                        ),
                        Expanded(child: Text('${r.label}  ${cancelledWhen(r.year, r.ec)}')),
                      ]),
                    ),
                  ),
              ]),
          ],
        ),
      ),
    );
  }
}

/// One cancellation: "cancelled [2011, E&C33]", old label, including, note and the replacing classes.
class _CancellationView extends StatelessWidget {
  final UdcCancellation c;
  final String lang;
  final void Function(String code) onOpen; // opens a replacing class
  final bool showCode;
  const _CancellationView(this.c, {required this.lang, required this.onOpen, this.showCode = true});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('${showCode ? '${c.code}  ' : ''}${tr('cancelled')} ${c.when}',
            style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant)),
        const SizedBox(height: 2),
        Text(c.label, style: const TextStyle(height: 1.35)),
        if (c.including.isNotEmpty)
          Text('${tr('Including')}: ${c.including}', style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant)),
        const SizedBox(height: 6),
        if (c.replacedBy.isEmpty)
          Text(c.note.isEmpty ? tr('No replacement') : tr(c.note), style: TextStyle(color: cs.onSurfaceVariant))
        else
          Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            Text(tr('Replaced by'), style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant)),
            for (final r in c.replacedBy)
              r.exists
                  ? ActionChip(
                      label: Text('${r.code}  ${r.label(lang)}', overflow: TextOverflow.ellipsis),
                      tooltip: tr('Show the information of {c}', {'c': r.code}),
                      onPressed: () => onOpen(r.code),
                    )
                  : Chip(label: Text(r.code)), // a combination, or a class not in this tree
          ]),
        if (c.replacedBy.isNotEmpty && c.note.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text(c.note, style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant)),
          ),
      ]),
    );
  }
}

class _CancelledDialog extends StatefulWidget {
  final String code;
  const _CancelledDialog({required this.code});

  @override
  State<_CancelledDialog> createState() => _CancelledDialogState();
}

class _CancelledDialogState extends State<_CancelledDialog> {
  late Future<List<UdcCancellation>> _future;

  @override
  void initState() {
    super.initState();
    _future = context.read<AppState>().api.udcCancelled(widget.code);
  }

  @override
  Widget build(BuildContext context) {
    final lang = context.watch<AppState>().udcLang;
    final cs = Theme.of(context).colorScheme;
    return Dialog(
      insetPadding: const EdgeInsets.all(12),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 640, maxHeight: 640),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 14, 8, 6),
            child: Row(children: [
              Icon(Icons.history, color: cs.onSurfaceVariant),
              const SizedBox(width: 10),
              Expanded(
                child: Text.rich(
                  TextSpan(children: [
                    TextSpan(
                        text: '${widget.code}  ',
                        style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: cs.onSurfaceVariant,
                            decoration: TextDecoration.lineThrough)),
                    TextSpan(text: tr('Cancelled notation')),
                  ]),
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              IconButton(tooltip: tr('Close'), icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
            ]),
          ),
          const Divider(height: 1),
          Flexible(
            child: FutureBuilder<List<UdcCancellation>>(
              future: _future,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()));
                }
                if (snap.hasError) {
                  final e = snap.error;
                  return Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(e is ApiException && e.isNetwork
                        ? tr('The server cannot be reached. This information is only available online.')
                        : tr('$e')),
                  );
                }
                return SelectionArea(
                  child: ListView(
                    shrinkWrap: true,
                    padding: const EdgeInsets.fromLTRB(24, 12, 24, 20),
                    children: [
                      for (final c in snap.data!)
                        _CancellationView(c,
                            lang: lang, showCode: false, onOpen: (code) => showUdcInfo(context, code)),
                      Text(tr('Do not use a cancelled notation for new items; use one of the replacing classes.'),
                          style: TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant)),
                    ],
                  ),
                );
              },
            ),
          ),
        ]),
      ),
    );
  }
}

/// A section of the information window: coloured title with an icon, the text in a soft card.
class _Section extends StatelessWidget {
  final String title;
  final IconData icon;
  final List<Widget> children;
  const _Section(this.title, this.icon, this.children);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(icon, size: 16, color: cs.primary),
          const SizedBox(width: 6),
          Text(title.toUpperCase(),
              style: TextStyle(
                  fontSize: kFsSmall, fontWeight: FontWeight.w800, letterSpacing: 0.8, color: cs.primary)),
        ]),
        const SizedBox(height: 6),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
          decoration: BoxDecoration(
            color: cs.surfaceContainerLow,
            borderRadius: BorderRadius.circular(kRadius),
            border: Border(left: BorderSide(color: cs.primary.withValues(alpha: 0.5), width: 3)),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: children),
        ),
      ]),
    );
  }
}

/// A note: split where it enumerates ("A.", "(a)"), notations painted and tappable (see rich_note.dart).
class _Para extends StatelessWidget {
  final String text;
  final void Function(String code) onOpen;
  const _Para(this.text, this.onOpen);

  @override
  Widget build(BuildContext context) {
    final index = context.read<AppState>().udc;
    return RichNote(text, exists: (c) => index.byCode.containsKey(c), onCode: onOpen);
  }
}

/// "◇ 330.322.014.3   Net investment"
class _ExampleRow extends StatelessWidget {
  final UdcExample x;
  const _ExampleRow(this.x);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text('◇ ', style: TextStyle(color: cs.onSurfaceVariant)),
        ConstrainedBox(
          constraints: const BoxConstraints(minWidth: 150),
          child: Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Text(x.code, style: TextStyle(fontWeight: FontWeight.w600, color: cs.primary)),
          ),
        ),
        Expanded(child: Text(x.label)),
      ]),
    );
  }
}
