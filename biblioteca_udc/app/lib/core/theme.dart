import 'package:flutter/material.dart';

// ============================================================================================================
//  LOOK OF THE APP. Change these values to fine-tune it (save, then "r" in `flutter run` to see the change).
// ============================================================================================================

/// Type scale, from the biggest to the smallest. The whole app uses only these sizes, so the hierarchy stays
/// the same everywhere: change one value and every text of that level changes.
const kFsTitle = 17.0; //   window titles, top bar
const kFsSection = 14.0; // section titles: number of results, "Supplementary material", help headings
const kFsBody = 13.0; //    general text: tree, search boxes, menus, card title
const kFsSmall = 12.0; //   card fields, labels of the search panel, check boxes, buttons
const kFsTiny = 11.0; //    secondary details: authors | year | size line, notes under a box
const kInfoFontSize = 13.5; // reading text of the information and help windows

/// Height of search boxes, dropdowns and square buttons next to them (all the same, for symmetry): a little
/// more than the text.
const kControlHeight = 28.0;

/// Width of the boxes of the search panel (they shrink by themselves when the pane is narrower).
const kSearchBoxWidth = 180.0;

/// Size of the check boxes: a little bigger than the text, smaller than the boxes. 1.0 = Flutter's size (18 px).
const kCheckScale = 0.82;

/// Time the mouse must rest on something before its tooltip (the floating label) appears.
const kTooltipDelay = Duration(seconds: 2);

/// Height of the action buttons of the selection bar (a bit taller than the other buttons).
const kActionButtonHeight = 34.0;

/// Height of the options of the dropdowns and menus.
const kMenuItemHeight = 36.0;

/// Size of the small round/square icons: (?) help, (i) class information, tree button.
const kIconSize = 17.0;

/// Corner radius of buttons, boxes and cards.
const kRadius = 8.0;

/// Space between search boxes, check boxes and dropdowns (smaller = more compact).
const kGap = 6.0;

/// UDC tree: row height, indentation per level (it shrinks by itself in a narrow pane) and text size.
const kTreeRowHeight = 28.0;
const kTreeIndent = 16.0;
const kTreeFontSize = kFsBody;

/// Empty space at the right end of each tree row, so the (i) is not covered by the scroll bar.
const kScrollbarGap = 14.0;

/// Transparency of secondary things (the (i) of the tree, "Unclassified", hints in the boxes):
/// 0 = invisible, 1 = solid.
const kFaintAlpha = 0.45;
const kHintAlpha = 0.55;

/// "Table 1a", "Table 1b"... at the start of some tree names: lighter than the other grey texts.
const kTableAlpha = 0.42;

/// Limits of the search + tree pane on wide screens, as a share of the window. It starts as wide as the search
/// panel (SearchPanel.naturalWidth) and the divider can be dragged between these limits.
const kTreeMin = 0.25;
const kTreeMax = 0.70;

/// Width from which the screen shows tree and results side by side (below: phone navigation).
const kWideLayout = 720.0;

// ============================================================================================================

