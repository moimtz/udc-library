import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/app_state.dart';
import '../core/models.dart';
import '../screens/item_form.dart';
import 'highlight_text.dart';

/// One result row. Tapping it unfolds the full bibliographic record below.
class ItemTile extends StatelessWidget {
  final Item item;
  const ItemTile({super.key, required this.item});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final open = s.expandedItemId == item.id;
    final cs = Theme.of(context).colorScheme;
    final cached = s.cache.has(item.id);
    final pinned = s.cache.isPinned(item.id);
    final meta = [
      if (item.creatorsText.isNotEmpty) item.creatorsText,
      if (item.year != null) '${item.year}',
      s.typeLabel(item.itemType),
      formatBytes(item.size),
    ].join('  |  ');

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      elevation: 0,
      color: open ? cs.surfaceContainerHigh : cs.surfaceContainerLow,
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        InkWell(
          onTap: () => s.toggleItem(item.id),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(14, 10, 10, 10),
            child: Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  HighlightText(item.title,
                      spans: item.matches['title'],
                      maxLines: 2,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                  const SizedBox(height: 3),
                  Text(meta,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
                ]),
              ),
              if (pinned)
                Tooltip(message: 'Kept offline', child: Icon(Icons.offline_pin, size: 18, color: cs.primary))
              else if (cached)
                Tooltip(message: 'Saved on this device', child: Icon(Icons.download_done, size: 18, color: cs.onSurfaceVariant)),
              Icon(open ? Icons.expand_less : Icons.expand_more, color: cs.onSurfaceVariant),
            ]),
          ),
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 160),
          alignment: Alignment.topCenter,
          child: open ? _Detail(item: item) : const SizedBox(width: double.infinity),
        ),
      ]),
    );
  }
}

class _Detail extends StatelessWidget {
  final Item item;
  const _Detail({required this.item});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final type = s.schema.type(item.itemType);

    final rows = <(String, String, String?)>[
      ('Authors', item.creatorsText, 'creators'),
      ('Year', item.year?.toString() ?? '', 'year'),
      ('Type', s.typeLabel(item.itemType), 'type'),
      ('Language', item.language, 'language'),
      ('UDC', item.udc, 'udc'),
      for (final key in type?.fields ?? <String>[])
        if ((item.data[key] ?? '').isNotEmpty) (s.schema.fields[key]?.label ?? key, item.data[key]!, key),
      ('Citation key', item.citekey, 'citekey'),
      ('File', '${item.filename}  (${formatBytes(item.size)}${item.pages != null ? ', ${item.pages} pages' : ''})', null),
    ];
    final udcText = s.udc.describe(item.udc, s.udcLang);

    final details = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final r in rows)
        if (r.$2.isNotEmpty)
          Padding(
            padding: const EdgeInsets.only(bottom: 6),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              SizedBox(
                width: 104,
                child: Text(r.$1, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13)),
              ),
              Expanded(
                child: SelectionArea(
                  child: HighlightText(r.$2, spans: r.$3 == null ? null : item.matches[r.$3], style: const TextStyle(fontSize: 13.5)),
                ),
              ),
            ]),
          ),
      if (udcText.isNotEmpty)
        Padding(
          padding: const EdgeInsets.only(left: 104, bottom: 6),
          child: Text(udcText, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
        ),
    ]);

    final cover = ClipRRect(
      borderRadius: BorderRadius.circular(4),
      child: Image.network(
        s.api.coverUrl(item.id),
        headers: s.api.headers,
        width: 150,
        fit: BoxFit.fitWidth,
        errorBuilder: (_, __, ___) => Container(
          width: 150, height: 200, color: cs.surfaceContainerHighest,
          child: Icon(Icons.picture_as_pdf, size: 48, color: cs.onSurfaceVariant),
        ),
        loadingBuilder: (_, child, p) => p == null
            ? child
            : SizedBox(width: 150, height: 200, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
      ),
    );

    final pinned = s.cache.isPinned(item.id);
    final buttons = Wrap(spacing: 8, runSpacing: 8, children: [
      FilledButton.icon(
          onPressed: () => openItem(context, item), icon: const Icon(Icons.open_in_new, size: 18), label: const Text('Open')),
      if (s.user?.canEdit ?? false)
        OutlinedButton.icon(
            onPressed: s.offline ? null : () => editItemDialog(context, item),
            icon: const Icon(Icons.edit_outlined, size: 18),
            label: const Text('Edit fields')),
      OutlinedButton.icon(
          onPressed: () => togglePin(context, item),
          icon: Icon(pinned ? Icons.offline_pin : Icons.offline_pin_outlined, size: 18),
          label: Text(pinned ? 'Kept offline' : 'Keep offline')),
      if (s.user?.canEdit ?? false)
        TextButton.icon(
            onPressed: s.offline ? null : () => deleteItemFlow(context, item),
            style: TextButton.styleFrom(foregroundColor: cs.error),
            icon: const Icon(Icons.delete_outline, size: 18),
            label: const Text('Delete')),
    ]);

    return Padding(
      padding: const EdgeInsets.fromLTRB(14, 4, 14, 14),
      child: LayoutBuilder(builder: (context, c) {
        final narrow = c.maxWidth < 560;
        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Divider(height: 12),
          if (narrow) ...[
            Center(child: cover),
            const SizedBox(height: 12),
            details,
          ] else
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: details),
              const SizedBox(width: 16),
              cover,
            ]),
          const SizedBox(height: 8),
          buttons,
        ]);
      }),
    );
  }
}
