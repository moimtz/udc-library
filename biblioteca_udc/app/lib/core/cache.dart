import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'models.dart';

class CachedEntry {
  Item item;
  String sha;
  int size;
  bool pinned;
  DateTime lastUsed;
  CachedEntry(this.item, this.sha, this.size, this.pinned, this.lastUsed);

  Map<String, dynamic> toJson() => {
        'item': item.raw,
        'sha': sha,
        'size': size,
        'pinned': pinned,
        'last': lastUsed.toIso8601String(),
      };

  factory CachedEntry.fromJson(Map<String, dynamic> j) => CachedEntry(
        Item.fromJson(Map<String, dynamic>.from(j['item'] as Map)),
        j['sha'] as String,
        (j['size'] as num).toInt(),
        j['pinned'] == true,
        DateTime.tryParse(j['last'] as String? ?? '') ?? DateTime.now(),
      );
}

/// Downloaded PDFs. "Pinned" files are kept forever; the rest are removed
/// least-recently-used first once they exceed [limitGb].
class FileCache extends ChangeNotifier {
  late Directory _files;
  late File _index;
  final Map<int, CachedEntry> entries = {};
  double limitGb = 2;

  String pathOf(int id) => p.join(_files.path, '$id.pdf');

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
          final id = int.parse(e.key);
          if (await File(pathOf(id)).exists()) {
            entries[id] = CachedEntry.fromJson(Map<String, dynamic>.from(e.value as Map));
          }
        }
      } catch (_) {
        // A damaged index only means the cache starts empty.
      }
    }
  }

  Future<void> _save() async {
    final j = {for (final e in entries.entries) '${e.key}': e.value.toJson()};
    await _index.writeAsString(jsonEncode(j));
  }

  bool has(int id) => entries.containsKey(id);
  bool isPinned(int id) => entries[id]?.pinned ?? false;

  /// True when the saved copy matches the server's current file.
  bool isFresh(Item item) {
    final e = entries[item.id];
    return e != null && e.sha == item.sha256;
  }

  int get pinnedBytes =>
      entries.values.where((e) => e.pinned).fold(0, (a, e) => a + e.size);
  int get unpinnedBytes =>
      entries.values.where((e) => !e.pinned).fold(0, (a, e) => a + e.size);

  /// Returns the local path (downloading first when needed). `stale` is true
  /// when the server was unreachable and an older saved copy was used.
  Future<({String path, bool stale})> ensure(ApiClient api, Item item,
      {void Function(int received, int total)? onProgress}) async {
    final existing = entries[item.id];
    if (existing != null && existing.sha == item.sha256) {
      existing.lastUsed = DateTime.now();
      await _save();
      return (path: pathOf(item.id), stale: false);
    }
    try {
      await api.download(item.id, File(pathOf(item.id)), onProgress: onProgress);
    } on ApiException catch (e) {
      if (e.isNetwork && existing != null) {
        return (path: pathOf(item.id), stale: true);
      }
      rethrow;
    }
    entries[item.id] = CachedEntry(
        item, item.sha256, item.size, existing?.pinned ?? false, DateTime.now());
    await _evict(keep: item.id);
    await _save();
    notifyListeners();
    return (path: pathOf(item.id), stale: false);
  }

  Future<void> setPinned(int id, bool pinned) async {
    final e = entries[id];
    if (e == null) return;
    e.pinned = pinned;
    if (!pinned) await _evict();
    await _save();
    notifyListeners();
  }

  void updateMeta(Item item) {
    final e = entries[item.id];
    if (e != null) {
      e.item = item;
      _save();
    }
  }

  Future<void> remove(int id) async {
    entries.remove(id);
    final f = File(pathOf(id));
    if (await f.exists()) await f.delete();
    await _save();
    notifyListeners();
  }

  Future<void> _evict({int? keep}) async {
    final limit = (limitGb * 1024 * 1024 * 1024).round();
    var total = unpinnedBytes;
    if (total <= limit) return;
    final candidates = entries.values
        .where((e) => !e.pinned && e.item.id != keep)
        .toList()
      ..sort((a, b) => a.lastUsed.compareTo(b.lastUsed));
    for (final e in candidates) {
      if (total <= limit) break;
      total -= e.size;
      entries.remove(e.item.id);
      final f = File(pathOf(e.item.id));
      if (await f.exists()) await f.delete();
    }
  }

  Future<void> applyLimit(double gb) async {
    limitGb = gb;
    await _evict();
    await _save();
    notifyListeners();
  }

  Future<void> clear({bool includePinned = false}) async {
    for (final id in entries.keys.toList()) {
      if (!includePinned && entries[id]!.pinned) continue;
      entries.remove(id);
      final f = File(pathOf(id));
      if (await f.exists()) await f.delete();
    }
    await _save();
    notifyListeners();
  }
}
