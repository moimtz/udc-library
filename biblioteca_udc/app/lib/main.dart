import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:provider/provider.dart';

import 'core/app_state.dart';
import 'core/i18n.dart';
import 'core/theme.dart';
import 'screens/home.dart';
import 'screens/login.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final state = AppState();
  state.init();
  runApp(ChangeNotifierProvider.value(value: state, child: const BibliotecaApp()));
}

class BibliotecaApp extends StatelessWidget {
  const BibliotecaApp({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return MaterialApp(
      onGenerateTitle: (_) => tr('UDC Library'),
      debugShowCheckedModeBanner: false,
      themeMode: s.themeMode,
      theme: buildTheme(Brightness.light, s.palette),
      darkTheme: buildTheme(Brightness.dark, s.palette),
      // Flutter's own texts (Copy, Paste, Back, Cancel of the system dialogs) in the chosen language
      locale: Locale(uiLang),
      supportedLocales: [for (final l in uiLanguages.keys) Locale(l)],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
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
