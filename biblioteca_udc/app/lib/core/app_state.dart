import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'cache.dart';
import 'models.dart';

class AppState extends ChangeNotifier {
  AppState() {
    cache.addListener(notifyListeners);
  }

  late SharedPreferences prefs;
  final FileCache cache = FileCache();
  ApiClient api = ApiClient('');

  bool booting = true;
  UserInfo? user;
  bool get loggedIn => user != null;
  bool offline = false;

  // settings
  String serverUrl = '';
  ThemeMode themeMode = ThemeMode.system;
  String udcLang = 'en';

  // server data
  SchemaInfo schema = SchemaInfo.empty();
  UdcIndex udc = UdcIndex.empty();
  Map<String, dynamic>? stats;
  final Set<String> expanded = {};

  // query
  final TextEditingController searchController = TextEditingController();
  bool regex = false;
  bool caseSensitive = false;
  bool whole = false;
  String field = 'all';
  String? udcScope; // class code, 'none' (unclassified) or null (everything)
  bool includeDesc = true;
  String? typeFilter;
  int? yearFrom;
  int? yearTo;
  String? languageFilter;
  String sort = 'title';
  bool ascending = true;
  bool downloadedMode = false;

  // results
  List<Item> results = [];
  int total = 0;
  bool loading = false;
  String? error;
  String? searchError;
  int? expandedItemId;
  int _ticket = 0;

  bool get hasActiveFilters =>
      typeFilter != null || yearFrom != null || yearTo != null || languageFilter != null;

  // ------------------------------------------------------------------ startup / session
  String? startupError;

  Future<void> init() async {
    try {
      prefs = await SharedPreferences.getInstance();
      serverUrl = prefs.getString('server_url') ?? '';
      final themeName = prefs.getString('theme');
      themeMode = ThemeMode.values.firstWhere((m) => m.name == themeName,
          orElse: () => ThemeMode.system);
      udcLang = prefs.getString('udc_lang') ?? 'en';
      await cache.init();
      cache.limitGb = prefs.getDouble('cache_gb') ?? 2;

      final token = prefs.getString('token');
      api = ApiClient(serverUrl, token);
      if (token != null && serverUrl.isNotEmpty) {
        try {
          user = await api.me();
          await _loadAll();
        } on ApiException catch (e) {
          if (e.isNetwork) {
            user = UserInfo(prefs.getInt('user_id') ?? 0, prefs.getString('user_name') ?? '',
                prefs.getString('user_role') ?? 'viewer', false);
            offline = true;
            _showCached();
          } else {
            await _clearSession();
          }
        }
      }
    } catch (e, st) {
      startupError = 'The app could not start.\n\n$e\n\n$st';
      debugPrint('Startup error: $e\n$st');
    } finally {
      booting = false;
      notifyListeners();
    }
  }

  Future<void> login(String url, String username, String password) async {
    final client = ApiClient(ApiClient.normalize(url));
    final res = await client.login(username.trim(), password);
    client.token = res['token'] as String;
    final u = Map<String, dynamic>.from(res['user'] as Map);
    api = client;
    serverUrl = client.baseUrl;
    user = UserInfo((u['id'] as num).toInt(), u['username'] as String, u['role'] as String, false);
    await prefs.setString('server_url', serverUrl);
    await prefs.setString('token', client.token!);
    await prefs.setInt('user_id', user!.id);
    await prefs.setString('user_name', user!.username);
    await prefs.setString('user_role', user!.role);
    offline = false;
    await _loadAll();
    notifyListeners();
  }

  Future<void> logout() async {
    await api.logout();
    await _clearSession();
    notifyListeners();
  }

  Future<void> _clearSession() async {
    await prefs.remove('token');
    api.token = null;
    user = null;
    results = [];
    udc = UdcIndex.empty();
    udcScope = null;
    searchController.clear();
  }

  Future<void> _loadAll() async {
    schema = await api.schema();
    udc = await api.udcTree();
    try {
      stats = await api.stats();
    } catch (_) {}
    offline = false;
    await runQuery();
  }

  Future<void> refreshAfterChange() async {
    try {
      udc = await api.udcTree();
      stats = await api.stats();
    } catch (_) {}
    await runQuery();
  }

  // ------------------------------------------------------------------ query
  Map<String, String> _params() {
    final q = searchController.text;
    return {
      if (q.trim().isNotEmpty) ...{
        'q': q,
        'field': field,
        'regex': '$regex',
        'case': '$caseSensitive',
        'whole': '$whole',
      },
      if (udcScope != null) 'udc': udcScope!,
      'include_desc': '$includeDesc',
      if (typeFilter != null) 'type': typeFilter!,
      if (yearFrom != null) 'year_from': '$yearFrom',
      if (yearTo != null) 'year_to': '$yearTo',
      if (languageFilter != null && languageFilter!.isNotEmpty) 'language': languageFilter!,
      'sort': sort,
      'order': ascending ? 'asc' : 'desc',
    };
  }

