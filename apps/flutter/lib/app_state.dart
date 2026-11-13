/// App state: one ChangeNotifier, no state-management framework.
///
/// Owns settings, the API client, sessions, messages, usage and version
/// info. The server is the source of truth for sessions and messages:
/// the list is re-fetched from GET /api/v1/chats on open and on
/// pull-to-refresh, and every sent message is persisted server-side.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import 'api_client.dart';
import 'credential_store.dart';
import 'models.dart';
import 'sse.dart';

class AppState extends ChangeNotifier {
  AppState({CredentialStore? store, ApiClient Function(String baseUrl, String key)? clientFactory})
      : _store = store ?? defaultCredentialStore(),
        _clientFactory = clientFactory ??
            ((baseUrl, key) => ApiClient(baseUrl: baseUrl, clientKey: key));

  final CredentialStore _store;
  final ApiClient Function(String, String) _clientFactory;

  static const defaultBaseUrl = 'http://127.0.0.1:8000';

  // ------------------------------------------------------------ settings
  String baseUrl = defaultBaseUrl;
  String clientKey = '';
  String? selectedModelId;
  bool streamingEnabled = true;

  bool get isConfigured => clientKey.isNotEmpty && baseUrl.isNotEmpty;

  ApiClient? _api;
  ApiClient? get api => _api;

  // ------------------------------------------------------------ data
  List<GatewayModel> models = [];
  List<ChatSession> sessions = [];
  ChatSession? currentSession;
  List<ChatMessage> messages = [];
  UsageSummary? usageToday;
  UsageSummary? usageMonth;
  AppVersionInfo? versionInfo;

  // ------------------------------------------------------------ status
  bool isLoading = false;
  bool isStreaming = false;
  bool isTestingConnection = false;
  String? errorMessage;
  String? connectionMessage;

  StreamSubscription<ChatStreamEvent>? _streamSub;
  bool _streamFinalized = false;
  int? _streamSessionId;
  String? _streamModelId;
  String _assistantText = '';
  int? _streamTokensIn;
  int? _streamTokensOut;

  /// Persist the (possibly partial) assistant reply and clear streaming
  /// state. Idempotent: safe to call from stop, done and error paths.
  Future<void> _finalizeStream() async {
    if (_streamFinalized) {
      return;
    }
    _streamFinalized = true;
    isStreaming = false;
    final api = _api;
    final sessionId = _streamSessionId;
    if (api != null && sessionId != null && _assistantText.isNotEmpty) {
      try {
        final saved = await api.postMessage(sessionId,
            role: 'assistant',
            content: _assistantText,
            model: _streamModelId,
            tokensIn: _streamTokensIn,
            tokensOut: _streamTokensOut);
        if (messages.isNotEmpty) {
          messages = [...messages.sublist(0, messages.length - 1), saved];
        }
      } on GatewayException catch (e) {
        // The reply is shown even if persisting it failed; say so.
        errorMessage = '回复已显示，但保存到服务器失败：${e.message}';
      }
    } else if (messages.isNotEmpty &&
        messages.last.role == 'assistant' &&
        messages.last.content.isEmpty) {
      messages = messages.sublist(0, messages.length - 1);
    }
    notifyListeners();
  }

  void _setError(String? message) {
    errorMessage = message;
    notifyListeners();
  }

  void clearError() {
    errorMessage = null;
    notifyListeners();
  }

  Future<void> init() async {
    baseUrl = await _store.read(CredentialKeys.baseUrl) ?? defaultBaseUrl;
    clientKey = await _store.read(CredentialKeys.clientKey) ?? '';
    selectedModelId = await _store.read(CredentialKeys.selectedModel);
    streamingEnabled =
        (await _store.read(CredentialKeys.streamingEnabled)) != 'false';
    if (isConfigured) {
      _api = _clientFactory(baseUrl, clientKey);
      await testConnection();
      if (models.isNotEmpty) {
        await loadSessions();
      }
      await checkVersion();
    }
    notifyListeners();
  }

  Future<void> saveSettings({
    required String newBaseUrl,
    required String newClientKey,
    bool? newStreamingEnabled,
  }) async {
    baseUrl = newBaseUrl.trim().replaceAll(RegExp(r'/+$'), '');
    clientKey = newClientKey.trim();
    if (newStreamingEnabled != null) {
      streamingEnabled = newStreamingEnabled;
    }
    await _store.write(CredentialKeys.baseUrl, baseUrl);
    await _store.write(CredentialKeys.clientKey, clientKey);
    await _store.write(
        CredentialKeys.streamingEnabled, streamingEnabled ? 'true' : 'false');
    _api = isConfigured ? _clientFactory(baseUrl, clientKey) : null;
    notifyListeners();
  }

