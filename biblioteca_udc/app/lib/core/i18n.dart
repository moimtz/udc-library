import 'l10n_es.dart';

/// Interface language. The texts are written in English in the code and wrapped in tr('...'); the
/// translations live in one table per language (l10n_es.dart). A text missing from the table is shown in
/// English, so a forgotten translation never breaks the app.
///
/// To correct a translation, edit l10n_es.dart (the English text on the left must stay exactly as in the code).
/// To add a language: copy l10n_es.dart (e.g. l10n_fr.dart), translate the right-hand side, and add it to
/// [_tables] and [uiLanguages].
///
/// Placeholders: tr('{n} results', {'n': 5}) -> '5 resultados' with '{n} results': '{n} resultados'.

/// Languages offered in Settings (code -> name in that language).
const uiLanguages = {'en': 'English', 'es': 'Español'};

const _tables = <String, Map<String, String>>{'es': es};

String _lang = 'en';

/// Current interface language ('en', 'es'). Also used for the UDC class names and for Zotero's labels.
String get uiLang => _lang;

void setUiLang(String code) => _lang = uiLanguages.containsKey(code) ? code : 'en';

/// Zotero locale for the field and type names sent by the server (/api/schema?lang=).
String get zoteroLocale => switch (_lang) { 'es' => 'es-ES', _ => 'en-US' };

String tr(String en, [Map<String, Object?> args = const {}]) {
  var s = _tables[_lang]?[en] ?? en;
  args.forEach((k, v) => s = s.replaceAll('{$k}', '${v ?? ''}'));
  return s;
}
