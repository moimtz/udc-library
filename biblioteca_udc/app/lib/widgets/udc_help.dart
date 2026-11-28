import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/theme.dart';
import 'rich_note.dart';
import 'udc_info_dialog.dart';

/// Help window of the Number builder and of the search panel: how a UDC number is built (summary of the UDC
/// Consortium's "Using UDC: Practical Guide", folder using_udc_practical_guide) and how to search.
///
/// The content is in [_en] and [_es] below: blocks of type
///   _H('Title')                       section title
///   _P('Text with «62-1» and **bold**') paragraph («...» = notation, **...** = bold)
///   _T([['code', 'meaning'], ...])    two-column table (first column = notation)
Future<void> showUdcHelp(BuildContext context, {bool searchFirst = false}) =>
    showDialog<void>(context: context, builder: (_) => _HelpDialog(searchFirst: searchFirst));

sealed class _B {
  const _B();
}

class _H extends _B {
  final String t;
  const _H(this.t);
}

class _P extends _B {
  final String t;
  const _P(this.t);
}

class _T extends _B {
  final List<List<String>> rows;
  const _T(this.rows);
}

class _HelpDialog extends StatelessWidget {
  final bool searchFirst;
  const _HelpDialog({required this.searchFirst});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final content = uiLang == 'es' ? _es : _en;
    final search = uiLang == 'es' ? _esSearch : _enSearch;
    final blocks = searchFirst ? [...search, ...content] : [...content, ...search];
    final s = context.read<AppState>();
    return Dialog(
      insetPadding: const EdgeInsets.all(12),
      clipBehavior: Clip.antiAlias,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 760, maxHeight: 800),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Container(
            color: cs.primaryContainer,
            padding: const EdgeInsets.fromLTRB(20, 12, 8, 12),
            child: Row(children: [
              Icon(Icons.menu_book_outlined, color: cs.onPrimaryContainer),
              const SizedBox(width: 10),
              Expanded(
                child: Text(tr('How to build and search UDC numbers'),
                    style: Theme.of(context).textTheme.titleMedium?.copyWith(color: cs.onPrimaryContainer)),
              ),
              IconButton(
                  tooltip: tr('Close'),
                  icon: Icon(Icons.close, color: cs.onPrimaryContainer),
                  onPressed: () => Navigator.pop(context)),
            ]),
          ),
          Flexible(
            child: SelectionArea(
              child: ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(22, 8, 22, 24),
                children: [
                  for (final b in blocks)
                    switch (b) {
                      _H(:final t) => Padding(
                          padding: const EdgeInsets.only(top: 18, bottom: 6),
                          child: Row(children: [
                            Container(width: 4, height: 18, color: cs.primary),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(t,
                                  style: TextStyle(
                                      fontSize: kFsSection + 1, fontWeight: FontWeight.w700, color: cs.primary)),
                            ),
                          ]),
                        ),
                      _P(:final t) => Padding(
                          padding: const EdgeInsets.only(bottom: 8),
                          child: richLine(context, t,
                              exists: (c) => s.udc.byCode.containsKey(c), onCode: (c) => showUdcInfo(context, c)),
                        ),
                      _T(:final rows) => _table(context, rows),
                    },
                  const SizedBox(height: 12),
                  Text('${tr('Source')}: UDC Consortium, “Using UDC: Practical Guide” (udcc.org).',
                      style: TextStyle(fontSize: kFsTiny, color: cs.onSurfaceVariant)),
                ],
              ),
            ),
          ),
        ]),
      ),
    );
  }

  Widget _table(BuildContext context, List<List<String>> rows) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(
        border: Border.all(color: cs.outlineVariant),
        borderRadius: BorderRadius.circular(kRadius),
      ),
      clipBehavior: Clip.antiAlias,
      child: Column(children: [
        for (var i = 0; i < rows.length; i++)
          Container(
            color: i.isEven ? cs.surfaceContainerLow : cs.surface,
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                width: 190,
                child: Text(rows[i][0],
                    style: TextStyle(
                        fontFamily: 'monospace', fontWeight: FontWeight.w700, color: cs.primary, fontSize: kInfoFontSize)),
              ),
              Expanded(child: Text(rows[i][1], style: const TextStyle(fontSize: kInfoFontSize, height: 1.3))),
            ]),
          ),
      ]),
    );
  }
}

