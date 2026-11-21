import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../core/models.dart';

/// Information window of a UDC class: scope note, application note, including,
/// examples of combination and "see also". Also used for informative nodes
/// (e.g. "INFORMATION ON SPECIAL AUXILIARY TABLES").
Future<void> showUdcInfo(BuildContext context, String code) {
  return showDialog<void>(context: context, builder: (_) => _UdcInfoDialog(code: code));
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
                    IconButton(tooltip: 'Back', icon: const Icon(Icons.arrow_back), onPressed: _back)
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
                      tooltip: 'Close', icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
                ]),
              ),
              if (info != null && info.path.isNotEmpty)
                Padding(
                  padding: const EdgeInsets.fromLTRB(24, 0, 24, 6),
                  child: Text(
                    info.path.map((p) => p.label(lang)).join(' › '),
                    style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
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
          ? 'The server cannot be reached. Class notes are only available online.'
          : '$e';
      return Padding(padding: const EdgeInsets.all(24), child: Text(msg));
    }
    final info = snap.data!;
    if (info.isEmpty) {
      return const Padding(
          padding: EdgeInsets.all(24), child: Text('There is no additional information for this class.'));
    }
    final scope = UdcNodeInfo.inLang(info.scope, lang);
    final app = UdcNodeInfo.inLang(info.app, lang);
    final including = UdcNodeInfo.inLang(info.including, lang);
    final examples = UdcNodeInfo.inLang(info.examples, lang);
    return SelectionArea(
      child: ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(24, 12, 24, 20),
        children: [
          if (scope.isNotEmpty) _Section('Scope note', [for (final t in scope) _Para(t)]),
          if (app.isNotEmpty) _Section('Application note', [for (final t in app) _Para(t)]),
          if (including.isNotEmpty) _Section('Including', [for (final t in including) _Para(t)]),
          if (examples.isNotEmpty)
            _Section('Examples of combination', [for (final x in examples) _ExampleRow(x)]),
          if (info.related.isNotEmpty)
            _Section('See also', [
              Wrap(spacing: 8, runSpacing: 8, children: [
                for (final r in info.related)
                  ActionChip(
                    label: Text('${r.code}  ${r.label(lang)}', overflow: TextOverflow.ellipsis),
                    tooltip: 'Show the information of ${r.code}',
                    onPressed: () => _open(r.code),
                  ),
              ]),
            ]),
        ],
      ),
    );
  }
}

class _Section extends StatelessWidget {
  final String title;
  final List<Widget> children;
  const _Section(this.title, this.children);

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: TextStyle(fontWeight: FontWeight.w700, color: cs.primary)),
        const SizedBox(height: 6),
        ...children,
      ]),
    );
  }
}

class _Para extends StatelessWidget {
  final String text;
  const _Para(this.text);

  @override
  Widget build(BuildContext context) =>
      Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(text, style: const TextStyle(height: 1.35)));
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
