import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'models.dart';

/// Cache key of a file: '<item id>' for the main file, 'a<attachment id>' for a supplementary file.
String fileKey(Item item, [Attachment? att]) => att == null || att.isMain ? '${item.id}' : 'a${att.id}';

class CachedEntry {
  Item item; // the item the file belongs to (lets the "Downloaded" view work offline)
  int? attachmentId; // null = main file
  String sha;
  int size;
  bool pinned;
  DateTime lastUsed;
  CachedEntry(this.item, this.attachmentId, this.sha, this.size, this.pinned, this.lastUsed);

  Map<String, dynamic> toJson() => {
        'item': item.raw,
        if (attachmentId != null) 'att': attachmentId,
        'sha': sha,
        'size': size,
        'pinned': pinned,
        'last': lastUsed.toIso8601String(),
      };

  factory CachedEntry.fromJson(Map<String, dynamic> j) => CachedEntry(
        Item.fromJson(Map<String, dynamic>.from(j['item'] as Map)),
        (j['att'] as num?)?.toInt(),
        j['sha'] as String,
        (j['size'] as num).toInt(),
        j['pinned'] == true,
        DateTime.tryParse(j['last'] as String? ?? '') ?? DateTime.now(),
      );
}

/// Downloaded files. "Pinned" files are kept forever; the rest are removed
/// least-recently-used first once they exceed [limitGb].
class FileCache extends ChangeNotifier {
  late Directory _files;
  late File _index;
  final Map<String, CachedEntry> entries = {};
  double limitGb = 2;

  String pathOf(String key) => p.join(_files.path, '$key.pdf');

  Future<void> init() async {
    final base = await getApplicationSupportDirectory();
    final root = Directory(p.join(base.path, 'cache'));
    _files = Directory(p.join(root.path, 'files'));
    await _files.create(recursive: true);
    _index = File(p.join(root.path, 'index.json'));
    if (await _index.exists()) {
      try {
        final j = jsonDecode(await _index.readAsString()) as Map<String, dynamic>;
        for (final e in j.entries) {
          if (await File(pathOf(e.key)).exists()) {
            entries[e.key] = CachedEntry.fromJson(Map<String, dynamic>.from(e.value as Map));
          }
        }
      } catch (_) {
        // A damaged index (or one from before the Zotero item format) only means the cache starts empty.
        entries.clear();
      }
    }
  }

  Future<void> _save() async {
    final j = {for (final e in entries.entries) e.key: e.value.toJson()};
    await _index.writeAsString(jsonEncode(j));
  }

  /// Items with a saved main file (for the "Downloaded" view).
  List<Item> get items => [for (final e in entries.values) if (e.attachmentId == null) e.item];

  bool has(Item item, [Attachment? att]) => entries.containsKey(fileKey(item, att));
  bool isPinned(Item item, [Attachment? att]) => entries[fileKey(item, att)]?.pinned ?? false;

  /// True when the saved copy matches the server's current file.
  bool isFresh(Item item, [Attachment? att]) {
    final e = entries[fileKey(item, att)];
    return e != null && e.sha == (att ?? item.main)?.sha256;
  }

  int get pinnedBytes => entries.values.where((e) => e.pinned).fold(0, (a, e) => a + e.size);
  int get unpinnedBytes => entries.values.where((e) => !e.pinned).fold(0, (a, e) => a + e.size);

  /// Returns the local path (downloading first when needed). `stale` is true
  /// when the server was unreachable and an older saved copy was used.
  Future<({String path, bool stale})> ensure(ApiClient api, Item item,
      {Attachment? att, void Function(int received, int total)? onProgress}) async {
    final key = fileKey(item, att);
    final file = att ?? item.main;
    final existing = entries[key];
    if (existing != null && existing.sha == file?.sha256) {
      existing.lastUsed = DateTime.now();
      await _save();
      return (path: pathOf(key), stale: false);
    }
    try {
      await api.download(item.id, File(pathOf(key)),
          attachmentId: att == null || att.isMain ? null : att.id, onProgress: onProgress);
    } on ApiException catch (e) {
      if (e.isNetwork && existing != null) {
        return (path: pathOf(key), stale: true);
      }
      rethrow;
    }
    entries[key] = CachedEntry(item, att == null || att.isMain ? null : att.id, file?.sha256 ?? '',
        file?.size ?? 0, existing?.pinned ?? false, DateTime.now());
    await _evict(keep: key);
    await _save();
    notifyListeners();
    return (path: pathOf(key), stale: false);
  }

  Future<void> setPinned(Item item, bool pinned, [Attachment? att]) async {
    final e = entries[fileKey(item, att)];
    if (e == null) return;
    e.pinned = pinned;
    if (!pinned) await _evict();
    await _save();
    notifyListeners();
  }

  void updateMeta(Item item) {
    var changed = false;
    for (final e in entries.values) {
      if (e.item.id == item.id) {
        e.item = item;
        changed = true;
      }
    }
    if (changed) _save();
  }

  /// Forgets every saved file of an item (main and supplementary).
  Future<void> removeItem(int itemId) async {
    for (final key in [for (final e in entries.entries) if (e.value.item.id == itemId) e.key]) {
      await _delete(key);
    }
    await _save();
    notifyListeners();
  }

  Future<void> removeAttachment(Item item, Attachment att) async {
    await _delete(fileKey(item, att));
    await _save();
    notifyListeners();
  }

  Future<void> _delete(String key) async {
    entries.remove(key);
    final f = File(pathOf(key));
    if (await f.exists()) await f.delete();
  }

  Future<void> _evict({String? keep}) async {
    final limit = (limitGb * 1024 * 1024 * 1024).round();
    var total = unpinnedBytes;
    if (total <= limit) return;
    final candidates = entries.entries.where((e) => !e.value.pinned && e.key != keep).toList()
      ..sort((a, b) => a.value.lastUsed.compareTo(b.value.lastUsed));
    for (final e in candidates) {
      if (total <= limit) break;
      total -= e.value.size;
      await _delete(e.key);
    }
  }

  Future<void> applyLimit(double gb) async {
    limitGb = gb;
    await _evict();
    await _save();
    notifyListeners();
  }

  Future<void> clear({bool includePinned = false}) async {
    for (final key in entries.keys.toList()) {
      if (!includePinned && entries[key]!.pinned) continue;
      await _delete(key);
    }
    await _save();
    notifyListeners();
  }
}
