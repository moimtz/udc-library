import 'package:flutter/material.dart';

import '../core/models.dart';
import 'udc_info_dialog.dart';

/// Scrollable UDC tree. Used by the left pane and by the full-tree picker.
class UdcTreeView extends StatelessWidget {
  final UdcIndex index;
  final Set<String> expanded;
  final String? selected;
  final String lang;
  final String filter;
  final bool showCounts;
  final bool showVirtualRows; // "All items" and "Unclassified"
  final ValueChanged<String?> onSelect;
  final ValueChanged<String> onToggle;

  const UdcTreeView({
    super.key,
    required this.index,
    required this.expanded,
    required this.selected,
    required this.lang,
    required this.onSelect,
    required this.onToggle,
    this.filter = '',
    this.showCounts = true,
    this.showVirtualRows = true,
  });

  @override
  Widget build(BuildContext context) {
    final rows = index.rows(expanded, filter: filter, lang: lang);
    final virtual = showVirtualRows && filter.trim().isEmpty;
    final total = rows.length + (virtual ? 2 : 0);
    if (index.isEmpty) {
      return const Center(child: Text('The UDC tree is empty.'));
    }
    if (total == 0) {
      return const Center(child: Text('No class matches this text.'));
    }
    return ListView.builder(
      itemCount: total,
      itemExtent: 38,
      itemBuilder: (context, i) {
        if (virtual && i == 0) {
          return _Row(
              depth: 0, chevron: false, code: '', label: 'All items', count: null,
              selected: selected == null, onTap: () => onSelect(null));
        }
        if (virtual && i == total - 1) {
          return _Row(
              depth: 0, chevron: false, code: '', label: 'Unclassified',
              count: showCounts ? index.unclassified : null,
              selected: selected == 'none', onTap: () => onSelect('none'));
        }
        final r = rows[i - (virtual ? 1 : 0)];
        final n = r.node;
        final open = filter.trim().isNotEmpty || expanded.contains(n.code);
        return _Row(
          depth: r.depth,
          chevron: r.hasChildren,
          open: open,
          code: n.displayCode,
          label: n.label(lang),
          count: showCounts && !n.isInfo ? n.count : null,
          selected: selected == n.code,
          heading: n.isHeading,
          onToggle: () => onToggle(n.code),
          // headings and informative nodes are not classes: they cannot be selected
          onInfo: n.hasInfo ? () => showUdcInfo(context, n.code) : null,
          onTap: () {
            if (n.isInfo) {
              showUdcInfo(context, n.code);
            } else if (n.isHeading) {
              if (r.hasChildren) onToggle(n.code);
            } else {
              onSelect(n.code);
              if (r.hasChildren && !expanded.contains(n.code)) onToggle(n.code);
            }
          },
        );
      },
    );
  }
}

class _Row extends StatelessWidget {
  final int depth;
  final bool chevron;
  final bool open;
  final String code;
  final String label;
  final int? count;
  final bool selected;
  final bool heading;
  final VoidCallback onTap;
  final VoidCallback? onToggle;
  final VoidCallback? onInfo; // shows the information window (notes, examples)

  const _Row({
    required this.depth,
    required this.chevron,
    this.open = false,
    required this.code,
    required this.label,
    required this.count,
    required this.selected,
    this.heading = false,
    required this.onTap,
    this.onToggle,
    this.onInfo,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Material(
      color: selected ? cs.secondaryContainer : Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: EdgeInsets.only(left: 4.0 + depth * 16, right: 10),
          child: Row(children: [
            SizedBox(
              width: 28,
              child: chevron
                  ? IconButton(
                      padding: EdgeInsets.zero,
                      iconSize: 20,
                      tooltip: open ? 'Collapse' : 'Expand',
                      icon: Icon(open ? Icons.expand_more : Icons.chevron_right),
                      onPressed: onToggle,
                    )
                  : null,
            ),
            if (code.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(right: 8),
                child: Text(code, style: TextStyle(fontWeight: FontWeight.w600, color: cs.primary)),
              ),
            Expanded(
              child: Text(label,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: heading
                      ? TextStyle(fontWeight: FontWeight.w600, color: cs.onSurfaceVariant, letterSpacing: 0.3)
                      : null),
            ),
            if (count != null && count! > 0)
              Text('$count', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
            if (onInfo != null)
              SizedBox(
                width: 30,
                child: IconButton(
                  padding: EdgeInsets.zero,
                  iconSize: 18,
                  tooltip: 'Class information',
                  icon: Icon(Icons.info_outline, color: cs.primary),
                  onPressed: onInfo,
                ),
              ),
          ]),
        ),
      ),
    );
  }
}
