# 客户端覆盖 — 四个平台与更新方式

> 用户 2026-11-14 定：四个平台的交付形式与更新方式。
> 网关优先的阶段顺序不变（B → C → D → …）。

## 1. 四个平台（交付形式与更新方式）

| 平台 | 交付形式 | 更新方式 | 入口 |
|---|---|---|---|
| iPhone / iPad | `.ipa` 安装包（未签名，用户自签） | 去 GitHub Releases 下载新版 IPA，自己重新签名安装 | 见 §2 |
| Windows 电脑 | `.exe` 安装程序 | 应用内检测新版本、下载更新包 | 桌面应用（§3） |
| macOS 电脑 | `.dmg` 安装包 | 应用内检测新版本、下载更新包 | 桌面应用（§3） |
| 网页 | 浏览器直接访问 | 服务器部署新版，刷新即可使用 | 网页聊天 + PWA（§4） |

- 四个入口共用同一套网关鉴权和模型配置，模型新增仍只改网关。
- 客户端只存 base URL 和自己的密钥、对模型无硬编码；设备本身
  不存官方 Key。

## 2. iPhone / iPad：.ipa（GitHub Releases + 用户自签）

- 交付物：未签名 IPA（CI 的 macOS runner 上 xcodebuild 无签名编译
  .app 再打包 .ipa；我方不提供签名证书或账号）。
- 分发：GitHub Releases 发布未签名包；更新时用户去 GitHub 下新版
  IPA，自己重新签名安装。
- 自签安装步骤：AltStore / SideStore / ESign 或 Xcode 个人账号自签，
  按用户已有侧载方式写，以实际验证为准（见 `docs/IPA_EVALUATION.md`）。
- 第一版形态（用户 2026-11-14 定 Flutter 路线后调整）：iOS 客户端
  为 **Flutter 客户端**（与 Windows/macOS 共用一套代码），此前
  “WKWebView 壳 + 网页聊天首选”的决定已被 Flutter 路线取代；
  PWA 仍是第一版先行的 iPhone 入口，IPA 不阻塞网关和网页聊天。
- 【2026-11-14 阶段 C 已交付】Flutter 客户端 v0.1.0（`apps/flutter`）：
  登录、流式聊天 + 停止、模型切换、服务端历史同步、用量统计、
  版本检测与更新入口、设置中心。本地验证：`flutter analyze`
  通过、`flutter test` 24 passed、mock 网关集成测试通过
  （见 `docs/STATUS.md` 阶段 C 记录）。IPA 本身仍未编过——出包走
  GitHub Actions（步骤 5），未经真机安装测试前只记“仅构建验证”。

## 3. 桌面与三端客户端：Flutter（Windows .exe + macOS .dmg + iOS .ipa，共用一套代码）

- **技术路线（用户 2026-11-14 定，取代之前桌面端待评估 Tauri 的方向）：**
  Flutter 开发 iOS、Windows、macOS 三端客户端，界面和功能代码
  尽量共用一套（`apps/flutter`）；三端 Flutter 客户端与 Next.js
  网页共用同一套网关 API 和鉴权，界面风格保持一致。
- 构建一律走 GitHub Actions：macOS runner 出 IPA/DMG，Windows
  runner 出 EXE；各 runner 的前置条件（Flutter SDK 版本、Xcode
  版本、Windows 构建工具链）写进 CI 工作流文档，以实际跑通为准。
  本地只验证到 `flutter build linux --debug` 成功 + analyze / test /
  集成测试通过；iOS/macOS/Windows 包本地没编过。
- 版本检测 + 更新包下载做进桌面应用里：启动/定期查服务端版本
  信息接口（见 §5），有新版则提示并下载更新包；分发走
  GitHub Releases。
- 桌面应用范围先对齐：**聊天 + 模型切换 + 设置（连接地址、密钥）**
  即可，不把管理后台全搬进去，除非时间允许。
- 桌面三入口（Flutter 桌面应用、Codex CLI、VS Code 扩展）与网页
  共用同一套网关鉴权（客户端密钥）与模型注册表。

## 4. 网页与 PWA（第一版先行的 iPhone 入口）

- 网页聊天做成 PWA：可添加到主屏幕（`manifest.webmanifest`）、
  离线壳（Service Worker 缓存应用壳，离线显示明确的“离线”状态，
  不假装能聊天）、服务端更新后下次打开自动拿到新版。
- 网页更新方式：服务器部署新版，刷新即可使用。
- 验收：真机 Safari“添加到主屏幕”后可打开、可登录、可发消息；
  服务端发新版后再次打开拿到新版（版本号可见）。
- 【2026-11-14 阶段 D 已交付】Next.js 网页聊天 v0.1.0
  （`apps/web`，见 `docs/STATUS.md` 阶段 D 记录）：登录（网关地址 +
  客户端密钥，`GET /v1/models` 真实校验，凭据只存 localStorage）、
  流式聊天 + Stop、模型切换、服务端历史同步（全量拉取）、Markdown
  GFM + 代码高亮 + 复制、侧栏搜索/重命名/删除、重新生成、编辑重发、
  导出 Markdown/JSON、按消息 token 展示、用量条（美元数字仅
  `cost_status === "ok"` 时显示）、版本横幅（`configured: false`
  时不渲染，有新版时提示刷新）、浅色/深色主题、移动端布局。
  PWA：manifest + SW（`pag-v1`；静态资源缓存优先，`/api` 与导航
  网络优先）+ 180px PNG 图标与 SVG 图标；SW 只在生产环境注册。
  **网页客户端不做的事：没有文件/图片输入**（Phase 2，待真实模型能力
  支持）。管理后台是阶段 E 已实现的独立部分（`/admin/*`，会话登录 +
  CSRF，见 ARCHITECTURE.md §9 与 STATUS.md），与聊天页共用同一 Next.js
  应用但鉴权分离。
  编辑/重新生成只在本地截断（网关无截断端点，被取代的消息仍在
  服务端历史里，重载后可能重新出现——已在 README 与页头注释写明）。
  待办：真实浏览器复核（安装 / 离线 / SW 刷新流程）、192/512 图标、
  `max-h-50` 文本框上限目视确认、VersionBanner 有新版路径实测。

## 5. 更新信息由服务端提供（版本信息接口）

- 桌面应用检测新版本时查服务端的版本信息接口
  （`GET /api/v1/app/version`，返回最新版本号、各平台下载链接、
  SHA-256、更新说明），不要写死在客户端里。
- GitHub Releases 是下载源，服务端是信息源，两者版本号必须一致
  （发版流程：先打 GitHub Release，再更新服务端版本信息；不一致
  时客户端以服务端信息为准并明确提示）。
- 网页/PWA 不走此接口更新（刷新即新版），但页脚/设置页可显示
  服务端版本号以便核对。
