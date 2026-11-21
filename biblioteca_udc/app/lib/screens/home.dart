import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../core/models.dart';
import '../widgets/item_tile.dart';
import '../widgets/udc_tree_view.dart';
import 'admin.dart';
import 'item_form.dart';
import 'settings.dart';
import 'trash.dart';
import 'udc_picker.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return Scaffold(
      appBar: AppBar(
        title: const Text('Biblioteca UDC'),
        actions: [
          if (s.offline)
            TextButton.icon(
              onPressed: s.reconnect,
              icon: const Icon(Icons.cloud_off, size: 18),
              label: const Text('Offline - reconnect'),
            ),
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh),
            onPressed: s.offline ? s.reconnect : s.refreshAfterChange,
          ),
        ],
      ),
      drawer: SideMenu(parentContext: context),
      body: LayoutBuilder(builder: (context, c) {
        final landscape = c.maxWidth >= c.maxHeight;
        const left = _LeftPane();
        const right = _RightPane();
        if (landscape) {
          return Row(children: [
            SizedBox(width: (c.maxWidth * 0.36).clamp(330.0, 520.0).toDouble(), child: left),
            const VerticalDivider(width: 1),
            const Expanded(child: right),
          ]);
        }
        return const Column(children: [
          Expanded(flex: 4, child: left),
          Divider(height: 1),
          Expanded(flex: 6, child: right),
        ]);
      }),
    );
  }
}

// ---------------------------------------------------------------------- side menu
class SideMenu extends StatelessWidget {
  final BuildContext parentContext;
  const SideMenu({super.key, required this.parentContext});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;

    void go(VoidCallback fn) {
      Navigator.pop(context);
      fn();
    }

    return Drawer(
      child: SafeArea(
        child: ListView(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 12),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text('Biblioteca UDC', style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 2),
              Text('${s.user?.username ?? ''}  (${s.user?.role ?? ''})', style: TextStyle(color: cs.onSurfaceVariant)),
            ]),
          ),
          if (s.user?.canEdit ?? false)
            ListTile(
              leading: const Icon(Icons.add_circle_outline),
              title: const Text('Add files'),
              enabled: !s.offline,
              onTap: () => go(() => addFilesFlow(parentContext)),
            ),
          ListTile(
            leading: const Icon(Icons.library_books_outlined),
            title: const Text('Library'),
            onTap: () => go(() => s.offline ? s.reconnect() : s.selectNode(null)),
          ),
          ListTile(
            leading: const Icon(Icons.download_done),
            title: const Text('Saved on this device'),
            subtitle: Text('${s.cache.entries.length} files'),
            onTap: () => go(s.showDownloaded),
          ),
          if (s.user?.canEdit ?? false)
            ListTile(
              leading: const Icon(Icons.delete_outline),
              title: const Text('Trash'),
              enabled: !s.offline,
              onTap: () => go(() => Navigator.push(parentContext, MaterialPageRoute(builder: (_) => const TrashScreen()))),
            ),
          if (s.user?.isAdmin ?? false)
            ListTile(
              leading: const Icon(Icons.admin_panel_settings_outlined),
              title: const Text('Users and resource types'),
              enabled: !s.offline,
              onTap: () => go(() => Navigator.push(parentContext, MaterialPageRoute(builder: (_) => const AdminScreen()))),
            ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('Settings'),
            onTap: () => go(() => Navigator.push(parentContext, MaterialPageRoute(builder: (_) => const SettingsScreen()))),
          ),
          ListTile(
            leading: const Icon(Icons.info_outline),
            title: const Text('About'),
            onTap: () => go(() => showAboutDialog(
                  context: parentContext,
                  applicationName: 'Biblioteca UDC',
                  applicationVersion: '1.0.0',
                  children: const [
                    Text('Multilingual Universal Decimal Classification Summary (UDCC Publication No. 088).\n'
                        'Copyright: UDC Consortium, 2013. Released for use and distribution under the '
                        'Creative Commons Attribution Share Alike 3.0 license.'),
                  ],
                )),
          ),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Sign out'),
            onTap: () => go(s.logout),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------------- left pane
