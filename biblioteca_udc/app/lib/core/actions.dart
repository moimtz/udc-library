import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import 'api.dart';
import 'app_state.dart';
import 'i18n.dart';
import 'models.dart';
import 'theme.dart';

void toast(BuildContext context, String message, {bool error = false}) {
  final cs = Theme.of(context).colorScheme;
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(message, style: TextStyle(color: error ? cs.onError : null)),
      backgroundColor: error ? cs.error : null,
      behavior: SnackBarBehavior.floating,
    ));
}

/// Opens a PDF with the system's default viewer. Returns an error message or null.
Future<String?> launchPdf(String path) async {
  try {
    if (Platform.isWindows) {
      await Process.start('explorer.exe', [path], mode: ProcessStartMode.detached);
      return null;
    }
    final r = await OpenFilex.open(path, type: 'application/pdf');
    return r.type == ResultType.done ? null : r.message;
  } catch (e) {
    return tr('Could not open the PDF: {e}', {'e': e});
  }
}

class _ProgressDialog extends StatelessWidget {
  final ValueNotifier<double?> progress;
  final String title;
  const _ProgressDialog({required this.progress, required this.title});

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: false,
        child: AlertDialog(
          title: Text(tr('Downloading')),
          content: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(title, maxLines: 2, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 16),
            ValueListenableBuilder<double?>(
              valueListenable: progress,
              builder: (_, v, __) => LinearProgressIndicator(value: v),
            ),
          ]),
        ),
      );
}

/// Makes sure a local copy of the main file (or of [att]) exists, showing progress if a download is needed.
Future<String?> _localCopy(BuildContext context, Item item, [Attachment? att]) async {
  final state = context.read<AppState>();
  final needs = !state.cache.isFresh(item, att);
  final progress = ValueNotifier<double?>(null);
  var dialogOpen = false;
  if (needs) {
    dialogOpen = true;
    showDialog(
      context: context,
      barrierDismissible: false,
      useRootNavigator: true,
      builder: (_) => _ProgressDialog(progress: progress, title: att == null ? item.title : '${item.title}: ${att.label}'),
    );
  }
  void closeDialog() {
    if (dialogOpen && context.mounted) {
      Navigator.of(context, rootNavigator: true).pop();
    }
    dialogOpen = false;
  }

  try {
    final r = await state.cache.ensure(state.api, item,
        att: att,
        onProgress: (got, total) => progress.value = total > 0 ? got / total : null);
    closeDialog();
    if (r.stale && context.mounted) {
      toast(context, tr('Server unreachable. Opened the copy saved on this device.'));
    }
    return r.path;
  } on ApiException catch (e) {
    closeDialog();
    if (context.mounted) {
      toast(context, e.isNetwork ? '${tr(e.message)} ${tr('This file is not saved offline.')}' : tr(e.message),
          error: true);
    }
    return null;
  } finally {
    progress.dispose();
  }
}

/// Opens the main file, or the supplementary file [att].
Future<void> openItem(BuildContext context, Item item, [Attachment? att]) async {
  final path = await _localCopy(context, item, att);
  if (path == null) return;
  final err = await launchPdf(path);
  if (err != null && context.mounted) {
    toast(context, err.isEmpty ? tr('No app on this device can open PDF files.') : err, error: true);
  }
}

Future<void> togglePin(BuildContext context, Item item, [Attachment? att]) async {
  final cache = context.read<AppState>().cache;
  if (cache.isPinned(item, att)) {
    await cache.setPinned(item, false, att);
    if (context.mounted) toast(context, tr('No longer kept offline.'));
    return;
  }
  final path = await _localCopy(context, item, att);
  if (path == null) return;
  await cache.setPinned(item, true, att);
  if (context.mounted) toast(context, tr('Kept offline on this device.'));
}

