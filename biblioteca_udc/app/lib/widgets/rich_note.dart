import 'package:flutter/material.dart';

import '../core/theme.dart';

/// Long UDC notes made readable: the text is split where the note enumerates ("A. ...", "(a) ...", "1. ..."),
/// "Examples:" / "e.g." are emphasised and UDC notations are painted (and tappable when [onCode] says the
/// class exists). Used by the class information window and by the help.

// notations inside running text: 62-1/-9  .01/.09  `0/`9  (410)  =112.2  "18"  329.17`23`12  547.426.24`171
final _notationRe = RegExp(r'''(?<![\w])(?:\([0-9=][^()\s]*\)|"[0-9][0-9./]*"|=[0-9][0-9.]*|[-.`'][0-9][0-9.]*(?:/[-.`']?[0-9][0-9.]*)?|[0-9]{1,3}(?:\.[0-9]+)*(?:[-`'.:+/][0-9][0-9.]*)*)(?![\w])''');
final _emphRe = RegExp(r'\b(Examples?:|e\.g\.|Ejemplos?:|p\. ?ej\.|Note:|Nota:|AN:|SN:)');

/// One paragraph (or bullet) of a note.
class _Piece {
  final String marker; // 'A.', '(a)', '' for plain text
  final String text;
  _Piece(this.marker, this.text);
}

List<_Piece> _split(String text) {
  final out = <_Piece>[];
  // a new block starts at "A. ", "B. "... or "(a) ", "(b) "... preceded by the start or a sentence end
  final re = RegExp(r'(?:^|(?<=[.;:]\s))(\([a-z]\)|[A-H]\.|\d\))\s');
  var last = 0;
  var marker = '';
  for (final m in re.allMatches(text)) {
    final before = text.substring(last, m.start).trim();
    if (before.isNotEmpty) out.add(_Piece(marker, before));
    marker = m.group(1)!;
    last = m.end;
  }
  final rest = text.substring(last).trim();
  if (rest.isNotEmpty) out.add(_Piece(marker, rest));
  return out;
}

class RichNote extends StatelessWidget {
  final String text;

  /// Tapping a notation; return false when the class is not in the tree (it is then painted but not tappable).
  final bool Function(String code)? exists;
  final void Function(String code)? onCode;
  const RichNote(this.text, {super.key, this.exists, this.onCode});

  @override
  Widget build(BuildContext context) {
    final pieces = _split(text);
    final cs = Theme.of(context).colorScheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final p in pieces)
        Padding(
          padding: EdgeInsets.only(bottom: 8, left: p.marker.isEmpty ? 0 : 4),
          child: p.marker.isEmpty
              ? richLine(context, p.text, exists: exists, onCode: onCode)
              : Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Container(
                    margin: const EdgeInsets.only(right: 8, top: 1),
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1),
                    decoration: BoxDecoration(
                      color: cs.primaryContainer,
                      borderRadius: BorderRadius.circular(kRadius),
                    ),
                    child: Text(p.marker,
                        style: TextStyle(
                            fontSize: kInfoFontSize - 1, fontWeight: FontWeight.w700, color: cs.onPrimaryContainer)),
                  ),
                  Expanded(child: richLine(context, p.text, exists: exists, onCode: onCode)),
                ]),
        ),
    ]);
  }
}

/// A line of text with notations painted, `code` in back-quotes shown as code, and **bold**.
Widget richLine(BuildContext context, String text,
    {bool Function(String code)? exists, void Function(String code)? onCode, TextStyle? style}) {
  final cs = Theme.of(context).colorScheme;
  final base = style ?? const TextStyle(fontSize: kInfoFontSize, height: 1.4);
  final spans = <InlineSpan>[];
  final marked = RegExp(r'\*\*([^*]+)\*\*|«([^»]+)»');
  var pos = 0;

  void plain(String t) {
    var p = 0;
    final hits = <(int, int, String)>[];
    for (final m in _notationRe.allMatches(t)) {
      hits.add((m.start, m.end, 'code'));
    }
    for (final m in _emphRe.allMatches(t)) {
      if (!hits.any((h) => m.start < h.$2 && m.end > h.$1)) hits.add((m.start, m.end, 'emph'));
    }
    hits.sort((a, b) => a.$1.compareTo(b.$1));
    for (final h in hits) {
      if (h.$1 < p) continue;
      if (h.$1 > p) spans.add(TextSpan(text: t.substring(p, h.$1)));
      final s = t.substring(h.$1, h.$2);
      if (h.$3 == 'emph') {
        spans.add(TextSpan(text: s, style: const TextStyle(fontWeight: FontWeight.w700, fontStyle: FontStyle.italic)));
      } else {
        spans.add(_code(context, s, exists, onCode));
      }
      p = h.$2;
    }
    if (p < t.length) spans.add(TextSpan(text: t.substring(p)));
  }

  for (final m in marked.allMatches(text)) {
    if (m.start > pos) plain(text.substring(pos, m.start));
    if (m.group(1) != null) {
      spans.add(TextSpan(text: m.group(1), style: const TextStyle(fontWeight: FontWeight.w700)));
    } else {
      spans.add(_code(context, m.group(2)!, exists, onCode, chip: true));
    }
    pos = m.end;
  }
  if (pos < text.length) plain(text.substring(pos));
  return Text.rich(TextSpan(style: base.copyWith(color: base.color ?? cs.onSurface), children: spans));
}

InlineSpan _code(BuildContext context, String code, bool Function(String)? exists, void Function(String)? onCode,
    {bool chip = false}) {
  final cs = Theme.of(context).colorScheme;
  final tappable = onCode != null && (exists?.call(code) ?? false);
  final style = TextStyle(
    fontWeight: FontWeight.w700,
    color: cs.primary,
    fontFamily: 'monospace',
    decoration: tappable ? TextDecoration.underline : null,
    decorationColor: cs.primary.withValues(alpha: 0.5),
  );
  if (!chip && !tappable) return TextSpan(text: code, style: style);
  return WidgetSpan(
    alignment: PlaceholderAlignment.middle,
    child: InkWell(
      onTap: tappable ? () => onCode(code) : null,
      borderRadius: BorderRadius.circular(4),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 4),
        decoration: chip
            ? BoxDecoration(color: cs.primaryContainer.withValues(alpha: 0.6), borderRadius: BorderRadius.circular(4))
            : null,
        child: Text(code, style: style),
      ),
    ),
  );
}