class _LeftPane extends StatelessWidget {
  const _LeftPane();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;

    final fieldItems = <DropdownMenuItem<String>>[
      const DropdownMenuItem(value: 'all', child: Text('All fields')),
      const DropdownMenuItem(value: 'title', child: Text('Title')),
      const DropdownMenuItem(value: 'creators', child: Text('Authors')),
      const DropdownMenuItem(value: 'year', child: Text('Year')),
      const DropdownMenuItem(value: 'type', child: Text('Type')),
      const DropdownMenuItem(value: 'language', child: Text('Language')),
      const DropdownMenuItem(value: 'udc', child: Text('UDC')),
      const DropdownMenuItem(value: 'citekey', child: Text('Citation key')),
      for (final e in s.schema.fields.entries)
        DropdownMenuItem(value: e.key, child: Text(e.value.label)),
    ];
    final fieldValue = fieldItems.any((d) => d.value == s.field) ? s.field : 'all';

    return Column(children: [
      Padding(
        padding: const EdgeInsets.fromLTRB(10, 10, 10, 4),
        child: Row(children: [
          Expanded(
            child: TextField(
              controller: s.searchController,
              onSubmitted: (_) => s.submitSearch(),
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: 'Search the library',
                isDense: true,
                prefixIcon: const Icon(Icons.search),
                border: const OutlineInputBorder(),
                errorText: s.searchError,
                errorMaxLines: 2,
                suffixIcon: IconButton(
                  tooltip: 'Clear',
                  icon: const Icon(Icons.clear),
                  onPressed: () {
                    s.searchController.clear();
                    s.submitSearch();
                  },
                ),
              ),
            ),
          ),
          IconButton(
            tooltip: 'Filters',
            icon: Badge(isLabelVisible: s.hasActiveFilters, child: const Icon(Icons.tune)),
            onPressed: () => showFilterDialog(context),
          ),
        ]),
      ),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 10),
        child: Row(children: [
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(children: [
                _opt(context, 'Aa', 'Match case', s.caseSensitive, (v) => s.setSearchOption(caseSensitive: v)),
                _opt(context, 'Word', 'Whole word', s.whole, (v) => s.setSearchOption(whole: v)),
                _opt(context, '.*', 'Regular expression', s.regex, (v) => s.setSearchOption(regex: v)),
                const SizedBox(width: 6),
                DropdownButton<String>(
                  value: fieldValue,
                  underline: const SizedBox.shrink(),
                  isDense: true,
                  items: fieldItems,
                  onChanged: (v) => s.setSearchOption(field: v),
                ),
              ]),
            ),
          ),
          IconButton(
            tooltip: 'Collapse all',
            icon: const Icon(Icons.unfold_less),
            onPressed: s.collapseAll,
          ),
          IconButton(
            tooltip: 'Expand all',
            icon: const Icon(Icons.unfold_more),
            onPressed: s.expandAll,
          ),
        ]),
      ),
      if (s.udcScope != null || s.hasActiveFilters)
        Padding(
          padding: const EdgeInsets.fromLTRB(10, 0, 10, 4),
          child: Align(
            alignment: Alignment.centerLeft,
            child: Wrap(spacing: 6, runSpacing: 0, children: [
              if (s.udcScope != null)
                InputChip(
                  visualDensity: VisualDensity.compact,
                  label: Text(s.udcScope == 'none'
                      ? 'Unclassified'
                      : 'UDC ${s.udcScope}${s.udc.byCode[s.udcScope] == null ? '' : ' ${s.udc.byCode[s.udcScope]!.label(s.udcLang)}'}',
                      overflow: TextOverflow.ellipsis),
                  onDeleted: s.clearScope,
                ),
              if (s.typeFilter != null)
                InputChip(
                    visualDensity: VisualDensity.compact,
                    label: Text(s.typeLabel(s.typeFilter!)),
                    onDeleted: () => s.applyFilters(
                        yearFrom: s.yearFrom, yearTo: s.yearTo, language: s.languageFilter, scope: s.udcScope)),
              if (s.yearFrom != null || s.yearTo != null)
                InputChip(
                    visualDensity: VisualDensity.compact,
                    label: Text('Year ${s.yearFrom ?? ''}-${s.yearTo ?? ''}'),
                    onDeleted: () => s.applyFilters(type: s.typeFilter, language: s.languageFilter, scope: s.udcScope)),
              if (s.languageFilter != null)
                InputChip(
                    visualDensity: VisualDensity.compact,
                    label: Text('Language ${s.languageFilter}'),
                    onDeleted: () => s.applyFilters(
                        type: s.typeFilter, yearFrom: s.yearFrom, yearTo: s.yearTo, scope: s.udcScope)),
            ]),
          ),
        ),
      const Divider(height: 1),
      Expanded(
        child: Container(
          color: cs.surfaceContainerLowest,
          child: UdcTreeView(
            index: s.udc,
            expanded: s.expanded,
            selected: s.udcScope,
            lang: s.udcLang,
            onSelect: s.selectNode,
            onToggle: s.toggleExpanded,
          ),
        ),
      ),
    ]);
  }

  Widget _opt(BuildContext context, String label, String tip, bool on, ValueChanged<bool> cb) => Padding(
        padding: const EdgeInsets.only(right: 4),
        child: FilterChip(
          label: Text(label),
          tooltip: tip,
          selected: on,
          visualDensity: VisualDensity.compact,
          onSelected: cb,
        ),
      );
}

