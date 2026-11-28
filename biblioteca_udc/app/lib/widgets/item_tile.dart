import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../core/actions.dart';
import '../core/app_state.dart';
import '../core/i18n.dart';
import '../core/models.dart';
import '../core/theme.dart';
import '../screens/item_form.dart';
import 'highlight_text.dart';
import 'udc_breakdown.dart';

/// "Suggested by Crossref (90%)" for values no person has confirmed yet.
String sourceLabel(String source, double? confidence) {
  final names = {
    'pdfmeta': tr('the PDF metadata'), 'layout': tr('the page layout'), 'regex': tr('a text pattern'),
    'inid': tr('INID codes'), 'filename': tr('the file name'), 'ner': tr('name recognition'),
    'crossref': 'Crossref', 'openlibrary': 'Open Library', 'arxiv': 'arXiv', 'llm': tr('the language model'),
    'classifier': tr('the UDC classifier'), 'langid': tr('language detection'), 'import': tr('the bulk import'),
  };
  final pct = confidence == null ? '' : ' (${(confidence * 100).round()}%)';
  return tr('Suggested by {s}{p}, not confirmed yet', {'s': names[source] ?? source, 'p': pct});
}

/// "2026-11-25 14:03" from the server's ISO time (UTC), in local time.
String formatAdded(String iso) {
  final d = DateTime.tryParse(iso)?.toLocal();
  if (d == null) return iso;
  String two(int n) => n.toString().padLeft(2, '0');
  return '${d.year}-${two(d.month)}-${two(d.day)} ${two(d.hour)}:${two(d.minute)}';
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

/// Authors for the result row: at most [max] names, then "(+n)".
String shortCreators(Item item, {int max = 3}) {
  final names = [for (final c in item.creators) c.lastName].where((n) => n.trim().isNotEmpty).toList();
  if (names.isEmpty) return item.creatorsText;
  if (names.length <= max) return names.join('; ');
  return '${names.take(max).join('; ')} (+${names.length - max})';
}

/// One result: check box, title (one line), authors | year | type | size. Tapping it unfolds the record.
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
      if (item.year != null) '${item.year}',
      s.typeLabel(item.itemType),
      formatBytes(item.size) + (extra > 0 ? ' + ${tr('{n} supplementary', {'n': extra})}' : ''),
    ].join('  |  ');
    final authors = shortCreators(item);

    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
      elevation: 0,
      color: open ? cs.surfaceContainerHigh : cs.surfaceContainerLow,
      clipBehavior: Clip.antiAlias,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        InkWell(
          onTap: () => s.toggleItem(item.id),
          child: Padding(
            padding: const EdgeInsets.fromLTRB(6, 8, 8, 8),
            child: Row(children: [
              SmallCheckbox(value: s.selectedIds.contains(item.id), onChanged: (_) => s.toggleSelected(item.id)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Tooltip(
                    message: item.title,
                    child: HighlightText(item.title,
                        spans: item.matches[titleField],
                        maxLines: 1,
                        style: const TextStyle(fontWeight: FontWeight.w600, fontSize: kFsBody)),
                  ),
                  const SizedBox(height: 2),
                  Row(children: [
                    if (authors.isNotEmpty)
                      Flexible(
                        child: Tooltip(
                          message: item.creatorsText,
                          child: Text(authors,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(color: cs.onSurfaceVariant, fontSize: kFsTiny)),
                        ),
                      ),
                    Flexible(
                      child: Text('${authors.isNotEmpty ? '  |  ' : ''}$meta',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(color: cs.onSurfaceVariant, fontSize: kFsTiny)),
                    ),
                  ]),
                ]),
              ),
              if (item.hasUnconfirmed)
                Tooltip(
                    message: tr('Has values suggested automatically that nobody has confirmed'),
                    child: Icon(Icons.auto_awesome, size: 16, color: cs.tertiary)),
              if (pinned)
                Tooltip(message: tr('Kept offline'), child: Icon(Icons.offline_pin, size: 16, color: cs.primary))
              else if (cached)
                Tooltip(
                    message: tr('Saved on this device'),
                    child: Icon(Icons.download_done, size: 16, color: cs.onSurfaceVariant)),
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

/// The unfolded record: fields | cover, supplementary material, notes, and the action buttons at the bottom.
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
      _Row(tr('Item type'), s.typeLabel(item.itemType), 'type'),
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
        _Row(tr('UDC'), item.udcText, 'udc',
            item.udc.any((u) => !u.confirmed)
                ? FieldValue('', source: item.udc.firstWhere((u) => !u.confirmed).source,
                    confidence: item.udc.firstWhere((u) => !u.confirmed).confidence, confirmed: false)
                : null),
      if (item.tags.isNotEmpty) _Row(tr('Tags'), item.tags.map((t) => t.name).join('; '), 'tags'),
      if (item.addedAt.isNotEmpty) _Row(tr('Date added'), formatAdded(item.addedAt), null),
    ];

    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 14),
      child: LayoutBuilder(builder: (context, c) {
        final narrow = c.maxWidth < 560;
        final labelW = narrow ? 96.0 : 120.0;

        Widget row(_Row r) => Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                SizedBox(
                    width: labelW,
                    child: Text(r.label, style: TextStyle(color: cs.onSurfaceVariant, fontSize: kFsSmall))),
                Expanded(
                  child: SelectionArea(
                    child: HighlightText(r.text,
                        spans: r.matchKey == null ? null : item.matches[r.matchKey],
                        style: const TextStyle(fontSize: kFsSmall)),
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
              // every part of the UDC number with its meaning
              if (r.matchKey == 'udc')
                Container(
                  margin: EdgeInsets.only(left: labelW, bottom: 8),
                  padding: const EdgeInsets.fromLTRB(8, 5, 8, 5),
                  decoration: BoxDecoration(
                    color: cs.surfaceContainerLowest,
                    border: Border.all(color: cs.outlineVariant.withValues(alpha: 0.6)),
                    borderRadius: BorderRadius.circular(kRadius),
                  ),
                  child: UdcBreakdown(item.udcText),
                ),
            ],
          row(_Row(tr('File'),
              '${item.filename}  (${formatBytes(item.size)}${item.pages != null ? ', ${tr('{n} pages', {'n': item.pages})}' : ''})',
              null)),
        ]);

        final cover = ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: Image.network(
            s.api.coverUrl(item.id),
            headers: s.api.headers,
            width: 140,
            fit: BoxFit.fitWidth,
            errorBuilder: (_, __, ___) => Container(
              width: 140, height: 190, color: cs.surfaceContainerHighest,
              child: Icon(Icons.picture_as_pdf, size: 44, color: cs.onSurfaceVariant),
            ),
            loadingBuilder: (_, child, p) => p == null
                ? child
                : const SizedBox(width: 140, height: 190, child: Center(child: CircularProgressIndicator(strokeWidth: 2))),
          ),
        );

        final pinned = s.cache.isPinned(item);
        final buttons = Wrap(spacing: 8, runSpacing: 8, children: [
          FilledButton.icon(
              onPressed: () => openItem(context, item),
              icon: const Icon(Icons.open_in_new, size: 16),
              label: Text(tr('Open'))),
          if (s.user?.canEdit ?? false)
            OutlinedButton.icon(
                onPressed: s.offline ? null : () => editItemDialog(context, item),
                icon: const Icon(Icons.edit_outlined, size: 16),
                label: Text(tr('Edit fields'))),
          OutlinedButton.icon(
              onPressed: () => togglePin(context, item),
              icon: Icon(pinned ? Icons.offline_pin : Icons.offline_pin_outlined, size: 16),
              label: Text(pinned ? tr('Kept offline') : tr('Keep offline'))),
          if (s.user?.canEdit ?? false)
            OutlinedButton.icon(
                onPressed: s.offline ? null : () => deleteItemFlow(context, item),
                style: OutlinedButton.styleFrom(foregroundColor: cs.error),
                icon: const Icon(Icons.delete_outline, size: 16),
                label: Text(tr('Delete'))),
        ]);

        return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Divider(height: 10),
          if (narrow) ...[
            Center(child: cover),
            const SizedBox(height: 10),
            details,
          ] else
            Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: details),
              const SizedBox(width: 16),
              cover,
            ]),
          if (item.supplementary.isNotEmpty || canEdit) SupplementarySection(item: item, canEdit: canEdit),
          if (item.notes.isNotEmpty || canEdit) NotesSection(item: item, canEdit: canEdit),
          const Divider(height: 22),
          buttons,
        ]);
      }),
    );
  }
}

