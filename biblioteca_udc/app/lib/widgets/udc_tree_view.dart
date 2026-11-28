import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';
import 'udc_info_dialog.dart';

/// Scrollable UDC tree with guide lines (├ └ │). Used by the main screen and by the Number builder.
///
/// Look: row height [kTreeRowHeight], indentation [kTreeIndent] and colours in core/theme.dart.
class UdcTreeView extends StatelessWidget {
  final UdcIndex index;
  final Set<String> expanded;
  final String? selected;
  final String lang;
  final String filter;
  final bool showUnclassified; // the "Unclassified" row at the end (main screen only)
  final ValueChanged<String> onSelect;
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
    this.showUnclassified = true,
  });

  @override
  Widget build(BuildContext context) {
    final rows = index.rows(expanded, filter: filter, lang: lang);
    final unclassifiedRow = showUnclassified && filter.trim().isEmpty;
    final cancelled = _cancelledMatches(context);
    final extra = cancelled.isEmpty ? 0 : cancelled.length + 1; // section header + rows, after the classes
    final total = rows.length + (unclassifiedRow ? 1 : 0) + extra;
    if (index.isEmpty) {
      return Center(child: Text(tr('The UDC tree is empty.')));
    }
    if (total == 0) {
      return Center(child: Text(tr('No class matches this text.')));
    }
    var maxDepth = 1;
    for (final r in rows) {
      if (r.depth > maxDepth) maxDepth = r.depth;
    }
    return LayoutBuilder(builder: (context, c) {
      // deep branches in a narrow pane: the indentation shrinks so the names stay readable
      final indent = ((c.maxWidth * 0.45) / maxDepth).clamp(6.0, kTreeIndent).toDouble();
      return ListView.builder(
        itemCount: total,
        itemExtent: kTreeRowHeight,
        itemBuilder: (context, i) {
          if (i >= total - extra) {
            final k = i - (total - extra);
            if (k == 0) return const _CancelledHeader();
            final e = cancelled[k - 1];
            return _CancelledRow(e, onTap: () => showCancelledInfo(context, e.code));
          }
          if (unclassifiedRow && i == rows.length) {
            return _Row(
              row: null,
              indent: indent,
              code: '',
              label: tr('Unclassified'),
              muted: true,
              selected: selected == 'none',
              onTap: () => onSelect('none'),
            );
          }
          final r = rows[i];
          final n = r.node;
          final open = filter.trim().isNotEmpty || expanded.contains(n.code);
          return _Row(
            row: r,
            indent: indent,
            open: open,
            code: n.displayCode,
            label: n.label(lang),
            including: n.includingIn(lang),
            selected: selected == n.code,
            heading: n.isHeading || n.isInfo,
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
    });
  }

  static const _maxCancelled = 50;

  /// Cancelled notations (not in the current tree) matching the filter: by notation prefix, or by old label
  /// from 3 characters. They are listed after the classes, greyed out.
  List<CancelledEntry> _cancelledMatches(BuildContext context) {
    final f = foldText(filter.trim());
    if (f.isEmpty) return const [];
    final s = context.watch<AppState>();
    s.ensureCancelledIndex();
    final all = s.cancelledIndex;
    if (all == null) return const [];
    final out = <CancelledEntry>[];
    for (final e in all) {
      if (foldText(e.code).startsWith(f) || (f.length >= 3 && foldText(e.label).contains(f))) {
        out.add(e);
        if (out.length == _maxCancelled) break;
      }
    }
    return out;
  }
}

class _CancelledHeader extends StatelessWidget {
  const _CancelledHeader();

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 10, 10, 0),
      child: Text(tr('Cancelled notations (no longer in the UDC)'),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: kFsSmall, fontWeight: FontWeight.w700, color: cs.onSurfaceVariant)),
    );
  }
}

