import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:provider/provider.dart';

import 'api.dart';
import 'app_state.dart';
import 'models.dart';

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
    return 'Could not open the PDF: $e';
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
          title: const Text('Downloading'),
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
      toast(context, 'Server unreachable. Opened the copy saved on this device.');
    }
    return r.path;
  } on ApiException catch (e) {
    closeDialog();
    if (context.mounted) {
      toast(context, e.isNetwork ? '${e.message} This file is not saved offline.' : e.message,
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
    toast(context, err.isEmpty ? 'No app on this device can open PDF files.' : err, error: true);
  }
}

Future<void> togglePin(BuildContext context, Item item, [Attachment? att]) async {
  final cache = context.read<AppState>().cache;
  if (cache.isPinned(item, att)) {
    await cache.setPinned(item, false, att);
    if (context.mounted) toast(context, 'No longer kept offline.');
    return;
  }
  final path = await _localCopy(context, item, att);
  if (path == null) return;
  await cache.setPinned(item, true, att);
  if (context.mounted) toast(context, 'Kept offline on this device.');
}

Future<void> deleteItemFlow(BuildContext context, Item item) async {
  final state = context.read<AppState>();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Move to trash?'),
      content: Text('"${item.title}" will be kept in the trash for '
          '${state.stats?['trash_days'] ?? 30} days. You can restore it from the Trash screen.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Move to trash')),
      ],
    ),
  );
  if (ok != true) return;
  try {
    await state.api.trashItem(item.id);
    await state.itemTrashed(item.id);
    if (context.mounted) toast(context, 'Moved to trash.');
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
}

// ---------------------------------------------------------------------- supplementary material and notes
/// Asks for one line (or several, [multiline]) of text. Returns null on Cancel.
Future<String?> askText(BuildContext context,
    {required String title, String label = '', String initial = '', String ok = 'Save', bool multiline = false}) async {
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
          decoration: InputDecoration(labelText: label, border: const OutlineInputBorder()),
          onSubmitted: multiline ? null : (v) => Navigator.pop(ctx, v),
        ),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(ctx, ctl.text), child: Text(ok)),
      ],
    ),
  );
  ctl.dispose();
  return r;
}

Future<void> _updateItem(BuildContext context, Future<Item> Function() call, String done) async {
  final state = context.read<AppState>();
  try {
    final item = await call();
    state.itemUpdated(item);
    if (context.mounted) toast(context, done);
  } on ApiException catch (e) {
    if (context.mounted) toast(context, e.message, error: true);
  }
}

/// Adds a PDF as supplementary material (errata, solutions manual, parts...) with a label.
Future<void> addSupplementaryFlow(BuildContext context, Item item) async {
  final state = context.read<AppState>();
  final res = await FilePicker.platform.pickFiles(type: FileType.custom, allowedExtensions: ['pdf']);
  final file = res?.files.single;
  if (file?.path == null || !context.mounted) return;
  final label = await askText(context,
      title: 'Supplementary file', label: 'Label (e.g. Errata, Solutions manual, Parts)', ok: 'Add');
  if (label == null || label.trim().isEmpty || !context.mounted) {
    if (label != null && context.mounted) toast(context, 'A supplementary file needs a label.', error: true);
    return;
  }
  toast(context, 'Uploading ${file!.name}...');
  await _updateItem(context, () async {
    final up = await state.api.upload(file.path!, file.name);
    return state.api.addAttachment(item.id, up['temp_id'] as String, label.trim());
  }, 'Supplementary file added.');
  await state.refreshAfterChange(); // storage use changed
}

Future<void> renameSupplementaryFlow(BuildContext context, Item item, Attachment att) async {
  final label = await askText(context, title: 'Change label', label: 'Label', initial: att.label);
  if (label == null || label.trim().isEmpty || label.trim() == att.label || !context.mounted) return;
  await _updateItem(context, () => context.read<AppState>().api.renameAttachment(att.id, label.trim()), 'Label changed.');
}

Future<void> moveSupplementary(BuildContext context, Item item, Attachment att, int delta) async {
  final ids = [for (final a in item.supplementary) a.id];
  final i = ids.indexOf(att.id);
  final j = i + delta;
  if (i < 0 || j < 0 || j >= ids.length) return;
  ids[i] = ids[j];
  ids[j] = att.id;
  await _updateItem(context, () => context.read<AppState>().api.orderAttachments(item.id, ids), 'Order changed.');
}

Future<void> trashSupplementaryFlow(BuildContext context, Item item, Attachment att) async {
  final state = context.read<AppState>();
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Move to trash?'),
      content: Text('"${att.label}" will be removed from this item and kept in the trash for '
          '${state.stats?['trash_days'] ?? 30} days.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Move to trash')),
      ],
    ),
  );
  if (ok != true || !context.mounted) return;
  await _updateItem(context, () async {
    await state.api.trashAttachment(att.id);
    await state.cache.removeAttachment(item, att);
    return state.api.getItem(item.id);
  }, 'Moved to trash.');
}

Future<void> editNoteFlow(BuildContext context, Item item, [ItemNote? note]) async {
  final body = await askText(context,
      title: note == null ? 'New note' : 'Edit note', initial: note?.body ?? '', multiline: true);
  if (body == null || body.trim().isEmpty || !context.mounted) return;
  final api = context.read<AppState>().api;
  await _updateItem(
      context, () => note == null ? api.addNote(item.id, body.trim()) : api.editNote(note.id, body.trim()), 'Note saved.');
}

Future<void> deleteNoteFlow(BuildContext context, Item item, ItemNote note) async {
  final ok = await showDialog<bool>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: const Text('Delete note?'),
      content: const Text('The note is deleted for good.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
        FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete')),
      ],
    ),
  );
  if (ok != true || !context.mounted) return;
  await _updateItem(context, () => context.read<AppState>().api.deleteNote(note.id), 'Note deleted.');
}
