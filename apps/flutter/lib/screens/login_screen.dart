/// Login / first-run screen: gateway base URL + client key entry,
/// with a "Test connection" button that calls GET /v1/models and shows
/// the honest result (success, failure with the gateway's real error,
/// or "no verified models yet" — never a fake success).
library;

import 'package:material_ui/material_ui.dart';

import '../app_state.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key, required this.state, required this.onDone});

  final AppState state;
  final VoidCallback onDone;

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _urlController;
  late final TextEditingController _keyController;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.state.baseUrl);
    _keyController = TextEditingController(text: widget.state.clientKey);
  }

  @override
  void dispose() {
    _urlController.dispose();
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _testAndSave({required bool enter}) async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    await widget.state.saveSettings(
      newBaseUrl: _urlController.text,
      newClientKey: _keyController.text,
    );
    final ok = await widget.state.testConnection();
    if (ok && enter && mounted) {
      widget.onDone();
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Personal AI Gateway')),
      body: ListenableBuilder(
        listenable: widget.state,
        builder: (context, _) {
          final state = widget.state;
          return SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  const Text(
                    '连接到你的私人 AI 网关',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  const Text(
                    '密钥只保存在本设备的安全存储中（Linux 开发环境为 0600 权限文件），'
                    '不会上传到任何地方。管理密钥绝不能当作客户端密钥使用。',
                  ),
                  const SizedBox(height: 24),
                  TextFormField(
                    controller: _urlController,
                    decoration: const InputDecoration(
                      labelText: '网关地址',
                      hintText: 'http://127.0.0.1:8000',
                      border: OutlineInputBorder(),
                    ),
                    keyboardType: TextInputType.url,
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) {
                        return '请输入网关地址';
                      }
                      final uri = Uri.tryParse(v.trim());
                      if (uri == null || !uri.hasScheme) {
                        return '请输入带 http:// 或 https:// 的地址';
                      }
                      return null;
                    },
                  ),
                  const SizedBox(height: 16),
                  TextFormField(
                    controller: _keyController,
                    decoration: const InputDecoration(
                      labelText: '客户端密钥',
                      hintText: 'pag_sk_…',
                      border: OutlineInputBorder(),
                    ),
                    obscureText: true,
                    validator: (v) {
                      if (v == null || v.trim().isEmpty) {
                        return '请输入客户端密钥';
                      }
                      if (!v.trim().startsWith('pag_sk_')) {
                        return '客户端密钥应以 pag_sk_ 开头';
                      }
                      return null;
                    },
                  ),
                  const SizedBox(height: 24),
                  if (state.isTestingConnection)
                    const Center(child: CircularProgressIndicator())
                  else ...[
                    FilledButton(
                      onPressed: () => _testAndSave(enter: true),
                      child: const Text('测试连接并进入'),
                    ),
                    const SizedBox(height: 12),
                    OutlinedButton(
                      onPressed: () => _testAndSave(enter: false),
                      child: const Text('仅测试连接'),
                    ),
                  ],
                  if (state.connectionMessage != null) ...[
                    const SizedBox(height: 16),
                    Text(
                      state.connectionMessage!,
                      style: TextStyle(
                        color: state.models.isNotEmpty
                            ? Theme.of(context).colorScheme.primary
                            : Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
