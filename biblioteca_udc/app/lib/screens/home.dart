import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/theme.dart';
import '../widgets/compact_dropdown.dart';
import '../widgets/item_tile.dart';
import '../widgets/search_panel.dart';
import '../widgets/udc_tree_view.dart';
import 'admin.dart';
import 'item_form.dart';
import 'settings.dart';
import 'trash.dart';

/// Main screen.
///  - Wide (laptop, tablet in landscape): search panel + UDC tree on the left, results on the right. The left
///    pane starts as wide as the search panel (from "UDC number" to "Search", same margin on both sides);
///    drag the divider to change it, double-click it to go back.
///  - Narrow (phone): search panel + tree; "Search" slides the results in from the right (back = return).
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final wide = MediaQuery.sizeOf(context).width >= kWideLayout;
    return Scaffold(
      appBar: AppBar(
        title: Text(tr('UDC Library')),
        toolbarHeight: 46,
        actions: [
          if (s.offline)
            TextButton.icon(
              onPressed: s.reconnect,
              icon: const Icon(Icons.cloud_off, size: 18),
              label: Text(tr('Offline - reconnect')),
            ),
          IconButton(
            tooltip: tr('Refresh'),
            icon: const Icon(Icons.refresh),
            onPressed: s.offline ? s.reconnect : s.refreshAfterChange,
          ),
        ],
      ),
      drawer: SideMenu(parentContext: context, wide: wide),
      body: wide ? const _WideBody() : _TreePane(onSearched: () => openResultsPage(context)),
    );
  }
}

/// Phone: the results as a page that slides in from the right.
void openResultsPage(BuildContext context) {
  if (MediaQuery.sizeOf(context).width >= kWideLayout) return;
  Navigator.of(context).push(PageRouteBuilder(
    transitionDuration: const Duration(milliseconds: 260),
    reverseTransitionDuration: const Duration(milliseconds: 220),
    pageBuilder: (_, __, ___) => const _ResultsPage(),
    transitionsBuilder: (_, anim, __, child) => SlideTransition(
      position: Tween(begin: const Offset(1, 0), end: Offset.zero)
          .animate(CurvedAnimation(parent: anim, curve: Curves.easeOutCubic)),
      child: child,
    ),
  ));
}

class _ResultsPage extends StatelessWidget {
  const _ResultsPage();

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: Text(tr('Results')), toolbarHeight: 46),
        body: const _ResultsPane(),
      );
}

class _WideBody extends StatelessWidget {
  const _WideBody();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return LayoutBuilder(builder: (context, c) {
      final natural = SearchPanel.naturalWidth(context);
      double fit(double w) => w.clamp(c.maxWidth * kTreeMin, c.maxWidth * kTreeMax).toDouble();
      final treeW = fit(s.treeWidth ?? natural);
      return Row(children: [
        SizedBox(width: treeW, child: const _TreePane(withSearch: true)),
        _DragDivider(
          onDrag: (dx) => s.previewTreeWidth(fit(treeW + dx)),
          onEnd: () => s.setTreeWidth(s.treeWidth),
          onReset: () => s.setTreeWidth(null),
        ),
        const Expanded(child: _ResultsPane()),
      ]);
    });
  }
}