  Future<void> clearCredentials() async {
    await _store.delete(CredentialKeys.clientKey);
    clientKey = '';
    selectedModelId = null;
    models = [];
    sessions = [];
    currentSession = null;
    messages = [];
    _api = null;
    notifyListeners();
  }

  // ------------------------------------------------------------ connection
  /// Calls GET /v1/models and reports the honest result. Returns true
  /// only when the server answered with a valid model list.
  Future<bool> testConnection() async {
    if (!isConfigured) {
      connectionMessage = '请先填写网关地址和客户端密钥';
      _setError(connectionMessage);
      return false;
    }
    isTestingConnection = true;
    connectionMessage = null;
    _setError(null);
    notifyListeners();
    final api = _clientFactory(baseUrl, clientKey);
    try {
      final fetched = await api.getModels();
      _api = api;
      models = fetched;
      if (selectedModelId == null ||
          !models.any((m) => m.id == selectedModelId)) {
        selectedModelId = models.isEmpty ? null : models.first.id;
        if (selectedModelId != null) {
          await _store.write(CredentialKeys.selectedModel, selectedModelId!);
        }
      }
      connectionMessage = fetched.isEmpty
          ? '连接成功，但网关暂无已验证可用模型'
          : '连接成功，已验证可用模型 ${fetched.length} 个';
      notifyListeners();
      return true;
    } on GatewayException catch (e) {
      connectionMessage = '连接失败：${e.message}'
          '${e.code != null ? '（${e.code}）' : ''}';
      _setError(connectionMessage);
      notifyListeners();
      return false;
    } finally {
      isTestingConnection = false;
      notifyListeners();
    }
  }

  Future<void> selectModel(String modelId) async {
    selectedModelId = modelId;
    await _store.write(CredentialKeys.selectedModel, modelId);
    notifyListeners();
  }

