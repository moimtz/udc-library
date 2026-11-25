import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/app_state.dart';
import '../core/models.dart';
import '../screens/item_form.dart';
import 'highlight_text.dart';

/// "Suggested by Crossref (90%)" for values no person has confirmed yet.
String sourceLabel(String source, double? confidence) {
  const names = {
    'pdfmeta': 'the PDF metadata', 'layout': 'the page layout', 'regex': 'a text pattern', 'inid': 'INID codes',
    'filename': 'the file name', 'ner': 'name recognition', 'crossref': 'Crossref', 'openlibrary': 'Open Library',
    'arxiv': 'arXiv', 'llm': 'the language model', 'classifier': 'the UDC classifier',
  };
  final pct = confidence == null ? '' : ' (${(confidence * 100).round()}%)';
  return 'Suggested by ${names[source] ?? source}$pct, not confirmed yet';
}

/// Small marker shown next to an automatic value that nobody has confirmed.
class UnconfirmedMark extends StatelessWidget {
  final String source;
  final double? confidence;
  const UnconfirmedMark(this.source, this.confidence, {super.key});

  @override
  Widget build(BuildContext context) => Tooltip(
        message: sourceLabel(source, confidence),
        child: Padding(
          padding: const EdgeInsets.only(left: 4),
          child: Icon(Icons.auto_awesome, size: 14, color: Theme.of(context).colorScheme.tertiary),
        ),
      );
}

/// One result row. Tapping it unfolds the full bibliographic record below.
class ItemTile extends StatelessWidget {
  final Item item;
  const ItemTile({super.key, required this.item});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final open = s.expandedItemId == item.id;
    final cs = Theme.of(context).colorScheme;
    final cached = s.cache.has(item);
    final pinned = s.cache.isPinned(item);
    final titleField = s.schema.type(item.itemType)?.titleField ?? 'title';
    final extra = item.supplementary.length;
    final meta = [
      if (item.creatorsText.isNotEmpty) item.creatorsText,
      if (item.year != null) '${item.year}',
      s.typeLabel(item.itemType),
      formatBytes(item.size) + (extra > 0 ? ' + $extra supplementary' : ''),
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
                      spans: item.matches[titleField],
                      maxLines: 2,
                      style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                  const SizedBox(height: 3),
                  Text(meta,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
                ]),
              ),
              if (item.hasUnconfirmed)
                Tooltip(
                    message: 'Has values suggested automatically that nobody has confirmed',
                    child: Icon(Icons.auto_awesome, size: 18, color: cs.tertiary)),
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

class _Row {
  final String label;
  final String text;
  final String? matchKey;
  final FieldValue? provenance;
  const _Row(this.label, this.text, this.matchKey, [this.provenance]);
}

class _Detail extends StatelessWidget {
  final Item item;
  const _Detail({required this.item});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final type = s.schema.type(item.itemType);
    final canEdit = (s.user?.canEdit ?? false) && !s.offline;

    // Creators grouped by role, in citation order: "Author", "Editor"...
    final byRole = <String, List<Creator>>{};
    for (final c in item.creators) {
      byRole.putIfAbsent(c.creatorType, () => []).add(c);
    }
    String names(List<Creator> cs) =>
        cs.map((c) => c.fieldMode == 1 || c.firstName.isEmpty ? c.lastName : '${c.lastName}, ${c.firstName}').join('; ');

    final rows = <_Row>[
      _Row('Item type', s.typeLabel(item.itemType), 'type'),
      for (final e in byRole.entries)
        _Row(s.schema.creatorLabel(e.key), names(e.value), 'creators',
            e.value.any((c) => !c.confirmed)
                ? FieldValue('', source: e.value.firstWhere((c) => !c.confirmed).source,
                    confidence: e.value.firstWhere((c) => !c.confirmed).confidence, confirmed: false)
                : null),
      for (final f in type?.fields ?? const <FieldDef>[])
        if (!f.hidden && item.value(f.code).isNotEmpty) _Row(f.label, item.value(f.code), f.code, item.fields[f.code]),
      // values of fields the type no longer has (should not happen; shown rather than hidden)
      for (final e in item.fields.entries)
        if (type?.field(e.key) == null) _Row(s.schema.fieldLabel(e.key), e.value.value, e.key, e.value),
      if (item.udc.isNotEmpty)
        _Row('UDC', item.udcText, 'udc',
            item.udc.any((u) => !u.confirmed)
                ? FieldValue('', source: item.udc.firstWhere((u) => !u.confirmed).source,
                    confidence: item.udc.firstWhere((u) => !u.confirmed).confidence, confirmed: false)
                : null),
      if (item.tags.isNotEmpty) _Row('Tags', item.tags.map((t) => t.name).join('; '), 'tags'),
      _Row('Citation key', item.citekey, 'citekey'),
    ];
    final udcText = [for (final u in item.udc) s.udc.describe(u.notation, s.udcLang)].where((t) => t.isNotEmpty).join('; ');

