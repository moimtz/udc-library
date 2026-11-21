import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/api.dart';
import '../core/app_state.dart';
import '../core/models.dart';

class TrashScreen extends StatefulWidget {
  const TrashScreen({super.key});

  @override
  State<TrashScreen> createState() => _TrashScreenState();
}

class _TrashScreenState extends State<TrashScreen> {
  List<Item>? _items;
  String? _error;

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
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _restore(Item it) async {
    final s = context.read<AppState>();
    try {
      await s.api.restore(it.id);
      await s.refreshAfterChange();
      if (mounted) toast(context, 'Restored.');
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _purge(Item it) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Delete permanently?'),
        content: Text('"${it.title}" and its PDF will be erased from the server. This cannot be undone.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete permanently')),
        ],
      ),
    );
    if (ok != true || !mounted) return;
    final s = context.read<AppState>();
    try {
      await s.api.deleteForever(it.id);
      await s.refreshAfterChange();
      _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final days = context.watch<AppState>().stats?['trash_days'] ?? 30;
    return Scaffold(
      appBar: AppBar(title: const Text('Trash')),
      body: _error != null
          ? Center(child: Text(_error!))
          : _items == null
              ? const Center(child: CircularProgressIndicator())
              : _items!.isEmpty
                  ? const Center(child: Text('The trash is empty.'))
                  : ListView(children: [
                      Padding(
                        padding: const EdgeInsets.all(16),
                        child: Text('Items are erased automatically $days days after they were moved here.'),
                      ),
                      for (final it in _items!)
                        ListTile(
                          title: Text(it.title, maxLines: 2, overflow: TextOverflow.ellipsis),
                          subtitle: Text([
                            if (it.creatorsText.isNotEmpty) it.creatorsText,
                            if (it.year != null) '${it.year}',
                            formatBytes(it.size),
                          ].join('  |  ')),
                          trailing: Wrap(children: [
                            TextButton(onPressed: () => _restore(it), child: const Text('Restore')),
                            TextButton(
                              onPressed: () => _purge(it),
                              style: TextButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error),
                              child: const Text('Delete'),
                            ),
                          ]),
                        ),
                    ]),
    );
  }
}