/// "568  [2011] Sauropsida (fossil)...  -> 56; 598", greyed out.
class _CancelledRow extends StatelessWidget {
  final CancelledEntry e;
  final VoidCallback onTap;
  const _CancelledRow(this.e, {required this.onTap});

  @override
  Widget build(BuildContext context) {
    final muted = Theme.of(context).colorScheme.onSurfaceVariant;
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.only(left: 24, right: 8),
        child: Align(
          alignment: Alignment.centerLeft,
          child: Text.rich(
            TextSpan(children: [
              TextSpan(
                  text: '${e.code}  ',
                  style: TextStyle(fontWeight: FontWeight.w600, decoration: TextDecoration.lineThrough)),
              TextSpan(text: '[${e.year ?? '?'}] ${e.label}'),
              if (e.replacedBy.isNotEmpty) TextSpan(text: '  →  ${e.replacedBy.join('; ')}'),
            ]),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(color: muted, fontSize: kTreeFontSize),
          ),
        ),
      ),
    );
  }
}

class _Row extends StatelessWidget {
  final TreeRow? row; // null = the "Unclassified" row
  final double indent;
  final bool open;
  final String code;
  final String label;
  final String including; // "Including ..." text, shown after a square as in UDC Online
  final bool selected;
  final bool heading;
  final bool muted;
  final VoidCallback onTap;
  final VoidCallback? onToggle;
  final VoidCallback? onInfo; // shows the information window (notes, examples)

  const _Row({
    required this.row,
    required this.indent,
    this.open = false,
    required this.code,
    required this.label,
    this.including = '',
    required this.selected,
    this.heading = false,
    this.muted = false,
    required this.onTap,
    this.onToggle,
    this.onInfo,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final r = row;
    final depth = r?.depth ?? 0;
    final faint = cs.onSurfaceVariant.withValues(alpha: kFaintAlpha);
    // informative texts inside the tree (headings, informative nodes, "Including"): grey as the pane headers
    final info = cs.onSurfaceVariant.withValues(alpha: 0.6);
    final chevron = r?.hasChildren ?? false;

    final text = Text.rich(
      TextSpan(children: [
        if (code.isNotEmpty)
          TextSpan(text: '$code  ', style: TextStyle(fontWeight: FontWeight.w600, color: heading ? info : cs.primary)),
        ..._labelSpans(label, cs),
        if (including.isNotEmpty) ...[
          WidgetSpan(
            alignment: PlaceholderAlignment.middle,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 5),
              child: Icon(Icons.crop_square, size: 10, color: info),
            ),
          ),
          TextSpan(text: including, style: TextStyle(color: info)),
        ],
      ]),
      maxLines: 1,
      overflow: TextOverflow.ellipsis,
      style: TextStyle(
        fontSize: kTreeFontSize,
        fontStyle: muted ? FontStyle.italic : null,
        color: muted ? faint : (heading ? info : null),
        fontWeight: heading ? FontWeight.w600 : null,
        letterSpacing: heading ? 0.3 : null,
      ),
    );

    // full name on hover (long press on a phone), for names cut by a narrow pane
    final tip = [
      if (code.isNotEmpty) code,
      label,
      if (including.isNotEmpty) '\n${tr('Including')}: $including',
    ].join('  ');

    return Material(
      color: selected ? cs.secondaryContainer : Colors.transparent,
      child: InkWell(
        onTap: onTap,
        child: Row(children: [
          SizedBox(
            width: 4 + indent * depth + 22,
            child: CustomPaint(
              painter: r == null ? null : _GuidePainter(r, indent, open, cs.outlineVariant),
              child: Align(
                alignment: Alignment.centerRight,
                child: chevron
                    ? Padding(
                        padding: const EdgeInsets.only(right: 11 - _box / 2),
                        child: InkResponse(
                          onTap: onToggle,
                          radius: 12,
                          child: _ToggleBox(open: open),
                        ),
                      )
                    : null,
              ),
            ),
          ),
          const SizedBox(width: 4),
          Expanded(
            child: Tooltip(
              message: tip,
              preferBelow: false,
              child: text,
            ),
          ),
          if (onInfo != null)
            SmallIconButton(
              icon: Icons.info_outline,
              tooltip: tr('Class information'),
              color: cs.primary.withValues(alpha: kFaintAlpha),
              onPressed: onInfo,
            ),
          // room for the scroll bar, so the (i) never sits under it
          const SizedBox(width: kScrollbarGap),
        ]),
      ),
    );
  }
}

