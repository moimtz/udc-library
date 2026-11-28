// Widget tests without a server: the screens are drawn with sample data at laptop and phone sizes, in English
// and Spanish. Any overflow (the red stripes) or exception fails the test.
//
// Run inside app_build after setup_app.ps1:  flutter test
import 'package:biblioteca_udc/core/api.dart';
import 'package:biblioteca_udc/core/app_state.dart';
import 'package:biblioteca_udc/core/i18n.dart';
import 'package:biblioteca_udc/core/models.dart';
import 'package:biblioteca_udc/core/theme.dart';
import 'package:biblioteca_udc/core/udc_notation.dart';
import 'package:biblioteca_udc/screens/home.dart';
import 'package:biblioteca_udc/screens/trash.dart';
import 'package:biblioteca_udc/widgets/search_panel.dart';
import 'package:biblioteca_udc/widgets/udc_builder.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

UdcNode node(String code, String? parent, String en, {String? es, int ord = 0, String? type, bool info = false}) =>
    UdcNode(code, parent, {'en': en, if (es != null) 'es': es}, ord, 0, 0, type: type, hasInfo: info);

UdcIndex sampleTree() {
  final nodes = <UdcNode>[
    node('0', null, 'Science and knowledge. Organization. Computer science. Information. Documentation', es: 'Ciencia', ord: 1),
    node('00', '0', 'Prolegomena. Fundamentals of knowledge and culture', ord: 2),
    node('004', '00', 'Computer science and technology. Computing', ord: 3, info: true),
    node('004.8', '004', 'Artificial intelligence', es: 'Inteligencia artificial', ord: 4),
    node('6', null, 'Applied sciences. Medicine. Technology', ord: 5),
    node('61', '6', 'Medical sciences', es: 'Ciencias médicas', ord: 6),
    node('62', '6', 'Engineering. Technology in general', ord: 7),
    node('62-1', '62', 'General characteristics of machines', ord: 8),
    node('(4)', null, 'Europe', ord: 9),
    node('(46)', '(4)', 'Iberian Peninsula', ord: 10),
    node('(460)', '(46)', 'Spain', es: 'España', ord: 11),
    node(':', null, 'Simple relation', ord: 12),
    node('+, /', null, 'Table 1a - Connecting symbols. Coordination. Extension', ord: 13),
  ];
  // a very deep branch with long names (narrow panes used to overflow)
  var parent = '62';
  for (var i = 1; i <= 14; i++) {
    final code = '62${'1' * i}';
    nodes.add(node(code, parent, 'A very long class name number $i that does not fit in a narrow pane at all', ord: 20 + i));
    parent = code;
  }
  return UdcIndex(nodes);
}

Item sampleItem(int id, {bool manyAuthors = false}) => Item.fromJson({
      'id': id,
      'citekey': 'k$id',
      'item_type': 'book',
      'title': 'A rather long title about neural networks and their use in medicine, with a subtitle that goes on $id',
      'year': 2010,
      'fields': {'title': 'Neural networks $id', 'publisher': 'UNAM'},
      'creators': [
        for (var i = 0; i < (manyAuthors ? 9 : 1); i++)
          {'creator_type': 'author', 'first_name': 'Ana', 'last_name': 'Pérez-González $i', 'confirmed': true}
      ],
      'creators_text': manyAuthors ? 'Many authors' : 'Pérez-González 0, Ana',
      'udc': [
        {'notation': '004.8:61(460)=134.2', 'source': 'manual', 'confirmed': true}
      ],
      'udc_text': '004.8:61(460)=134.2',
      'attachments': [
        {'id': id * 10, 'role': 'main', 'filename': 'perez2010neural.pdf', 'size': 123456, 'pages': 300},
        {'id': id * 10 + 1, 'role': 'supplementary', 'label': 'Solutions manual with a long label', 'size': 1000, 'pages': 2},
      ],
      'notes': [
        {'id': 1, 'body': 'Chapter 3 is the important one.'}
      ],
      'added_at': '2026-11-25T14:03:00Z',
    });

Future<AppState> makeState() async {
  SharedPreferences.setMockInitialValues({});
  final s = AppState();
  s.prefs = await SharedPreferences.getInstance();
  s.user = UserInfo(1, 'ed', 'editor', false);
  s.udc = sampleTree();
  s.results = [sampleItem(1, manyAuthors: true), sampleItem(2), sampleItem(3)];
  s.total = 3;
  s.booting = false;
  return s;
}

Widget app(AppState s, Widget home) => ChangeNotifierProvider.value(
      value: s,
      child: MaterialApp(theme: buildTheme(Brightness.light), home: home),
    );

