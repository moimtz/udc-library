import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/api.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  late final TextEditingController _url;
  final _user = TextEditingController();
  final _pass = TextEditingController();
  bool _busy = false;
  bool _show = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: context.read<AppState>().serverUrl);
  }

  @override
  void dispose() {
    _url.dispose();
    _user.dispose();
    _pass.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_url.text.trim().isEmpty || _user.text.trim().isEmpty || _pass.text.isEmpty) {
      setState(() => _error = tr('Enter the server address, username and password.'));
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await context.read<AppState>().login(_url.text, _user.text, _pass.text);
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = tr(e.message));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 400),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Icon(Icons.local_library_outlined, size: 56, color: cs.primary),
              const SizedBox(height: 12),
              Text(tr('UDC Library'), textAlign: TextAlign.center, style: Theme.of(context).textTheme.headlineMedium),
              const SizedBox(height: 28),
              TextField(
                controller: _url,
                keyboardType: TextInputType.url,
                decoration: InputDecoration(labelText: tr('Server address'), hintText: 'http://100.x.y.z:8765'),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _user,
                autofillHints: const [AutofillHints.username],
                decoration: InputDecoration(labelText: tr('Username')),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _pass,
                obscureText: !_show,
                onSubmitted: (_) => _submit(),
                decoration: InputDecoration(
                  labelText: tr('Password'),
                  suffixIcon: IconButton(
                    icon: Icon(_show ? Icons.visibility_off : Icons.visibility),
                    onPressed: () => setState(() => _show = !_show),
                  ),
                ),
              ),
              if (_error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(_error!, style: TextStyle(color: cs.error)),
                ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: _busy ? null : _submit,
                child: _busy
                    ? const SizedBox(height: 18, width: 18, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(tr('Sign in')),
              ),
            ]),
          ),
        ),
      ),
    );
  }
}