/// The vertical line between tree and results; drag it to change their widths.
class _DragDivider extends StatelessWidget {
  final ValueChanged<double> onDrag;
  final VoidCallback onEnd;
  final VoidCallback onReset; // double click: back to the width of the search panel
  const _DragDivider({required this.onDrag, required this.onEnd, required this.onReset});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return MouseRegion(
      cursor: SystemMouseCursors.resizeColumn,
      child: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onHorizontalDragUpdate: (d) => onDrag(d.delta.dx),
        onHorizontalDragEnd: (_) => onEnd(),
        onDoubleTap: onReset,
        child: SizedBox(
          width: 7,
          child: Center(child: Container(width: 1, color: cs.outlineVariant)),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------- side menu
class SideMenu extends StatelessWidget {
  final BuildContext parentContext;
  final bool wide;
  const SideMenu({super.key, required this.parentContext, required this.wide});

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
              Text(tr('UDC Library'), style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 2),
              Text('${s.user?.username ?? ''}  (${tr(s.user?.role ?? '')})', style: TextStyle(color: cs.onSurfaceVariant)),
            ]),
          ),
          if (s.user?.canEdit ?? false)
            ListTile(
              leading: const Icon(Icons.add_circle_outline),
              title: Text(tr('Add files')),
              enabled: !s.offline,
              onTap: () => go(() => addFilesFlow(parentContext)),
            ),
          ListTile(
            leading: const Icon(Icons.library_books_outlined),
            title: Text(tr('Library')),
            onTap: () => go(() {
              s.offline ? s.reconnect() : s.showLibrary();
              openResultsPage(parentContext);
            }),
          ),
          ListTile(
            leading: const Icon(Icons.download_done),
            title: Text(tr('Saved on this device')),
            subtitle: Text(tr('{n} files', {'n': s.cache.entries.length})),
            onTap: () => go(() {
              s.showDownloaded();
              openResultsPage(parentContext);
            }),
          ),
          if (s.user?.canEdit ?? false)
            ListTile(
              leading: const Icon(Icons.delete_outline),
              title: Text(tr('Trash')),
              enabled: !s.offline,
              onTap: () => go(() => Navigator.push(parentContext, MaterialPageRoute(builder: (_) => const TrashScreen()))),
            ),
          if (s.user?.isAdmin ?? false)
            ListTile(
              leading: const Icon(Icons.admin_panel_settings_outlined),
              title: Text(tr('Users')),
              enabled: !s.offline,
              onTap: () => go(() => Navigator.push(parentContext, MaterialPageRoute(builder: (_) => const AdminScreen()))),
            ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: Text(tr('Settings')),
            onTap: () => go(() => Navigator.push(parentContext, MaterialPageRoute(builder: (_) => const SettingsScreen()))),
          ),
          ListTile(
            leading: const Icon(Icons.info_outline),
            title: Text(tr('About')),
            onTap: () => go(() => showAboutDialog(
                  context: parentContext,
                  applicationName: tr('UDC Library'),
                  applicationVersion: '0.2.0',
                  children: [
                    Text(tr('Multilingual Universal Decimal Classification Summary (UDCC Publication No. 088). '
                        'Copyright: UDC Consortium, 2013. Released for use and distribution under the '
                        'Creative Commons Attribution Share Alike 3.0 license.')),
                  ],
                )),
          ),
          ListTile(
            leading: const Icon(Icons.logout),
            title: Text(tr('Sign out')),
            onTap: () => go(s.logout),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------------- tree pane
/// Search panel on top and the UDC tree below. [onSearched] (phone) = slide to the results.
class _TreePane extends StatelessWidget {
  final VoidCallback? onSearched;
  final bool withSearch;
  const _TreePane({this.onSearched, this.withSearch = true});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final faint = cs.onSurfaceVariant.withValues(alpha: 0.6);
    return Column(children: [
      if (withSearch) SearchPanel(onSearched: onSearched),
      PaneHeader(icon: Icons.account_tree_outlined, title: tr('UDC tree'), actions: [
        SmallIconButton(icon: Icons.unfold_less, tooltip: tr('Collapse all'), color: faint, onPressed: s.collapseAll),
      ]),
      Expanded(
        child: Container(
          color: cs.surfaceContainerLowest,
          child: UdcTreeView(
            index: s.udc,
            expanded: s.expanded,
            selected: s.treeSelection,
            lang: s.udcLang,
            onSelect: (code) {
              s.selectNode(code);
              onSearched?.call();
            },
            onToggle: s.toggleExpanded,
          ),
        ),
      ),
    ]);
  }
}

// ---------------------------------------------------------------------- results pane
class _ResultsPane extends StatelessWidget {
  const _ResultsPane();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final heading = s.downloadedMode
        ? tr('Saved on this device: {n}', {'n': s.total})
        : (s.loading ? tr('Searching...') : tr(s.total == 1 ? '{n} result' : '{n} results', {'n': s.total}));
    final n = s.selectedIds.length;
    final all = s.results.isNotEmpty && n == s.results.length;