ThemeData buildTheme(Brightness b, [AppPalette palette = defaultPalette]) {
  final p = b == Brightness.dark ? palette.dark : palette.light;
  final cs = p.scheme(b);
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: cs,
    visualDensity: VisualDensity.compact,
    scaffoldBackgroundColor: p.background,
    extensions: [p],
  );
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadius));
  final border = BorderSide(color: cs.outlineVariant);
  const pad = EdgeInsets.symmetric(horizontal: 12, vertical: 4);
  const minSize = Size(0, kControlHeight - 2);
  const label = TextStyle(fontSize: kFsSmall, fontWeight: FontWeight.w600);
  // buttons: framed, rounded, background a bit lighter than the page
  final framed = ButtonStyle(
    shape: WidgetStatePropertyAll(shape),
    side: WidgetStateProperty.resolveWith((s) => s.contains(WidgetState.disabled)
        ? BorderSide(color: cs.outlineVariant.withValues(alpha: 0.5))
        : border),
    backgroundColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.disabled) ? cs.surfaceContainerLow : cs.surfaceContainerHigh),
    padding: const WidgetStatePropertyAll(pad),
    minimumSize: const WidgetStatePropertyAll(minSize),
    textStyle: const WidgetStatePropertyAll(label),
  );
  final m = Typography.material2021().englishLike.merge(base.textTheme);
  TextStyle? sz(TextStyle? s, double size, [FontWeight? w]) => s?.copyWith(fontSize: size, fontWeight: w, height: 1.35);
  final text = m.copyWith(
    headlineSmall: sz(m.headlineSmall, kFsTitle + 1),
    titleLarge: sz(m.titleLarge, kFsTitle, FontWeight.w600),
    titleMedium: sz(m.titleMedium, kFsSection + 1, FontWeight.w600),
    titleSmall: sz(m.titleSmall, kFsSection, FontWeight.w600),
    bodyLarge: sz(m.bodyLarge, kFsBody),
    bodyMedium: sz(m.bodyMedium, kFsBody),
    bodySmall: sz(m.bodySmall, kFsTiny),
    labelLarge: sz(m.labelLarge, kFsSmall, FontWeight.w600),
    labelMedium: sz(m.labelMedium, kFsSmall),
    labelSmall: sz(m.labelSmall, kFsTiny),
  );
  final hint = TextStyle(fontSize: kFsBody, color: cs.onSurfaceVariant.withValues(alpha: kHintAlpha));
  return base.copyWith(
    textTheme: text,
    appBarTheme: AppBarTheme(titleTextStyle: TextStyle(fontSize: kFsTitle + 1, fontWeight: FontWeight.w600, color: cs.onSurface)),
    outlinedButtonTheme: OutlinedButtonThemeData(style: framed),
    textButtonTheme: TextButtonThemeData(style: framed),
    // main buttons (Search, Open, Done, Save, Add...): the palette's action colour (green)
    filledButtonTheme: FilledButtonThemeData(
      style: ButtonStyle(
        backgroundColor: WidgetStateProperty.resolveWith(
            (s) => s.contains(WidgetState.disabled) ? p.action.withValues(alpha: 0.35) : p.action),
        foregroundColor: WidgetStateProperty.resolveWith(
            (s) => s.contains(WidgetState.disabled) ? p.onAction.withValues(alpha: 0.7) : p.onAction),
        iconColor: WidgetStatePropertyAll(p.onAction),
        shape: WidgetStatePropertyAll(shape),
        padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 14, vertical: 4)),
        minimumSize: const WidgetStatePropertyAll(minSize),
        textStyle: const WidgetStatePropertyAll(label),
      ),
    ),
    iconButtonTheme: const IconButtonThemeData(style: ButtonStyle(iconSize: WidgetStatePropertyAll(20))),
    inputDecorationTheme: InputDecorationTheme(
      isDense: true,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(kRadius)),
      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      hintStyle: hint,
      labelStyle: TextStyle(fontSize: kFsBody, color: cs.onSurfaceVariant),
      floatingLabelStyle: TextStyle(fontSize: kFsSmall, color: cs.primary),
      suffixIconConstraints: const BoxConstraints(minWidth: 24, minHeight: 24),
      prefixIconConstraints: const BoxConstraints(minWidth: 24, minHeight: 24),
    ),
    cardTheme: CardThemeData(shape: shape),
    chipTheme: base.chipTheme.copyWith(shape: shape, labelStyle: const TextStyle(fontSize: kFsSmall)),
    dialogTheme: DialogThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(kRadius * 1.5)),
      titleTextStyle: TextStyle(fontSize: kFsTitle, fontWeight: FontWeight.w600, color: cs.onSurface),
      contentTextStyle: TextStyle(fontSize: kFsBody, height: 1.4, color: cs.onSurface),
    ),
    checkboxTheme: const CheckboxThemeData(visualDensity: VisualDensity(horizontal: -4, vertical: -4)),
    // menus (dropdowns, "Field", the ... menus): rows close together
    menuTheme: const MenuThemeData(
      style: MenuStyle(
        padding: WidgetStatePropertyAll(EdgeInsets.symmetric(vertical: 6)),
        visualDensity: VisualDensity(horizontal: -2, vertical: -2),
      ),
    ),
    menuButtonTheme: const MenuButtonThemeData(
      style: ButtonStyle(
        minimumSize: WidgetStatePropertyAll(Size(0, kMenuItemHeight)),
        padding: WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 14)),
        visualDensity: VisualDensity(horizontal: -2, vertical: -2),
        textStyle: WidgetStatePropertyAll(TextStyle(fontSize: kFsBody)),
      ),
    ),
    popupMenuTheme: PopupMenuThemeData(labelTextStyle: const WidgetStatePropertyAll(TextStyle(fontSize: kFsBody))),
    listTileTheme: const ListTileThemeData(dense: true),
    tooltipTheme: TooltipThemeData(
      waitDuration: kTooltipDelay,
      textStyle: TextStyle(fontSize: kFsSmall, color: cs.onInverseSurface),
      decoration: BoxDecoration(color: cs.inverseSurface.withValues(alpha: 0.94), borderRadius: BorderRadius.circular(6)),
    ),
  );
}

