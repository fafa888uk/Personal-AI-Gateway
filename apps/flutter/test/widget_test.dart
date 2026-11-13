import 'dart:async';
import 'dart:convert';

import 'package:http/testing.dart';
import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:personal_ai_gateway/api_client.dart';
import 'package:personal_ai_gateway/app_state.dart';
import 'package:personal_ai_gateway/credential_store.dart';
import 'package:personal_ai_gateway/screens/chat_screen.dart';
import 'test_helpers.dart';
import 'package:personal_ai_gateway/screens/login_screen.dart';
import 'package:personal_ai_gateway/screens/settings_screen.dart';

void main() {
  group('LoginScreen', () {
    testWidgets('validation rejects empty fields and a bad key prefix',
        (tester) async {
      final state = AppState(store: MemoryCredentialStore());
      var entered = false;
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(state: state, onDone: () => entered = true),
        ),
      );
      // The URL field is prefilled with the default; clear it first so
      // the empty-field validation is exercised.
      await tester.enterText(find.byType(TextField).first, '');
      await tester.tap(find.text('测试连接并进入'));
      await tester.pump();
      expect(find.text('请输入网关地址'), findsOneWidget);
      expect(find.text('请输入客户端密钥'), findsOneWidget);

      await tester.enterText(
          find.byType(TextField).first, 'http://127.0.0.1:8000');
      await tester.enterText(find.byType(TextField).last, 'not-a-key');
      await tester.tap(find.text('测试连接并进入'));
      await tester.pump();
      expect(find.text('客户端密钥应以 pag_sk_ 开头'), findsOneWidget);
      expect(entered, isFalse);
    });

    testWidgets('test-connection flow succeeds with a mocked gateway',
        (tester) async {
      final rec = RecordingMock();
      final store = MemoryCredentialStore();
      final state = AppState(
        store: store,
        clientFactory: (baseUrl, key) => ApiClient(
          baseUrl: baseUrl,
          clientKey: key,
          httpClient: MockClient(rec.handler),
        ),
      );
      var entered = false;
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(state: state, onDone: () => entered = true),
        ),
      );
      await tester.enterText(
          find.byType(TextField).first, 'http://127.0.0.1:8000');
      await tester.enterText(find.byType(TextField).last, 'pag_sk_testkey');
      await tester.tap(find.text('测试连接并进入'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pumpAndSettle();
      expect(find.textContaining('连接成功'), findsOneWidget);
      expect(state.models.length, 2);
      expect(entered, isTrue);
    });
  });

  group('ChatScreen', () {
    testWidgets('send streams a reply and persists both messages',
        (tester) async {
      final rec = RecordingMock();
      final state = await configuredState(rec);
      await tester.pumpWidget(
        MaterialApp(home: ChatScreen(state: state)),
      );
      await tester.pumpAndSettle();
      expect(state.models.length, 2);

      await tester.enterText(find.byType(TextField), '你好');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));
      await tester.pumpAndSettle();

      expect(find.textContaining('Hello from mock.'), findsOneWidget);
      expect(state.messages.any((m) => m.content == '你好'), isTrue);
      expect(state.isStreaming, isFalse);
      // User message + completed assistant message persisted server-side.
      expect(rec.postedMessages.length, 2);
      expect(rec.postedMessages[0]['role'], 'user');
      expect(rec.postedMessages[1]['role'], 'assistant');
      expect(rec.postedMessages[1]['content'], 'Hello from mock.');
      expect(rec.postedMessages[1]['tokens_in'], 12);
      expect(rec.postedMessages[1]['tokens_out'], 7);
    });

    testWidgets('stop cancels the stream and persists the partial reply',
        (tester) async {
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
          httpClient: ControlledStreamClient(
              MockClient(rec.handler), controller),
        ),
      );
      await state.init();
      await tester.pumpWidget(
        MaterialApp(home: ChatScreen(state: state)),
      );
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField), '你好');
      await tester.tap(find.byIcon(Icons.send));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      controller.add(utf8.encode(
          'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.textContaining('Hello'), findsOneWidget);
      expect(find.text('停止'), findsOneWidget);

      await tester.tap(find.text('停止'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));
      await tester.pumpAndSettle();
      expect(state.isStreaming, isFalse);
      // The partial assistant reply is still persisted server-side.
      expect(rec.postedMessages.length, 2);
      expect(rec.postedMessages[1]['role'], 'assistant');
      expect(rec.postedMessages[1]['content'], 'Hello ');
      // Do not await controller.close() here: closing waits for the
      // still-detaching stream subscription, whose completion needs
      // event-loop turns the fake-async zone will not deliver after the
      // test body ends. The test process exits regardless.
      unawaited(controller.close());
    });

    testWidgets('model switcher selects another verified model',
        (tester) async {
      final rec = RecordingMock();
      final state = await configuredState(rec);
      await tester.pumpWidget(
        MaterialApp(home: ChatScreen(state: state)),
      );
      await tester.pumpAndSettle();
      expect(state.selectedModelId, 'gpt-5.4-mini');

      await tester.tap(find.byTooltip('切换模型（仅显示已验证可用模型）'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('gpt-5.4-nano'));
      await tester.pumpAndSettle();
      expect(state.selectedModelId, 'gpt-5.4-nano');
    });
  });

  group('SettingsScreen', () {
    testWidgets('saving settings persists the base URL', (tester) async {
      final rec = RecordingMock();
      final inspectStore = MemoryCredentialStore();
      await inspectStore.write(
          CredentialKeys.baseUrl, 'http://127.0.0.1:8000');
      await inspectStore.write(CredentialKeys.clientKey, 'pag_sk_testkey');
      final inspectState = AppState(
        store: inspectStore,
        clientFactory: (baseUrl, key) => ApiClient(
          baseUrl: baseUrl,
          clientKey: key,
          httpClient: MockClient(rec.handler),
        ),
      );
      await inspectState.init();
      await tester.pumpWidget(
        MaterialApp(home: SettingsScreen(state: inspectState)),
      );
      await tester.pumpAndSettle();

      await tester.enterText(
          find.byType(TextField).first, 'http://127.0.0.1:9000');
      await tester.tap(find.text('保存设置'));
      await tester.pumpAndSettle();
      expect(await inspectStore.read(CredentialKeys.baseUrl),
          'http://127.0.0.1:9000');
      expect(find.text('设置已保存'), findsOneWidget);
    });
  });
}
