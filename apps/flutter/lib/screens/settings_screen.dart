/// Settings screen: gateway base URL + client key, streaming toggle,
/// test connection, and sign out (clears the stored key).
library;

import 'package:material_ui/material_ui.dart';

import '../app_state.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key, required this.state});

  final AppState state;

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _urlController;
  late final TextEditingController _keyController;
  late bool _streaming;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.state.baseUrl);
    _keyController = TextEditingController(text: widget.state.clientKey);
    _streaming = widget.state.streamingEnabled;
  }

  @override
  void dispose() {
    _urlController.dispose();
    _keyController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_formKey.currentState!.validate()) {
      return;
    }
    await widget.state.saveSettings(
      newBaseUrl: _urlController.text,
      newClientKey: _keyController.text,
      newStreamingEnabled: _streaming,
    );
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('设置已保存')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
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
                  TextFormField(
                    controller: _urlController,
                    decoration: const InputDecoration(
                      labelText: '网关地址',
                      border: OutlineInputBorder(),
                    ),
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
                  const SizedBox(height: 16),
                  SwitchListTile(
                    title: const Text('流式输出'),
                    subtitle: const Text('关闭后使用非流式请求（一次性返回完整回复）'),
                    value: _streaming,
                    onChanged: (v) => setState(() => _streaming = v),
                  ),
                  const SizedBox(height: 16),
                  FilledButton(onPressed: _save, child: const Text('保存设置')),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: state.isTestingConnection
                        ? null
                        : () async {
                            await _save();
                            await state.testConnection();
                          },
                    child: const Text('测试连接'),
                  ),
                  if (state.connectionMessage != null) ...[
                    const SizedBox(height: 16),
                    Text(state.connectionMessage!),
                  ],
                  const SizedBox(height: 32),
                  const Text('存储说明', style: TextStyle(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 8),
                  const Text(
                    '密钥保存在本设备安全存储中（iOS/macOS/Windows 为系统安全存储；'
                    'Linux 开发环境为 ~/.config/personal_ai_gateway/credentials.json，'
                    '0600 权限）。本客户端不提供任何管理功能，不存储管理密钥。',
                  ),
                  const SizedBox(height: 24),
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      foregroundColor: Theme.of(context).colorScheme.error,
                    ),
                    onPressed: () async {
                      final confirm = await showDialog<bool>(
                        context: context,
                        builder: (context) => AlertDialog(
                          title: const Text('退出登录'),
                          content: const Text('将清除本设备保存的客户端密钥。'),
                          actions: [
                            TextButton(
                              onPressed: () =>
                                  Navigator.of(context).pop(false),
                              child: const Text('取消'),
                            ),
                            FilledButton(
                              onPressed: () =>
                                  Navigator.of(context).pop(true),
                              child: const Text('清除并退出'),
                            ),
                          ],
                        ),
                      );
                      if (confirm == true) {
                        await state.clearCredentials();
                      }
                    },
                    child: const Text('退出登录（清除密钥）'),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
