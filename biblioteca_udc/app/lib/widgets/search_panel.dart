import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/theme.dart';
import 'udc_builder.dart';
import 'udc_help.dart';

/// Search panel, on top of the UDC tree:
///
///   SEARCH                                        (clear) (?)
///   UDC number [______________][tree]
///              [ ] Exact search
///              [ ] Include cancelled numbers
///        Text  [______________][Search]
///              [ ] Exact search
///       Field  [All fields   v]
///
/// The boxes are [kSearchBoxWidth] wide (they shrink when the pane is narrower) and [kControlHeight] high.
/// When the pane is wide enough ([naturalWidth]) the UDC group and the text group go side by side. Both boxes search
/// freely by default (see server/search.py and the help); "Search" with everything empty = the whole library.
/// [onSearched] runs after a search is started (the phone uses it to slide to the results).
class SearchPanel extends StatelessWidget {
  final VoidCallback? onSearched;
  const SearchPanel({super.key, this.onSearched});

  /// Left and right margin of the panel (the same on both sides).
  static const margin = 10.0;

  /// Space between the UDC group (ending with the tree button) and the "Text" label.
  static const groupGap = 14.0;

  /// Widths measured from the texts in the current language, so the label columns are exactly as wide as
  /// their longest label: "UDC number" starts right at the margin and "Search" ends right at the other one.
  static PanelSizes measure(BuildContext context) {
    final base = DefaultTextStyle.of(context).style;
    final scaler = MediaQuery.textScalerOf(context);
    double w(String t, TextStyle st) {
      final tp = TextPainter(
          text: TextSpan(text: t, style: base.merge(st)), textDirection: TextDirection.ltr, textScaler: scaler)
        ..layout();
      return tp.width.ceilToDouble();
    }

    const label = TextStyle(fontSize: kFsSmall, fontWeight: FontWeight.w600);
    const pad = 8.0; // between a label and its box
    final udc = w(tr('UDC number'), label) + pad;
    final text = [w(tr('Text'), label), w(tr('Field'), label)].reduce((a, b) => a > b ? a : b) + pad;
    // FilledButton.icon: 14 + icon 16 + 8 + text + 14 (theme.dart), +2 of rounding
    final button = 14 + 16 + 8 + w(tr('Search'), const TextStyle(fontSize: kFsSmall, fontWeight: FontWeight.w600)) + 14 + 2;
    return PanelSizes(udc, text, udc > text ? udc : text, button);
  }

  /// Width of the panel with "Text" next to the tree button: from "UDC number" to "Search", plus the margins.
  /// The search + tree pane starts with this width (home.dart, _WideBody).
  static double naturalWidth(BuildContext context) => measure(context).natural;

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final m = measure(context);

    void search() {
      s.submitSearch();
      onSearched?.call();
    }

