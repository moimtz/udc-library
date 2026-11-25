import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/api.dart';
import '../core/app_state.dart';
import '../core/models.dart';

/// Administrator tools: users. (Item types come from Zotero's schema and are not edited in the app.)
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

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Users')),
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
                  const SizedBox(height: 32),
                ]),
    );
  }
}
