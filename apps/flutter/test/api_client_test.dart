import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:personal_ai_gateway/api_client.dart';
import 'package:personal_ai_gateway/models.dart';

ApiClient clientWith(MockClient mock) => ApiClient(
      baseUrl: 'http://127.0.0.1:8000',
      clientKey: 'pag_sk_testkey',
      httpClient: mock,
    );

void main() {
  group('ApiClient', () {
    test('sends Bearer auth header and parses /v1/models', () async {
      String? auth;
      final mock = MockClient((request) async {
        auth = request.headers['Authorization'];
        return http.Response(
          '{"object":"list","data":['
          '{"id":"gpt-5.4-mini","object":"model","created":1763000000,'
          '"owned_by":"gateway"}]}',
          200,
        );
      });
      final models = await clientWith(mock).getModels();
      expect(auth, 'Bearer pag_sk_testkey');
      expect(models.map((m) => m.id), ['gpt-5.4-mini']);
    });

    test('returns empty list when the gateway has no verified models', () async {
      final mock = MockClient((request) async {
        return http.Response('{"object":"list","data":[]}', 200);
      });
      expect(await clientWith(mock).getModels(), isEmpty);
    });

    test('maps gateway errors to GatewayException with code', () async {
      final mock = MockClient((request) async {
        return http.Response(
          '{"error":{"message":"invalid client key","type":"gateway_error",'
          '"code":"invalid_client_key"}}',
          401,
        );
      });
      try {
        await clientWith(mock).getModels();
        fail('expected GatewayException');
      } on GatewayException catch (e) {
        expect(e.code, 'invalid_client_key');
        expect(e.status, 401);
        expect(e.message, 'invalid client key');
      }
    });

    test('maps non-JSON error bodies to a plain HTTP error', () async {
      final mock = MockClient((request) async {
        return http.Response('Service Unavailable', 503);
      });
      try {
        await clientWith(mock).getModels();
        fail('expected GatewayException');
      } on GatewayException catch (e) {
        expect(e.status, 503);
      }
    });

    test('parses configured version info', () async {
      final mock = MockClient((request) async {
        return http.Response(
          '{"configured":true,"version":"0.1.0","gateway_version":"0.3.0",'
          '"platforms":{"ios":{"version":"0.1.0",'
          '"release_date":"2026-11-14",'
          '"download_url":"https://example.com/app.ipa",'
          '"sha256":"abc","release_notes":"first build"}}}',
          200,
        );
      });
      final info = await clientWith(mock).getVersion();
      expect(info.configured, isTrue);
      expect(info.version, '0.1.0');
      expect(info.gatewayVersion, '0.3.0');
      expect(info.platforms['ios']!.version, '0.1.0');
      expect(info.platforms['ios']!.downloadUrl,
          'https://example.com/app.ipa');
    });

    test('parses configured:false honestly, never inventing a version',
        () async {
      final mock = MockClient((request) async {
        return http.Response(
          '{"configured":false,"version":null,"platforms":{},'
          '"note":"no release configured on this server"}',
          200,
        );
      });
      final info = await clientWith(mock).getVersion();
      expect(info.configured, isFalse);
      expect(info.version, isNull);
      expect(info.platforms, isEmpty);
    });

    test('parses usage summary with cost status', () async {
      final mock = MockClient((request) async {
        return http.Response(
          '{"period":"today","requests":2,"tokens_in":12,"tokens_out":7,'
          '"cost_usd":0.000026,"cost_status":"ok",'
          '"by_model":[{"model":"gpt-5.4-mini","requests":2,'
          '"tokens_in":12,"tokens_out":7,"cost_usd":0.000026}]}',
          200,
        );
      });
      final summary = await clientWith(mock).usageSummary('today');
      expect(summary.requests, 2);
      expect(summary.tokensIn, 12);
      expect(summary.costStatus, 'ok');
      expect(summary.costIsExact, isTrue);
      expect(summary.byModel.single.model, 'gpt-5.4-mini');
    });

    test('usage summary keeps non-ok cost status visible', () async {
      final mock = MockClient((request) async {
        return http.Response(
          '{"period":"month","requests":1,"tokens_in":100,"tokens_out":50,'
          '"cost_usd":0,"cost_status":"price_not_configured","by_model":[]}',
          200,
        );
      });
      final summary = await clientWith(mock).usageSummary('month');
      expect(summary.costStatus, 'price_not_configured');
      expect(summary.costIsExact, isFalse);
      expect(summary.costStatusLabel, contains('未配置价格'));
    });

    test('chat session CRUD round-trips through the API', () async {
      final seen = <String>[];
      final mock = MockClient((request) async {
        seen.add('${request.method} ${request.url.path}');
        if (request.method == 'POST' &&
            request.url.path == '/api/v1/chats') {
          return http.Response(
            '{"id":1,"title":"hello","model":"gpt-5.4-mini",'
            '"created_at":"2026-11-14T00:00:00Z",'
            '"updated_at":"2026-11-14T00:00:00Z"}',
            201,
          );
        }
        if (request.method == 'GET' &&
            request.url.path == '/api/v1/chats/1/messages') {
          return http.Response(
            '{"messages":[{"id":2,"session_id":1,"role":"user",'
            '"content":"hi","model":"gpt-5.4-mini","tokens_in":null,'
            '"tokens_out":null}]}',
            200,
          );
        }
        return http.Response('{"error":{"message":"not found","code":"x"}}',
            404);
      });
      final api = clientWith(mock);
      final session =
          await api.createSession(title: 'hello', model: 'gpt-5.4-mini');
      expect(session.id, 1);
      final messages = await api.listMessages(1);
      expect(messages.single.content, 'hi');
      expect(seen, contains('POST /api/v1/chats'));
    });

    test('streaming chat yields deltas then done', () async {
      const sse = 'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
          'data: {"choices":[{"delta":{"content":"world"}}],'
          '"usage":{"prompt_tokens":12,"completion_tokens":7}}\n\n'
          'data: [DONE]\n\n';
      final mock = MockClient((request) async {
        return http.Response(sse, 200,
            headers: {'content-type': 'text/event-stream'});
      });
      final events = await clientWith(mock)
          .chatCompletionsStream(model: 'gpt-5.4-mini', messages: [
        {'role': 'user', 'content': 'hi'}
      ]).toList();
      final deltas = events.where((e) => e.delta.isNotEmpty).toList();
      expect(deltas.map((e) => e.delta).join(), 'Hello world');
      final usage = events.where((e) => e.usage != null).toList();
      expect(usage.single.tokensIn, 12);
      expect(usage.single.tokensOut, 7);
      expect(events.any((e) => e.isDone), isTrue);
    });
  });
}