    Widget label(String t, double w) => SizedBox(
          width: w,
          child: Padding(
            padding: const EdgeInsets.only(right: 8),
            child: Text(t,
                textAlign: TextAlign.right,
                style: TextStyle(fontSize: kFsSmall, fontWeight: FontWeight.w600, color: cs.onSurfaceVariant)),
          ),
        );
    // a box of the panel: fixed width (shrinks if needed) and the common height
    Widget box(Widget w) => Flexible(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: kSearchBoxWidth),
            child: SizedBox(height: kControlHeight, child: w),
          ),
        );
    Widget under(Widget w, double lw) => Row(children: [SizedBox(width: lw), Expanded(child: w)]);

    Widget udcGroup(double lw) => Column(mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            label(tr('UDC number'), lw),
            box(_SearchBox(
              controller: s.udcController,
              hint: tr('e.g. 004.8:61'),
              onSubmitted: search,
              style: const TextStyle(fontSize: kFsBody, fontFamily: 'monospace', fontWeight: FontWeight.w600),
            )),
            const SizedBox(width: kGap),
            SquareIconButton(
              icon: Icons.account_tree_outlined,
              tooltip: tr('Number builder (UDC tree)'),
              onPressed: () async {
                final n =
                    await buildUdcNumber(context, initial: s.udcController.text, doneLabel: tr('Use this number'));
                if (n != null) s.udcController.text = n;
              },
            ),
          ]),
          const SizedBox(height: 3),
          under(_Check(tr('Exact search'), s.udcExact, (v) => s.setSearchOption(udcExact: v)), lw),
          under(
              _Check(tr('Include cancelled numbers'), s.includeCancelled, (v) => s.setSearchOption(includeCancelled: v),
                  tip: tr('Also items classed with an old number that the searched one replaces')),
              lw),
        ]);

    Widget textGroup(double lw) => Column(mainAxisSize: MainAxisSize.min, children: [
          Row(children: [
            label(tr('Text'), lw),
            box(_SearchBox(
              controller: s.searchController,
              hint: tr('words, "a phrase", a | b, -word, electr*'),
              onSubmitted: search,
            )),
            const SizedBox(width: kGap),
            SizedBox(
              height: kControlHeight,
              child:
                  SizedBox(
                    width: m.button,
                    child: FilledButton.icon(
                        onPressed: search, icon: const Icon(Icons.search, size: 16), label: Text(tr('Search'))),
                  ),
            ),
          ]),
          const SizedBox(height: 3),
          under(_Check(tr('Exact search'), s.textExact, (v) => s.setSearchOption(textExact: v)), lw),
          const SizedBox(height: 3),
          Row(children: [label(tr('Field'), lw), box(const _FieldPicker())]),
        ]);

    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      PaneHeader(icon: Icons.search, title: tr('Search panel'), actions: [
        SmallIconButton(icon: Icons.restart_alt, tooltip: tr('Clear the search boxes'), onPressed: s.resetSearch),
        SmallIconButton(
          icon: Icons.help_outline,
          tooltip: tr('How to search'),
          onPressed: () => showUdcHelp(context, searchFirst: true),
        ),
      ]),
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: margin, vertical: 10),
        child: LayoutBuilder(builder: (context, c) {
          // "Text" next to the tree button when it fits (the margins are already outside c.maxWidth)
          final side = c.maxWidth + 0.5 >= m.natural - 2 * margin;
          return Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            if (side)
              // "Text" right after the tree button, both groups as narrow as they can be
              Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(width: m.udcGroup, child: udcGroup(m.udcLabel)),
                const SizedBox(width: groupGap),
                SizedBox(width: m.textGroup, child: textGroup(m.textLabel)),
              ])
            else ...[
              udcGroup(m.stackLabel),
              const SizedBox(height: 8),
              textGroup(m.stackLabel),
            ],
            if (s.searchError != null)
              Padding(
                padding: EdgeInsets.only(left: m.stackLabel, top: 4),
                child: Text(s.searchError!, style: TextStyle(color: cs.error, fontSize: kFsSmall)),
              ),
            if (s.unclassified)
              Padding(
                padding: EdgeInsets.only(left: m.stackLabel, top: 4),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: InputChip(
                    visualDensity: VisualDensity.compact,
                    label: Text(tr('Only unclassified items')),
                    onDeleted: s.clearUnclassified,
                  ),
                ),
              ),
          ]);
        }),
      ),
    ]);
  }
}

/// A search box drawn by the app (same frame as "Field"): a borderless text field centred inside a rounded
/// frame of height kControlHeight. The frame turns to the primary colour while the box has the focus.
class _SearchBox extends StatefulWidget {
  final TextEditingController controller;
  final String hint;
  final VoidCallback onSubmitted;
  final TextStyle style;
  const _SearchBox({
    required this.controller,
    required this.hint,
    required this.onSubmitted,
    this.style = const TextStyle(fontSize: kFsBody),
  });

  @override
  State<_SearchBox> createState() => _SearchBoxState();
}

class _SearchBoxState extends State<_SearchBox> {
  final _focus = FocusNode();

  @override
  void initState() {
    super.initState();
    _focus.addListener(() => setState(() {}));
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final focused = _focus.hasFocus;
    return Container(
      height: kControlHeight,
      padding: const EdgeInsets.only(left: 10, right: 2),
      decoration: BoxDecoration(
        color: cs.surfaceContainerLowest,
        border: Border.all(color: focused ? cs.primary : cs.outline, width: focused ? 1.6 : 1),
        borderRadius: BorderRadius.circular(kRadius),
      ),
      child: Row(children: [
        Expanded(
          child: TextField(
            controller: widget.controller,
            focusNode: _focus,
            onSubmitted: (_) => widget.onSubmitted(),
            textInputAction: TextInputAction.search,
            style: widget.style.copyWith(height: 1.2),
            decoration: InputDecoration.collapsed(
              hintText: widget.hint,
              hintStyle: TextStyle(fontSize: kFsBody, height: 1.2, color: cs.onSurfaceVariant.withValues(alpha: kHintAlpha)),
            ),
          ),
        ),
        _ClearButton(widget.controller),
      ]),
    );
  }
}

