# Personal AI Gateway — 状态与证据

## 仓库（GitHub，公开）

- 仓库：**https://github.com/fafa920q-hue/Personal-AI-Gateway**，
  公开库，2026-11-14 05:58 建好（初始提交 807b2bf，仅 README.md，
  连接器已验证可读）。本地项目以它为准；分支模型 main 稳定 /
  develop 开发整合 / feature/* 新功能 / vX.Y.Z Tag 正式发布。
- 推送方式：GitHub 连接器 snapshot push（快照提交，不携带本地提交
  历史；本地仓库保留完整历史）。GitHub App 无 workflows 权限，
  `.github/workflows/` 文件不能经 API 推送，须用浏览器网页编辑器创建。

## 环境实测（2026-11-14 05:50 CST，本地）

- Node v24.22.1，Python 3.12.3，git 2.43.0
- docker：未安装；psql：未安装
- 磁盘：144G 空闲；CPU：4 核；内存：7.7 GiB（空闲约 133 MiB）
- 结论：本地用 FastAPI/Next.js 直跑 + SQLite（仅开发）；PostgreSQL +
  Alembic 仍为生产路径；Docker Compose 部署验证只能在目标服务器或
  有 Docker 的环境做。

## 服务器环境检测（只读，2026-11-14 05:53 CST）

见 `docs/SERVER_ENV.md`：Ubuntu 24.04.5、Docker 29.1.3、Compose 2.40.3、
磁盘 47G 可用、内存 6.5G 可用；80/443 已被 nginx 占用（网关不得盲目绑定）；
7 容器全 Up。待解决：ubuntu 用户无权直接访问 docker.sock（部署前须确认
sudo 或 docker 组成员身份），部署前先备份。

## 阶段记录

### A — 环境检查与项目初始化

- 仓库：`~/workspace/personal-ai-gateway`，git init，main 分支
- 交付：`README.md`、`.gitignore`、`docs/ARCHITECTURE.md`、
  `docs/PLAN.md`、`docs/STATUS.md`（本文件）、`docs/DNS.md`、
  `docs/OPENAI_BUDGET.md`、`.env.example`
- 架构第一原则与五条优先级已记入 `ARCHITECTURE.md`

## 明确阻塞项（不得绕过、不得伪造）

1. **真实 OpenAI API 密钥没有。** 严禁复用其他对话/截图里出现过的
   密钥（那些已泄露）。真实模型验证、真实 Codex 测试都等主聊天通过
   安全流程拿到用户提供的新密钥后再做。
2. **服务器 SSH 访问已打通（2026-11-14 05:53，主聊天验证）。**
   Muse 公钥已加入 ubuntu 的 authorized_keys（原有 huohua 密钥未动）；
   直连验证成功（hostname `ip-172-31-18-252`，up 4 天 8 小时）。
   关键细节：本机 ssh 默认找 `/root/.ssh`，必须显式用
   `-i /home/hatch/.ssh/id_ed25519`（HOME=/home/hatch 但 ssh 按
   passwd 取 /root）——以后上服务器都用这个参数。
   服务器现状：7 个容器全 Up（dy-portal-web/scheduler healthy，
   douyin-web、login-desktop、douyin-scheduler、mihomo、
   dy-family-network-xui-1）；部署网关时必须与它们共存、不得干扰。
   阶段 H 仍按门禁：测试全过才部署，部署前先做服务器环境检测
   （端口、磁盘、Docker、现有 443 占用）并先备份。
3. **DNS 记录未创建。** `ai.fafa888.uk` A 记录由主聊天负责（见 `DNS.md`）。
4. **本地无 Docker/PostgreSQL。** Compose 构建与容器健康检查本地
   无法验证，记为受限项。
5. **原生 IPA 待 CI 验证。** 本机无 Xcode，本地编不出真 IPA；
   用户已确认自签（交付未签名包，用户用已有侧载方式自签安装）。
   构建验证在 CI macOS runner 上做，结论如实记录在
   `docs/IPA_EVALUATION.md`；分发走 GitHub Releases；PWA 先行，不等 IPA。
6. **桌面应用方案待评估。** Windows .exe + macOS .dmg 同一套代码，
   优先评估 Tauri（轻量、多平台、自带更新器），决定后写明理由；
   范围先对齐聊天 + 模型切换 + 设置。服务端职责已定（统一中转、
   模型管理、历史聊天、设备同步、鉴权、更新信息），同步方式与
   版本信息接口见 `docs/ARCHITECTURE.md` §13。
   【2026-11-14 05:55 更新：Tauri 方向已被用户定的 Flutter 路线取代，
   见第 7 条。】
7. **最终技术路线（2026-11-14 用户定）。** Flutter 做 iOS/Windows/
   macOS 三端客户端（`apps/flutter`，共用代码）、Next.js 做网页聊天
   与管理后台、FastAPI 做独立中转、PostgreSQL 同步记录/设置/用量、
   GitHub Actions 自动编译 IPA/EXE/DMG 与服务端镜像、GitHub Releases
   集中发布、Docker Compose + Caddy 部署与 HTTPS。一次源码更新经
   工作流分别生成安装包，网页和服务器测试通过后部署更新，移动和
   桌面端从 Releases 取对应版本。Flutter SDK 本机未安装（`which
   flutter dart` 无结果，`~/flutter`、`/opt/flutter`、`/usr/lib/flutter`
   均不存在）；官方下载站可达（storage.googleapis.com 清单 HTTP 200），
   SDK 在 Flutter 阶段安装；本地验证以 `flutter analyze` / `flutter
   test` 能跑的部分为主，出包一律走 GitHub Actions。阶段顺序不变：
   网关优先、Codex 真实端到端先行，Flutter 客户端在网关和网页聊天
   可用之后再接。
