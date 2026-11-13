/// Usage screen: server-side totals for this client key only
/// (GET /api/v1/usage/summary, today + month). Costs are shown exactly
/// as the gateway reports them; a non-"ok" cost status is shown honestly
/// instead of presenting a partial sum as a complete total.
library;

import 'package:material_ui/material_ui.dart';

import '../app_state.dart';
import '../models.dart';

class UsageScreen extends StatelessWidget {
  const UsageScreen({super.key, required this.state});

  final AppState state;

  Widget _summaryCard(BuildContext context, String title, UsageSummary? s) {
    if (s == null) {
      return const Card(child: ListTile(title: Text('尚未加载')));
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title,
                style:
                    const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
            const SizedBox(height: 8),
            Text('请求：${s.requests} 次'),
            Text('输入 tokens：${s.tokensIn}'),
            Text('输出 tokens：${s.tokensOut}'),
            Text('费用：\$${s.costUsd.toStringAsFixed(6)}'),
            Text(
              s.costStatusLabel,
              style: TextStyle(
                color: s.costIsExact
                    ? Theme.of(context).colorScheme.primary
                    : Theme.of(context).colorScheme.error,
              ),
            ),
            if (s.byModel.isNotEmpty) ...[
              const SizedBox(height: 8),
              const Text('按模型', style: TextStyle(fontWeight: FontWeight.w600)),
              for (final row in s.byModel)
                Text(
                  '${row.model}：${row.requests} 次，'
                  '输入 ${row.tokensIn} / 输出 ${row.tokensOut}，'
                  '费用 \$${row.costUsd.toStringAsFixed(6)}',
                ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('用量'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: '刷新',
            onPressed: state.loadUsage,
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: state,
        builder: (context, _) {
          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text('服务端统计，仅统计当前客户端密钥的用量。'),
                const SizedBox(height: 12),
                _summaryCard(context, '今日', state.usageToday),
                const SizedBox(height: 12),
                _summaryCard(context, '本月', state.usageMonth),
                if (state.errorMessage != null) ...[
                  const SizedBox(height: 12),
                  Text(
                    state.errorMessage!,
                    style: TextStyle(
                        color: Theme.of(context).colorScheme.error),
                  ),
                ],
              ],
            ),
          );
        },
      ),
    );
  }
}