Future<void> deleteItemFlow(BuildContext context, Item item) async {
  final state = context.read<AppState>();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(tr('Move to trash?')),
      content: Text(tr('"{t}" will be kept in the trash for {d} days. You can restore it from the Trash screen.',
          {'t': item.title, 'd': state.stats?['trash_days'] ?? 30})),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
        FilledButton(style: dangerButton(ctx), onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Move to trash'))),
      ],
    ),
  );
  if (ok != true) return;
  // optimistic: the item leaves the list at once; it comes back if the server refuses
  final taken = state.takeOut([item.id]);
  try {
    await state.api.trashItem(item.id);
    if (context.mounted) toast(context, tr('Moved to trash.'));
    await state.cache.removeItem(item.id);
    state.refreshAfterChange(); // tree and storage, in the background
  } on ApiException catch (e) {
    state.putBack(taken);
    if (context.mounted) toast(context, tr('Could not move to trash: {e}', {'e': tr(e.message)}), error: true);
  }
}

// ---------------------------------------------------------------------- actions on the ticked items
/// Keeps offline (downloading what is missing) or removes from this device every ticked item.
Future<void> bulkPin(BuildContext context, List<Item> items, bool keep) async {
  final state = context.read<AppState>();
  var done = 0;
  for (final it in items) {
    if (!context.mounted) return;
    if (keep) {
      if (!state.cache.isPinned(it)) {
        final path = await _localCopy(context, it);
        if (path == null) break; // the error was shown: stop here
        await state.cache.setPinned(it, true);
      }
    } else {
      await state.cache.removeItem(it.id);
    }
    done++;
  }
  if (context.mounted) {
    toast(context,
        keep ? tr('{n} items kept offline.', {'n': done}) : tr('{n} items removed from this device.', {'n': done}));
  }
}

/// Moves every ticked item to the trash, after one confirmation.
Future<void> bulkTrashFlow(BuildContext context, List<Item> items) async {
  final state = context.read<AppState>();
  if (items.isEmpty) return;
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(tr('Move {n} items to trash?', {'n': items.length})),
      content: Text(tr('They will be kept in the trash for {d} days. You can restore them from the Trash screen.',
          {'d': state.stats?['trash_days'] ?? 30})),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
        FilledButton(style: dangerButton(ctx), onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Move to trash'))),
      ],
    ),
  );
  if (ok != true) return;
  // optimistic: all of them leave the list at once; the ones the server refuses come back
  final taken = state.takeOut(items.map((i) => i.id));
  var moved = 0;
  String? error;
  for (final it in items) {
    try {
      await state.api.trashItem(it.id);
      await state.cache.removeItem(it.id);
      moved++;
    } on ApiException catch (e) {
      error ??= tr(e.message);
      state.putBack(taken.where((t) => t.$2.id == it.id).toList());
    }
  }
  state.refreshAfterChange(); // tree and storage, in the background
  if (!context.mounted) return;
  if (error == null) {
    toast(context, tr('{n} items moved to trash.', {'n': moved}));
  } else {
    toast(context, tr('{n} of {t} items moved to trash. The others: {e}', {'n': moved, 't': items.length, 'e': error}),
        error: true);
  }
}

// ---------------------------------------------------------------------- supplementary material and notes
/// Asks for one line (or several, [multiline]) of text. Returns null on Cancel.
Future<String?> askText(BuildContext context,
    {required String title, String label = '', String initial = '', String? ok, bool multiline = false}) async {
  final ctl = TextEditingController(text: initial);
  final r = await showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: SizedBox(
        width: 460,
        child: TextField(
          controller: ctl,
          autofocus: true,
          minLines: multiline ? 4 : 1,
          maxLines: multiline ? 12 : 1,
          decoration: InputDecoration(labelText: label),
          onSubmitted: multiline ? null : (v) => Navigator.pop(ctx, v),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: Text(tr('Cancel'))),
        FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text), child: Text(ok ?? tr('Save'))),
      ],
    ),
  );
  // disposed after the dialog's closing animation, which still uses it
  Future.delayed(const Duration(milliseconds: 400), ctl.dispose);
  return r;
}

