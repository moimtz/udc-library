import 'package:flutter/material.dart';

import '../core/models.dart';

/// Text with search matches painted in a highlight colour.
class HighlightText extends StatelessWidget {
  final String text;
  final Spans? spans;
  final TextStyle? style;
  final int? maxLines;

  const HighlightText(this.text, {super.key, this.spans, this.style, this.maxLines});

  @override
  Widget build(BuildContext context) {
    final base = style ?? DefaultTextStyle.of(context).style;
    final list = spans;
    if (list == null || list.isEmpty) {
      return Text(text, style: base, maxLines: maxLines, overflow: maxLines == null ? null : TextOverflow.ellipsis);
    }
    final hl = base.copyWith(
      backgroundColor: Theme.of(context).brightness == Brightness.dark
          ? const Color(0x99B8860B)
          : const Color(0xB3FFE082),
      color: Theme.of(context).brightness == Brightness.dark ? Colors.white : Colors.black,
    );
    final sorted = [...list]..sort((a, b) => a[0].compareTo(b[0]));
    final children = <TextSpan>[];
    var pos = 0;
    for (final s in sorted) {
      final start = s[0].clamp(0, text.length);
      final end = s[1].clamp(0, text.length);
      if (start < pos || end <= start) continue;
      if (start > pos) children.add(TextSpan(text: text.substring(pos, start)));
      children.add(TextSpan(text: text.substring(start, end), style: hl));
      pos = end;
    }
    if (pos < text.length) children.add(TextSpan(text: text.substring(pos)));
    return Text.rich(TextSpan(style: base, children: children),
        maxLines: maxLines, overflow: maxLines == null ? TextOverflow.clip : TextOverflow.ellipsis);
  }
}
