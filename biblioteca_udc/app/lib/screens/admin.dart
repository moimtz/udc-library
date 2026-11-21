import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/api.dart';
import '../core/app_state.dart';
import '../core/models.dart';

/// Administrator tools: users and resource types.
class AdminScreen extends StatefulWidget {
  const AdminScreen({super.key});

  @override
  State<AdminScreen> createState() => _AdminScreenState();
}

class _AdminScreenState extends State<AdminScreen> {
  List<UserInfo>? _users;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final u = await context.read<AppState>().api.users();
      if (mounted) setState(() => _users = u);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _run(Future<void> Function() fn, {String? done}) async {
    try {
      await fn();
      if (done != null && mounted) toast(context, done);
      await _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  Future<void> _addUser() async {
    final name = TextEditingController();
    final pass = TextEditingController();
    var role = 'viewer';
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('New user'),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: name, decoration: const InputDecoration(labelText: 'Username')),
            TextField(controller: pass, obscureText: true, decoration: const InputDecoration(labelText: 'Password (8+ characters)')),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: role,
              decoration: const InputDecoration(labelText: 'Role'),
              items: const [
                DropdownMenuItem(value: 'viewer', child: Text('Viewer - can search and open')),
                DropdownMenuItem(value: 'editor', child: Text('Editor - can also add, edit and delete')),
                DropdownMenuItem(value: 'admin', child: Text('Administrator')),
              ],
              onChanged: (v) => setLocal(() => role = v ?? role),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Create user')),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      final api = context.read<AppState>().api;
      await _run(() => api.createUser(name.text.trim(), pass.text, role), done: 'User created.');
    }
    name.dispose();
    pass.dispose();
  }