    Widget row(_Row r) => Padding(
          padding: const EdgeInsets.only(bottom: 6),
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: 120, child: Text(r.label, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 13))),
            Expanded(
              child: SelectionArea(
                child: HighlightText(r.text,
                    spans: r.matchKey == null ? null : item.matches[r.matchKey], style: const TextStyle(fontSize: 13.5)),
              ),
            ),
            if (r.provenance != null && !r.provenance!.confirmed)
              UnconfirmedMark(r.provenance!.source, r.provenance!.confidence),
          ]),
        );

    final details = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      for (final r in rows)
        if (r.text.isNotEmpty) ...[
          row(r),
          if (r.matchKey == 'udc' && udcText.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(left: 120, bottom: 6),
              child: Text(udcText, style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12)),
            ),
        ],
      row(_Row('File',
          '${item.filename}  (${formatBytes(item.size)}${item.pages != null ? ', ${item.pages} pages' : ''})', null)),
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
            : const SizedBox(width: 150, height: 200, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
      ),
    );

    final pinned = s.cache.isPinned(item);
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
          if (item.supplementary.isNotEmpty || canEdit) SupplementarySection(item: item, canEdit: canEdit),
          if (item.notes.isNotEmpty || canEdit) NotesSection(item: item, canEdit: canEdit),
        ]);
      }),
    );
  }
}

/// "Supplementary material": extra files of the item (errata, solutions, parts...), each with its label.
class SupplementarySection extends StatelessWidget {
  final Item item;
  final bool canEdit;
  const SupplementarySection({super.key, required this.item, required this.canEdit});

  @override
  Widget build(BuildContext context) {
    final s = context.watch<AppState>();
    final cs = Theme.of(context).colorScheme;
    final files = item.supplementary;
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.attach_file, size: 18, color: cs.onSurfaceVariant),
          const SizedBox(width: 6),
          Expanded(child: Text('Supplementary material', style: Theme.of(context).textTheme.titleSmall)),
          if (canEdit)
            TextButton.icon(
                onPressed: () => addSupplementaryFlow(context, item),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('Add file')),
        ]),
        if (files.isEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 24, top: 2),
            child: Text('None. Extra PDFs that come with this item (errata, solutions, parts) go here.',
                style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
          ),
        for (final a in files)
          Padding(
            padding: const EdgeInsets.only(left: 24, top: 4),
            child: Wrap(crossAxisAlignment: WrapCrossAlignment.center, spacing: 8, runSpacing: 4, children: [
              ConstrainedBox(
                constraints: const BoxConstraints(minWidth: 180),
                child: Text.rich(TextSpan(children: [
                  TextSpan(text: a.label, style: const TextStyle(fontWeight: FontWeight.w600)),
                  TextSpan(
                      text: '  ${formatBytes(a.size)}${a.pages != null ? ', ${a.pages} pages' : ''}',
                      style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
                ])),
              ),
              OutlinedButton.icon(
                  onPressed: () => openItem(context, item, a),
                  icon: const Icon(Icons.open_in_new, size: 16),
                  label: const Text('Open')),
              OutlinedButton.icon(
                  onPressed: () => togglePin(context, item, a),
                  icon: Icon(s.cache.isPinned(item, a) ? Icons.offline_pin : Icons.offline_pin_outlined, size: 16),
                  label: Text(s.cache.isPinned(item, a) ? 'Kept offline' : 'Keep offline')),
              if (canEdit)
                PopupMenuButton<String>(
                  tooltip: 'More',
                  onSelected: (v) => switch (v) {
                    'rename' => renameSupplementaryFlow(context, item, a),
                    'up' => moveSupplementary(context, item, a, -1),
                    'down' => moveSupplementary(context, item, a, 1),
                    _ => trashSupplementaryFlow(context, item, a),
                  },
                  itemBuilder: (_) => [
                    const PopupMenuItem(value: 'rename', child: Text('Change label')),
                    if (files.first.id != a.id) const PopupMenuItem(value: 'up', child: Text('Move up')),
                    if (files.last.id != a.id) const PopupMenuItem(value: 'down', child: Text('Move down')),
                    PopupMenuItem(value: 'trash', child: Text('Move to trash', style: TextStyle(color: cs.error))),
                  ],
                ),
            ]),
          ),
      ]),
    );
  }
}

class NotesSection extends StatelessWidget {
  final Item item;
  final bool canEdit;
  const NotesSection({super.key, required this.item, required this.canEdit});

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.sticky_note_2_outlined, size: 18, color: cs.onSurfaceVariant),
          const SizedBox(width: 6),
          Expanded(child: Text('Notes', style: Theme.of(context).textTheme.titleSmall)),
          if (canEdit)
            TextButton.icon(
                onPressed: () => editNoteFlow(context, item),
                icon: const Icon(Icons.add, size: 18),
                label: const Text('Add note')),
        ]),
        for (final n in item.notes)
          Padding(
            padding: const EdgeInsets.only(left: 24, top: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: SelectableText(n.body, style: const TextStyle(fontSize: 13.5))),
              if (canEdit) ...[
                IconButton(
                    tooltip: 'Edit note',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => editNoteFlow(context, item, n),
                    icon: const Icon(Icons.edit_outlined, size: 18)),
                IconButton(
                    tooltip: 'Delete note',
                    visualDensity: VisualDensity.compact,
                    onPressed: () => deleteNoteFlow(context, item, n),
                    icon: Icon(Icons.delete_outline, size: 18, color: cs.error)),
              ],
            ]),
          ),
      ]),
    );
  }
}
