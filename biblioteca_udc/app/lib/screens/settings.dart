import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/app_state.dart';
import '../core/models.dart';

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
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(children: [
        section('Server'),
        ListTile(title: const Text('Address'), subtitle: Text(s.serverUrl)),
        if (used != null && max != null)
          ListTile(
            title: const Text('Server storage'),
            subtitle: Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                LinearProgressIndicator(value: max == 0 ? 0 : (used / max).clamp(0.0, 1.0)),
                const SizedBox(height: 4),
                Text('${formatBytes(used)} of ${formatBytes(max)}  (limit set in run_server.bat)'),
              ]),
            ),
          ),
        section('Appearance'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(value: ThemeMode.system, label: Text('System')),
              ButtonSegment(value: ThemeMode.light, label: Text('Light')),
              ButtonSegment(value: ThemeMode.dark, label: Text('Dark')),
            ],
            selected: {s.themeMode},
            onSelectionChanged: (v) => s.setTheme(v.first),
          ),
        ),
        const SizedBox(height: 12),
        ListTile(
          title: const Text('Language of UDC class names'),
          trailing: SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'en', label: Text('English')),
              ButtonSegment(value: 'es', label: Text('Spanish')),
            ],
            selected: {s.udcLang},
            onSelectionChanged: (v) => s.setUdcLang(v.first),
          ),
        ),
        section('Offline files on this device'),
        ListTile(
          title: const Text('Cache size limit'),
          subtitle: const Text('Least recently used files are removed beyond this size. Files marked "Keep offline" are never removed.'),
          trailing: DropdownButton<double>(
            value: limit,
            items: [for (final l in limits) DropdownMenuItem(value: l, child: Text('${l == l.roundToDouble() ? l.toInt() : l} GB'))],
            onChanged: (v) => v == null ? null : s.setCacheGb(v),
          ),
        ),
        ListTile(
          title: const Text('In use'),
          subtitle: Text('Cache: ${formatBytes(s.cache.unpinnedBytes)}   |   Kept offline: ${formatBytes(s.cache.pinnedBytes)}'),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: Wrap(spacing: 8, runSpacing: 8, children: [
            OutlinedButton(
              onPressed: () async {
                await s.cache.clear();
                if (context.mounted) toast(context, 'Cache cleared. Files kept offline were not touched.');
              },
              child: const Text('Clear cache'),
            ),
            OutlinedButton(
              onPressed: () async {
                final ok = await showDialog<bool>(
                  context: context,
                  builder: (ctx) => AlertDialog(
                    title: const Text('Remove all offline files?'),
                    content: const Text('This also removes the files marked "Keep offline" from this device. They stay on the server.'),
                    actions: [
                      TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                      FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Remove all')),
                    ],
                  ),
                );
                if (ok == true) await s.cache.clear(includePinned: true);
              },
              child: const Text('Remove everything'),
            ),
          ]),
        ),
        const SizedBox(height: 32),
      ]),
    );
  }
}
