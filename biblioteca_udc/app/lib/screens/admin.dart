import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/api.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../widgets/compact_dropdown.dart';

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
      if (mounted) setState(() => _error = tr(e.message));
    }
  }

  Future<void> _run(Future<void> Function() fn, {String? done}) async {
    try {
      await fn();
      if (done != null && mounted) toast(context, done);
      await _load();
    } on ApiException catch (e) {
      if (mounted) toast(context, tr(e.message), error: true);
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
          title: Text(tr('New user')),
          content: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: name, decoration: InputDecoration(labelText: tr('Username'))),
            const SizedBox(height: 10),
            TextField(controller: pass, obscureText: true, decoration: InputDecoration(labelText: tr('Password (8+ characters)'))),
            const SizedBox(height: 12),
            CompactDropdown<String>(
              value: role,
              label: tr('Role'),
              options: [
                Opt('viewer', tr('Viewer - can search and open')),
                Opt('editor', tr('Editor - can also add, edit and delete')),
                Opt('admin', tr('Administrator')),
              ],
              onChanged: (v) => setLocal(() => role = v),
            ),
          ]),
          actions: [
            TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
            FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Create user'))),
          ],
        ),
      ),
    );
    if (ok == true && mounted) {
      final api = context.read<AppState>().api;
      await _run(() => api.createUser(name.text.trim(), pass.text, role), done: tr('User created.'));
    }
    // after the dialog's closing animation, which still uses them (disposing earlier showed a red screen)
    Future.delayed(const Duration(milliseconds: 400), () {
      name.dispose();
      pass.dispose();
    });
  }

  Future<void> _resetPassword(UserInfo u) async {
    final pass = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('New password for {u}', {'u': u.username})),
        content: TextField(controller: pass, obscureText: true, decoration: InputDecoration(labelText: tr('Password (8+ characters)'))),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Save'))),
        ],
      ),
    );
    if (ok == true && mounted) {
      final api = context.read<AppState>().api;
      await _run(() => api.patchUser(u.id, {'password': pass.text}), done: tr('Password changed. Their sessions were closed.'));
    }
    Future.delayed(const Duration(milliseconds: 400), pass.dispose);
  }

  Future<void> _deleteUser(UserInfo u) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(tr('Delete {u}?', {'u': u.username})),
        content: Text(tr('The account is removed. Files this person added stay in the library.')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
          FilledButton(style: dangerButton(ctx), onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Delete user'))),
        ],
      ),
    );
    if (ok == true && mounted) {
      final api = context.read<AppState>().api;
      await _run(() => api.deleteUser(u.id), done: tr('User deleted.'));
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Users'))),
      body: _error != null
          ? Center(child: Text(_error!))
          : _users == null
              ? const Center(child: CircularProgressIndicator())
              : ListView(children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 8, 0),
                    child: Row(children: [
                      Expanded(child: Text(tr('Users'), style: Theme.of(context).textTheme.titleMedium)),
                      FilledButton.icon(onPressed: _addUser, icon: const Icon(Icons.person_add_alt, size: 18), label: Text(tr('New user'))),
                      const SizedBox(width: 8),
                    ]),
                  ),
                  for (final u in _users!)
                    ListTile(
                      leading: Icon(u.role == 'admin' ? Icons.shield_outlined : Icons.person_outline),
                      title: Text(u.username + (u.disabled ? '  (${tr('disabled')})' : '')),
                      subtitle: Text(tr(u.role)),
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
                          if (u.role != 'viewer') PopupMenuItem(height: kMenuItemHeight, value: 'viewer', child: Text(tr('Make viewer'))),
                          if (u.role != 'editor') PopupMenuItem(height: kMenuItemHeight, value: 'editor', child: Text(tr('Make editor'))),
                          if (u.role != 'admin') PopupMenuItem(height: kMenuItemHeight, value: 'admin', child: Text(tr('Make administrator'))),
                          PopupMenuItem(height: kMenuItemHeight, value: 'password', child: Text(tr('Reset password'))),
                          PopupMenuItem(height: kMenuItemHeight, value: 'toggle', child: Text(u.disabled ? tr('Enable account') : tr('Disable account'))),
                          PopupMenuItem(height: kMenuItemHeight, value: 'delete', child: Text(tr('Delete user'), style: TextStyle(color: cs.error))),
                        ],
                      ),
                    ),
                  const SizedBox(height: 32),
                ]),
    );
  }
}
