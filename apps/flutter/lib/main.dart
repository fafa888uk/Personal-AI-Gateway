/// Personal AI Gateway — Flutter client (iOS / Windows / macOS).
///
/// One shared codebase. Chat + model switching + settings + usage +
/// version check only — no admin features. Talks to the real gateway API;
/// the client key is a bearer secret stored in the platform secure store
/// (0600-file fallback on Linux dev only).
library;

import 'package:material_ui/material_ui.dart';

import 'app_state.dart';
import 'screens/chat_screen.dart';
import 'screens/login_screen.dart';
import 'screens/settings_screen.dart';
import 'screens/usage_screen.dart';
import 'screens/version_screen.dart';

/// This build's version (matches pubspec.yaml). Used only to compare
/// against the server-reported per-platform versions.
const String kAppVersion = '0.1.3';

void main() {
  runApp(const GatewayApp());
}

class GatewayApp extends StatefulWidget {
  const GatewayApp({super.key});

  @override
  State<GatewayApp> createState() => _GatewayAppState();
}

class _GatewayAppState extends State<GatewayApp> {
  late final AppState _state;
  bool _ready = false;
  int _tab = 0;

  @override
  void initState() {
    super.initState();
    _state = AppState();
    _state.init().then((_) {
      if (mounted) {
        setState(() => _ready = true);
      }
    });
  }

  @override
  void dispose() {
    _state.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF1E5AA8); // brand deep-sea blue
    return MaterialApp(
      title: 'Personal AI Gateway',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        useMaterial3: true,
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: seed,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      themeMode: ThemeMode.system,
      home: !_ready
          ? const Scaffold(
              body: Center(child: CircularProgressIndicator()),
            )
          : ListenableBuilder(
              listenable: _state,
              builder: (context, _) {
                if (!_state.isConfigured) {
                  return LoginScreen(
                    state: _state,
                    onDone: () => setState(() {}),
                  );
                }
                final pages = [
                  ChatScreen(state: _state),
                  UsageScreen(state: _state),
                  VersionScreen(state: _state, appVersion: kAppVersion),
                  SettingsScreen(state: _state),
                ];
                return Scaffold(
                  body: IndexedStack(index: _tab, children: pages),
                  bottomNavigationBar: NavigationBar(
                    selectedIndex: _tab,
                    onDestinationSelected: (i) {
                      setState(() => _tab = i);
                      if (i == 1) {
                        _state.loadUsage();
                      } else if (i == 2) {
                        _state.checkVersion();
                      }
                    },
                    destinations: const [
                      NavigationDestination(
                          icon: Icon(Icons.chat_bubble_outline),
                          label: '聊天'),
                      NavigationDestination(
                          icon: Icon(Icons.bar_chart), label: '用量'),
                      NavigationDestination(
                          icon: Icon(Icons.system_update), label: '版本'),
                      NavigationDestination(
                          icon: Icon(Icons.settings), label: '设置'),
                    ],
                  ),
                );
              },
            ),
    );
  }
}
