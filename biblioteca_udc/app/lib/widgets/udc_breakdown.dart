import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/theme.dart';
import '../core/udc_notation.dart';
import 'udc_info_dialog.dart';

/// Breakdown of a UDC number, one line per part, with its meaning taken from the tree:
///
///     004.8   Artificial intelligence
///     :       Simple relation
///     61      Medical sciences
///     (460)   Spain
///
/// A meaning in grey italics belongs to a broader class (the number is more detailed than the tree); tapping a
/// part opens its class information. Several numbers separated by ' ; ' are shown one after another.
class UdcBreakdown extends StatelessWidget {
  final String udc;
  final bool compact;
  const UdcBreakdown(this.udc, {super.key, this.compact = false});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final numbers = [for (final n in udc.split(RegExp(r'\s;\s|;'))) if (n.trim().isNotEmpty) n.trim()];
    const size = kFsSmall;
    final rows = <Widget>[];
    for (var k = 0; k < numbers.length; k++) {
      if (k > 0) rows.add(Divider(height: compact ? 8 : 12, color: cs.outlineVariant.withValues(alpha: 0.5)));
      for (final m in explainUdc(s.udc, numbers[k], s.udcLang)) {
        final sign = m.part.isSign;
        final label = Text(
          m.label,
          maxLines: compact ? 1 : 3,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: size,
            color: sign || !m.exact ? cs.onSurfaceVariant : cs.onSurface,
            fontStyle: sign || !m.exact ? FontStyle.italic : null,
          ),
        );
        rows.add(InkWell(
          onTap: m.code.isEmpty ? null : () => showUdcInfo(context, m.code),
          child: Padding(
            padding: EdgeInsets.symmetric(vertical: compact ? 0.5 : 1.5),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                width: compact ? 96 : 110,
                child: Text(m.part.text,
                    style: TextStyle(
                        fontFamily: 'monospace',
                        fontSize: size,
                        fontWeight: FontWeight.w700,
                        color: sign ? cs.tertiary : cs.primary)),
              ),
              Expanded(
                child: m.exact || m.code.isEmpty
                    ? label
                    : Tooltip(message: tr('Meaning of the broader class {c}', {'c': m.code}), child: label),
              ),
            ]),
          ),
        ));
      }
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: rows);
  }
}