/// TextButton without frame or background (for "+ Add file", "+ Add note"...).
final plainButton = TextButton.styleFrom(
  side: BorderSide.none,
  backgroundColor: Colors.transparent,
  padding: const EdgeInsets.symmetric(horizontal: 8),
);


/// A rounded frame for small controls (sort selector, option groups).
class Framed extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  const Framed({super.key, required this.child, this.padding = const EdgeInsets.symmetric(horizontal: 6)});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      height: kControlHeight,
      padding: padding,
      decoration: BoxDecoration(
        color: cs.surfaceContainerHigh,
        border: Border.all(color: cs.outlineVariant),
        borderRadius: BorderRadius.circular(kRadius),
      ),
      child: child,
    );
  }
}

/// Check box a bit smaller than Flutter's (kCheckScale), without the big invisible margin around it.
class SmallCheckbox extends StatelessWidget {
  final bool? value;
  final ValueChanged<bool?>? onChanged;
  final bool tristate;
  const SmallCheckbox({super.key, required this.value, required this.onChanged, this.tristate = false});

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: 18 * kCheckScale + 4,
        child: Transform.scale(
          scale: kCheckScale,
          child: Checkbox(
            value: value,
            tristate: tristate,
            onChanged: onChanged,
            materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
            visualDensity: const VisualDensity(horizontal: -4, vertical: -4),
          ),
        ),
      );
}

/// Header of a pane ("Search", "UDC tree"): small icon and title in translucent grey, actions on the right.
class PaneHeader extends StatelessWidget {
  final IconData icon;
  final String title;
  final List<Widget> actions;
  const PaneHeader({super.key, required this.icon, required this.title, this.actions = const []});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final faint = cs.onSurfaceVariant.withValues(alpha: 0.6);
    return Container(
      height: 30,
      padding: const EdgeInsets.only(left: 12, right: 6),
      decoration: BoxDecoration(
        color: cs.surfaceContainer,
        border: Border(bottom: BorderSide(color: cs.outlineVariant)),
      ),
      child: IconTheme(
        data: IconThemeData(color: faint),
        child: Row(children: [
          Icon(icon, size: 15, color: faint),
          const SizedBox(width: 6),
          Expanded(
            child: Text(title.toUpperCase(),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: kFsTiny, fontWeight: FontWeight.w700, color: faint, letterSpacing: 0.8)),
          ),
          ...actions,
        ]),
      ),
    );
  }
}

/// Square button with a small icon (the tree button next to "UDC number"), as tall as the boxes.
class SquareIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  const SquareIconButton({super.key, required this.icon, required this.tooltip, this.onPressed});

  @override
  Widget build(BuildContext context) => SizedBox.square(
        dimension: kControlHeight,
        child: Tooltip(
          message: tooltip,
          child: OutlinedButton(
            onPressed: onPressed,
            style: OutlinedButton.styleFrom(padding: EdgeInsets.zero, minimumSize: const Size.square(kControlHeight)),
            child: Icon(icon, size: kIconSize),
          ),
        ),
      );
}

/// Round (?) / (i) icon button, the same size everywhere.
class SmallIconButton extends StatelessWidget {
  final IconData icon;
  final String tooltip;
  final VoidCallback? onPressed;
  final Color? color;
  const SmallIconButton({super.key, required this.icon, required this.tooltip, this.onPressed, this.color});

