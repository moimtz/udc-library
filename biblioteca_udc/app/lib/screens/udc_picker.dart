import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../widgets/udc_tree_view.dart';

/// Window with the complete UDC tree. Returns the chosen class code or null.
Future<String?> pickUdc(BuildContext context, {String? initial}) {
  return showDialog<String>(
    context: context,
    builder: (_) => _UdcPickerDialog(initial: initial),
  );
}

class _UdcPickerDialog extends StatefulWidget {
  final String? initial;
  const _UdcPickerDialog({this.initial});

  @override
  State<_UdcPickerDialog> createState() => _UdcPickerDialogState();
}

class _UdcPickerDialogState extends State<_UdcPickerDialog> {
  final _filter = TextEditingController();
  final Set<String> _expanded = {};
  String? _selected;

  @override
  void initState() {
    super.initState();
    final s = context.read<AppState>();
    final init = widget.initial;
    if (init != null && s.udc.byCode.containsKey(init)) {
      _selected = init;
      String? p = s.udc.byCode[init]!.parent;
      while (p != null) {
        _expanded.add(p);
        p = s.udc.byCode[p]?.parent;
      }
    }
  }

  @override
  void dispose() {
    _filter.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    return Dialog(
      insetPadding: const EdgeInsets.all(12),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620, maxHeight: 720),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 18, 12, 4),
            child: Row(children: [
              Expanded(child: Text('Select a UDC class', style: Theme.of(context).textTheme.titleLarge)),
              IconButton(icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
            ]),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: TextField(
              controller: _filter,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                prefixIcon: const Icon(Icons.search),
                hintText: 'Filter by number or name',
                isDense: true,
                border: const OutlineInputBorder(),
                suffixIcon: _filter.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.clear),
                        onPressed: () => setState(_filter.clear),
                      ),
              ),
            ),
          ),
          Row(mainAxisAlignment: MainAxisAlignment.end, children: [
            TextButton(onPressed: () => setState(_expanded.clear), child: const Text('Collapse all')),
            TextButton(
                onPressed: () => setState(() => _expanded
                  ..clear()
                  ..addAll(s.udc.expandable)),
                child: const Text('Expand all')),
            const SizedBox(width: 8),
          ]),
          const Divider(height: 1),
          Expanded(
            child: UdcTreeView(
              index: s.udc,
              expanded: _expanded,
              selected: _selected,
              lang: s.udcLang,
              filter: _filter.text,
              showCounts: false,
              showVirtualRows: false,
              onSelect: (c) => setState(() => _selected = c),
              onToggle: (c) => setState(() {
                if (!_expanded.remove(c)) _expanded.add(c);
              }),
            ),
          ),
          const Divider(height: 1),
          Padding(
            padding: const EdgeInsets.all(12),
            child: Row(children: [
              Expanded(
                child: Text(
                  _selected == null
                      ? 'Tap a class to select it.'
                      : '$_selected  ${s.udc.byCode[_selected]?.label(s.udcLang) ?? ''}',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: cs.onSurfaceVariant),
                ),
              ),
              const SizedBox(width: 8),
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
              FilledButton(
                onPressed: _selected == null ? null : () => Navigator.pop(context, _selected),
                child: const Text('Use this class'),
              ),
            ]),
          ),
        ]),
      ),
    );
  }
}
