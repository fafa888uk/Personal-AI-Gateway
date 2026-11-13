/// Chat screen: session list (drawer, server is source of truth),
/// model switcher, streaming messages with Stop, pull-to-refresh.
library;

import 'package:material_ui/material_ui.dart';

import '../app_state.dart';
import '../models.dart';
import '../widgets/message_bubble.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key, required this.state});

  final AppState state;

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final _inputController = TextEditingController();
  final _scrollController = ScrollController();

  AppState get _state => widget.state;

  @override
  void dispose() {
    _inputController.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scrollController.hasClients) {
        _scrollController.animateTo(
          _scrollController.position.maxScrollExtent,
          duration: const Duration(milliseconds: 200),
          curve: Curves.easeOut,
        );
      }
    });
  }

  Future<void> _send() async {
    final text = _inputController.text;
    if (text.trim().isEmpty) {
      return;
    }
    _inputController.clear();
    await _state.sendMessage(text);
    _scrollToBottom();
  }

  Future<void> _renameDialog(ChatSession session) async {
    final controller = TextEditingController(text: session.title);
    final title = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('重命名对话'),
        content: TextField(
          controller: controller,
          decoration: const InputDecoration(labelText: '标题'),
          autofocus: true,
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            child: const Text('保存'),
          ),
        ],
      ),
    );
    if (title != null) {
      await _state.renameSession(session, title.trim());
    }
  }

  Future<void> _deleteDialog(ChatSession session) async {
    final confirm = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('删除对话'),
        content: Text('确定删除「${session.displayTitle}」吗？服务器上的记录也会删除。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirm == true) {
      await _state.deleteSession(session);
    }
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: _state,
      builder: (context, _) {
        final state = _state;
        return Scaffold(
          appBar: AppBar(
            title: Text(state.currentSession?.displayTitle ?? '新对话'),
            actions: [
              if (state.models.isNotEmpty)
                PopupMenuButton<String>(
                  icon: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Flexible(
                        child: Text(
                          state.selectedModelId ?? '',
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const Icon(Icons.arrow_drop_down),
                    ],
                  ),
                  tooltip: '切换模型（仅显示已验证可用模型）',
                  onSelected: (id) => state.selectModel(id),
                  itemBuilder: (context) => [
                    for (final m in state.models)
                      PopupMenuItem<String>(
                        value: m.id,
                        child: Row(
                          children: [
                            Expanded(child: Text(m.id)),
                            if (m.id == state.selectedModelId)
                              const Icon(Icons.check, size: 18),
                          ],
                        ),
                      ),
                  ],
                )
              else
                const Padding(
                  padding: EdgeInsets.only(right: 12),
                  child: Center(child: Text('暂无已验证模型')),
                ),
            ],
          ),
          drawer: Drawer(
            child: SafeArea(
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.add),
                    title: const Text('新对话'),
                    onTap: () {
                      Navigator.of(context).pop();
                      state.newSession();
                    },
                  ),
                  const Divider(),
                  Expanded(
                    child: RefreshIndicator(
                      onRefresh: state.loadSessions,
                      child: ListView.builder(
                        itemCount: state.sessions.length,
                        itemBuilder: (context, i) {
                          final s = state.sessions[i];
                          return ListTile(
                            title: Text(s.displayTitle),
                            selected: state.currentSession?.id == s.id,
                            onTap: () {
                              Navigator.of(context).pop();
                              state.selectSession(s);
                            },
                            trailing: PopupMenuButton<String>(
                              onSelected: (v) {
                                if (v == 'rename') {
                                  _renameDialog(s);
                                } else if (v == 'delete') {
                                  _deleteDialog(s);
                                }
                              },
                              itemBuilder: (context) => const [
                                PopupMenuItem(
                                    value: 'rename', child: Text('重命名')),
                                PopupMenuItem(
                                    value: 'delete', child: Text('删除')),
                              ],
                            ),
                          );
                        },
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          body: Column(
            children: [
              if (state.errorMessage != null)
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(8),
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Row(
                    children: [
                      Expanded(child: Text(state.errorMessage!)),
                      IconButton(
                        icon: const Icon(Icons.close, size: 18),
                        onPressed: state.clearError,
                      ),
                    ],
                  ),
                ),
              Expanded(
                child: state.messages.isEmpty
                    ? const Center(child: Text('输入消息开始聊天'))
                    : RefreshIndicator(
                        onRefresh: () async {
                          final s = state.currentSession;
                          if (s != null) {
                            await state.selectSession(s);
                          }
                        },
                        child: ListView.builder(
                          controller: _scrollController,
                          padding: const EdgeInsets.symmetric(vertical: 8),
                          itemCount: state.messages.length,
                          itemBuilder: (context, i) =>
                              MessageBubble(message: state.messages[i]),
                        ),
                      ),
              ),
              const Divider(height: 1),
              SafeArea(
                child: Padding(
                  padding: const EdgeInsets.all(8),
                  child: Row(
                    children: [
                      Expanded(
                        child: TextField(
                          controller: _inputController,
                          decoration: const InputDecoration(
                            hintText: '输入消息…',
                            border: OutlineInputBorder(),
                          ),
                          minLines: 1,
                          maxLines: 5,
                          onSubmitted: (_) => _send(),
                        ),
                      ),
                      const SizedBox(width: 8),
                      if (state.isStreaming)
                        FilledButton(
                          onPressed: state.stopStreaming,
                          child: const Text('停止'),
                        )
                      else
                        IconButton(
                          icon: const Icon(Icons.send),
                          tooltip: '发送',
                          onPressed: _send,
                        ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
