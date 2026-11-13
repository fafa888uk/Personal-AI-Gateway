/// HTTP client for the Personal AI Gateway.
///
/// Talks to the REAL gateway API only. Auth is `Authorization: Bearer`
/// plus a client key; the client never touches /admin/* and never stores
/// an admin key. [http.Client] is injectable so unit tests can use a mock.
library;

import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';
import 'sse.dart';

class ApiClient {
  ApiClient({
    required String baseUrl,
    required this.clientKey,
    http.Client? httpClient,
  })  : baseUrl = baseUrl.replaceAll(RegExp(r'/+$'), ''),
        _http = httpClient ?? http.Client();

  final String baseUrl;
  final String clientKey;
  final http.Client _http;

  Map<String, String> get _headers => {
        'Authorization': 'Bearer $clientKey',
        'Content-Type': 'application/json',
      };

  Uri _uri(String path) => Uri.parse('$baseUrl$path');

  Future<Map<String, dynamic>> _getJson(String path) async {
    late http.Response resp;
    try {
      resp = await _http.get(_uri(path), headers: _headers);
    } on Exception catch (e) {
      throw GatewayException('无法连接网关：$e');
    }
    return _decode(resp);
  }

  Future<Map<String, dynamic>> _sendJson(
    String method,
    String path, [
    Map<String, dynamic>? body,
  ]) async {
    late http.Response resp;
    try {
      final uri = _uri(path);
      final encoded = body == null ? null : jsonEncode(body);
      switch (method) {
        case 'POST':
          resp = await _http.post(uri, headers: _headers, body: encoded);
        case 'PATCH':
          resp = await _http.patch(uri, headers: _headers, body: encoded);
        case 'DELETE':
          resp = await _http.delete(uri, headers: _headers);
        default:
          throw GatewayException('不支持的请求方法：$method');
      }
    } on GatewayException {
      rethrow;
    } on Exception catch (e) {
      throw GatewayException('无法连接网关：$e');
    }
    return _decode(resp);
  }

  Map<String, dynamic> _decode(http.Response resp) {
    Map<String, dynamic> json = {};
    if (resp.body.isNotEmpty) {
      try {
        final decoded = jsonDecode(resp.body);
        if (decoded is Map<String, dynamic>) {
          json = decoded;
        }
      } on FormatException {
        // Non-JSON body: fall through to the status check below.
      }
    }
    if (resp.statusCode >= 400) {
      final err = json['error'];
      if (err is Map<String, dynamic>) {
        throw GatewayException(
          err['message'] as String? ?? '网关返回错误',
          code: err['code'] as String?,
          status: resp.statusCode,
        );
      }
      throw GatewayException(
        '网关返回 HTTP ${resp.statusCode}',
        status: resp.statusCode,
      );
    }
    return json;
  }

  // ------------------------------------------------------------ models
  /// GET /v1/models — only verified + enabled models are ever returned.
  Future<List<GatewayModel>> getModels() async {
    final json = await _getJson('/v1/models');
    final data = json['data'];
    if (data is! List) {
      return const [];
    }
    return data
        .whereType<Map<String, dynamic>>()
        .map(GatewayModel.fromJson)
        .toList();
  }

  // ------------------------------------------------------------ app version
  /// GET /api/v1/app/version — public, no auth. When the server has no
  /// release configured the result is `configured: false`, never fake.
  Future<AppVersionInfo> getVersion() async {
    late http.Response resp;
    try {
      resp = await _http.get(_uri('/api/v1/app/version'));
    } on Exception catch (e) {
      throw GatewayException('无法连接网关：$e');
    }
    if (resp.statusCode >= 400) {
      throw GatewayException('版本信息请求失败：HTTP ${resp.statusCode}',
          status: resp.statusCode);
    }
    try {
      final decoded = jsonDecode(resp.body);
      if (decoded is Map<String, dynamic>) {
        return AppVersionInfo.fromJson(decoded);
      }
    } on FormatException {
      throw GatewayException('版本信息不是有效的 JSON');
    }
    return AppVersionInfo.unconfigured();
  }

  // ------------------------------------------------------------ chats
  Future<List<ChatSession>> listSessions() async {
    final json = await _getJson('/api/v1/chats');
    final data = json['sessions'];
    if (data is! List) {
      return const [];
    }
    return data
        .whereType<Map<String, dynamic>>()
        .map(ChatSession.fromJson)
        .toList();
  }

  Future<ChatSession> createSession({String? title, String? model}) async {
    final body = <String, dynamic>{};
    if (title != null) {
      body['title'] = title;
    }
    if (model != null) {
      body['model'] = model;
    }
    final json = await _sendJson('POST', '/api/v1/chats', body);
    return ChatSession.fromJson(json);
  }

  Future<ChatSession> renameSession(int id, String title) async {
    final json = await _sendJson('PATCH', '/api/v1/chats/$id', {'title': title});
    return ChatSession.fromJson(json);
  }

  Future<void> deleteSession(int id) async {
    await _sendJson('DELETE', '/api/v1/chats/$id');
  }