// ---------------------------------------------------------------------------------------------- English
const _en = <_B>[
  _H('What a UDC number is'),
  _P('The UDC is an **analytico-synthetic** classification: a subject is expressed by a main number, which can be '
      'combined with auxiliary numbers (place, time, language, form...) and joined to other numbers with signs. '
      'The longer the number, the more specific the subject: «5» Mathematics. Natural sciences, «53» Physics, '
      '«539» Physical nature of matter, «539.1» Nuclear physics.'),
  _H('Main tables (classes 0 to 9)'),
  _T([
    ['0', 'Science and knowledge. Organization. Computer science. Information. Documentation. Librarianship'],
    ['1', 'Philosophy. Psychology'],
    ['2', 'Religion. Theology'],
    ['3', 'Social sciences'],
    ['4', '(vacant)'],
    ['5', 'Mathematics. Natural sciences'],
    ['6', 'Applied sciences. Medicine. Technology'],
    ['7', 'The arts. Entertainment. Sport'],
    ['8', 'Linguistics. Literature'],
    ['9', 'Geography. History'],
  ]),
  _H('Signs that join numbers'),
  _T([
    ['+', 'Addition, coordination: 69+72 Building and architecture'],
    ['/', 'Consecutive extension: 622.341.1/.2 iron and manganese ores'],
    [':', 'Simple relation: 37:004 computers in education'],
    ['::', 'Order-fixing relation (cannot be reversed)'],
    ['[ ]', 'Subgrouping (like brackets in algebra)'],
    ['*', 'Introduces a non-UDC notation: 622.341.1*Fe2O3'],
    ['A/Z', 'Direct alphabetical specification: 622.341.1GOE'],
  ]),
  _H('Common auxiliaries (can follow any number)'),
  _T([
    ['=...', 'Language: =112.2 German, =134.2 Spanish'],
    ['(0...)', 'Form of the document: (075) textbook, (084.3) map'],
    ['(1/9)', 'Place: (410) United Kingdom, (460) Spain'],
    ['(=...)', 'Ethnic grouping, nationality: (=112.2) German speaking peoples'],
    ['"..."', 'Time: "18" 19th century, "197" the 1970s'],
    ['-02, -03, -04, -05', 'General characteristics: properties, materials, processes, persons'],
  ]),
  _H('Special auxiliaries (only in their part of the tables)'),
  _P('They begin with «.0», a hyphen «-» or an apostrophe «`», and mean something only under the class where they '
      'are listed: «62-1» engineering details, «82-1» poetry. In the tree they appear next to their class. '
      'Example: «599.744.212» polar bear + «.017.7» metabolism + «"327.502"» February.'),
  _H('Citation order'),
  _P('Main number first, then special auxiliaries, then common auxiliaries from the most specific to the most '
      'general: -05, -04, -03, -02, "...", (=...), (1/9), (0...), =...'),
  _T([
    ['622"18"(430)=112.2', 'Mining - 19th century - Germany - in German'],
    ['94(410)"19"(075)', 'History - United Kingdom - 20th century - textbook'],
    ['338.48(734.211.4)"197"(084.3)', 'Tourism - Grafton County - 1970s - map'],
  ]),
  _P('The order may change to group a collection differently, e.g. «(410)94"19"» puts everything about Britain '
      'together. With «:» the treated subject goes first: 37:004 is “computers in education”.'),
  _H('How the Number builder works'),
  _P('**Click a class** in the tree: it replaces the last part of the number, so you can go down from 6 to 61 '
      'to 616 without getting “661”.'),
  _P('**Click an auxiliary** (place, time, language...): it is added to the number, e.g. 616 + (460) = '
      '616(460). An auxiliary of the same table replaces the previous one: (46) then (460) gives (460).'),
  _P('**Press a sign** (+ / : :: [ ]) and then click a class: the class is added after the sign, e.g. 004.8 : 61 '
      '= 004.8:61. ⌫ removes the last part. You can also type in the box.'),
  _P('Below the box, the breakdown shows the meaning of every part.'),
];