// ---------------------------------------------------------------------- right pane
class _RightPane extends StatelessWidget {
  const _RightPane();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final heading = s.downloadedMode
        ? 'Saved on this device: ${s.total}'
        : (s.loading ? 'Searching...' : '${s.total} ${s.total == 1 ? 'result' : 'results'}');

    return Column(children: [
      if (s.offline)
        Container(
          width: double.infinity,
          color: cs.tertiaryContainer,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          child: Text('The server is unreachable. Showing files saved on this device.',
              style: TextStyle(color: cs.onTertiaryContainer)),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(14, 6, 6, 0),
        child: Row(children: [
          Expanded(child: Text(heading, style: Theme.of(context).textTheme.titleSmall)),
          if (s.udcScope != null && s.udcScope != 'none' && !s.downloadedMode)
            Padding(
              padding: const EdgeInsets.only(right: 4),
              child: FilterChip(
                label: const Text('Include subclasses'),
                visualDensity: VisualDensity.compact,
                selected: s.includeDesc,
                onSelected: s.setIncludeDesc,
              ),
            ),
          if (!s.downloadedMode) ...[
            DropdownButton<String>(
              value: s.sort,
              underline: const SizedBox.shrink(),
              isDense: true,
              items: const [
                DropdownMenuItem(value: 'title', child: Text('Title')),
                DropdownMenuItem(value: 'author', child: Text('Author')),
                DropdownMenuItem(value: 'year', child: Text('Year')),
                DropdownMenuItem(value: 'added', child: Text('Date added')),
              ],
              onChanged: (v) => s.setSort(v ?? 'title', s.ascending),
            ),
            IconButton(
              tooltip: s.ascending ? 'Ascending' : 'Descending',
              icon: Icon(s.ascending ? Icons.arrow_upward : Icons.arrow_downward, size: 20),
              onPressed: () => s.setSort(s.sort, !s.ascending),
            ),
          ],
        ]),
      ),
      if (s.loading) const LinearProgressIndicator(minHeight: 2) else const SizedBox(height: 2),
      Expanded(child: _results(context, s)),
    ]);
  }

  Widget _results(BuildContext context, AppState s) {
    final cs = Theme.of(context).colorScheme;
    if (s.error != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Text(s.error!, textAlign: TextAlign.center, style: TextStyle(color: cs.error)),
            const SizedBox(height: 12),
            OutlinedButton(onPressed: s.runQuery, child: const Text('Try again')),
          ]),
        ),
      );
    }
    if (s.results.isEmpty && !s.loading) {
      final empty = s.searchController.text.trim().isEmpty && s.udcScope == null && !s.hasActiveFilters;
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            s.downloadedMode
                ? 'Nothing is saved on this device yet. Open a file or choose "Keep offline".'
                : empty
                    ? (s.user?.canEdit ?? false
                        ? 'The library is empty. Open the menu and choose "Add files".'
                        : 'The library is empty.')
                    : 'No results. Change the search, or clear the filters and the selected class.',
            textAlign: TextAlign.center,
            style: TextStyle(color: cs.onSurfaceVariant),
          ),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.only(bottom: 24, top: 4),
      itemCount: s.results.length,
      itemBuilder: (_, i) => ItemTile(key: ValueKey(s.results[i].id), item: s.results[i]),
    );
  }
}

