import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:http/http.dart' as http;

import 'models.dart';

class ApiException implements Exception {
  final int? status; // null = the server could not be reached
  final String message;
  final dynamic detail;
  ApiException(this.status, this.message, [this.detail]);

  bool get isNetwork => status == null;

  @override
  String toString() => message;
}

class ApiClient {
  String baseUrl;
  String? token;
  final http.Client _c = http.Client();

  ApiClient(this.baseUrl, [this.token]);

  static String normalize(String url) {
    var u = url.trim();
    if (u.isEmpty) return u;
    if (!u.startsWith('http://') && !u.startsWith('https://')) u = 'http://$u';
    while (u.endsWith('/')) {
      u = u.substring(0, u.length - 1);
    }
    return u;
  }

  Map<String, String> get headers =>
      {if (token != null) 'Authorization': 'Bearer $token'};

  Uri _u(String path, [Map<String, String>? query]) {
    final uri = Uri.parse('${normalize(baseUrl)}$path');
    return query == null || query.isEmpty ? uri : uri.replace(queryParameters: query);
  }

  String coverUrl(int id) => _u('/api/items/$id/cover').toString();
  String itemPageUrl(int id, int page, {int w = 420}) =>
      _u('/api/items/$id/page/$page', {'w': '$w'}).toString();
  String uploadPageUrl(String tempId, int page, {int w = 420}) =>
      _u('/api/uploads/$tempId/page/$page', {'w': '$w'}).toString();

  String _message(http.Response r) {
    try {
      final body = jsonDecode(utf8.decode(r.bodyBytes));
      final d = body is Map ? body['detail'] : null;
      if (d is String) return d;
      if (d is Map && d['message'] != null) return d['message'].toString();
      if (d is List && d.isNotEmpty) {
        final first = d.first;
        if (first is Map) {
          final loc =
              (first['loc'] as List?)?.where((e) => e != 'body').join(' > ') ?? '';
          return '${first['msg']}${loc.isEmpty ? '' : ' ($loc)'}';
        }
      }
    } catch (_) {}
    return 'The server answered with error ${r.statusCode}.';
  }

  static const _unreachable =
      'Cannot reach the server. Check the address and your Tailscale connection.';

  Future<dynamic> _json(String method, String path,
      {Map<String, String>? query,
      Object? body,
      Duration timeout = const Duration(seconds: 30)}) async {
    final req = http.Request(method, _u(path, query));
    req.headers.addAll(headers);
    if (body != null) {
      req.headers['Content-Type'] = 'application/json';
      req.body = jsonEncode(body);
    }
    try {
      final r = await http.Response.fromStream(await _c.send(req).timeout(timeout));
      if (r.statusCode >= 400) {
        dynamic detail;
        try {
          detail = (jsonDecode(utf8.decode(r.bodyBytes)) as Map)['detail'];
        } catch (_) {}
        throw ApiException(r.statusCode, _message(r), detail);
      }
      if (r.bodyBytes.isEmpty) return null;
      return jsonDecode(utf8.decode(r.bodyBytes));
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw ApiException(null, 'The server took too long to answer.');
    } on IOException {
      throw ApiException(null, _unreachable);
    } on http.ClientException {
      throw ApiException(null, _unreachable);
    } on FormatException {
      throw ApiException(null, 'The address does not look like a Biblioteca UDC server.');
    }
  }

  // ---- auth
  Future<Map<String, dynamic>> login(String user, String pass) async =>
      Map<String, dynamic>.from(await _json('POST', '/api/auth/login',
          body: {'username': user, 'password': pass}));

  Future<UserInfo> me() async {
    final j = Map<String, dynamic>.from(
        await _json('GET', '/api/auth/me', timeout: const Duration(seconds: 8)));
    return UserInfo((j['id'] as num).toInt(), j['username'] as String,
        j['role'] as String, false);
  }

  Future<void> logout() async {
    try {
      await _json('POST', '/api/auth/logout', timeout: const Duration(seconds: 5));
    } catch (_) {}
  }

  // ---- library
  /// Zotero item types with their fields and creator roles. The interface is in English (en-US).
  Future<SchemaInfo> schema({String lang = 'en-US'}) async => SchemaInfo.fromJson(
      Map<String, dynamic>.from(await _json('GET', '/api/schema', query: {'lang': lang})));

