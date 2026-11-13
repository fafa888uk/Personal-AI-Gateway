# apps/flutter — Flutter 三端客户端（占位）

iOS / Windows / macOS 三端客户端，界面和功能代码尽量共用一套。

- 技术路线（用户 2026-11-14 定）：Flutter + Dart。
- 与 Next.js 网页共用同一套网关 API 和鉴权，界面风格保持一致。
- 范围先对齐：聊天 + 模型切换 + 设置（连接地址、密钥）。
- 出包一律走 GitHub Actions（macOS runner 出 IPA/DMG，Windows
  runner 出 EXE），分发走 GitHub Releases；IPA 为未签名包，用户自签。
- 版本检测查服务端版本信息接口（`GET /api/version`），不写死在客户端。

状态：占位。Flutter 客户端在网关（阶段 B）和网页聊天（阶段 D）
可用之后再接；本地尚无 Flutter/Dart SDK（官方下载站可达，SDK 在
Flutter 阶段安装），本地验证以 `flutter analyze` / `flutter test`
能跑的部分为主。
