import 'package:flutter/material.dart';

import '../core/theme.dart';

/// One option of a [CompactDropdown]: value, text and an optional tooltip.
class Opt<T> {
  final T value;
  final String text;
  final String? tip;
  final Widget? leading; // e.g. colour dots of a palette
  const Opt(this.value, this.text, {this.tip, this.leading});
}

/// Dropdown with the options close together (Flutter's DropdownButton forces 48 px per option).
/// Used for Sort, Language, Cache size, Item type, Role...
///
/// With [label] it looks like a form box (label on the border); without it, it is plain text + arrow
/// (for use inside a [Framed] or a list tile).
class CompactDropdown<T> extends StatelessWidget {
  final T? value;
  final List<Opt<T>> options;
  final ValueChanged<T>? onChanged; // null = disabled
  final String? label;
  final Widget? suffix; // e.g. a help icon inside the box

  const CompactDropdown({
    super.key,
    required this.value,
    required this.options,
    required this.onChanged,
    this.label,
    this.suffix,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final current = options.where((o) => o.value == value).firstOrNull;
    final enabled = onChanged != null;
    return MenuAnchor(
      style: const MenuStyle(maximumSize: WidgetStatePropertyAll(Size(380, 440))),
      menuChildren: [
        for (final o in options)
          _wrapTip(
            o.tip,
            MenuItemButton(
              leadingIcon: o.leading,
              onPressed: () => onChanged?.call(o.value),
              child: Text(o.text,
                  style: o.value == value ? TextStyle(fontWeight: FontWeight.w700, color: cs.primary) : null),
            ),
          ),
      ],
      builder: (context, ctl, _) {
        final text = Text(current?.text ?? '',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: kFsBody, color: enabled ? cs.onSurface : cs.onSurface.withValues(alpha: 0.4)));
        final arrow = Icon(Icons.arrow_drop_down, size: 20, color: cs.onSurfaceVariant);
        void toggle() => ctl.isOpen ? ctl.close() : ctl.open();
        if (label == null) {
          return InkWell(
            borderRadius: BorderRadius.circular(kRadius),
            onTap: enabled ? toggle : null,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                if (current?.leading != null) ...[current!.leading!, const SizedBox(width: 6)],
                Flexible(child: text),
                arrow,
              ]),
            ),
          );
        }
        return InkWell(
          borderRadius: BorderRadius.circular(kRadius),
          onTap: enabled ? toggle : null,
          child: InputDecorator(
            isEmpty: current == null,
            decoration: InputDecoration(labelText: label, enabled: enabled, suffixIcon: suffix),
            child: Row(children: [Expanded(child: text), arrow]),
          ),
        );
      },
    );
  }

  static Widget _wrapTip(String? tip, Widget w) => tip == null || tip.isEmpty ? w : Tooltip(message: tip, child: w);
}