  Future<void> _resetPassword(UserInfo u) async {
    final pass = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('New password for ${u.username}'),
        content: TextField(controller: pass, obscureText: true, decoration: const InputDecoration(labelText: 'Password (8+ characters)')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Save')),
        ],
      ),
    );
    if (ok == true && mounted) {
      final api = context.read<AppState>().api;
      await _run(() => api.patchUser(u.id, {'password': pass.text}), done: 'Password changed. Their sessions were closed.');
    }
    pass.dispose();
  }

  Future<void> _deleteUser(UserInfo u) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Delete ${u.username}?'),
        content: const Text('The account is removed. Files this person added stay in the library.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete user')),
        ],
      ),
    );
    if (ok == true && mounted) {
      final api = context.read<AppState>().api;
      await _run(() => api.deleteUser(u.id), done: 'User deleted.');
    }
  }

  Future<void> _addType() async {
    final s = context.read<AppState>();
    final code = TextEditingController();
    final label = TextEditingController();
    final newKey = TextEditingController();
    final newLabel = TextEditingController();
    final chosen = <String>{'abstract', 'keywords', 'url', 'notes'};
    final fields = {...s.schema.fields};

    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          title: const Text('New resource type'),
          content: SizedBox(
            width: 460,
            child: SingleChildScrollView(
              child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                TextField(controller: code, decoration: const InputDecoration(labelText: 'Code', hintText: 'standard')),
                TextField(controller: label, decoration: const InputDecoration(labelText: 'Name shown in the app', hintText: 'Standard')),
                const SizedBox(height: 16),
                const Text('Fields for this type'),
                const SizedBox(height: 6),
                Wrap(spacing: 6, runSpacing: 4, children: [
                  for (final f in fields.values)
                    FilterChip(
                      label: Text(f.label),
                      selected: chosen.contains(f.key),
                      onSelected: (v) => setLocal(() => v ? chosen.add(f.key) : chosen.remove(f.key)),
                    ),
                ]),
                const SizedBox(height: 16),
                const Text('Need a field that does not exist yet?'),
                Row(children: [
                  Expanded(child: TextField(controller: newKey, decoration: const InputDecoration(labelText: 'Key', hintText: 'edition_year'))),
                  const SizedBox(width: 8),
                  Expanded(child: TextField(controller: newLabel, decoration: const InputDecoration(labelText: 'Label'))),
                  IconButton(
                    tooltip: 'Create field',
                    icon: const Icon(Icons.add),
                    onPressed: () async {
                      try {
                        await s.api.addField(newKey.text.trim(), newLabel.text.trim(), 'text');
                        await s.refreshSchema();
                        setLocal(() {
                          fields
                            ..clear()
                            ..addAll(s.schema.fields);
                          chosen.add(newKey.text.trim());
                          newKey.clear();
                          newLabel.clear();
                        });
                      } on ApiException catch (e) {
                        if (ctx.mounted) toast(ctx, e.message, error: true);
                      }
                    },
                  ),
                ]),
              ]),
            ),
          ),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Create type')),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      await _run(() async {
        await s.api.addType(code.text.trim(), label.text.trim(), chosen.toList());
        await s.refreshSchema();
      }, done: 'Resource type created.');
    }
    for (final c in [code, label, newKey, newLabel]) {
      c.dispose();
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Users and resource types')),
      body: _error != null
          ? Center(child: Text(_error!))
          : _users == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 8, 0),
                    child: Row(children: [
                      Expanded(child: Text('Users', style: Theme.of(context).textTheme.titleMedium)),
                      FilledButton.icon(onPressed: _addUser, icon: const Icon(Icons.person_add_alt, size: 18), label: const Text('New user')),
                      const SizedBox(width: 8),
                    ]),
                  ),
                  for (final u in _users!)
                    ListTile(
                      leading: Icon(u.role == 'admin' ? Icons.shield_outlined : Icons.person_outline),
                      title: Text(u.username + (u.disabled ? '  (disabled)' : '')),
                      subtitle: Text(u.role),
                      trailing: PopupMenuButton<String>(
                        onSelected: (v) {
                          final api = s.api;
                          switch (v) {
                            case 'password':
                              _resetPassword(u);
                            case 'delete':
                              _deleteUser(u);
                            case 'toggle':
                              _run(() => api.patchUser(u.id, {'disabled': !u.disabled}));
                            default:
                              _run(() => api.patchUser(u.id, {'role': v}));
                          }
                        },
                        itemBuilder: (_) => [
                          if (u.role != 'viewer') const PopupMenuItem(value: 'viewer', child: Text('Make viewer')),
                          if (u.role != 'editor') const PopupMenuItem(value: 'editor', child: Text('Make editor')),
                          if (u.role != 'admin') const PopupMenuItem(value: 'admin', child: Text('Make administrator')),
                          const PopupMenuItem(value: 'password', child: Text('Reset password')),
                          PopupMenuItem(value: 'toggle', child: Text(u.disabled ? 'Enable account' : 'Disable account')),
                          PopupMenuItem(value: 'delete', child: Text('Delete user', style: TextStyle(color: cs.error))),
                        ],
                      ),
                    ),
                  const Divider(height: 32),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 0, 8, 0),
                    child: Row(children: [
                      Expanded(child: Text('Resource types', style: Theme.of(context).textTheme.titleMedium)),
                      OutlinedButton.icon(onPressed: _addType, icon: const Icon(Icons.add, size: 18), label: const Text('New type')),
                      const SizedBox(width: 8),
                    ]),
                  ),
                  for (final t in s.schema.types)
                    ListTile(
                      title: Text(t.label),
                      subtitle: Text('${t.code}  |  ${t.fields.length} fields'),
                      trailing: t.code == 'other'
                          ? null
                          : IconButton(
                              tooltip: 'Delete type',
                              icon: const Icon(Icons.delete_outline),
                              onPressed: () => _run(() async {
                                await s.api.deleteType(t.code);
                                await s.refreshSchema();
                              }, done: 'Type deleted.'),
                            ),
                    ),
                  const SizedBox(height: 32),
                ]),
    );
  }
}