  @override
  Widget build(BuildContext context) => IconButton(
        tooltip: tooltip,
        onPressed: onPressed,
        iconSize: kIconSize,
        padding: EdgeInsets.zero,
        constraints: const BoxConstraints.tightFor(width: 26, height: 26),
        icon: Icon(icon, color: color ?? Theme.of(context).colorScheme.onSurfaceVariant),
      );
}

/// Red main button, for confirming that something is deleted ("Move to trash", "Delete permanently"...).
ButtonStyle dangerButton(BuildContext context) {
  final cs = Theme.of(context).colorScheme;
  return FilledButton.styleFrom(backgroundColor: cs.error, foregroundColor: cs.onError, iconColor: cs.onError);
}

// ============================================================================================================
//  PALETTES (Settings > Palette). Each one has a light and a dark version. To change a colour, edit its hex
//  value (0xFF + RRGGBB). To add a palette: copy one AppPalette(...) block, give it a new id, add it to
//  kPalettes and add its name to the translations (l10n_es.dart).
// ============================================================================================================

/// Colours of one mode of a palette. It is also a ThemeExtension, so any widget can read them with
/// `Theme.of(context).extension<PaletteColors>()` (e.g. the highlight of search matches).
@immutable
class PaletteColors extends ThemeExtension<PaletteColors> {
  final Color primary; //    UDC numbers, section titles, ticked boxes, links
  final Color action; //     main buttons (Search, Open, Done, Save, Add)
  final Color onAction; //   text on the main buttons
  final Color background; // page
  final Color surface; //    cards, tree pane
  final Color button; //     background of framed buttons and boxes
  final Color border; //     borders and tree guide lines
  final Color text; //       text
  final Color textMuted; //  secondary text
  final Color selection; //  selected tree row, selection bar
  final Color highlight; //  search matches painted in the results
  final Color warning; //    values not confirmed (the sparkle), warnings
  final Color error; //      errors and delete buttons

  const PaletteColors({
    required this.primary,
    required this.action,
    required this.onAction,
    required this.background,
    required this.surface,
    required this.button,
    required this.border,
    required this.text,
    required this.textMuted,
    required this.selection,
    required this.highlight,
    required this.warning,
    required this.error,
  });

  /// Flutter's colour scheme with these colours (the roles not listed derive from the primary).
  ColorScheme scheme(Brightness b) {
    final seed = ColorScheme.fromSeed(seedColor: primary, brightness: b);
    final dark = b == Brightness.dark;
    return seed.copyWith(
      primary: primary,
      onPrimary: primary.computeLuminance() > 0.45 ? const Color(0xFF111111) : Colors.white,
      surface: background,
      onSurface: text,
      onSurfaceVariant: textMuted,
      surfaceContainerLowest: surface,
      surfaceContainerLow: surface,
      surfaceContainer: Color.lerp(background, button, 0.6),
      surfaceContainerHigh: button,
      surfaceContainerHighest: Color.lerp(button, border, 0.45),
      outlineVariant: border,
      outline: Color.lerp(border, textMuted, 0.5),
      secondaryContainer: selection,
      onSecondaryContainer: text,
      tertiary: warning,
      error: error,
      onError: dark ? const Color(0xFF601410) : Colors.white,
    );
  }

  @override
  PaletteColors copyWith() => this;

  @override
  PaletteColors lerp(ThemeExtension<PaletteColors>? other, double t) =>
      t < 0.5 || other is! PaletteColors ? this : other;
}

class AppPalette {
  final String id; //   saved in the settings
  final String name; // English name (translated with tr)
  final PaletteColors light;
  final PaletteColors dark;
  const AppPalette(this.id, this.name, this.light, this.dark);
}

/// A. Library: petrol + green (default).
const defaultPalette = AppPalette(
  'library',
  'Library (petrol and green)',
  PaletteColors(
    primary: Color(0xFF2F5D62), action: Color(0xFF2E7D32), onAction: Colors.white,
    background: Color(0xFFF6F7F5), surface: Color(0xFFFFFFFF), button: Color(0xFFECEFEC),
    border: Color(0xFFCBD3D1), text: Color(0xFF1C2524), textMuted: Color(0xFF5B6866),
    selection: Color(0xFFD6E8E5), highlight: Color(0xFFFFE08A), warning: Color(0xFFB26A00),
    error: Color(0xFFB3261E),
  ),
  PaletteColors(
    primary: Color(0xFF7FC4C9), action: Color(0xFF66BB6A), onAction: Color(0xFF0B2A0D),
    background: Color(0xFF121615), surface: Color(0xFF1B2120), button: Color(0xFF262D2C),
    border: Color(0xFF3A4543), text: Color(0xFFE3EAE8), textMuted: Color(0xFFA3B1AE),
    selection: Color(0xFF24403D), highlight: Color(0xFF7A6215), warning: Color(0xFFFFB74D),
    error: Color(0xFFF2B8B5),
  ),
);