/// "Table 1a - Connecting symbols" -> "Table 1a" in light translucent grey bold, a space, then the name.
final _tableRe = RegExp(
    r'^((?:Table|Tabla|Tableau|Tabelle|Tabella|Tabela|Tabel|Tabulka|Tablica|Taulukko)\s+\d+[a-z]?)\s*[-–—]\s*',
    caseSensitive: false);

List<InlineSpan> _labelSpans(String label, ColorScheme cs) {
  final m = _tableRe.firstMatch(label);
  if (m == null) return [TextSpan(text: label)];
  return [
    TextSpan(
        text: m.group(1),
        style: TextStyle(fontWeight: FontWeight.w700, color: cs.onSurfaceVariant.withValues(alpha: kTableAlpha))),
    const TextSpan(text: ' '),
    TextSpan(text: label.substring(m.end)),
  ];
}

/// Side of the [+] / [-] box of a class with subdivisions.
const _box = 11.0;

/// [+] closed, [-] open: a small framed square, as in classic file trees.
class _ToggleBox extends StatelessWidget {
  final bool open;
  const _ToggleBox({required this.open});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Tooltip(
      message: open ? tr('Collapse') : tr('Expand'),
      child: Container(
        width: _box,
        height: _box,
        decoration: BoxDecoration(
          color: cs.surface,
          border: Border.all(color: cs.onSurfaceVariant.withValues(alpha: 0.75)),
          borderRadius: BorderRadius.circular(2),
        ),
        child: CustomPaint(painter: _SignPainter(open, cs.onSurface)),
      ),
    );
  }
}

class _SignPainter extends CustomPainter {
  final bool open;
  final Color color;
  _SignPainter(this.open, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 1.2;
    final c = size.center(Offset.zero);
    const arm = 2.6;
    canvas.drawLine(c.translate(-arm, 0), c.translate(arm, 0), p);
    if (!open) canvas.drawLine(c.translate(0, -arm), c.translate(0, arm), p);
  }

  @override
  bool shouldRepaint(_SignPainter old) => old.open != open || old.color != color;
}

/// Draws the guide lines: | for the ancestors that continue below, the elbow (|- or L) that joins the row to
/// its parent, and the line going down from an open box to its first subdivision.
class _GuidePainter extends CustomPainter {
  final TreeRow row;
  final double indent;
  final bool open;
  final Color color;
  _GuidePainter(this.row, this.indent, this.open, this.color);

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..color = color
      ..strokeWidth = 1;
    final midY = size.height / 2;
    double c(int level) => 4 + indent * level + 11; // centre of the box of a row at this depth
    final d = row.depth;
    for (var i = 1; i < d; i++) {
      if (i < row.continues.length && row.continues[i]) {
        canvas.drawLine(Offset(c(i - 1), 0), Offset(c(i - 1), size.height), p);
      }
    }
    if (d > 0) {
      final px = c(d - 1);
      canvas.drawLine(Offset(px, 0), Offset(px, row.isLast ? midY : size.height), p);
      final end = row.hasChildren ? c(d) - _box / 2 : c(d) + 3;
      canvas.drawLine(Offset(px, midY), Offset(end, midY), p);
    }
    if (row.hasChildren && open) {
      canvas.drawLine(Offset(c(d), midY + _box / 2), Offset(c(d), size.height), p);
    }
  }

  @override
  bool shouldRepaint(_GuidePainter old) =>
      old.row != row || old.indent != indent || old.open != open || old.color != color;
}
