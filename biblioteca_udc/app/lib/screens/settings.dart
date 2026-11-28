import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../widgets/compact_dropdown.dart';

/// Language of the whole app: menus, help, Zotero's field names and the UDC tree. A UDC class without a name
/// in that language is shown in English.
Widget _langTile(AppState s) {
  final langs = s.udc.labelLangs;
  final total = s.udc.byCode.length;
  String treePct(String l) {
    final n = langs.where((e) => e.key == l).map((e) => e.value).firstOrNull ?? 0;
    return total == 0 ? '' : tr('UDC tree: {p}% of the classes in this language', {'p': (100 * n / total).round()});
  }

  return ListTile(
    title: Text(tr('Language')),
    subtitle: Text(
        '${tr('The whole app, the Zotero fields and the UDC tree. Classes without a name in this language are shown in English.')}'
        '${total == 0 ? '' : '\n${treePct(uiLang)}'}'),
    isThreeLine: total > 0,
    trailing: Framed(
      padding: const EdgeInsets.symmetric(horizontal: 6),
      child: CompactDropdown<String>(
        value: uiLang,
        options: [for (final e in uiLanguages.entries) Opt(e.key, e.value)],
        onChanged: s.changeLanguage,
      ),
    ),
  );
}

class SettingsScreen extends StatelessWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    const limits = [0.5, 1.0, 2.0, 5.0, 10.0, 20.0];
    final limit = limits.contains(s.cache.limitGb) ? s.cache.limitGb : 2.0;
    final used = s.stats?['used_bytes'] as int?;
    final max = s.stats?['max_bytes'] as int?;

    Widget section(String t) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 20, 16, 6),
          child: Text(t, style: Theme.of(context).textTheme.titleSmall?.copyWith(color: cs.primary)),
        );

    return Scaffold(
      appBar: AppBar(title: Text(tr('Settings'))),
      body: ListView(children: [
        section(tr('Server')),
        ListTile(title: Text(tr('Address')), subtitle: Text(s.serverUrl)),
        if (used != null && max != null)
          ListTile(
            title: Text(tr('Server storage')),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                LinearProgressIndicator(value: max == 0 ? 0 : (used / max).clamp(0.0, 1.0)),
                const SizedBox(height: 4),
                Text(tr('{u} of {m}  (limit set in run_server.bat)', {'u': formatBytes(used), 'm': formatBytes(max)})),
              ]),
            ),
          ),
        section(tr('Appearance')),
        _langTile(s),
        ListTile(
          title: Text(tr('Palette')),
          subtitle: Text(tr('Colours of the app; each palette has a light and a dark version.')),
          trailing: Framed(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: CompactDropdown<String>(
              value: s.palette.id,
              options: [for (final p in kPalettes) Opt(p.id, tr(p.name), leading: PaletteSwatch(p))],
              onChanged: (id) => s.setPalette(paletteById(id)),
            ),
          ),
        ),
        const SizedBox(height: 8),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: SegmentedButton<ThemeMode>(
            segments: [
              ButtonSegment(value: ThemeMode.system, label: Text(tr('System'))),
              ButtonSegment(value: ThemeMode.light, label: Text(tr('Light'))),
              ButtonSegment(value: ThemeMode.dark, label: Text(tr('Dark'))),
            ],
            selected: {s.themeMode},
            onSelectionChanged: (v) => s.setTheme(v.first),
          ),
        ),
        section(tr('Offline files on this device')),
        ListTile(
          title: Text(tr('Cache size limit')),
          subtitle: Text(tr('Least recently used files are removed beyond this size. Files marked "Keep offline" are never removed.')),
          trailing: Framed(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: CompactDropdown<double>(
              value: limit,
              options: [for (final l in limits) Opt(l, '${l == l.roundToDouble() ? l.toInt() : l} GB')],
              onChanged: s.setCacheGb,
            ),
          ),
        ),
        ListTile(
          title: Text(tr('In use')),
          subtitle: Text(tr('Cache: {c}   |   Kept offline: {k}',
              {'c': formatBytes(s.cache.unpinnedBytes), 'k': formatBytes(s.cache.pinnedBytes)})),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            OutlinedButton(
              onPressed: () async {
                await s.cache.clear();
                if (context.mounted) toast(context, tr('Cache cleared. Files kept offline were not touched.'));
              },
              child: Text(tr('Clear cache')),
            ),
            OutlinedButton(
              onPressed: () async {
                final ok = await showDialog<bool>(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: Text(tr('Remove all offline files?')),
                    content: Text(tr('This also removes the files marked "Keep offline" from this device. They stay on the server.')),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
                      FilledButton(style: dangerButton(ctx), onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Remove all'))),
                    ],
                  ),
                );
                if (ok == true) await s.cache.clear(includePinned: true);
              },
              child: Text(tr('Remove everything')),
            ),
          ]),
        ),
        const SizedBox(height: 32),
      ]),
    );
  }
}
