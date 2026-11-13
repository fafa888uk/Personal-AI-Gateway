/// Version / update screen: GET /api/v1/app/version on open and on
/// manual tap. Shows per-platform version, release notes and a download
/// link. iOS is explicitly unsigned — the user self-signs; there is no
/// silent install. When the server reports configured:false the screen
/// says "服务端未配置发布信息" and never fakes a version.
library;

import 'package:material_ui/material_ui.dart';
import 'package:url_launcher/url_launcher.dart';

import '../app_state.dart';
import '../models.dart';
import '../sse.dart';

class VersionScreen extends StatelessWidget {
  const VersionScreen({super.key, required this.state, required this.appVersion});

  final AppState state;

  /// This build of the Flutter client (from pubspec.yaml).
  final String appVersion;

  static const _platformNames = {
    'ios': 'iOS',
    'windows': 'Windows',
    'macos': 'macOS',
    'web': '网页版',
  };

  static const _platformNotes = {
    'ios':
        'IPA 为未签名包：下载后请用自己的签名方式安装（如 AltStore / SideStore / 开发者签名）。本应用不提供静默安装。',
    'windows': '下载安装包后手动安装；新版检测到后会提示下载。',
    'macos': '下载 DMG 后手动安装；新版检测到后会提示下载。',
    'web': '网页版随服务端更新，刷新即用，无需安装。',
  };

  Widget _platformCard(
      BuildContext context, String key, PlatformRelease release) {
    final name = _platformNames[key] ?? key;
    final isNewer = compareVersions(release.version, appVersion) > 0;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '$name ${release.version}',
                    style: const TextStyle(
                        fontSize: 16, fontWeight: FontWeight.w600),
                  ),
                ),
                if (isNewer)
                  Chip(
                    label: const Text('有新版'),
                    backgroundColor:
                        Theme.of(context).colorScheme.primaryContainer,
                  )
                else
                  const Chip(label: Text('已是最新')),
              ],
            ),
            if (release.releaseDate != null)
              Text('发布日期：${release.releaseDate}'),
            if (release.releaseNotes != null &&
                release.releaseNotes!.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(release.releaseNotes!),
            ],
            const SizedBox(height: 4),
            Text(_platformNotes[key] ?? ''),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              icon: const Icon(Icons.download, size: 18),
              label: const Text('打开下载链接'),
              onPressed: () async {
                final uri = Uri.tryParse(release.downloadUrl);
                if (uri != null) {
                  await launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              },
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('版本与更新'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            tooltip: '重新检查',
            onPressed: state.checkVersion,
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: state,
        builder: (context, _) {
          final info = state.versionInfo;
          return SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('当前客户端版本：$appVersion'),
                const SizedBox(height: 12),
                if (info == null)
                  const Text('尚未检查版本，请点右上角刷新。')
                else if (!info.configured)
                  const Card(
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: Text('服务端未配置发布信息'),
                    ),
                  )
                else ...[
                  if (info.gatewayVersion != null)
                    Text('网关版本：${info.gatewayVersion}'),
                  const SizedBox(height: 12),
                  for (final entry in info.platforms.entries)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 12),
                      child: _platformCard(context, entry.key, entry.value),
                    ),
                  if (info.platforms.isEmpty)
                    const Text('服务端未提供任何平台的发布信息。'),
                ],
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
