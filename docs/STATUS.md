# Personal AI Gateway — 状态与证据

## 仓库（GitHub，公开）

- 仓库：**https://github.com/fafa920q-hue/Personal-AI-Gateway**，
  公开库，2026-11-14 05:58 建好（初始提交 807b2bf，仅 README.md，
  连接器已验证可读）。本地项目以它为准；分支模型 main 稳定 /
  develop 开发整合 / feature/* 新功能 / vX.Y.Z Tag 正式发布。
- 推送方式：GitHub 连接器 snapshot push（快照提交，不携带本地提交
  历史；本地仓库保留完整历史）。GitHub App 无 workflows 权限，
  `.github/workflows/` 文件不能经 API 推送，须用浏览器网页编辑器创建。
- 推送记录：Stage A 快照已推 main，远程提交
  `4327366097844f8f5f22c193ed663e8b95669afc`（2026-11-14 06:00，
  13 文件，已验证为 main HEAD）；`develop` 分支已建在同一提交。
  Stage B 快照已推 main，远程提交
  `a3f4e8a374a5ab3d3243dd1ae0b8347d652454c1`（2026-11-14 06:04，
  32 文件，已验证为 main HEAD，含网关 + 版本接口）。
  Stage C/D/E 快照已推 develop（`7a61b545` / `919ad0df` /
  `2c06762`）。同步记录见仓库外
  `personal-ai-gateway.muse-github-snapshot-sync.json`
  （5 条记录，Stage F 推送后追加第 6 条）。
- 分支说明：Stage B 直接落在本地 main（分支模型建立前的启动例外）；
  从下一阶段起按 feature/* → PR → develop → main 走。

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

### B — 核心 API 网关（2026-11-14 06:00–06:20 CST，本地）

- 交付：`apps/api/`（FastAPI + httpx + Pydantic + SQLAlchemy + Alembic，
  依赖仅此六项，无 LiteLLM/Open WebUI）、`tests/`（Mock 上游 pytest）
- 端点：`GET /api/health`；`GET /v1/models`（仅已验证启用模型，初始为空——
  正确，非 bug）；`POST /v1/responses`、`POST /v1/chat/completions`（原生
  透传，SSE + 非流式）；`GET /v1/responses/{id}`；`POST /v1/responses/{id}/cancel`
  与 `POST /v1/responses/compact` 与 `DELETE /v1/responses/{id}`（三者均经
  官方文档/Codex 资料核实为真实端点后实现，compact 的加密 blob 只透传不解析）
- 模型注册表：`model_registry` 表 + `CANDIDATE_MODELS` 种子，全部以
  `pending` 开始；别名解析、启用/默认/排序/固定版本分组、能力标记、
  验证状态 + 最后验证时间/方式。管理端 `GET /admin/models`、
  `POST /admin/models/{name}/verify`（`mode=real` 发最小真实请求；
  `mode=mock` 仅 `GATEWAY_ALLOW_MOCK_VERIFY=true` 时可用，记为
  `mock-test-only`，绝非真实验证）
- 客户端密钥：`pag_sk_...`，仅存 SHA-256 摘要；每密钥允许模型、每分钟限流、
  并发限制、月预算、启用/停用；`seed_dev` 脚本建测试密钥仅打印一次；
  管理密钥绝不能兼作客户端密钥（当作客户端密钥用返回 401）
- 转发：上游地址固定 `OPENAI_BASE_URL`；未知合法参数原样透传；SSE 按字节
  顺序透传，客户端断开/取消/超时终止上游请求；重试仅流式开始前（最多 2 次，
  按 `Retry-After` + 指数退避）；真实上游状态码/请求 ID/限流头保留；
  401/403/404/429/5xx/网络错误分别处理；不静默降级模型；每请求内部 trace ID；
  超时由网关用 `asyncio.wait_for` 强制执行（不依赖 httpx 传输层超时，
  MockTransport 并不执行 httpx 超时——测试中发现并已修）
- 预算硬停：全局日 $5 / 全局月 $50 / 每客户端月 $20；超限返回 429
  `budget_exceeded` + 审计事件；费用只按真实 usage + `pricing_rules` 计算，
  无 usage 记 `not_obtained`、无价格记 `price_not_configured`，两者都不计入
  预算；价格未配置前预算无法触发（已在 README 写明）
- 日志：`api_request_logs` + `usage_records`（trace、客户端、模型、状态、
  耗时、tokens in/out/cached/reasoning、错误类型），默认不存 prompt 内容
- 迁移：`apps/api/alembic/versions/0001_initial.py`，无 SQLite 专属 SQL；
  本地 SQLite 上 `alembic upgrade head` 已验证通过（0001）
- 本地冒烟：uvicorn 直跑，`GET /api/health` 返回 `ok` + `db: ok`；
  持有效测试密钥 `GET /v1/models` 返回空列表；无密钥调用返回 401
- 测试命令：`cd ~/workspace/personal-ai-gateway && .venv/bin/python -m pytest tests/ -q`
  → **25 passed，exit code 0**（覆盖：正常请求、未授权、未知模型、无权限模型、
  429、超时、上游 5xx、请求取消、SSE 正常结束与中途中断、结构化工具调用、
  Responses 流式与非流式、预算硬停、/v1/models 隐藏未验证模型、别名解析、
  管理端鉴权、Mock 验证开关）
- 未解决/阻塞：
  1. **真实 OpenAI 密钥仍没有**——真实模型验证与真实 Codex 测试继续阻塞。
  2. 预算硬停在价格未配置时无法触发：需在有真实价格后填 `pricing_rules`。
  3. 并发限制（每客户端信号量）已实现但无确定性本地测试（时序敏感），
     仅代码级实现，待 Stage G 集成测试覆盖。
  4. 本地无 Docker/PostgreSQL：Compose 与 PostgreSQL 迁移路径未在本地验证，
     仅 SQLite 验证通过；生产迁移验证留待 Stage H。

### C — Flutter 三端客户端（2026-11-14 06:55–07:45 CST，本地分支 `feature/flutter-client`）

- 提交：`06d40d8`（Stage C 服务端部分：聊天记录 API + 用量汇总，
  migration 0002）与 `04c4d25`（Flutter 客户端：脚手架、应用、
  单元/Widget 测试、mock 网关集成测试，147 文件）。本地分支
  `feature/flutter-client`，从 main `ac62719` 建出；按分支模型走
  feature → PR → develop → main，见仓库说明。
- Flutter SDK：**3.50.0 stable / Dart 3.14.0**（2026-11-11 发布，
  revision `ab2912035e`），tarball SHA-256 校验通过，装在 `~/flutter`
 （不在 PATH，用前 `export PATH="$HOME/flutter/bin:$PATH"`）。
  `flutter doctor`：Flutter / Proxy / Connected device / Network ✓；
  Android 工具链 ✗（无 Android SDK，预期内）、Chrome ✗（无 Chrome）。
  Linux 工具链初版 ✗，已装 clang / ninja / CMake / GTK / libsecret
  修好（一处虚拟机怪癖：`libzstd1` 的 `+hatch1` 变体与 `libzstd-dev`
  冲突，降级到 Ubuntu 官方 1.5.5 后 GTK 装上）。
- 服务端新增（为让“历史同步”真实而非假装，必须有服务端接口才成立）：
  migration `0002_chat_history`（`chat_sessions` / `chat_messages`，
  可移植类型）；`POST/GET/PATCH/DELETE /api/v1/chats`、
  `GET/POST /api/v1/chats/{id}/messages`（按客户端密钥隔离，别人的
  会话返回 404 不泄露）；`GET /api/v1/usage/summary?period=today|month`
  （仅调用方密钥的服务端汇总）。消息内容按设计存在 `chat_messages`
  里（同步存储，可按会话删除）；`api_request_logs` 仍不存 prompt。
  契约见 `docs/ARCHITECTURE.md` §13.1。
- 客户端（`apps/flutter`，v0.1.0）：登录（地址 + 客户端密钥，
  安全存储；iOS/macOS/Windows 用 `flutter_secure_storage`，Linux
  本地开发用 0600 文件 fallback 并已在代码与 README 注明）、聊天
  （Chat Completions 流式 SSE + 停止；停止后部分内容也保存服务端；
  非流式备用）、模型切换（只显示 `/v1/models` 返回的已验证模型）、
  历史同步（服务端全量拉取）、Markdown + 代码复制、按消息 token
  显示、用量统计（服务端汇总）、模型状态、版本检测与更新入口
  （`GET /api/v1/app/version`，未配置时如实显示）、设置中心
  （浅色/深色）。无管理后台功能，客户端不存官方 Key。
- 测试（协调员 2026-11-14 07:45 CST 独立重跑，全部通过）：
  - `cd ~/workspace/personal-ai-gateway && ./.venv/bin/pytest tests/ -q`
    → **36 passed，exit 0**（29 旧 + 7 新增聊天/用量测试）
  - `cd apps/flutter && flutter analyze` → **No issues found，exit 0**
  - `cd apps/flutter && flutter test` → **24 passed，exit 0**
  - `xvfb-run -a scripts/run_integration_test.sh`（mock 网关实测：
    登录 → 列模型 → 建会话 → 流式发送 → 两端消息经 API 核实落库）
    → **All tests passed，exit 0**（另含 Linux 应用构建成功）
  - 测试中发现并修好的真 bug：取消卡在 `await for` 的 `async*` 流
    上永不完成（最小 Dart 复现验证），已改写为显式 StreamController +
    手动取消；停止按钮不再 await cancel，不会再挂住。
  - 两处真实问题已在过程中修复：Flutter 3.50 弃用
    `package:flutter/material.dart`（改用
    `package:material_ui/material_ui.dart`）、`flutter_markdown` 的
    `Element` 与 Flutter 的冲突（经 `package:markdown` 别名）。
- 未验证（不得谎称）：iOS/macOS/Windows 安装包本地没编过（无 Xcode、
  无 Windows 工具链），出包走 GitHub Actions（步骤 5）；未经真机/
  真电脑安装测试的结果只记“仅构建验证”。全部验证均为 Mock 上游，
  真实模型验证与真实 Codex 测试继续阻塞。增量同步、删除 tombstone、
  离线队列未实现（当前为全量拉取 + 服务端硬删除），见
  `docs/ARCHITECTURE.md` §13.1。

### D — 网页聊天（Next.js，2026-11-14 07:55–08:10 CST，本地分支 `feature/web-chat`）

- 提交：`a7f289b`（Stage D 1/3：脚手架——Next.js 应用、网关客户端、
  SSE、PWA 壳）与 `eca93f1`（Stage D 2/3：聊天 UI——流式、Markdown、
  历史、用量、版本提示）。本地分支 `feature/web-chat`，从 main
  `a3f4e8a` 建出；按分支模型走 feature → PR → develop → main。
- 客户端（`apps/web` v0.1.0，Next.js 15.5.29 + React 19 + TypeScript +
  Tailwind v4）：登录页（网关地址 + 客户端密钥，`GET /v1/models`
  真实校验，凭据只存 localStorage）+ 聊天页（侧栏搜索/内联重命名/
  两步删除/移动端抽屉、模型选择器、Markdown GFM + 代码高亮 + 复制、
  流式输出 + Stop（AbortController）、重新生成、编辑重发、导出
  Markdown/JSON、按消息 token 展示、错误卡片 + 重试、用量条、版本
  横幅、浅色/深色主题、移动端布局）。只调网关，不存官方 Key。
- 用量条：今日 + 本月来自 `GET /api/v1/usage/summary`；美元数字
  仅当 `cost_status === "ok"` 时显示，否则只显示状态标签（与
  Flutter 同一口径）。版本横幅：公开 `GET /api/v1/app/version`；
  `configured: false` 时什么都不渲染；服务端 `web` 发行版更新时
  显示版本号 + 说明 + “刷新获取新版”（SW SKIP_WAITING + reload）。
- PWA：`public/manifest.webmanifest`、`public/sw.js`（缓存名
  `pag-v1`；`/_next/static` 与图标缓存优先，`/api` 与导航网络优先，
  绝不提供过期聊天数据；skipWaiting + clients.claim +
  SKIP_WAITING 消息处理）、`public/icon-180.png`（实测 180×180）
  + `public/icon.svg`；SW 只在生产环境注册（`src/app/init.tsx`）。
- 编辑/重新生成诚实说明（已写进 `apps/web/README.md` 与
  `src/app/chat/page.tsx` 页头注释，不改行为）：网关没有截断或
  消息删除端点，编辑/重新生成只在本地截断/替换，新助手回复才
  保存服务端；被取代的消息仍在服务端历史里，全量拉取后（如重载）
  可能重新出现。服务端截断端点是 Stage E/Backlog 工作，不是本阶段。
- 本阶段独立验证（2026-11-14 08:03–08:10 CST，验证代理重跑，
  全部通过，命令与退出码）：
  - `cd apps/web && npm run typecheck` → **exit 0**
  - `cd apps/web && npm test` → **45 passed（7 文件），exit 0**
  - `cd apps/web && npm run lint` → **exit 0**
  - `cd apps/web && npm run build` → **exit 0**（`/` 106 kB、
    `/chat` 208 kB 首屏 JS）
  - `cd ~/workspace/personal-ai-gateway && ./.venv/bin/pytest tests/ -q`
    → **36 passed，exit 0**（网关无改动，回归确认）
  - 生产模式实测（`dev_mock_server.py` 真实网关 + Mock 上游，
    临时种子密钥仅存 `/tmp`，验证后已删除；`npm run start` 端口
    3000）：`/` 200、`/chat` 200、`/manifest.webmanifest` 200
    （合法 JSON）、`/sw.js` 200；`GET /v1/models` 200
    （`gpt-5.4-mini`，mock 已验证）；`POST /api/v1/chats` 201；
    `POST /api/v1/chats/{id}/messages` 201（user）；`POST
    /v1/chat/completions stream:true` 200 `text/event-stream`，
    SSE 增量到达（含 usage 块 prompt 12 / completion 7 / total
    19 与 `[DONE]`）；助手消息以 tokens 12/8 落库，
    `GET .../messages` 200 确认 2 条；`GET /api/v1/usage/summary`
    today/month 均 200（requests 1，`cost_status:
    price_not_configured`，故用量条不显示美元数字——与规则一致）；
    `GET /api/v1/app/version` 无鉴权 200（`configured: false`，
    故版本横幅不渲染）。验证后两个服务器均已停，`/tmp` 密钥文件
    已删，3000/8000 无监听残留。
- 未验证（不得谎称）：浏览器内安装 / 离线 / SW 刷新流程**未验证**
  ——验证代理无 live browser，需真实浏览器复核；`max-h-50`
  文本框上限需目视确认；192/512 图标未做（manifest 的 192 条目
  复用 180px PNG）；VersionBanner 的“有新版”刷新路径未实测
  （mock 报告 `configured: false`）；全部验证均为 Mock 上游，
  真实模型验证与真实 Codex 测试继续阻塞。

### E — 管理后台（2026-11-14 08:15–08:35 CST，本地分支 `feature/admin-backend`）

- 提交：`86cb447`（Stage E 1/3：后端——Argon2id 会话鉴权、
  `/api/v1/admin/*`、迁移 0003、35 个新测试）、`9bcf374`（Stage E 2/3：
  前端——管理控制台 7 个页面 + admin 客户端库 + 14 个新测试，含联调
  归一化修复 + 6 个归一化回归测试）、本文档提交（Stage E 3/3）。
  协调员独立复核后提交；本地分支 `feature/admin-backend`，从 Stage D
  `daa055b` 建出；按分支模型走 feature → develop 快照推送。
- 后端（`apps/api`，FastAPI）：新增 `AdminAccount` / `AdminSession` /
  `SystemSetting` 表 + `ClientKey.client_type` / `key_prefix`，Alembic
  迁移 `0003_admin_auth`（`0001 → 0002 → 0003` 全新 SQLite 库升级验证通过，
  降级到 0002 再升级回 head 亦验证通过；PostgreSQL 兼容性按可移植类型
  构造，未在 PG 上实跑）。单管理员账号：启动时从 `ADMIN_USERNAME` +
  `ADMIN_PASSWORD` 种子一次（Argon2id 哈希，仅表空时；无密码则登录
  503）。`POST /api/v1/admin/login` 设 HttpOnly SameSite=Lax `pag_admin`
  会话 Cookie（12h，`SESSION_COOKIE_SECURE=true` 时 Secure）；失败 5 次 /
  15 分钟 /（IP + 用户名）→ 429；`POST /logout`、`GET /me`、
  `GET /csrf`（双提交：`X-CSRF-Token` 须与会话 token 及 `pag_csrf`
  Cookie 一致，变更加操作缺失即 403；登录是唯一免 CSRF 的变更操作）。
  新规范管理 API `/api/v1/admin/*`：模型中心（列表含 `in_upstream` /
  `upstream_only` / `upstream_reachable`、PATCH、verify 含 cost_warning，
  mock 记 `mock-test-only` 永不记 `real`）、密钥中心（列表不含原始密钥、
  创建/重新生成仅返回一次 `raw_key`、撤销保留行 + 审计）、用量仪表盘
  （today/yesterday/month 聚合：请求/成功率/错误率/平均 + P95 延迟/
  token / 成本 + `exact/not_obtained/price_not_configured` 明细、模型与
  客户端排行、日趋势、错误分布、预算状态 + 告警）、请求诊断（trace
  查询 + 最近请求列表）、设置（全局预算/定价规则/保留天数/版本信息，
  存 `system_settings`）、审计列表。旧 bearer `/admin/*` 端点行为未变
  （verify 逻辑抽为共享 `_verify_model`，行为一致）。
- 前端（`apps/web`，Next.js）：`/admin/login`（401/429/503 映射）、
  `/admin` 总览、`/admin/models`（固定版本分组、状态徽章、启用/默认/
  别名/排序/能力编辑、验证前两步确认并显示费用警告）、`/admin/keys`
  （创建/撤销/重新生成、密钥仅显示一次、连接指南含 base URL + 环境变量
  + Codex 配置）、`/admin/usage`（时段切换、统计卡片、排行、日趋势、
  错误分布、预算告警；成本状态标签：非 exact 一律标为不完整合计）、
  `/admin/diagnostics`（trace 查询 + 最近请求/仅错误过滤）、
  `/admin/settings`（全局预算、定价规则编辑、保留策略、版本信息）。
  共享 `src/lib/admin.ts`（会话 Cookie `credentials: include`、CSRF
  自动获取、登录错误映射、成本标签、verified 判定仅
  `available + real`）。
- 远程推送：Stage E 快照已推远程 `develop`，提交
  `2c067624ca2bf66d470816e9aa2d5eac5086ca4a`（203 个 UTF-8 文件，已验证为
  develop HEAD；37 个二进制文件未进快照——连接器只接受 UTF-8 文本，
  与此前阶段同一已知缺口，步骤 5 处理）。同步记录见仓库外
  `personal-ai-gateway.muse-github-snapshot-sync.json`（第 5 条记录）。
- 协调员联调修复（本阶段关键发现）：后端与前端的响应信封形状不一致，
  前端原样直传会导致管理页空白/崩溃：模型行能力是嵌套 `capabilities`
  而非平铺 `cap_*`；`upstream_only` 是 `[{id}]` 对象而非字符串数组；
  verify 返回 `{model, cost_warning, ...}` 包裹而非模型本身；
  密钥列表是 `{client_keys: [...]}` 而非 `keys`；用量是嵌套 `tokens` /
  `per_model` / `per_client` / `errors` / `budget` 与 `cost_status`
  明细对象而非平铺字段；设置是 `pricing_rules` 与
  `global_daily_usd/global_monthly_usd` 而非 `pricing` /
  `daily_usd/monthly_usd`；请求行是 `client` / `error_type` 而非
  `client_name` / `error`。修复在 `src/lib/admin.ts` 集中做归一化
  （`normalizeAdminModel` / `normalizeUsageStats` /
  `normalizeAdminSettings` / `toBackendSettings` /
  `normalizeAdminRequest`），后端 API 与测试未动；新增 6 个归一化
  回归测试（用真实后端形状的 fixture）。随后用真实网关 + Mock 上游
  做端到端冒烟：登录 200、CSRF 200、建密钥 200（无 CSRF 时 403）、
  mock 验证 200、`/v1/chat/completions` 200（tokens 12/7）、用量聚合
  requests 1 且 `cost_status` 明细为 `price_not_configured: 1`（归一化
  后标签为“价格未配置”，不显示为精确合计）、trace 可查、登出后
  `/me` 401。
- 本阶段独立验证（协调员重跑，全部通过，命令与退出码）：
  - `./.venv/bin/pytest tests/ -q` → **71 passed（36 旧 + 35 新），
    1 warning（既有 Starlette 弃用警告），exit 0**
  - `cd apps/web && npm test` → **65 passed（10 文件；45 旧 + 14 新 +
    6 归一化回归），exit 0**
  - `cd apps/web && npm run typecheck` → **exit 0**
  - `cd apps/web && npm run lint` → **exit 0**
  - `cd apps/web && npm run build` → **exit 0**（7 个 admin 路由均
    预渲染；`/` 与 `/chat` 未动仍可构建）
  - Alembic 全新库 `upgrade head` → `0001 → 0002 → 0003_admin_auth`，
    12 张表齐全；降级 + 再升级验证通过。
- 已知缺口（记入，不谎称完成）：`PUT /settings` 持久化的全局预算
  目前只在用量/设置接口中上报，`/v1/*` 请求时预算强制仍读环境变量
  默认值（按“不改既有端点行为”规则未接线），接线是后续工作；
  迁移的 PostgreSQL 实跑未验证（仅可移植类型构造）；真实浏览器内
  操作管理后台未验证（云端浏览器连不到本机 localhost，推迟到部署后，
  与网页聊天同一口径）。

### F — 安全与备份（2026-11-14 08:36–09:00 CST，本地分支 `feature/security-backup`）

- 提交：（待推送后填写）。本地分支 `feature/security-backup`，从
  Stage E `68ab02a` 建出；按分支模型走 feature → develop 快照推送。
- 预算接线（阶段 E 已知缺口已闭合）：`budgets.resolve_global_budgets`
  读 `system_settings` 持久化值，环境变量为默认值/兜底；非法或负值
  行被忽略、仍用环境变量；`check_budgets`（即 `/v1/*` 强制）改用有
  效值。旧版 `GET /admin/budgets` 未改行为（仍报环境变量值），口径
  不一致记为已知项。
- 管理员凭据轮换：新增 `POST /api/v1/admin/change-password`（验旧
  密码、新密码 ≥12 位且与旧不同、成功后撤销**全部**会话须重新登录）
  与 `POST /api/v1/admin/sessions/revoke-all`；登录失败记审计
  （用户名 + IP，不含密码；429 路径不写审计行，避免审计表被刷爆）。
  全部管理变更操作（9 个变更端点逐个核对）均有 CSRF + 审计。
- 密钥管理：客户端密钥创建/重新生成（只返回一次）/撤销已在阶段 E
  完整；本阶段补管理员凭据轮换与会话撤销；数据库密码永不出现在
  `pg_dump`/`pg_restore` 的 argv 里（剥离后走 `PGPASSWORD`，有测试）。
- 备份：新模块 `apps/api/gateway/backup.py` + CLI
  `scripts/backup_db.py`（`backup/list/restore/pg-dump`，系统
  python3 可跑）+ 管理接口 `GET/POST /api/v1/admin/backups`
  （SQLite 立即备份；PostgreSQL 返回 501 + 命令模板；恢复无 HTTP
  接口，只走 CLI）。备份文件 0600、目录 0700、manifest 记 SHA-256；
  保留按 `retention_days` 设置 + `BACKUP_RETENTION_COUNT`。
- 恢复演练（真实跑过，见 `docs/BACKUP_RESTORE.md`）：SQLite
  `scripts/restore_rehearsal.py` **12/12 通过**（丢失 + 损坏两阶段）；
  PostgreSQL `scripts/restore_rehearsal_pg.py` **11/11 通过**（真实
  PG 16：`pg_dump -Fc` → 删库 → `pg_restore` → 行数/抽查值/外键
  全一致）。演练中发现并修好两个真问题：备份清单幽灵条目、硬编码
  外键值的同批插入顺序（SQLite 因不强制外键才碰巧通过）。
- 日志安全：新模块 `apps/api/gateway/logsafe.py`（`redact()` +
  `RedactingFilter`，对最终渲染文本脱敏；`GATEWAY_LOG_FILE` 时加
  10 MiB × 5 轮转文件日志）；请求日志本来就不存提示词。
- 安全自查（见 `docs/SECURITY.md`）：CORS（API 无 CORS 头，同域
  Caddy 部署才成立）、上游 URL 固定、密钥扫描干净、`.env.example`
  死配置 `SESSION_SECRET` 已删；`pip-audit` 12 漏洞全在 pip 24.0
  本身（运行依赖零漏洞，只报不修）；`npm audit` 因仓库策略 403
  未能运行；`flutter pub audit` 无此子命令。
- 附带修好：`requirements.txt` 缺 PostgreSQL 驱动（`psycopg` 未装
  时 `postgresql://` 引擎建不出），已补 `psycopg[binary]>=3.2`；
  Alembic `0001 → 0002 → 0003` 在真实 PostgreSQL 16 上跑通（含降级
  再升级），“PG 迁移未实跑”缺口至此闭合；`gateway/__init__.py`
  改懒加载，备份 CLI 用系统 python3 也能跑。
- 本阶段独立验证（协调员重跑，全部通过）：
  - `./.venv/bin/pytest tests/ -q` → **102 passed（71 旧 + 31 新），
    1 warning（既有 Starlette 弃用警告），exit 0**
  - `cd apps/web && npm test` → **65 passed，exit 0**（前端未改动，
    回归确认）；`typecheck` / `lint` / `build` 均 exit 0
  - 恢复演练：SQLite 12/12、PostgreSQL 11/11（见上）
- 已知缺口（记入，不谎称完成）：备份文件未加密（只有权限保护）；
  登录限流与速率限制是进程内内存态（多副本部署须改共享存储）；
  管理后台的备份/改密 UI 未做（只有后端接口）；审计表无自动清理；
  `npm audit` 未能运行（仓库策略 403）；生产服务器上的 PG 备份/
  恢复流程未跑过（只有本机演练），阶段 H 须在服务器上再跑一次。

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
4. **本地无 Docker；PostgreSQL 已有并已验证。** 本机实际有
   PostgreSQL 16 在线（5432 端口），阶段 F 已在真实 PG 上跑通
   Alembic 迁移与备份/恢复演练（见阶段 F 记录）。Compose 构建与
   容器健康检查本地仍无法验证，记为受限项。
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
   【2026-11-14 07:45 更新：Flutter 三端客户端已在阶段 C 交付
   （`apps/flutter` v0.1.0，见阶段 C 记录），桌面范围与上述一致；
   安装包仍待 GitHub Actions（步骤 5）验证，本地未编过。】
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
   【2026-11-14 07:45 更新：Flutter SDK 已在阶段 C 安装并验证
   （3.50.0 stable，`~/flutter`；`flutter analyze` / `flutter test` /
   集成测试均已通过，见阶段 C 记录）。出包仍走 GitHub Actions。】