// ---------------------------------------------------------------------- filters
Future<void> showFilterDialog(BuildContext context) async {
  final s = context.read<AppState>();
  var type = s.typeFilter;
  var scope = s.udcScope;
  final from = TextEditingController(text: s.yearFrom?.toString() ?? '');
  final to = TextEditingController(text: s.yearTo?.toString() ?? '');
  final lang = TextEditingController(text: s.languageFilter ?? '');

  await showDialog<void>(
    context: context,
    builder: (ctx) => StatefulBuilder(builder: (ctx, setLocal) {
      return AlertDialog(
        title: const Text('Filters'),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              DropdownButtonFormField<String?>(
                value: type,
                decoration: const InputDecoration(labelText: 'Resource type', border: OutlineInputBorder()),
                items: [
                  const DropdownMenuItem<String?>(value: null, child: Text('Any')),
                  for (final t in s.schema.types) DropdownMenuItem<String?>(value: t.code, child: Text(t.label)),
                ],
                onChanged: (v) => setLocal(() => type = v),
              ),
              const SizedBox(height: 12),
              Row(children: [
                Expanded(
                  child: TextField(
                    controller: from,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)],
                    decoration: const InputDecoration(labelText: 'Year from', border: OutlineInputBorder()),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: TextField(
                    controller: to,
                    keyboardType: TextInputType.number,
                    inputFormatters: [FilteringTextInputFormatter.digitsOnly, LengthLimitingTextInputFormatter(4)],
                    decoration: const InputDecoration(labelText: 'Year to', border: OutlineInputBorder()),
                  ),
                ),
              ]),
              const SizedBox(height: 12),
              TextField(
                controller: lang,
                decoration: const InputDecoration(labelText: 'Language code', hintText: 'es', border: OutlineInputBorder()),
              ),
              const SizedBox(height: 16),
              Text('UDC class', style: Theme.of(ctx).textTheme.titleSmall),
              const SizedBox(height: 6),
              Row(children: [
                Expanded(
                  child: Text(
                    scope == null
                        ? 'Whole library'
                        : scope == 'none'
                            ? 'Unclassified'
                            : '$scope ${s.udc.byCode[scope]?.label(s.udcLang) ?? ''}',
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                OutlinedButton.icon(
                  icon: const Icon(Icons.account_tree_outlined, size: 18),
                  label: const Text('Choose'),
                  onPressed: () async {
                    final code = await pickUdc(ctx, initial: scope);
                    if (code != null) setLocal(() => scope = code);
                  },
                ),
                if (scope != null)
                  IconButton(tooltip: 'Clear', icon: const Icon(Icons.clear), onPressed: () => setLocal(() => scope = null)),
              ]),
            ]),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () {
              Navigator.pop(ctx);
              s.applyFilters(scope: s.udcScope);
            },
            child: const Text('Reset'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              s.applyFilters(
                type: type,
                yearFrom: int.tryParse(from.text.trim()),
                yearTo: int.tryParse(to.text.trim()),
                language: lang.text,
                scope: scope,
              );
            },
            child: const Text('Apply'),
          ),
        ],
      );
    }),
  );
  from.dispose();
  to.dispose();
  lang.dispose();
}