Future<void> _updateItem(BuildContext context, Future<Item> Function() call, String done) async {
  final state = context.read<AppState>();
  try {
    final item = await call();
    state.itemUpdated(item);
    if (context.mounted) toast(context, done);
  } on ApiException catch (e) {
    if (context.mounted) toast(context, tr(e.message), error: true);
  }
}

/// Adds a PDF as supplementary material (errata, solutions manual, parts...) with a label.
Future<void> addSupplementaryFlow(BuildContext context, Item item) async {
  final state = context.read<AppState>();
  final res = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['pdf']);
  final file = res?.files.single;
  if (file?.path == null || !context.mounted) return;
  final label = await askText(context,
      title: tr('Supplementary file'), label: tr('Label (e.g. Errata, Solutions manual, Parts)'), ok: tr('Add'));
  if (label == null || label.trim().isEmpty || !context.mounted) {
    if (label != null && context.mounted) toast(context, tr('A supplementary file needs a label.'), error: true);
    return;
  }
  toast(context, tr('Uploading {f}...', {'f': file!.name}));
  await _updateItem(context, () async {
    final up = await state.api.upload(file.path!, file.name);
    return state.api.addAttachment(item.id, up['temp_id'] as String, label.trim());
  }, tr('Supplementary file added.'));
  // only the storage figures: reloading the whole list here made the open card jump (bug of v0.1)
  await state.refreshStats();
}

Future<void> renameSupplementaryFlow(BuildContext context, Item item, Attachment att) async {
  final label = await askText(context, title: tr('Change label'), label: tr('Label'), initial: att.label);
  if (label == null || label.trim().isEmpty || label.trim() == att.label || !context.mounted) return;
  await _updateItem(
      context, () => context.read<AppState>().api.renameAttachment(att.id, label.trim()), tr('Label changed.'));
}

Future<void> moveSupplementary(BuildContext context, Item item, Attachment att, int delta) async {
  final ids = [for (final a in item.supplementary) a.id];
  final i = ids.indexOf(att.id);
  final j = i + delta;
  if (i < 0 || j < 0 || j >= ids.length) return;
  ids[i] = ids[j];
  ids[j] = att.id;
  await _updateItem(context, () => context.read<AppState>().api.orderAttachments(item.id, ids), tr('Order changed.'));
}

Future<void> trashSupplementaryFlow(BuildContext context, Item item, Attachment att) async {
  final state = context.read<AppState>();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(tr('Move to trash?')),
      content: Text(tr('"{t}" will be removed from this item and kept in the trash for {d} days.',
          {'t': att.label, 'd': state.stats?['trash_days'] ?? 30})),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
        FilledButton(style: dangerButton(ctx), onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Move to trash'))),
      ],
    ),
  );
  if (ok != true || !context.mounted) return;
  await _updateItem(context, () async {
    await state.api.trashAttachment(att.id);
    await state.cache.removeAttachment(item, att);
    return state.api.getItem(item.id);
  }, tr('Moved to trash.'));
}

Future<void> editNoteFlow(BuildContext context, Item item, [ItemNote? note]) async {
  final body = await askText(context,
      title: note == null ? tr('New note') : tr('Edit note'), initial: note?.body ?? '', multiline: true);
  if (body == null || body.trim().isEmpty || !context.mounted) return;
  final api = context.read<AppState>().api;
  await _updateItem(context, () => note == null ? api.addNote(item.id, body.trim()) : api.editNote(note.id, body.trim()),
      tr('Note saved.'));
}

Future<void> deleteNoteFlow(BuildContext context, Item item, ItemNote note) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(tr('Delete note?')),
      content: Text(tr('The note is deleted for good.')),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: Text(tr('Cancel'))),
        FilledButton(style: dangerButton(ctx), onPressed: () => Navigator.pop(ctx, true), child: Text(tr('Delete'))),
      ],
    ),
  );
  if (ok != true || !context.mounted) return;
  await _updateItem(context, () => context.read<AppState>().api.deleteNote(note.id), tr('Note deleted.'));
}