  Future<void> runQuery() async {
    if (downloadedMode) {
      _showCached();
      notifyListeners();
      return;
    }
    final ticket = ++_ticket;
    loading = true;
    error = null;
    searchError = null;
    notifyListeners();
    try {
      final page = await api.items(_params());
      if (ticket != _ticket) return;
      results = page.items;
      total = page.total;
      offline = false;
    } on ApiException catch (e) {
      if (ticket != _ticket) return;
      if (e.status == 400) {
        searchError = e.message; // e.g. invalid regular expression
      } else if (e.isNetwork) {
        offline = true;
        _showCached();
      } else if (e.status == 401) {
        await _clearSession();
      } else {
        error = e.message;
      }
    }
    if (ticket == _ticket) loading = false;
    notifyListeners();
  }

  void _showCached() {
    var list = cache.entries.values.map((e) => e.item).toList();
    final q = foldText(searchController.text.trim());
    if (q.isNotEmpty) {
      list = list
          .where((i) => foldText('${i.title} ${i.creatorsText} ${i.udc}').contains(q))
          .toList();
    }
    list.sort((a, b) => foldText(a.title).compareTo(foldText(b.title)));
    results = list;
    total = list.length;
    loading = false;
  }

  void selectNode(String? code) {
    udcScope = code;
    downloadedMode = false;
    searchController.clear();
    expandedItemId = null;
    runQuery();
  }

  void clearScope() => selectNode(null);

  void submitSearch() {
    downloadedMode = false;
    expandedItemId = null;
    runQuery();
  }

  void setSearchOption({bool? regex, bool? caseSensitive, bool? whole, String? field}) {
    if (regex != null) this.regex = regex;
    if (caseSensitive != null) this.caseSensitive = caseSensitive;
    if (whole != null) this.whole = whole;
    if (field != null) this.field = field;
    if (searchController.text.trim().isNotEmpty) {
      runQuery();
    } else {
      notifyListeners();
    }
  }

  void applyFilters({String? type, int? yearFrom, int? yearTo, String? language, String? scope}) {
    typeFilter = type;
    this.yearFrom = yearFrom;
    this.yearTo = yearTo;
    languageFilter = (language == null || language.trim().isEmpty) ? null : language.trim();
    udcScope = scope;
    downloadedMode = false;
    expandedItemId = null;
    runQuery();
  }

  void clearFilters() => applyFilters(scope: udcScope);

  void setSort(String s, bool asc) {
    sort = s;
    ascending = asc;
    runQuery();
  }

  void setIncludeDesc(bool v) {
    includeDesc = v;
    runQuery();
  }

  void showDownloaded() {
    downloadedMode = true;
    udcScope = null;
    searchController.clear();
    runQuery();
  }

  void toggleItem(int id) {
    expandedItemId = expandedItemId == id ? null : id;
    notifyListeners();
  }

  Future<void> reconnect() async {
    try {
      user = await api.me();
      downloadedMode = false;
      await _loadAll();
    } on ApiException catch (e) {
      if (e.status == 401) {
        await _clearSession();
      } else {
        offline = e.isNetwork;
        error = e.message;
      }
    }
    notifyListeners();
  }

  Future<void> refreshSchema() async {
    schema = await api.schema();
    notifyListeners();
  }

  // ------------------------------------------------------------------ tree
  void toggleExpanded(String code) {
    if (!expanded.remove(code)) expanded.add(code);
    notifyListeners();
  }

  void expandAll() {
    expanded
      ..clear()
      ..addAll(udc.expandable);
    notifyListeners();
  }

  void collapseAll() {
    expanded.clear();
    notifyListeners();
  }

  // ------------------------------------------------------------------ item changes
  void itemUpdated(Item item) {
    final i = results.indexWhere((r) => r.id == item.id);
    if (i >= 0) results[i] = item;
    cache.updateMeta(item);
    notifyListeners();
  }

  Future<void> itemTrashed(int id) async {
    results.removeWhere((r) => r.id == id);
    total = results.length;
    await cache.remove(id);
    await refreshAfterChange();
  }

  // ------------------------------------------------------------------ settings
  Future<void> setTheme(ThemeMode m) async {
    themeMode = m;
    await prefs.setString('theme', m.name);
    notifyListeners();
  }

  Future<void> setUdcLang(String l) async {
    udcLang = l;
    await prefs.setString('udc_lang', l);
    notifyListeners();
  }

  Future<void> setCacheGb(double gb) async {
    await prefs.setDouble('cache_gb', gb);
    await cache.applyLimit(gb);
  }

  String typeLabel(String code) => schema.typeLabel(code);

  @override
  void dispose() {
    searchController.dispose();
    super.dispose();
  }
}