/// Measured widths of the search panel (see [SearchPanel.measure]).
class PanelSizes {
  final double udcLabel; // "UDC number" column
  final double textLabel; // "Text" / "Field" column, when next to the UDC group
  final double stackLabel; // common column when the groups are one under the other
  final double button; // "Search" button
  const PanelSizes(this.udcLabel, this.textLabel, this.stackLabel, this.button);

  double get udcGroup => udcLabel + kSearchBoxWidth + kGap + kControlHeight;
  double get textGroup => textLabel + kSearchBoxWidth + kGap + button;
  double get natural => SearchPanel.margin + udcGroup + SearchPanel.groupGap + textGroup + SearchPanel.margin;
}

class _ClearButton extends StatelessWidget {
  final TextEditingController ctl;
  const _ClearButton(this.ctl);

  @override
  Widget build(BuildContext context) => ValueListenableBuilder<TextEditingValue>(
        valueListenable: ctl,
        builder: (_, v, __) => v.text.isEmpty
            ? const SizedBox.shrink()
            : IconButton(
                tooltip: tr('Clear'),
                onPressed: ctl.clear,
                iconSize: 15,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints.tightFor(width: 24, height: 24),
                icon: Icon(Icons.clear, color: Theme.of(context).colorScheme.onSurfaceVariant),
              ),
      );
}

/// Small check box with its text (both clickable).
class _Check extends StatelessWidget {
  final String text;
  final bool value;
  final ValueChanged<bool> onChanged;
  final String? tip;
  const _Check(this.text, this.value, this.onChanged, {this.tip});

  @override
  Widget build(BuildContext context) {
    final w = InkWell(
      borderRadius: BorderRadius.circular(kRadius),
      onTap: () => onChanged(!value),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          SmallCheckbox(value: value, onChanged: (v) => onChanged(v ?? false)),
          const SizedBox(width: 6),
          Flexible(child: Text(text, style: const TextStyle(fontSize: kFsSmall), overflow: TextOverflow.ellipsis)),
          const SizedBox(width: 6),
        ]),
      ),
    );
    return Align(alignment: Alignment.centerLeft, child: tip == null ? w : Tooltip(message: tip!, child: w));
  }
}

/// "Field" dropdown with check boxes: the fields searched by the text box (none ticked = all fields).
/// Drawn as a box of the same height and border as the search boxes.
class _FieldPicker extends StatelessWidget {
  const _FieldPicker();

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final options = <(String, String)>[
      ('title', tr('Title')),
      ('creators', tr('Creators')),
      ('year', tr('Year')),
      ('type', tr('Item type')),
      ('udc', tr('UDC')),
      ('tags', tr('Tags')),
      // Zotero fields; a base field also searches its variants (Publisher finds University, Institution...)
      for (final f in s.schema.searchFields)
        if (f.$1 != 'title') f,
    ];
    final names = [for (final o in options) if (s.fields.contains(o.$1)) o.$2];
    final summary = names.isEmpty
        ? tr('All fields')
        : names.length <= 2
            ? names.join(', ')
            : '${names.take(2).join(', ')} (+${names.length - 2})';

    return MenuAnchor(
      style: const MenuStyle(maximumSize: WidgetStatePropertyAll(Size(320, 440))),
      menuChildren: [
        CheckboxMenuButton(
          value: s.fields.isEmpty,
          closeOnActivate: false,
          onChanged: (_) => s.setFields({}),
          child: Text(tr('All fields'), style: const TextStyle(fontWeight: FontWeight.w600)),
        ),
        const Divider(height: 1),
        for (final o in options)
          CheckboxMenuButton(
            value: s.fields.contains(o.$1),
            closeOnActivate: false,
            onChanged: (v) => s.setFields(v == true ? {...s.fields, o.$1} : ({...s.fields}..remove(o.$1))),
            child: Text(o.$2),
          ),
      ],
      builder: (context, ctl, _) => InkWell(
        borderRadius: BorderRadius.circular(kRadius),
        onTap: () => ctl.isOpen ? ctl.close() : ctl.open(),
        child: Container(
          height: kControlHeight,
          padding: const EdgeInsets.only(left: 10, right: 4),
          decoration: BoxDecoration(
            border: Border.all(color: cs.outline),
            borderRadius: BorderRadius.circular(kRadius),
          ),
          child: Row(children: [
            Expanded(
                child: Text(summary, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: kFsBody))),
            Icon(Icons.arrow_drop_down, size: 20, color: cs.onSurfaceVariant),
          ]),
        ),
      ),
    );
  }
}