const _enSearch = <_B>[
  _H('Searching the library'),
  _P('Both boxes search **freely** by default; ticking “Exact search” narrows them.'),
  _T([
    ['61', 'UDC box: items with 61 or a subdivision (616.1, 004.8:61, 61(460)...)'],
    ['004.8:61', 'UDC box: items that have both 004.8 and 61 (each with its subdivisions)'],
    ['(460)', 'UDC box: anything about Spain or its regions'],
    ['004.8* (exact)', 'Exact UDC: the whole number; * = anything, ? = one character'],
    ['redes neuronales', 'Text box: both words, in any order'],
    ['"redes neuronales"', 'Text box: the words together, in this order'],
    ['fisica | quimica', 'Text box: either word (also OR)'],
    ['redes -sociales', 'Text box: leave out items with “sociales”'],
    ['electr*', 'Text box: electr + any letters (electricity, electrónica...)'],
  ]),
  _P('Capitals and accents never matter. “Field” limits the text box to some fields (Title, Author...). '
      '“Include cancelled numbers” also finds items classed with an old number that the searched one replaces. '
      'Search with every box empty to see the whole library.'),
];

// ---------------------------------------------------------------------------------------------- Español
const _es = <_B>[
  _H('Qué es un número CDU'),
  _P('La CDU es una clasificación **analítico-sintética**: un tema se expresa con un número principal, que se '
      'puede combinar con números auxiliares (lugar, tiempo, lengua, forma...) y unir a otros números mediante '
      'signos. Cuanto más largo el número, más específico el tema: «5» Matemáticas. Ciencias naturales, «53» '
      'Física, «539» Naturaleza física de la materia, «539.1» Física nuclear.'),
  _H('Tablas principales (clases 0 a 9)'),
  _T([
    ['0', 'Ciencia y conocimiento. Organización. Informática. Información. Documentación. Bibliotecología'],
    ['1', 'Filosofía. Psicología'],
    ['2', 'Religión. Teología'],
    ['3', 'Ciencias sociales'],
    ['4', '(vacante)'],
    ['5', 'Matemáticas. Ciencias naturales'],
    ['6', 'Ciencias aplicadas. Medicina. Tecnología'],
    ['7', 'Arte. Entretenimiento. Deporte'],
    ['8', 'Lingüística. Literatura'],
    ['9', 'Geografía. Historia'],
  ]),
  _H('Signos que unen números'),
  _T([
    ['+', 'Adición, coordinación: 69+72 Construcción y arquitectura'],
    ['/', 'Extensión consecutiva: 622.341.1/.2 minerales de hierro y de manganeso'],
    [':', 'Relación simple: 37:004 la computadora en la educación'],
    ['::', 'Relación de orden fijo (no se puede invertir)'],
    ['[ ]', 'Agrupación (como los corchetes en álgebra)'],
    ['*', 'Introduce una notación ajena a la CDU: 622.341.1*Fe2O3'],
    ['A/Z', 'Especificación alfabética directa: 622.341.1GOE'],
  ]),
  _H('Auxiliares comunes (pueden seguir a cualquier número)'),
  _T([
    ['=...', 'Lengua: =112.2 alemán, =134.2 español'],
    ['(0...)', 'Forma del documento: (075) libro de texto, (084.3) mapa'],
    ['(1/9)', 'Lugar: (410) Reino Unido, (460) España'],
    ['(=...)', 'Grupo étnico, nacionalidad: (=112.2) pueblos de habla alemana'],
    ['"..."', 'Tiempo: "18" siglo XIX, "197" la década de 1970'],
    ['-02, -03, -04, -05', 'Características generales: propiedades, materiales, procesos, personas'],
  ]),
  _H('Auxiliares especiales (solo en su parte de las tablas)'),
  _P('Empiezan con «.0», un guion «-» o un apóstrofo «`», y solo significan algo bajo la clase donde están '
      'listados: «62-1» detalles de ingeniería, «82-1» poesía. En el árbol aparecen junto a su clase. '
      'Ejemplo: «599.744.212» oso polar + «.017.7» metabolismo + «"327.502"» febrero.'),
  _H('Orden de cita'),
  _P('Primero el número principal, luego los auxiliares especiales y después los comunes, del más específico al '
      'más general: -05, -04, -03, -02, "...", (=...), (1/9), (0...), =...'),
  _T([
    ['622"18"(430)=112.2', 'Minería - siglo XIX - Alemania - en alemán'],
    ['94(410)"19"(075)', 'Historia - Reino Unido - siglo XX - libro de texto'],
    ['338.48(734.211.4)"197"(084.3)', 'Turismo - condado de Grafton - década de 1970 - mapa'],
  ]),
  _P('El orden puede cambiarse para agrupar una colección de otra manera; p. ej. «(410)94"19"» junta todo lo '
      'referente a Gran Bretaña. Con «:» el tema tratado va primero: 37:004 es “la computadora en la educación”.'),
  _H('Cómo funciona el constructor de números'),
  _P('**Clic en una clase** del árbol: sustituye la última parte del número, así puedes bajar de 6 a 61 y a 616 '
      'sin que quede “661”.'),
  _P('**Clic en un auxiliar** (lugar, tiempo, lengua...): se añade al número, p. ej. 616 + (460) = 616(460). '
      'Un auxiliar de la misma tabla sustituye al anterior: (46) y luego (460) da (460).'),
  _P('**Pulsa un signo** (+ / : :: [ ]) y después haz clic en una clase: la clase se añade tras el signo, p. ej. '
      '004.8 : 61 = 004.8:61. ⌫ quita la última parte. También puedes escribir en el recuadro.'),
  _P('Debajo del recuadro, el desglose muestra el significado de cada parte.'),
];

