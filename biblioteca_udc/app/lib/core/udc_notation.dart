import 'i18n.dart';
import 'models.dart';

/// Splitting of a UDC number into its components, as the server does (server/notation.py, same regex).
///
/// '004.8:61(460)=134.2' -> 004.8 | : | 61 | (460) | =134.2. Each component knows its kind (main number,
/// relation sign, place, language...), which the card and the Number builder use to explain it.

enum UdcKind { time, paren, lang, view, special, common, rel, main, other }

class UdcPart {
  final UdcKind kind;
  final String text;
  final int start;
  final int end;
  const UdcPart(this.kind, this.text, this.start, this.end);
  bool get isSign => kind == UdcKind.rel;
}

final _tokenRe = RegExp(r'("[^"]*")' // time
    r'|(\([^()]*\))' // place, form, ethnic grouping...
    r'|(=[0-9][0-9.]*)' // language
    r'|(\.00[0-9.]*)' // point of view
    r"|(\.0[0-9]+|-[1-9][0-9.]*|['`][0-9][0-9.]*)" // special auxiliaries
    r'|(-0[0-9.]*)' // common auxiliaries of general characteristics
    r'|(::|[:+/])' // relation signs
    r'|([0-9][0-9.]*)'); // main number

const _kinds = [
  UdcKind.time, UdcKind.paren, UdcKind.lang, UdcKind.view, UdcKind.special, UdcKind.common, UdcKind.rel,
  UdcKind.main
];

/// Components of a UDC number; characters that are not UDC notation are skipped.
List<UdcPart> tokenizeUdc(String s) {
  final out = <UdcPart>[];
  var pos = 0;
  while (pos < s.length) {
    final m = _tokenRe.matchAsPrefix(s, pos);
    if (m == null) {
      if (s[pos] == '[' || s[pos] == ']') out.add(UdcPart(UdcKind.rel, s[pos], pos, pos + 1));
      pos++;
      continue;
    }
    for (var g = 1; g <= 8; g++) {
      if (m.group(g) != null) {
        out.add(UdcPart(_kinds[g - 1], m.group(0)!, m.start, m.end));
        break;
      }
    }
    pos = m.end;
  }
  return out;
}

/// Name of a relation sign (also used for the buttons of the Number builder).
String udcSignName(String sign) => switch (sign) {
      '+' => tr('Addition (coordination)'),
      '/' => tr('Consecutive extension'),
      ':' => tr('Simple relation'),
      '::' => tr('Order-fixing relation'),
      '[' || ']' || '[]' => tr('Subgrouping'),
      _ => sign,
    };

/// Generic name of a kind of component, when the class itself is not in the tree.
String udcKindName(UdcKind k, String text) => switch (k) {
      UdcKind.time => tr('time'),
      UdcKind.lang => tr('language'),
      UdcKind.view => tr('point of view'),
      UdcKind.special => tr('special auxiliary'),
      UdcKind.common => tr('general characteristics'),
      UdcKind.paren => text.startsWith('(0')
          ? tr('form')
          : text.startsWith('(=')
              ? tr('ethnic grouping, nationality')
              : tr('place'),
      UdcKind.main => tr('main number'),
      _ => '',
    };

/// One line of the breakdown: '004.8' -> 'Artificial intelligence'. [exact] is false when the meaning is the
/// one of a broader class (the number is more specific than the tree).
class UdcMeaning {
  final UdcPart part;
  final String code; // class of the tree that gives the meaning ('' = none)
  final String label;
  final bool exact;
  const UdcMeaning(this.part, this.code, this.label, this.exact);
}

/// Candidates from the most to the least specific, keeping the wrapper: (460.1) -> (460.1), (460), (46), (4).
List<String> _shorter(String text) {
  var pre = '', body = text, post = '';
  if ((text.startsWith('(') || text.startsWith('"')) && text.length > 2) {
    pre = text[0];
    body = text.substring(1, text.length - 1);
    post = text[text.length - 1];
  }
  final lead = RegExp(r'^[^0-9]*').firstMatch(body)!.group(0)!;
  final out = <String>[];
  while (body.length > lead.length) {
    out.add('$pre$body$post');
    body = body.substring(0, body.length - 1);
    while (body.endsWith('.')) {
      body = body.substring(0, body.length - 1);
    }
  }
  return out;
}

/// Meaning of every component of [udc], looked up in the tree in [lang].
List<UdcMeaning> explainUdc(UdcIndex index, String udc, String lang) {
  final out = <UdcMeaning>[];
  var lastMain = '';
  for (final p in tokenizeUdc(udc)) {
    if (p.isSign) {
      final node = index.byCode[p.text == '[' || p.text == ']' ? '[]' : p.text];
      out.add(UdcMeaning(p, '', node?.label(lang) ?? udcSignName(p.text), true));
      continue;
    }
    final cands = <String>[];
    if (p.kind == UdcKind.main) lastMain = p.text;
    if ((p.kind == UdcKind.special || p.kind == UdcKind.view) && lastMain.isNotEmpty) {
      // special auxiliaries sit next to their main class in the tree ('62-1')
      var m = lastMain;
      while (m.isNotEmpty) {
        cands.add('$m${p.text}');
        m = m.substring(0, m.length - 1);
        while (m.endsWith('.')) {
          m = m.substring(0, m.length - 1);
        }
      }
    }
    cands.addAll(_shorter(p.text));
    String? hit;
    for (final c in cands) {
      if (index.byCode.containsKey(c)) {
        hit = c;
        break;
      }
    }
    if (hit == null) {
      out.add(UdcMeaning(p, '', udcKindName(p.kind, p.text), false));
    } else {
      final exact = hit == p.text || hit.endsWith(p.text);
      out.add(UdcMeaning(p, hit, index.byCode[hit]!.label(lang), exact));
    }
  }
  return out;
}
