/* End-to-end integration test against a REAL HTTP gateway server.
 *
 * Prerequisite: the mock gateway runner must be running first:
 *
 *   scripts/run_integration_test.sh
 *
 * which starts apps/api/gateway/dev_mock_server.py (MOCK ONLY) on
 * 127.0.0.1:8000, writes the seeded client key to a JSON file, and
 * exports PAG_MOCK_KEY_FILE for this test.
 *
 * Flow (all against the live server, no mocks):
 *   login (test connection) -> list models -> create chat ->
 *   send a streaming message -> verify both messages persisted
 *   server-side via the API.
 *
 * Run with: flutter test integration_test
 */
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:personal_ai_gateway/api_client.dart';
import 'package:personal_ai_gateway/app_state.dart';
import 'package:personal_ai_gateway/credential_store.dart';
import 'package:personal_ai_gateway/screens/chat_screen.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('end-to-end against the mock gateway server', (tester) async {
    final keyFile = Platform.environment['PAG_MOCK_KEY_FILE'];
    expect(keyFile, isNotNull,
        reason: 'PAG_MOCK_KEY_FILE is not set; run scripts/run_integration_test.sh');
    final creds =
        jsonDecode(await File(keyFile!).readAsString()) as Map<String, dynamic>;
    final baseUrl = creds['base_url'] as String;
    final clientKey = creds['client_key'] as String;
    expect(baseUrl, startsWith('http://127.0.0.1:'));
    expect(clientKey, startsWith('pag_sk_'));

    final store = MemoryCredentialStore();
    await store.write(CredentialKeys.baseUrl, baseUrl);
    await store.write(CredentialKeys.clientKey, clientKey);
    final state = AppState(store: store);
    await state.init();
    expect(state.isConfigured, isTrue);

    // Login / test connection: the mock server has one mock-verified model.
    final connected = await state.testConnection();
    expect(connected, isTrue);
    expect(state.models.map((m) => m.id), contains('gpt-5.4-mini'));
    expect(state.selectedModelId, 'gpt-5.4-mini');

    await state.loadSessions();
    expect(state.sessions, isEmpty);

    // Chat UI: send a message, stream the reply to completion.
    await tester.pumpWidget(MaterialApp(home: ChatScreen(state: state)));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField), '你好');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pump();
    await tester.pumpAndSettle(const Duration(seconds: 30));
    expect(state.isStreaming, isFalse);
    expect(state.errorMessage, isNull);
    expect(state.messages.length, 2);
    expect(state.messages[0].role, 'user');
    expect(state.messages[0].content, '你好');
    expect(state.messages[1].role, 'assistant');
    // The mock upstream streams "Hello " as its only delta.
    expect(state.messages[1].content, 'Hello ');
    expect(state.messages[1].tokensIn, 12);
    expect(state.messages[1].tokensOut, 7);

    // Verify server-side persistence via the API (source of truth).
    final sessionId = state.currentSession!.id;
    final api = ApiClient(baseUrl: baseUrl, clientKey: clientKey);
    final persisted = await api.listMessages(sessionId);
    expect(persisted.length, 2);
    expect(persisted[0].role, 'user');
    expect(persisted[0].content, '你好');
    expect(persisted[1].role, 'assistant');
    expect(persisted[1].content, 'Hello ');
    expect(persisted[1].tokensIn, 12);
    expect(persisted[1].tokensOut, 7);

    final sessions = await api.listSessions();
    expect(sessions.map((s) => s.id), contains(sessionId));
  });
}
