import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'cache.dart';
import 'i18n.dart';
import 'models.dart';
import 'theme.dart';

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
  AppPalette palette = defaultPalette; // Settings > Palette (theme.dart, kPalettes)

  /// Interface language, also used for the UDC class names and Zotero's labels (Settings > Language).
  String get udcLang => uiLang;

  /// Width in pixels of the search + tree pane on wide screens, once the divider has been dragged.
  /// null = the width of the search panel itself (SearchPanel.naturalWidth). Double-click the divider to go back.
  double? treeWidth;

  // server data
  SchemaInfo schema = SchemaInfo.empty();
  UdcIndex udc = UdcIndex.empty();
  // Cancelled notations not in the current tree; loaded the first time the tree is filtered.
  List<CancelledEntry>? cancelledIndex;
  bool _loadingCancelled = false;
  Map<String, dynamic>? stats;
  final Set<String> expanded = {};

  // query (search panel). Searching with every box empty shows the whole library.
  final TextEditingController udcController = TextEditingController(); // "UDC number" box
  bool udcExact = false;
  bool includeCancelled = false;
  final TextEditingController searchController = TextEditingController(); // "Text" box
  bool textExact = false;
  final Set<String> fields = {}; // fields searched by the text box; empty = all
  bool unclassified = false; // "Unclassified" chosen in the tree
  String? treeSelection; // class highlighted in the tree (the last one clicked)
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

  /// Items ticked in the results (check boxes), for the actions of the selection bar.
  final Set<int> selectedIds = {};

  // ------------------------------------------------------------------ startup / session
  String? startupError;

  Future<void> init() async {
    try {
      prefs = await SharedPreferences.getInstance();
      serverUrl = prefs.getString('server_url') ?? '';
      final themeName = prefs.getString('theme');
      themeMode = ThemeMode.values.firstWhere((m) => m.name == themeName,
          orElse: () => ThemeMode.system);
      palette = paletteById(prefs.getString('palette'));
      // up to v0.1 the language was 'udc_lang' (tree only)
      setUiLang(prefs.getString('ui_lang') ?? prefs.getString('udc_lang') ?? _systemLang());
      treeWidth = prefs.getDouble('tree_width');
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
      startupError = '${tr('The app could not start.')}\n\n$e\n\n$st';
      debugPrint('Startup error: $e\n$st');
    } finally {
      booting = false;
      notifyListeners();
    }
  }

  static String _systemLang() {
    final l = WidgetsBinding.instance.platformDispatcher.locale.languageCode;
    return uiLanguages.containsKey(l) ? l : 'en';
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
    cancelledIndex = null;
    clearSearchFields();
  }

  Future<void> _loadAll() async {
    schema = await api.schema(lang: zoteroLocale);
    udc = await api.udcTree();
    try {
      stats = await api.stats();
    } catch (_) {}
    offline = false;
    await runQuery();
  }

  /// Loads the cancelled-notation index once (used by the tree filter). Fails silently when offline.
  void ensureCancelledIndex() {
    if (cancelledIndex != null || _loadingCancelled || offline) return;
    _loadingCancelled = true;
    api.udcCancelledIndex().then((v) {
      cancelledIndex = v;
      notifyListeners();
    }).catchError((_) {}).whenComplete(() => _loadingCancelled = false);
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
    final u = udcController.text;
    return {
      if (q.trim().isNotEmpty) ...{
        'q': q,
        'text_exact': '$textExact',
        if (fields.isNotEmpty) 'fields': fields.join(','),
      },
      if (u.trim().isNotEmpty) ...{
        'udc_q': u,
        'udc_exact': '$udcExact',
        'udc_cancelled': '$includeCancelled',
      },
      if (unclassified) 'udc': 'none',
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
      selectedIds.removeWhere((id) => !results.any((r) => r.id == id));
      offline = false;
    } on ApiException catch (e) {
      if (ticket != _ticket) return;
      if (e.status == 400) {
        searchError = tr(e.message);
      } else if (e.isNetwork) {
        offline = true;
        _showCached();
      } else if (e.status == 401) {
        await _clearSession();
      } else {
        error = tr(e.message);
      }
    }
    if (ticket == _ticket) loading = false;
    notifyListeners();
  }

  /// Offline: a simple filter of the files saved on this device (every word of the text box; the UDC box as
  /// part of the item's number).
  void _showCached() {
    var list = cache.items;
    final words = foldText(searchController.text.trim()).split(RegExp(r'\s+')).where((w) => w.isNotEmpty);
    final u = udcController.text.replaceAll(' ', '').replaceAll('*', '');
    list = list.where((i) {
      final hay = foldText('${i.title} ${i.creatorsText} ${i.udcText}');
      if (!words.every(hay.contains)) return false;
      if (u.isEmpty) return true;
      return udcExact ? i.udc.any((x) => x.notation.replaceAll(' ', '') == u) : i.udcText.contains(u);
    }).toList();
    list.sort((a, b) => foldText(a.title).compareTo(foldText(b.title)));
    results = list;
    total = list.length;
    loading = false;
  }

  /// A class clicked in the tree goes to the "UDC number" box (free search: it includes its subdivisions)
  /// and the search runs. 'none' = items without UDC.
  void selectNode(String code) {
    downloadedMode = false;
    expandedItemId = null;
    treeSelection = code;
    if (code == 'none') {
      unclassified = true;
      udcController.clear();
    } else {
      unclassified = false;
      udcController.text = code;
      udcExact = false;
    }
    runQuery();
  }

  void clearUnclassified() {
    unclassified = false;
    if (treeSelection == 'none') treeSelection = null;
    runQuery();
  }

  /// "Search" button or Enter.
  void submitSearch() {
    downloadedMode = false;
    expandedItemId = null;
    unclassified = false;
    final u = udcController.text.trim();
    treeSelection = udc.byCode.containsKey(u) ? u : null;
    runQuery();
  }

  /// Empties every box and option of the search panel (does not search).
  void clearSearchFields() {
    udcController.clear();
    searchController.clear();
    udcExact = false;
    includeCancelled = false;
    textExact = false;
    fields.clear();
    unclassified = false;
    treeSelection = null;
  }

  /// The "clear" button of the search panel header: empties the boxes and options (does not search).
  void resetSearch() {
    clearSearchFields();
    searchError = null;
    notifyListeners();
  }

  void setSearchOption({bool? udcExact, bool? includeCancelled, bool? textExact}) {
    if (udcExact != null) this.udcExact = udcExact;
    if (includeCancelled != null) this.includeCancelled = includeCancelled;
    if (textExact != null) this.textExact = textExact;
    notifyListeners();
  }

  void setFields(Set<String> f) {
    fields
      ..clear()
      ..addAll(f);
    notifyListeners();
  }

  void setSort(String s, bool asc) {
    sort = s;
    ascending = asc;
    runQuery();
  }

  void showDownloaded() {
    downloadedMode = true;
    clearSearchFields();
    runQuery();
  }

  /// Menu > Library: the whole library again.
  void showLibrary() {
    downloadedMode = false;
    clearSearchFields();
    runQuery();
  }

  void toggleItem(int id) {
    expandedItemId = expandedItemId == id ? null : id;
    notifyListeners();
  }

  // ------------------------------------------------------------------ selection (check boxes)
  void toggleSelected(int id) {
    if (!selectedIds.remove(id)) selectedIds.add(id);
    notifyListeners();
  }

  void selectAll(bool on) {
    selectedIds.clear();
    if (on) selectedIds.addAll(results.map((r) => r.id));
    notifyListeners();
  }

  List<Item> get selectedItems => [for (final r in results) if (selectedIds.contains(r.id)) r];

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
        error = tr(e.message);
      }
    }
    notifyListeners();
  }

  Future<void> refreshSchema() async {
    schema = await api.schema(lang: zoteroLocale);
    notifyListeners();
  }

  // ------------------------------------------------------------------ tree
  void toggleExpanded(String code) {
    if (!expanded.remove(code)) expanded.add(code);
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

  /// Optimistic removal: the items leave the results at once. Returns what [putBack] needs to undo it.
  List<(int, Item)> takeOut(Iterable<int> ids) {
    final want = ids.toSet();
    final taken = <(int, Item)>[
      for (var i = 0; i < results.length; i++)
        if (want.contains(results[i].id)) (i, results[i])
    ];
    results.removeWhere((r) => want.contains(r.id));
    selectedIds.removeAll(want);
    if (want.contains(expandedItemId)) expandedItemId = null;
    total -= taken.length;
    notifyListeners();
    return taken;
  }

  /// Undoes [takeOut] (the server refused): the items go back to their places.
  void putBack(List<(int, Item)> taken) {
    for (final (i, item) in taken) {
      if (results.any((r) => r.id == item.id)) continue;
      results.insert(i.clamp(0, results.length), item);
      total++;
    }
    notifyListeners();
  }

  Future<void> itemTrashed(int id, {bool refresh = true}) async {
    results.removeWhere((r) => r.id == id);
    selectedIds.remove(id);
    total = results.length;
    await cache.removeItem(id);
    if (refresh) await refreshAfterChange();
  }

  /// Storage figures and tree after adding or removing files, without reloading the results list
  /// (reloading it while a card is open made the card jump).
  Future<void> refreshStats() async {
    try {
      stats = await api.stats();
      notifyListeners();
    } catch (_) {}
  }

  // ------------------------------------------------------------------ settings
  Future<void> setPalette(AppPalette p) async {
    palette = p;
    notifyListeners();
    await prefs.setString('palette', p.id);
  }

  Future<void> setTheme(ThemeMode m) async {
    themeMode = m;
    await prefs.setString('theme', m.name);
    notifyListeners();
  }

  /// Changes the language of the whole interface (also the UDC tree and Zotero's labels).
  Future<void> changeLanguage(String l) async {
    setUiLang(l);
    await prefs.setString('ui_lang', l);
    notifyListeners();
    try {
      schema = await api.schema(lang: zoteroLocale);
      notifyListeners();
    } catch (_) {} // offline: Zotero's labels change on the next start
  }

  /// While the divider is dragged (saved by [setTreeWidth] when the drag ends).
  void previewTreeWidth(double w) {
    treeWidth = w;
    notifyListeners();
  }

  /// Saves the width; null = back to the width of the search panel.
  Future<void> setTreeWidth(double? w) async {
    treeWidth = w;
    notifyListeners();
    w == null ? await prefs.remove('tree_width') : await prefs.setDouble('tree_width', w);
  }

  Future<void> setCacheGb(double gb) async {
    await prefs.setDouble('cache_gb', gb);
    await cache.applyLimit(gb);
  }

  String typeLabel(String code) => schema.typeLabel(code);

  @override
  void dispose() {
    searchController.dispose();
    udcController.dispose();
    super.dispose();
  }
}