Future<void> setSize(WidgetTester t, Size size) async {
  t.view.physicalSize = size;
  t.view.devicePixelRatio = 1.0;
  addTearDown(t.view.resetPhysicalSize);
  addTearDown(t.view.resetDevicePixelRatio);
}

/// A server that answers from memory: restore works (after a short wait), delete fails.
class FakeApi extends ApiClient {
  FakeApi() : super('http://fake');
  @override
  Future<List<Item>> trash() async => [sampleItem(7), sampleItem(8)];
  @override
  Future<void> restore(int id) => Future.delayed(const Duration(milliseconds: 100));
  @override
  Future<void> deleteForever(int id) async => throw ApiException(500, 'The server is on fire.');
  @override
  Future<UdcIndex> udcTree() async => sampleTree();
  @override
  Future<Map<String, dynamic>> stats() async => {};
  @override
  Future<ItemsPage> items(Map<String, String> q) async => ItemsPage(0, []);
}

void main() {
  test('UDC numbers are split and explained', () {
    final parts = tokenizeUdc('004.8:61(460)=134.2"18"62-1');
    expect(parts.map((p) => p.text), ['004.8', ':', '61', '(460)', '=134.2', '"18"', '62', '-1']);
    final m = explainUdc(sampleTree(), '004.8:61(460.1)', 'en');
    expect(m[0].label, 'Artificial intelligence');
    expect(m[1].label, 'Simple relation');
    expect(m[3].code, '(460)');
    expect(m[3].exact, false); // (460.1) is more specific than the tree
  });

  for (final lang in ['en', 'es']) {
    for (final size in [const Size(1366, 768), const Size(1000, 700), const Size(390, 844), const Size(320, 640)]) {
      testWidgets('home $lang ${size.width.toInt()}x${size.height.toInt()}', (t) async {
        setUiLang(lang);
        await setSize(t, size);
        final s = await makeState();
        s.expanded.addAll(s.udc.expandable);
        await t.pumpWidget(app(s, const HomeScreen()));
        await t.pump();
        if (size.width >= kWideLayout) {
          // open a card with its UDC breakdown, supplementary file, notes and buttons
          s.toggleItem(1);
          await t.pump(const Duration(milliseconds: 300));
          s.selectAll(true);
          await t.pump();
          expect(find.textContaining(lang == 'es' ? 'seleccionado' : 'selected'), findsWidgets);
          // drag the divider
          s.previewTreeWidth(600);
          await t.pump();
        }
        expect(t.takeException(), isNull);
        setUiLang('en');
      });
    }
  }

  for (final pal in kPalettes) {
    for (final b in Brightness.values) {
      testWidgets('palette ${pal.id} ${b.name}', (t) async {
        await setSize(t, const Size(1366, 768));
        final s = await makeState();
        s.toggleItem(1);
        await t.pumpWidget(ChangeNotifierProvider.value(
            value: s, child: MaterialApp(theme: buildTheme(b, pal), home: const HomeScreen())));
        await t.pump(const Duration(milliseconds: 300));
        expect(t.takeException(), isNull);
      });
    }
  }

  testWidgets('search panel: boxes of the same height, text centred', (t) async {
    await setSize(t, const Size(1366, 768));
    final s = await makeState();
    s.searchController.text = 'redes';
    await t.pumpWidget(app(s, const HomeScreen()));
    await t.pump();
    final panel = find.byType(SearchPanel);
    final fields = find.descendant(of: panel, matching: find.byType(TextField));
    expect(fields, findsNWidgets(2));
    for (final f in fields.evaluate()) {
      // the frame drawn around the field (a Container of kControlHeight)
      final box = t.getRect(find.ancestor(of: find.byWidget(f.widget), matching: find.byType(Container)).first);
      expect(box.height, kControlHeight);
      final text = t.getRect(find.descendant(of: find.byWidget(f.widget), matching: find.byType(EditableText)));
      expect((text.center.dy - box.center.dy).abs(), lessThan(1.5), reason: 'text centred in its box');
    }
    final picker = t.getRect(find.ancestor(of: find.text('All fields'), matching: find.byType(Container)).first);
    expect(picker.height, kControlHeight); // "Field" as high as the search boxes
    final udcBox = t.getRect(find.ancestor(of: fields.first, matching: find.byType(Container)).first);
    final checks = find.descendant(of: panel, matching: find.byType(SmallCheckbox));
    expect(t.getSize(checks.first).height, lessThan(udcBox.height));
    expect(t.takeException(), isNull);
  });

  testWidgets('trash: spinner, then the result; errors offer to try again', (t) async {
    await setSize(t, const Size(1000, 700));
    final s = await makeState();
    s.api = FakeApi();
    await t.pumpWidget(app(s, const TrashScreen()));
    await t.pump();
    await t.pump();
    expect(find.text('Restore'), findsNWidgets(2));
    await t.tap(find.text('Restore').first);
    await t.pump(const Duration(milliseconds: 30));
    expect(find.text('Restoring...'), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
    await t.pump(const Duration(milliseconds: 150));
    await t.pump(const Duration(milliseconds: 200));
    expect(find.text('Restored'), findsOneWidget);
    await t.pump(const Duration(milliseconds: 1500));
    await t.pump(const Duration(milliseconds: 400));
    expect(find.text('Restore'), findsOneWidget); // the restored row folded away
    // permanent delete: confirmation, then the server's error and "Try again" in the row
    await t.tap(find.text('Delete'));
    await t.pumpAndSettle();
    await t.tap(find.text('Delete permanently').last);
    await t.pump();
    await t.pump(const Duration(milliseconds: 300));
    expect(find.text('The server is on fire.'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    expect(t.takeException(), isNull);
  });

  testWidgets('tree: "Table 1a" in grey bold, no dash', (t) async {
    await setSize(t, const Size(1366, 768));
    final s = await makeState();
    await t.pumpWidget(app(s, const HomeScreen()));
    await t.pump();
    final rich = t
        .widgetList<RichText>(find.byType(RichText))
        .map((r) => r.text.toPlainText())
        .where((x) => x.contains('Table 1a'));
    expect(rich, isNotEmpty);
    expect(rich.first, contains('Table 1a Connecting symbols'));
    expect(rich.first, isNot(contains(' - ')));
  });

  testWidgets('search panel: "Text" next to the tree button on a laptop', (t) async {
    await setSize(t, const Size(1366, 768));
    final s = await makeState();
    await t.pumpWidget(app(s, const HomeScreen()));
    await t.pump();
    final tree = t.getRect(find.byIcon(Icons.account_tree_outlined).first);
    final text = t.getRect(find.text('Text'));
    expect((text.center.dy - tree.center.dy).abs(), lessThan(2)); // same row
    expect(text.left - tree.right, lessThan(80)); // close to it
  });

  testWidgets('left pane as wide as the search panel, same margin on both sides', (t) async {
    await setSize(t, const Size(1600, 900));
    final s = await makeState();
    await t.pumpWidget(app(s, const HomeScreen()));
    await t.pump();
    final pane = t.getRect(find.byType(SearchPanel));
    final label = t.getRect(find.text('UDC number'));
    final button = t.getRect(find.widgetWithText(FilledButton, 'Search'));
    expect((label.left - pane.left - SearchPanel.margin).abs(), lessThan(1.5));
    expect((pane.right - button.right - SearchPanel.margin).abs(), lessThan(1.5));
    expect(t.takeException(), isNull);
  });

  testWidgets('phone: search slides to the results, card opens', (t) async {
    await setSize(t, const Size(360, 740));
    final s = await makeState();
    await t.pumpWidget(app(s, const HomeScreen()));
    await t.pump();
    openResultsPage(t.element(find.byType(HomeScreen)));
    await t.pumpAndSettle(const Duration(milliseconds: 50));
    s.toggleItem(1);
    await t.pump(const Duration(milliseconds: 300));
    expect(t.takeException(), isNull);
  });

  testWidgets('number builder: clicks and signs', (t) async {
    await setSize(t, const Size(1200, 900));
    final s = await makeState();
    s.udc = sampleTree();
    await t.pumpWidget(app(s, const Scaffold(body: UdcBuilder())));
    await t.pump();
    Future<void> tapCode(String code) async {
      await t.tap(find.byWidgetPredicate((w) => w is RichText && w.text.toPlainText().startsWith('$code  ')).first);
      await t.pump();
    }

    String box() => (t.widget<TextField>(find.byType(TextField).first)).controller!.text;
    await tapCode('0');
    await tapCode('00');
    await tapCode('004');
    expect(box(), '004'); // going down replaces
    await tapCode('004.8');
    await t.tap(find.text(':'));
    await t.pump();
    await tapCode('6');
    await tapCode('61');
    expect(box(), '004.8:61');
    await tapCode('(4)');
    await tapCode('(46)');
    expect(box(), '004.8:61(46)'); // an auxiliary is added, then refined
    await t.tap(find.byIcon(Icons.backspace_outlined));
    await t.pump();
    expect(box(), '004.8:61');
    expect(t.takeException(), isNull);
  });
}
