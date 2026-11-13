import 'dart:async';
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/testing.dart';
import 'package:personal_ai_gateway/api_client.dart';
import 'package:personal_ai_gateway/app_state.dart';
import 'package:personal_ai_gateway/credential_store.dart';

import 'test_helpers.dart';

void main() {
  test('stopStreaming cancels the stream and posts the partial reply',
      () async {
    final rec = RecordingMock();
    final controller = StreamController<List<int>>();
    final store = MemoryCredentialStore();
    await store.write(CredentialKeys.baseUrl, 'http://127.0.0.1:8000');
    await store.write(CredentialKeys.clientKey, 'pag_sk_testkey');
    final state = AppState(
      store: store,
      clientFactory: (baseUrl, key) => ApiClient(
        baseUrl: baseUrl,
        clientKey: key,
        httpClient:
            ControlledStreamClient(MockClient(rec.handler), controller),
      ),
    );
    await state.init();
    expect(state.selectedModelId, 'gpt-5.4-mini');

    final sendFuture = state.sendMessage('你好');
    await Future<void>.delayed(const Duration(milliseconds: 200));
    expect(state.isStreaming, isTrue);
    controller.add(utf8.encode(
        'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'));
    await Future<void>.delayed(const Duration(milliseconds: 200));
    expect(state.messages.last.content, 'Hello ');

    await state.stopStreaming().timeout(const Duration(seconds: 5));
    expect(state.isStreaming, isFalse);
    expect(rec.postedMessages.length, 2);
    expect(rec.postedMessages[1]['content'], 'Hello ');
    await sendFuture.timeout(const Duration(seconds: 5));
    await controller.close();
  });
}
