import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';

/// Trash. Restoring and deleting are "optimistic": the row answers at once (spinner), then shows the result
/// (a check, or the error with "Try again") and folds away by itself when it worked.
class TrashScreen extends StatefulWidget {
  const TrashScreen({super.key});

  @override
  State<TrashScreen> createState() => _TrashScreenState();
}

enum _Phase { busy, done, failed }

/// What is happening to one row.
class _Op {
  final bool restore; // true = restore, false = delete permanently
  _Phase phase = _Phase.busy;
  String error = '';
  bool gone = false; // folding away after success
  _Op(this.restore);
}

/// How long the check stays visible before the row folds away.
const _showDone = Duration(milliseconds: 1100);
const _fold = Duration(milliseconds: 250);

class _TrashScreenState extends State<TrashScreen> {
  List<Item>? _items;
  String? _error;
  final Map<int, _Op> _ops = {};

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final list = await context.read<AppState>().api.trash();
      if (mounted) setState(() => _items = list);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = tr(e.message));
    }
  }

  Future<void> _purge(Item it) async {
    // deleting for good cannot be undone: it is the only step that asks first
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Delete permanently?')),
        content: Text(tr('"{t}" and its PDF will be erased from the server. This cannot be undone.', {'t': it.title})),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
          FilledButton(
              style: dangerButton(ctx),
              onPressed: () => Navigator.pop(ctx, true),
              child: Text(tr('Delete permanently'))),
        ],
      ),
    );
    if (ok == true && mounted) _run(it, restore: false);
  }

  /// Runs a restore or a permanent delete for one row, showing its progress in the row itself.
  Future<void> _run(Item it, {required bool restore}) async {
    final s = context.read<AppState>();
    final op = _Op(restore);
    setState(() => _ops[it.id] = op);
    try {
      restore ? await s.api.restore(it.id) : await s.api.deleteForever(it.id);
      if (!mounted) return;
      setState(() => op.phase = _Phase.done);
      s.refreshAfterChange(); // the library and the tree, in the background
      await Future.delayed(_showDone);
      if (!mounted) return;
      setState(() => op.gone = true);
      await Future.delayed(_fold);
      if (!mounted) return;
      setState(() {
        _items?.removeWhere((x) => x.id == it.id);
        _ops.remove(it.id);
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        op.phase = _Phase.failed;
        op.error = tr(e.message);
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final days = context.watch<AppState>().stats?['trash_days'] ?? 30;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Trash'))),
      body: _error != null
          ? Center(child: Text(_error!))
          : _items == null
              ? const Center(child: CircularProgressIndicator())
              : _items!.isEmpty
                  ? Center(child: Text(tr('The trash is empty.')))
                  : ListView(children: [
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text(tr('Items are erased automatically {d} days after they were moved here.', {'d': days})),
                      ),
                      for (final it in _items!) _row(it),
                    ]),
    );
  }

  Widget _row(Item it) {
    final cs = Theme.of(context).colorScheme;
    final op = _ops[it.id];
    final tile = ListTile(
      enabled: op == null || op.phase == _Phase.failed,
      title: Text(it.title, maxLines: 2, overflow: TextOverflow.ellipsis),
      subtitle: Text([
        if (it.creatorsText.isNotEmpty) it.creatorsText,
        if (it.year != null) '${it.year}',
        formatBytes(it.size),
      ].join('  |  ')),
      trailing: AnimatedSwitcher(duration: const Duration(milliseconds: 180), child: _status(it, op, cs)),
    );
    return AnimatedSize(
      key: ValueKey(it.id),
      duration: _fold,
      alignment: Alignment.topCenter,
      child: op?.gone == true ? const SizedBox(width: double.infinity) : tile,
    );
  }

  Widget _status(Item it, _Op? op, ColorScheme cs) {
    if (op == null) {
      return Wrap(key: const ValueKey('actions'), spacing: 6, children: [
        TextButton(onPressed: () => _run(it, restore: true), child: Text(tr('Restore'))),
        TextButton(
          onPressed: () => _purge(it),
          style: TextButton.styleFrom(foregroundColor: cs.error),
          child: Text(tr('Delete')),
        ),
      ]);
    }
    final small = TextStyle(fontSize: kFsSmall, color: cs.onSurfaceVariant);
    switch (op.phase) {
      case _Phase.busy:
        return Row(key: const ValueKey('busy'), mainAxisSize: MainAxisSize.min, children: [
          const SizedBox.square(dimension: 16, child: CircularProgressIndicator(strokeWidth: 2)),
          const SizedBox(width: 8),
          Text(op.restore ? tr('Restoring...') : tr('Deleting...'), style: small),
        ]);
      case _Phase.done:
        final ok = paletteOf(context).action;
        return Row(key: const ValueKey('done'), mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.check_circle, size: 18, color: ok),
          const SizedBox(width: 6),
          Text(op.restore ? tr('Restored') : tr('Deleted'),
              style: TextStyle(fontSize: kFsSmall, fontWeight: FontWeight.w600, color: ok)),
        ]);
      case _Phase.failed:
        return Row(key: const ValueKey('failed'), mainAxisSize: MainAxisSize.min, children: [
          Tooltip(message: op.error, child: Icon(Icons.error_outline, size: 18, color: cs.error)),
          const SizedBox(width: 4),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 220),
            child: Text(op.error,
                maxLines: 2, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: kFsSmall, color: cs.error)),
          ),
          const SizedBox(width: 6),
          TextButton(
            onPressed: () {
              setState(() => _ops.remove(it.id));
              op.restore ? _run(it, restore: true) : _run(it, restore: false);
            },
            child: Text(tr('Try again')),
          ),
        ]);
    }
  }
}
