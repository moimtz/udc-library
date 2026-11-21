import 'dart:io';

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

/// Makes sure a local copy exists (showing progress if a download is needed).
Future<String?> _localCopy(BuildContext context, Item item) async {
  final state = context.read<AppState>();
  final needs = !state.cache.isFresh(item);
  final progress = ValueNotifier<double?>(null);
  var dialogOpen = false;
  if (needs) {
    dialogOpen = true;
    showDialog(
      context: context,
      barrierDismissible: false,
      useRootNavigator: true,
      builder: (_) => _ProgressDialog(progress: progress, title: item.title),
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

Future<void> openItem(BuildContext context, Item item) async {
  final path = await _localCopy(context, item);
  if (path == null) return;
  final err = await launchPdf(path);
  if (err != null && context.mounted) {
    toast(context, err.isEmpty ? 'No app on this device can open PDF files.' : err, error: true);
  }
}

Future<void> togglePin(BuildContext context, Item item) async {
  final cache = context.read<AppState>().cache;
  if (cache.isPinned(item.id)) {
    await cache.setPinned(item.id, false);
    if (context.mounted) toast(context, 'No longer kept offline.');
    return;
  }
  final path = await _localCopy(context, item);
  if (path == null) return;
  await cache.setPinned(item.id, true);
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
