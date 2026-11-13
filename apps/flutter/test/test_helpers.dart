import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_ai_gateway/api_client.dart';
import 'package:personal_ai_gateway/app_state.dart';
import 'package:personal_ai_gateway/credential_store.dart';

const _modelsJson = '{"object":"list","data":['
    '{"id":"gpt-5.4-mini","object":"model","created":1763000000,'
    '"owned_by":"gateway"},'
    '{"id":"gpt-5.4-nano","object":"model","created":1763000000,'
    '"owned_by":"gateway"}]}';

const _versionUnconfigured =
    '{"configured":false,"version":null,"platforms":{}}';

const _chatSse = 'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"from mock."}}],'
    '"usage":{"prompt_tokens":12,"completion_tokens":7}}\n\n'
    'data: [DONE]\n\n';

/// Mock gateway that records every call. Models are "verified" here only
/// because this mock says so — never real verification.
class RecordingMock {
  RecordingMock({this.streamController});

  final List<String> calls = [];
  final List<Map<String, dynamic>> postedMessages = [];
  final StreamController<List<int>>? streamController;
  int _nextId = 10;

  Future<http.Response> handler(http.Request request) async {
    final path = request.url.path;
    calls.add('${request.method} $path');
    if (request.method == 'GET' && path == '/v1/models') {
      return http.Response(_modelsJson, 200);
    }
    if (request.method == 'GET' && path == '/api/v1/app/version') {
      return http.Response(_versionUnconfigured, 200);
    }
    if (request.method == 'GET' && path == '/api/v1/chats') {
      return http.Response('{"sessions":[]}', 200);
    }
    if (request.method == 'POST' && path == '/api/v1/chats') {
      return http.Response(
        '{"id":1,"title":"hi","model":"gpt-5.4-mini",'
        '"created_at":"2026-11-14T00:00:00Z",'
        '"updated_at":"2026-11-14T00:00:00Z"}',
        201,
      );
    }
    if (request.method == 'GET' && path == '/api/v1/chats/1/messages') {
      return http.Response('{"messages":[]}', 200);
    }
    if (request.method == 'POST' && path == '/api/v1/chats/1/messages') {
      final body = jsonDecode(request.body) as Map<String, dynamic>;
      postedMessages.add(body);
      _nextId++;
      // Response.bytes: the body may contain non-Latin-1 text.
      return http.Response.bytes(
        utf8.encode(jsonEncode({
          'id': _nextId,
          'session_id': 1,
          'role': body['role'],
          'content': body['content'],
          'model': body['model'],
          'tokens_in': body['tokens_in'],
          'tokens_out': body['tokens_out'],
        })),
        201,
        headers: {'content-type': 'application/json; charset=utf-8'},
      );
    }
    if (request.method == 'POST' && path == '/v1/chat/completions') {
      return http.Response(_chatSse, 200,
          headers: {'content-type': 'text/event-stream'});
    }
    if (request.method == 'GET' && path == '/api/v1/usage/summary') {
      return http.Response(
        '{"period":"today","requests":0,"tokens_in":0,"tokens_out":0,'
        '"cost_usd":0,"cost_status":"ok","by_model":[]}',
        200,
      );
    }
    return http.Response(
        '{"error":{"message":"not found","code":"not_found"}}', 404);
  }
}

/// HTTP client whose chat-completion stream the test controls chunk by
/// chunk (to test Stop); every other request goes to the mock fallback.
class ControlledStreamClient extends http.BaseClient {
  ControlledStreamClient(this.fallback, this.controller);

  final http.Client fallback;
  final StreamController<List<int>> controller;

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    if (request.url.path == '/v1/chat/completions') {
      return Future.value(http.StreamedResponse(
        controller.stream,
        200,
        headers: {'content-type': 'text/event-stream'},
      ));
    }
    return fallback.send(request);
  }
}

Future<AppState> configuredState(RecordingMock rec) async {
  final store = MemoryCredentialStore();
  await store.write(CredentialKeys.baseUrl, 'http://127.0.0.1:8000');
  await store.write(CredentialKeys.clientKey, 'pag_sk_testkey');
  final state = AppState(
    store: store,
    clientFactory: (baseUrl, key) => ApiClient(
      baseUrl: baseUrl,
      clientKey: key,
      httpClient: MockClient(rec.handler),
    ),
  );
  await state.init();
  return state;
}