  Future<List<ChatMessage>> listMessages(int sessionId) async {
    final json = await _getJson('/api/v1/chats/$sessionId/messages');
    final data = json['messages'];
    if (data is! List) {
      return const [];
    }
    return data
        .whereType<Map<String, dynamic>>()
        .map(ChatMessage.fromJson)
        .toList();
  }

  Future<ChatMessage> postMessage(
    int sessionId, {
    required String role,
    required String content,
    String? model,
    int? tokensIn,
    int? tokensOut,
  }) async {
    final body = <String, dynamic>{'role': role, 'content': content};
    if (model != null) {
      body['model'] = model;
    }
    if (tokensIn != null) {
      body['tokens_in'] = tokensIn;
    }
    if (tokensOut != null) {
      body['tokens_out'] = tokensOut;
    }
    final json =
        await _sendJson('POST', '/api/v1/chats/$sessionId/messages', body);
    return ChatMessage.fromJson(json);
  }

  // ------------------------------------------------------------ usage
  Future<UsageSummary> usageSummary(String period) async {
    final json = await _getJson('/api/v1/usage/summary?period=$period');
    return UsageSummary.fromJson(json);
  }

  // ------------------------------------------------------------ chat completions
  /// Non-streaming POST /v1/chat/completions. Returns the assistant text
  /// plus usage (when the server returns it).
  Future<({String text, int? tokensIn, int? tokensOut})> chatCompletions({
    required String model,
    required List<Map<String, String>> messages,
  }) async {
    final json = await _sendJson('POST', '/v1/chat/completions', {
      'model': model,
      'messages': messages,
    });
    var text = '';
    final choices = json['choices'];
    if (choices is List && choices.isNotEmpty) {
      final first = choices.first;
      if (first is Map<String, dynamic>) {
        final message = first['message'];
        if (message is Map<String, dynamic>) {
          text = message['content'] as String? ?? '';
        }
      }
    }
    int? tokensIn;
    int? tokensOut;
    final usage = json['usage'];
    if (usage is Map<String, dynamic>) {
      tokensIn = usage['prompt_tokens'] as int?;
      tokensOut = usage['completion_tokens'] as int?;
    }
    return (text: text, tokensIn: tokensIn, tokensOut: tokensOut);
  }

  /// Streaming POST /v1/chat/completions. Yields [ChatStreamEvent]s as
  /// they arrive. Cancelling the subscription stops the stream promptly
  /// and aborts delivery from the gateway.
  ///
  /// Implementation note: this is built on an explicit [StreamController]
  /// with a manually-cancelled byte subscription — NOT `await for` over a
  /// transformed stream inside an `async*` generator. Cancelling a
  /// subscription to such a generator while it is suspended in `await for`
  /// never completes (verified with a minimal Dart repro, 2026-11-14),
  /// which made the UI Stop button hang.
  Stream<ChatStreamEvent> chatCompletionsStream({
    required String model,
    required List<Map<String, String>> messages,
  }) {
    final controller = StreamController<ChatStreamEvent>();
    StreamSubscription<String>? byteSub;
    var closed = false;

    Future<void> close() async {
      if (closed) {
        return;
      }
      closed = true;
      await byteSub?.cancel();
      if (!controller.isClosed) {
        await controller.close();
      }
    }

    controller.onCancel = close;

    () async {
      final request = http.Request('POST', _uri('/v1/chat/completions'));
      request.headers.addAll(_headers);
      request.body = jsonEncode({
        'model': model,
        'messages': messages,
        'stream': true,
      });
      late http.StreamedResponse resp;
      try {
        resp = await _http.send(request);
      } on Exception catch (e) {
        if (!closed) {
          controller.add(
              ChatStreamEvent.error(GatewayException('无法连接网关：$e')));
          await close();
        }
        return;
      }
      if (closed) {
        return;
      }
      if (resp.statusCode >= 400) {
        final body = await resp.stream.bytesToString();
        if (closed) {
          return;
        }
        Map<String, dynamic> json = {};
        try {
          final decoded = jsonDecode(body);
          if (decoded is Map<String, dynamic>) {
            json = decoded;
          }
        } on FormatException {
          // ignore
        }
        final err = json['error'];
        if (err is Map<String, dynamic>) {
          controller.add(ChatStreamEvent.error(GatewayException(
            err['message'] as String? ?? '网关返回错误',
            code: err['code'] as String?,
            status: resp.statusCode,
          )));
        } else {
          controller.add(ChatStreamEvent.error(GatewayException(
            '网关返回 HTTP ${resp.statusCode}',
            status: resp.statusCode,
          )));
        }
        await close();
        return;
      }
      final parser = SseParser();
      byteSub = resp.stream
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(
        (line) {
          if (closed) {
            return;
          }
          for (final event in parser.feed('$line\n')) {
            controller.add(event);
            if (event.error != null) {
              unawaited(close());
              return;
            }
          }
        },
        onError: (Object e) {
          if (!closed) {
            controller.add(ChatStreamEvent.error(
                GatewayException('流式连接中断：$e')));
            unawaited(close());
          }
        },
        onDone: () {
          for (final event in parser.finish()) {
            controller.add(event);
          }
          controller.add(ChatStreamEvent.done());
          unawaited(close());
        },
        cancelOnError: true,
      );
    }();
    return controller.stream;
  }
}
