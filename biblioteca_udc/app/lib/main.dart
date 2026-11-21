import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'core/app_state.dart';
import 'screens/home.dart';
import 'screens/login.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState();
  state.init();
  runApp(ChangeNotifierProvider.value(value: state, child: const BibliotecaApp()));
}

ThemeData _theme(Brightness b) {
  final scheme = ColorScheme.fromSeed(seedColor: const Color(0xFF2F5D62), brightness: b);
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    visualDensity: VisualDensity.adaptivePlatformDensity,
  );
}

class BibliotecaApp extends StatelessWidget {
  const BibliotecaApp({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return MaterialApp(
      title: 'Biblioteca UDC',
      debugShowCheckedModeBanner: false,
      themeMode: s.themeMode,
      theme: _theme(Brightness.light),
      darkTheme: _theme(Brightness.dark),
      home: s.booting
          ? const Scaffold(body: Center(child: CircularProgressIndicator()))
          : s.startupError != null
              ? Scaffold(
                  body: Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: SelectableText(s.startupError!),
                    ),
                  ),
                )
              : (s.loggedIn ? const HomeScreen() : const LoginScreen()),
    );
  }
}