const kPalettes = <AppPalette>[
  defaultPalette,
  // B. Slate: blue grey + mint green
  AppPalette(
    'slate',
    'Slate (blue grey and mint)',
    PaletteColors(
      primary: Color(0xFF34506B), action: Color(0xFF2E7D5B), onAction: Colors.white,
      background: Color(0xFFF5F7FA), surface: Color(0xFFFFFFFF), button: Color(0xFFEBEFF4),
      border: Color(0xFFC9D2DC), text: Color(0xFF1B2430), textMuted: Color(0xFF5A6675),
      selection: Color(0xFFDCE6F2), highlight: Color(0xFFFFE6A3), warning: Color(0xFFA86400),
      error: Color(0xFFB3261E),
    ),
    PaletteColors(
      primary: Color(0xFF9DB8D6), action: Color(0xFF5CC08F), onAction: Color(0xFF06291A),
      background: Color(0xFF11151A), surface: Color(0xFF1A2027), button: Color(0xFF252C35),
      border: Color(0xFF36414D), text: Color(0xFFE2E8EF), textMuted: Color(0xFFA0ACBA),
      selection: Color(0xFF22344A), highlight: Color(0xFF6E5A1E), warning: Color(0xFFF5B860),
      error: Color(0xFFF2B8B5),
    ),
  ),
  // C. Paper: warm sepia + olive green
  AppPalette(
    'paper',
    'Paper (sepia and olive)',
    PaletteColors(
      primary: Color(0xFF6B4E2E), action: Color(0xFF4E7A27), onAction: Colors.white,
      background: Color(0xFFFAF7F0), surface: Color(0xFFFFFDF8), button: Color(0xFFF1ECE1),
      border: Color(0xFFDCD2BF), text: Color(0xFF2A2218), textMuted: Color(0xFF6E6250),
      selection: Color(0xFFEFE3CC), highlight: Color(0xFFFFE08A), warning: Color(0xFFA85A00),
      error: Color(0xFFB3261E),
    ),
    PaletteColors(
      primary: Color(0xFFD9B98F), action: Color(0xFF9CCC65), onAction: Color(0xFF1C2A08),
      background: Color(0xFF17140F), surface: Color(0xFF211D16), button: Color(0xFF2C271E),
      border: Color(0xFF4A4234), text: Color(0xFFEDE6DA), textMuted: Color(0xFFB5A994),
      selection: Color(0xFF3A3122), highlight: Color(0xFF6B5516), warning: Color(0xFFF0B35A),
      error: Color(0xFFF2B8B5),
    ),
  ),
];

AppPalette paletteById(String? id) => kPalettes.firstWhere((p) => p.id == id, orElse: () => defaultPalette);

/// Colours of the current palette and mode, from any widget.
PaletteColors paletteOf(BuildContext context) => Theme.of(context).extension<PaletteColors>() ?? defaultPalette.light;

/// Four dots with a palette's colours (light primary and action, dark primary and action), for Settings.
class PaletteSwatch extends StatelessWidget {
  final AppPalette palette;
  const PaletteSwatch(this.palette, {super.key});

  @override
  Widget build(BuildContext context) {
    Widget dot(Color c) => Container(
          width: 12,
          height: 12,
          margin: const EdgeInsets.only(right: 3),
          decoration:
              BoxDecoration(color: c, shape: BoxShape.circle, border: Border.all(color: Colors.black26, width: 0.5)),
        );
    return Row(mainAxisSize: MainAxisSize.min, children: [
      dot(palette.light.primary),
      dot(palette.light.action),
      const SizedBox(width: 4),
      dot(palette.dark.primary),
      dot(palette.dark.action),
    ]);
  }
}