  // ------------------------------------------------------------ sessions
  Future<void> loadSessions() async {
    final api = _api;
    if (api == null) {
      return;
    }
    isLoading = true;
    _setError(null);
    notifyListeners();
    try {
      sessions = await api.listSessions();
    } on GatewayException catch (e) {
      _setError('加载对话失败：${e.message}');
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  Future<void> selectSession(ChatSession session) async {
    currentSession = session;
    messages = [];
    notifyListeners();
    final api = _api;
    if (api == null) {
      return;
    }
    try {
      messages = await api.listMessages(session.id);
    } on GatewayException catch (e) {
      _setError('加载消息失败：${e.message}');
    }
    notifyListeners();
  }

  Future<void> newSession() async {
    currentSession = null;
    messages = [];
    notifyListeners();
  }

  Future<void> renameSession(ChatSession session, String title) async {
    final api = _api;
    if (api == null) {
      return;
    }
    try {
      final updated = await api.renameSession(session.id, title);
      sessions = sessions
          .map((s) => s.id == session.id ? updated : s)
          .toList();
      if (currentSession?.id == session.id) {
        currentSession = updated;
      }
    } on GatewayException catch (e) {
      _setError('重命名失败：${e.message}');
    }
    notifyListeners();
  }

  Future<void> deleteSession(ChatSession session) async {
    final api = _api;
    if (api == null) {
      return;
    }
    try {
      await api.deleteSession(session.id);
      sessions.removeWhere((s) => s.id == session.id);
      if (currentSession?.id == session.id) {
        currentSession = null;
        messages = [];
      }
    } on GatewayException catch (e) {
      _setError('删除失败：${e.message}');
    }
    notifyListeners();
  }

  // ------------------------------------------------------------ chat
  Future<void> sendMessage(String text) async {
    final api = _api;
    final trimmed = text.trim();
    if (api == null || trimmed.isEmpty || isStreaming) {
      return;
    }
    final modelId = selectedModelId;
    if (modelId == null) {
      _setError('没有可用的模型：网关未返回已验证可用模型');
      return;
    }
    _setError(null);
    // Ensure a server-side session exists first.
    var session = currentSession;
    if (session == null) {
      try {
        final title =
            trimmed.length > 20 ? trimmed.substring(0, 20) : trimmed;
        session = await api.createSession(title: title, model: modelId);
        currentSession = session;
        sessions = [session, ...sessions];
      } on GatewayException catch (e) {
        _setError('创建对话失败：${e.message}');
        return;
      }
    }
    final sessionId = session.id;
    // Persist the user message server-side before streaming.
    try {
      final saved = await api.postMessage(sessionId,
          role: 'user', content: trimmed, model: modelId);
      messages = [...messages, saved];
      notifyListeners();
    } on GatewayException catch (e) {
      _setError('保存消息失败：${e.message}');
      return;
    }
    final history = messages
        .map((m) => {'role': m.role, 'content': m.content})
        .toList();
    isStreaming = true;
    _streamFinalized = false;
    _streamSessionId = sessionId;
    _streamModelId = modelId;
    _assistantText = '';
    _streamTokensIn = null;
    _streamTokensOut = null;
    // Local placeholder for the streaming assistant reply.
    messages = [...messages, ChatMessage(role: 'assistant', content: '')];
    notifyListeners();

    void updatePlaceholder() {
      messages = [
        ...messages.sublist(0, messages.length - 1),
        ChatMessage(
          role: 'assistant',
          content: _assistantText,
          model: modelId,
          tokensIn: _streamTokensIn,
          tokensOut: _streamTokensOut,
        ),
      ];
      notifyListeners();
    }

    if (!streamingEnabled) {
      try {
        final result =
            await api.chatCompletions(model: modelId, messages: history);
        _assistantText = result.text;
        _streamTokensIn = result.tokensIn;
        _streamTokensOut = result.tokensOut;
        updatePlaceholder();
        await _finalizeStream();
      } on GatewayException catch (e) {
        messages = messages.sublist(0, messages.length - 1);
        isStreaming = false;
        _setError('请求失败：${e.message}'
            '${e.code != null ? '（${e.code}）' : ''}');
        notifyListeners();
      }
      return;
    }

    _streamSub = api
        .chatCompletionsStream(model: modelId, messages: history)
        .listen(
      (event) async {
        if (_streamFinalized) {
          return; // stopped already; late events must not resurrect the reply
        }
        if (event.error != null) {
          await _streamSub?.cancel();
          await _finalizeStream();
          _setError('请求失败：${event.error!.message}'
              '${event.error!.code != null ? '（${event.error!.code}）' : ''}');
          return;
        }
        if (event.isDone) {
          await _finalizeStream();
          return;
        }
        if (event.delta.isNotEmpty) {
          _assistantText += event.delta;
          updatePlaceholder();
        }
        if (event.usage != null) {
          _streamTokensIn = event.tokensIn;
          _streamTokensOut = event.tokensOut;
          updatePlaceholder();
        }
      },
      onError: (Object e) async {
        await _finalizeStream();
        if (e is GatewayException) {
          _setError('请求失败：${e.message}'
              '${e.code != null ? '（${e.code}）' : ''}');
        } else {
          _setError('请求失败：$e');
        }
      },
      onDone: () async {
        await _finalizeStream();
      },
      cancelOnError: true,
    );
  }

  /// Stop the current stream. The partial assistant reply (if any) is
  /// still posted to the server so history stays complete.
  ///
  /// The stream cancel is deliberately not awaited: some stream
  /// implementations never complete their cancel future (notably an
  /// async* generator suspended in `await for` over a transformed
  /// stream), and awaiting it made Stop hang. The cancel still
  /// propagates; finalization is idempotent, so late events are ignored.
  Future<void> stopStreaming() async {
    if (!isStreaming) {
      return;
    }
    final sub = _streamSub;
    _streamSub = null;
    unawaited(sub?.cancel());
    await _finalizeStream();
  }

  // ------------------------------------------------------------ usage
  Future<void> loadUsage() async {
    final api = _api;
    if (api == null) {
      return;
    }
    try {
      usageToday = await api.usageSummary('today');
      usageMonth = await api.usageSummary('month');
    } on GatewayException catch (e) {
      _setError('加载用量失败：${e.message}');
    }
    notifyListeners();
  }

  // ------------------------------------------------------------ version
  Future<void> checkVersion() async {
    final api = _api;
    if (api == null) {
      return;
    }
    try {
      versionInfo = await api.getVersion();
    } on GatewayException catch (e) {
      _setError('版本检查失败：${e.message}');
    }
    notifyListeners();
  }
}
