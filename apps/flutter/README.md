# apps/flutter — Flutter 三端客户端（iOS / Windows / macOS）

一套代码，三个平台：iOS / iPadOS、Windows、macOS 共用同一套界面与
功能代码。网页端见 `apps/web`（Next.js），后端见 `apps/api`（FastAPI）。

## 功能（v0.1.4）

- 账号登录：服务器地址 + 客户端密钥（`pag_sk_…`，Bearer 鉴权），
  “测试连接”调 `GET /v1/models` 真实验证，不造假。
- AI 聊天：`POST /v1/chat/completions` 流式输出（SSE，可中途停止；
  停止后已输出的部分内容也会保存到服务端），非流式备用开关。
- 模型切换：`GET /v1/models` 返回的才是“已验证可用”，不返回的
  模型绝不显示为可用；不写死模型名。
- 历史记录同步：服务端为准。会话与消息全部经
  `/api/v1/chats` 与 `/api/v1/chats/{id}/messages` 读写（见
  `docs/ARCHITECTURE.md` §13.1）；打开与下拉刷新时拉取服务端全量列表。
- Markdown + 代码块（可复制）、按消息显示 token 用量（上游返回时）。
- 用量统计：`GET /api/v1/usage/summary` 的服务端汇总（本密钥），
  价格未配置 / 未获取用量时如实显示，不伪造费用。
- 模型状态：以 `/v1/models` 返回为准。
- 版本检测与更新入口：`GET /api/v1/app/version`（服务端信息源，
  不写死版本、不内置 GitHub PAT）；未配置发布时如实显示“未配置”。
  iOS 显示未签名 IPA 下载入口（用户自签，不静默安装）；Windows /
  macOS 第一阶段为检测 + 下载 + 提示安装。
- 设置中心：服务器地址、密钥、默认模型、浅色/深色主题。
- **不在客户端里的东西**：管理后台（模型验证、密钥创建/撤销）、
  上游 OpenAI 密钥（客户端永远不存）。

## Flutter SDK（已安装，固定版本）

- **Flutter 3.50.0 stable，Dart 3.14.0**（2026-11-11 发布，
  revision `ab2912035e`；tarball SHA-256 已校验，见
  `docs/STATUS.md` 阶段 C 记录）。安装在 `~/flutter`，不在 PATH
  里——每次用前执行：
  `export PATH="$HOME/flutter/bin:$PATH"`。
  以 root 运行会有 "trying to run flutter as root" 提示，不影响使用。
- Flutter 3.50 下 `package:flutter/material.dart` 已弃用，本项目
  改用 `package:material_ui/material_ui.dart`。
- Linux 工具链：本机已装 clang / ninja / CMake / GTK / libsecret
  （apt）。一处虚拟机怪癖：`libzstd1` 的 `+hatch1` 变体与
  `libzstd-dev` 冲突，需先降级到 Ubuntu 官方 1.5.5 构建，GTK 才能装上。
- `flutter doctor`：Flutter / Proxy / Connected device / Network ✓；
  Android 工具链 ✗（无 Android SDK，预期内——三端包走 GitHub
  Actions）；Chrome ✗（无 Chrome，本地不跑 web）。

## 本地运行与测试（均已实测通过，见 `docs/STATUS.md`）

```bash
export PATH="$HOME/flutter/bin:$PATH"
cd apps/flutter
flutter analyze            # No issues found, exit 0
flutter test               # 24 passed, exit 0
flutter run -d linux       # Linux 桌面运行（另需显示服务）
flutter build linux --debug  # 本地 Linux 构建成功
```

集成测试（对 mock 网关实测，MOCK ONLY，绝无真实 OpenAI 调用）：

```bash
# 仓库根目录；无显示服务的机器上需 xvfb-run -a
xvfb-run -a scripts/run_integration_test.sh   # All tests passed, exit 0
```

脚本启动 `apps/api/gateway/dev_mock_server.py`（mock 上游，临时
SQLite 库 + 新种子客户端密钥 + 一个 mock 验证模型），跑
`flutter test integration_test`（登录 → 列模型 → 建会话 → 流式
发送 → 两端消息经 API 核实已落库服务端），随后停掉服务器。
网关全套 pytest：`./.venv/bin/pytest tests/ -q` → 36 passed。

## 未验证项（不得谎称已验证）

- iOS / macOS / Windows **安装包本地没有编过**（本机无 Xcode、
  无 Windows 工具链），出包一律走 GitHub Actions（步骤 5 的工作流），
  结论以 CI 为准；任何未经真机/真电脑安装测试的结果都只记
  “仅构建验证”。
- 全部验证用的都是 **Mock 上游**：模型“可用”是 mock 验证，
  真实 OpenAI 密钥仍没有，真实模型验证与真实 Codex 测试继续阻塞
  （见 `docs/STATUS.md` 明确阻塞项）。
- 增量同步、删除 tombstone、离线队列尚未实现（见
  `docs/ARCHITECTURE.md` §13.1）：当前是打开/刷新时拉服务端全量，
  删除为服务端硬删除。