    return Column(children: [
      if (s.offline)
        Container(
          width: double.infinity,
          color: cs.tertiaryContainer,
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
          child: Text(tr('The server is unreachable. Showing files saved on this device.'),
              style: TextStyle(color: cs.onTertiaryContainer)),
        ),
      Padding(
        padding: const EdgeInsets.fromLTRB(10, 6, 10, 4),
        child: Row(children: [
          Tooltip(
            message: all ? tr('Select none') : tr('Select all'),
            child: SmallCheckbox(
              value: n == 0 ? false : (all ? true : null),
              tristate: true,
              onChanged: s.results.isEmpty ? null : (_) => s.selectAll(!all),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Text(n > 0 ? tr('{n} selected', {'n': n}) : heading,
                maxLines: 1, overflow: TextOverflow.ellipsis, style: Theme.of(context).textTheme.titleSmall),
          ),
          // shrinks (with ...) when the results pane is narrow
          if (!s.downloadedMode) const Flexible(child: _SortSelector()),
        ]),
      ),
      if (n > 0) const _SelectionBar(),
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
            OutlinedButton(onPressed: s.runQuery, child: Text(tr('Try again'))),
          ]),
        ),
      );
    }
    if (s.results.isEmpty && !s.loading) {
      final empty = s.searchController.text.trim().isEmpty && s.udcController.text.trim().isEmpty && !s.unclassified;
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text(
            s.downloadedMode
                ? tr('Nothing is saved on this device yet. Open a file or choose "Keep offline".')
                : empty
                    ? (s.user?.canEdit ?? false
                        ? tr('The library is empty. Open the menu and choose "Add files".')
                        : tr('The library is empty.'))
                    : tr('No results. Change the search or tick fewer options.'),
            textAlign: TextAlign.center,
            style: TextStyle(color: cs.onSurfaceVariant),
          ),
        ),
      );
    }
    return ListView.builder(
      padding: const EdgeInsets.only(bottom: 16, top: 2),
      itemCount: s.results.length,
      itemBuilder: (_, i) => ItemTile(key: ValueKey(s.results[i].id), item: s.results[i]),
    );
  }
}

/// Order of the results, in a frame: [Title v] [up/down].
class _SortSelector extends StatelessWidget {
  const _SortSelector();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    return Framed(
      padding: const EdgeInsets.only(left: 10, right: 2),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        Flexible(
          child: Text('${tr('Sort')}:',
              maxLines: 1,
              overflow: TextOverflow.clip,
              softWrap: false,
              style: TextStyle(fontSize: kFsSmall, color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ),
        const SizedBox(width: 4),
        Flexible(
            child: CompactDropdown<String>(
          value: s.sort,
          options: [
            Opt('title', tr('Title')),
            Opt('author', tr('Author')),
            Opt('year', tr('Year')),
            Opt('added', tr('Date added')),
          ],
          onChanged: (v) => s.setSort(v, s.ascending),
        )),
        SmallIconButton(
          tooltip: s.ascending ? tr('Ascending') : tr('Descending'),
          icon: s.ascending ? Icons.arrow_upward : Icons.arrow_downward,
          onPressed: () => s.setSort(s.sort, !s.ascending),
        ),
      ]),
    );
  }
}

/// Actions on the ticked items.
class _SelectionBar extends StatelessWidget {
  const _SelectionBar();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final canEdit = (s.user?.canEdit ?? false) && !s.offline;
    // just the buttons, left-aligned, a bit taller than the rest (kActionButtonHeight)
    final tall = ButtonStyle(minimumSize: const WidgetStatePropertyAll(Size(0, kActionButtonHeight)));
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 2, 12, 6),
      child: Wrap(spacing: 8, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
        OutlinedButton.icon(
          style: tall,
          onPressed: () => bulkPin(context, s.selectedItems, true),
          icon: const Icon(Icons.offline_pin_outlined, size: 16),
          label: Text(tr('Keep offline')),
        ),
        OutlinedButton.icon(
          style: tall,
          onPressed: () => bulkPin(context, s.selectedItems, false),
          icon: const Icon(Icons.phonelink_erase_outlined, size: 16),
          label: Text(tr('Remove from this device')),
        ),
        if (canEdit)
          OutlinedButton.icon(
            onPressed: () => bulkTrashFlow(context, s.selectedItems),
            style: tall.merge(OutlinedButton.styleFrom(foregroundColor: cs.error, iconColor: cs.error)),
            icon: const Icon(Icons.delete_outline, size: 16),
            label: Text(tr('Move to trash')),
          ),
        TextButton(style: tall, onPressed: () => s.selectAll(false), child: Text(tr('Clear selection'))),
      ]),
    );
  }
}