  Future<UdcIndex> udcTree() async {
    final j = Map<String, dynamic>.from(await _json('GET', '/api/udc/tree'));
    return UdcIndex(
      (j['nodes'] as List)
          .map((e) => UdcNode.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList(),
      unclassified: (j['unclassified'] as num?)?.toInt() ?? 0,
    );
  }

  /// Notes of one class for the information window. The code goes in the query
  /// string because notations may contain '/'.
  Future<UdcNodeInfo> udcNode(String code) async => UdcNodeInfo.fromJson(Map<String, dynamic>.from(
      await _json('GET', '/api/udc/node', query: {'code': code})));

  /// Cancellations of a notation (404 if it was never cancelled).
  Future<List<UdcCancellation>> udcCancelled(String code) async {
    final j = Map<String, dynamic>.from(await _json('GET', '/api/udc/cancelled', query: {'code': code}));
    return [
      for (final c in (j['cancellations'] as List)) UdcCancellation.fromJson(Map<String, dynamic>.from(c as Map))
    ];
  }

  /// Cancelled notations that are not in the current tree (for the tree filter).
  Future<List<CancelledEntry>> udcCancelledIndex() async {
    final j = Map<String, dynamic>.from(await _json('GET', '/api/udc/cancelled-index'));
    return [for (final e in (j['cancelled'] as List)) CancelledEntry.fromJson(e as List)];
  }

  /// Checks a UDC string before saving an item: cancelled notations used as components and, for the item's
  /// type (and its Extra, for musical scores), a form auxiliary that does not fit the type.
  Future<UdcCheckResult> udcCheck(String udc, {String itemType = '', String extra = ''}) async {
    final j = Map<String, dynamic>.from(await _json('GET', '/api/udc/check',
        query: {'udc': udc, 'item_type': itemType, 'extra': extra}, timeout: const Duration(seconds: 10)));
    return UdcCheckResult.fromJson(j);
  }

  Future<ItemsPage> items(Map<String, String> q) async {
    final j = Map<String, dynamic>.from(await _json('GET', '/api/items', query: q));
    return ItemsPage(
        (j['total'] as num).toInt(),
        (j['items'] as List)
            .map((e) => Item.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList());
  }

  Future<Map<String, dynamic>> stats() async =>
      Map<String, dynamic>.from(await _json('GET', '/api/stats'));

  Future<Map<String, dynamic>> upload(String path, String filename) async {
    final req = http.MultipartRequest('POST', _u('/api/uploads'))
      ..headers.addAll(headers);
    req.files.add(await http.MultipartFile.fromPath('file', path, filename: filename));
    try {
      final r = await http.Response.fromStream(
          await req.send().timeout(const Duration(minutes: 30)));
      if (r.statusCode >= 400) throw ApiException(r.statusCode, _message(r));
      return Map<String, dynamic>.from(jsonDecode(utf8.decode(r.bodyBytes)));
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw ApiException(
          null, 'The upload took too long. Try a smaller file or a better connection.');
    } on IOException {
      throw ApiException(null, _unreachable);
    } on http.ClientException {
      throw ApiException(null, 'The connection dropped during the upload.');
    }
  }

  /// Looks up a DOI / ISBN / arXiv ID. Values come back fitted to [itemType] (or to the type the lookup
  /// suggests, when it is enabled), each with its source.
  Future<Map<String, dynamic>> autofill(
          {String? tempId, String? doi, String? isbn, String? arxiv, String? itemType}) async =>
      Map<String, dynamic>.from(await _json('POST', '/api/autofill',
          timeout: const Duration(seconds: 45),
          body: {
            if (tempId != null) 'temp_id': tempId,
            if (doi != null && doi.isNotEmpty) 'doi': doi,
            if (isbn != null && isbn.isNotEmpty) 'isbn': isbn,
            if (arxiv != null && arxiv.isNotEmpty) 'arxiv': arxiv,
            if (itemType != null) 'item_type': itemType,
          }));

  /// Whether the classifier runs on the server: {available, loading, queue}.
  Future<Map<String, dynamic>> classifierStatus() async =>
      Map<String, dynamic>.from(await _json('GET', '/api/classifier', timeout: const Duration(seconds: 10)));

  /// Queues the analysis of an uploaded PDF or of a stored item's PDF. Returns the job id for [analysis].
  /// [itemType]: fit the values to this type; null = the type the classifier detects.
  Future<String> analyze({String? tempId, int? itemId, String? itemType}) async {
    final path = tempId != null ? '/api/uploads/$tempId/analyze' : '/api/items/$itemId/analyze';
    final r = await _json('POST', path, body: {if (itemType != null) 'item_type': itemType});
    return (r as Map)['job'] as String;
  }

  /// {status: queued|running|done|error, position}; when done, the values for the form
  /// (item_type, detected_type, fields, creators, tags, udc suggestions, low_confidence, review).
  Future<Map<String, dynamic>> analysis(String job) async =>
      Map<String, dynamic>.from(await _json('GET', '/api/analyze/$job'));

  /// Moves a form's values to another item type (nothing is saved). Returns {fields, creators, report}.
  Future<Map<String, dynamic>> convertType(String from, String to, Map<String, dynamic> fields,
          List<Map<String, dynamic>> creators) async =>
      Map<String, dynamic>.from(await _json('POST', '/api/convert-type',
          body: {'from_type': from, 'to_type': to, 'fields': fields, 'creators': creators}));

  // ---- supplementary material and notes (each call returns the updated item)
  Future<Item> addAttachment(int itemId, String tempId, String label) async => Item.fromJson(Map<String, dynamic>.from(
      await _json('POST', '/api/items/$itemId/attachments', body: {'temp_id': tempId, 'label': label})));

  Future<Item> renameAttachment(int attId, String label) async => Item.fromJson(
      Map<String, dynamic>.from(await _json('PATCH', '/api/attachments/$attId', body: {'label': label})));

  Future<Item> orderAttachments(int itemId, List<int> ids) async => Item.fromJson(Map<String, dynamic>.from(
      await _json('PUT', '/api/items/$itemId/attachments/order', body: {'ids': ids})));

  Future<void> trashAttachment(int attId) => _json('DELETE', '/api/attachments/$attId');

  Future<Item> getItem(int id) async =>
      Item.fromJson(Map<String, dynamic>.from(await _json('GET', '/api/items/$id')));

  Future<Item> addNote(int itemId, String body) async => Item.fromJson(
      Map<String, dynamic>.from(await _json('POST', '/api/items/$itemId/notes', body: {'body': body})));

  Future<Item> editNote(int noteId, String body) async =>
      Item.fromJson(Map<String, dynamic>.from(await _json('PUT', '/api/notes/$noteId', body: {'body': body})));

  Future<Item> deleteNote(int noteId) async =>
      Item.fromJson(Map<String, dynamic>.from(await _json('DELETE', '/api/notes/$noteId')));

  Future<Item> createItem(Map<String, dynamic> body) async => Item.fromJson(
      Map<String, dynamic>.from(await _json('POST', '/api/items', body: body)));

  Future<Item> updateItem(int id, Map<String, dynamic> body) async => Item.fromJson(
      Map<String, dynamic>.from(await _json('PUT', '/api/items/$id', body: body)));

  Future<void> trashItem(int id) => _json('DELETE', '/api/items/$id');

  Future<List<Item>> trash() async {
    final j = Map<String, dynamic>.from(await _json('GET', '/api/trash'));
    return (j['items'] as List)
        .map((e) => Item.fromJson(Map<String, dynamic>.from(e as Map)))
        .toList();
  }

  Future<void> restore(int id) => _json('POST', '/api/trash/$id/restore');
  Future<void> deleteForever(int id) => _json('DELETE', '/api/trash/$id');

  // ---- admin
  Future<List<UserInfo>> users() async => ((await _json('GET', '/api/users')) as List)
      .map((e) => UserInfo.fromJson(Map<String, dynamic>.from(e as Map)))
      .toList();

  Future<void> createUser(String name, String pass, String role) => _json('POST', '/api/users',
      body: {'username': name, 'password': pass, 'role': role});

  Future<void> patchUser(int id, Map<String, dynamic> body) =>
      _json('PATCH', '/api/users/$id', body: body);
  Future<void> deleteUser(int id) => _json('DELETE', '/api/users/$id');

  // ---- file download (streamed to disk)
  /// The item's main file, or one supplementary file when [attachmentId] is given.
  Future<void> download(int id, File dest,
      {int? attachmentId, void Function(int received, int total)? onProgress}) async {
    final path = attachmentId == null ? '/api/items/$id/file' : '/api/attachments/$attachmentId/file';
    final req = http.Request('GET', _u(path))..headers.addAll(headers);
    final part = File('${dest.path}.part');
    IOSink? sink;
    try {
      final resp = await _c.send(req).timeout(const Duration(seconds: 30));
      if (resp.statusCode != 200) {
        throw ApiException(
            resp.statusCode,
            resp.statusCode == 404
                ? 'The PDF is missing on the server.'
                : 'The server answered with error ${resp.statusCode}.');
      }
      sink = part.openWrite();
      var got = 0;
      await for (final chunk in resp.stream) {
        sink.add(chunk);
        got += chunk.length;
        onProgress?.call(got, resp.contentLength ?? 0);
      }
      await sink.flush();
      await sink.close();
      sink = null;
      if (await dest.exists()) await dest.delete();
      await part.rename(dest.path);
    } on ApiException {
      rethrow;
    } on TimeoutException {
      throw ApiException(null, 'The server took too long to answer.');
    } on IOException {
      throw ApiException(null, _unreachable);
    } on http.ClientException {
      throw ApiException(null, 'The download was interrupted.');
    } finally {
      if (sink != null) await sink.close();
      if (await part.exists()) await part.delete();
    }
  }
}
