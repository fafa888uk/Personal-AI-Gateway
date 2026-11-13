import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_gateway/sse.dart';

void main() {
  group('SseParser', () {
    test('parses deltas, usage and [DONE]', () {
      const text = 'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
          'data: {"choices":[{"delta":{"content":"world"}}],'
          '"usage":{"prompt_tokens":12,"completion_tokens":7}}\n\n'
          'data: [DONE]\n\n';
      final events = parseSseText(text);
      expect(events.where((e) => e.delta.isNotEmpty).map((e) => e.delta).join(),
          'Hello world');
      final usage = events.where((e) => e.usage != null).single;
      expect(usage.tokensIn, 12);
      expect(usage.tokensOut, 7);
      expect(events.where((e) => e.isDone).length, 1);
    });

    test('handles partial lines split across chunks', () {
      final parser = SseParser();
      final first = parser.feed('data: {"choices":[{"delta":{"con');
      final second = parser.feed('tent":"Hel');
      final third = parser.feed('lo"}}]}\n\ndata: [DONE]\n\n');
      expect([...first, ...second, ...third]
          .where((e) => e.delta.isNotEmpty)
          .map((e) => e.delta)
          .join(), 'Hello');
      expect(third.any((e) => e.isDone), isTrue);
    });

    test('handles an error event with the gateway error shape', () {
      const text =
          'data: {"error":{"message":"model not verified","type":"gateway_error",'
          '"code":"model_not_verified"}}\n\n';
      final events = parseSseText(text);
      expect(events.length, 1);
      expect(events.single.error, isNotNull);
      expect(events.single.error!.code, 'model_not_verified');
      expect(events.single.error!.message, 'model not verified');
    });

    test('ignores comments, empty lines and malformed JSON', () {
      const text = ': ping\n\n'
          'event: message\n'
          'data: not-json\n\n'
          'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n';
      final events = parseSseText(text);
      expect(events.map((e) => e.delta).join(), 'ok');
    });

    test('empty body yields no events', () {
      expect(parseSseText(''), isEmpty);
    });
  });

  group('compareVersions', () {
    test('numeric comparison', () {
      expect(compareVersions('0.1.0', '0.2.0'), -1);
      expect(compareVersions('1.0.0', '0.9.9'), 1);
      expect(compareVersions('1.0.0', '1.0.0'), 0);
      expect(compareVersions('1.0', '1.0.0'), 0);
      expect(compareVersions('1.10.0', '1.9.0'), 1);
    });

    test('pre-release sorts below the release', () {
      expect(compareVersions('1.0.0-beta', '1.0.0'), -1);
      expect(compareVersions('1.0.0-beta', '1.0.0-alpha'), 1);
    });
  });
}