/// Titles inside the card ("Supplementary material", "Notes"): one step above the card's text.
TextStyle _sectionStyle(BuildContext context) =>
    TextStyle(fontSize: kFsBody, fontWeight: FontWeight.w700, color: Theme.of(context).colorScheme.onSurface);

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
      padding: const EdgeInsets.only(top: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.attach_file, size: 17, color: cs.onSurfaceVariant),
          const SizedBox(width: 6),
          Expanded(child: Text(tr('Supplementary material'), style: _sectionStyle(context))),
          if (canEdit)
            TextButton.icon(
                style: plainButton,
                onPressed: () => addSupplementaryFlow(context, item),
                icon: const Icon(Icons.add, size: 16),
                label: Text(tr('Add file'))),
        ]),
        if (files.isEmpty)
          Padding(
            padding: const EdgeInsets.only(left: 23, top: 2),
            child: Text(tr('None. Extra PDFs that come with this item (errata, solutions, parts) go here.'),
                style: TextStyle(color: cs.onSurfaceVariant, fontSize: kFsTiny)),
          ),
        for (final a in files)
          Padding(
            padding: const EdgeInsets.only(left: 23, top: 4),
            child: Row(children: [
              Expanded(
                child: Text.rich(
                  TextSpan(children: [
                    TextSpan(text: a.label, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: kFsSmall)),
                    TextSpan(
                        text: '  ${formatBytes(a.size)}${a.pages != null ? ', ${tr('{n} pages', {'n': a.pages})}' : ''}',
                        style: TextStyle(color: cs.onSurfaceVariant, fontSize: kFsTiny)),
                  ]),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              SmallIconButton(
                  tooltip: tr('Open'), onPressed: () => openItem(context, item, a), icon: Icons.open_in_new),
              SmallIconButton(
                  tooltip: s.cache.isPinned(item, a) ? tr('Kept offline') : tr('Keep offline'),
                  onPressed: () => togglePin(context, item, a),
                  icon: s.cache.isPinned(item, a) ? Icons.offline_pin : Icons.offline_pin_outlined),
              if (canEdit)
                PopupMenuButton<String>(
                  tooltip: tr('More'),
                  iconSize: kIconSize,
                  onSelected: (v) => switch (v) {
                    'rename' => renameSupplementaryFlow(context, item, a),
                    'up' => moveSupplementary(context, item, a, -1),
                    'down' => moveSupplementary(context, item, a, 1),
                    _ => trashSupplementaryFlow(context, item, a),
                  },
                  itemBuilder: (_) => [
                    PopupMenuItem(height: kMenuItemHeight, value: 'rename', child: Text(tr('Change label'))),
                    if (files.first.id != a.id)
                      PopupMenuItem(height: kMenuItemHeight, value: 'up', child: Text(tr('Move up'))),
                    if (files.last.id != a.id)
                      PopupMenuItem(height: kMenuItemHeight, value: 'down', child: Text(tr('Move down'))),
                    PopupMenuItem(
                        height: kMenuItemHeight,
                        value: 'trash',
                        child: Text(tr('Move to trash'), style: TextStyle(color: cs.error))),
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
      padding: const EdgeInsets.only(top: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(Icons.sticky_note_2_outlined, size: 17, color: cs.onSurfaceVariant),
          const SizedBox(width: 6),
          Expanded(child: Text(tr('Notes'), style: _sectionStyle(context))),
          if (canEdit)
            TextButton.icon(
                style: plainButton,
                onPressed: () => editNoteFlow(context, item),
                icon: const Icon(Icons.add, size: 16),
                label: Text(tr('Add note'))),
        ]),
        for (final n in item.notes)
          Padding(
            padding: const EdgeInsets.only(left: 23, top: 4),
            child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Expanded(child: SelectableText(n.body, style: const TextStyle(fontSize: kFsSmall))),
              if (canEdit) ...[
                SmallIconButton(
                    tooltip: tr('Edit note'), onPressed: () => editNoteFlow(context, item, n), icon: Icons.edit_outlined),
                SmallIconButton(
                    tooltip: tr('Delete note'),
                    onPressed: () => deleteNoteFlow(context, item, n),
                    icon: Icons.delete_outline,
                    color: cs.error),
              ],
            ]),
          ),
      ]),
    );
  }
}