const _esSearch = <_B>[
  _H('Buscar en la biblioteca'),
  _P('Los dos recuadros buscan de forma **libre** por defecto; marcar “Búsqueda exacta” los acota.'),
  _T([
    ['61', 'Número CDU: ítems con 61 o una subdivisión (616.1, 004.8:61, 61(460)...)'],
    ['004.8:61', 'Número CDU: ítems que tienen 004.8 y también 61 (cada uno con sus subdivisiones)'],
    ['(460)', 'Número CDU: todo lo referente a España o sus regiones'],
    ['004.8* (exacta)', 'CDU exacta: el número completo; * = cualquier cosa, ? = un carácter'],
    ['redes neuronales', 'Texto: las dos palabras, en cualquier orden'],
    ['"redes neuronales"', 'Texto: las palabras juntas y en ese orden'],
    ['fisica | quimica', 'Texto: cualquiera de las dos (también OR)'],
    ['redes -sociales', 'Texto: deja fuera los ítems con “sociales”'],
    ['electr*', 'Texto: electr + cualquier terminación (electricidad, electrónica...)'],
  ]),
  _P('Mayúsculas y acentos nunca importan. “Campo” limita el texto a algunos campos (Título, Autor...). '
      '“Incluir números cancelados” también encuentra ítems clasificados con un número antiguo que el buscado '
      'sustituye. Busca con todos los recuadros vacíos para ver la biblioteca completa.'),
];
