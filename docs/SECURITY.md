# Personal AI Gateway — 安全自查（阶段 F，2026-11-14）

## 访问控制复核

| 边界 | 实现 | 复核结果 |
|---|---|---|
| 客户端密钥 | 只存 SHA-256 摘要；`require_client` 校验 + 停用即 403；管理密钥当客户端密钥用返回 401 | 通过（既有测试覆盖） |
| 管理员会话 | 单管理员，Argon2id；会话令牌只存 SHA-256；HttpOnly SameSite=Lax Cookie，12h 过期；`SESSION_COOKIE_SECURE=true` 时 Secure | 通过 |
| CSRF | 双提交：`X-CSRF-Token` 须与会话 token 及 `pag_csrf` Cookie 一致；全部管理变更操作都要求，登录是唯一例外 | 通过；已逐个核对 9 个变更端点（登录、登出、改密、撤销会话、模型 PATCH/验证、密钥创建/PATCH/撤销/重新生成、设置 PUT、备份创建） |
| 登录限流 | 失败 5 次 / 15 分钟 /（IP + 用户名）→ 429；失败记审计（上限 5 条/窗口，429 路径不写审计行，避免审计表被刷爆） | 通过 |
| 越权路径 | 客户端密钥只能访问自己的会话/用量（他人会话返回 404）；管理接口只认管理员会话或 bearer 管理密钥，两者不互通 | 通过（既有测试覆盖） |
| 上游 URL | 固定 `OPENAI_BASE_URL`（默认 `https://api.openai.com/v1`），请求体无法改目标 | 通过（`upstream.py` 单一来源） |
| CORS | **API 不发任何 CORS 头**：浏览器跨域调用会被浏览器直接拦截。生产部署是 Caddy 同域反代（`ai.fafa888.uk` 上网页与 API 同源），所以不需要 CORS；若将来网页与 API 分域，必须加显式 allowlist 中间件，不得放 `*` | 通过（设计如此，已记录约束） |

## 审计日志覆盖（管理员操作）

全部管理变更操作都记 `audit_events`，含：登录/登出、登录失败、密码修改、会话全部撤销、模型更新/验证、密钥创建/更新/撤销/重新生成、设置更新（含定价规则）、预算超限拦截、备份创建。只读的 GET 不记审计。审计明细只含 id、用户名、字段名、文件名、IP——**不含任何密码、原始密钥、令牌、提示词**（有测试覆盖：失败登录审计行不含密码）。

## 密钥生命周期

| 凭据 | 生成 | 轮换 | 撤销 |
|---|---|---|---|
| 客户端密钥 `pag_sk_…` | 管理后台创建，原始密钥**只返回一次**（响应 + 界面只显示一次） | `POST /api/v1/admin/client-keys/{id}/regenerate`（旧哈希立即失效，新密钥只返回一次） | `POST …/revoke`（行保留 + 审计，密钥停用）或 PATCH `enabled=false` |
| 管理员密码 | 首次启动从 `ADMIN_PASSWORD` 种子一次（Argon2id），之后环境变量不再覆盖 | `POST /api/v1/admin/change-password`（验旧密码，新密码 ≥12 位且与旧的不同；成功后**全部会话失效**，须重新登录） | 改密即撤销全部会话；另有 `POST /api/v1/admin/sessions/revoke-all` |
| 管理 bearer 密钥 | `GATEWAY_ADMIN_KEY` 环境变量；缺失则旧 `/admin/*` 返回 503 | 改环境变量后重启（无接口可改——有意为之，密钥不经过 HTTP） | 同上（改变量 + 重启） |
| 上游 OpenAI 密钥 | 只从环境变量注入服务端，永不发给客户端 | 同上 | 同上 |

原始密钥只在创建/重新生成时返回一次；日志、错误信息、审计、备份清单里都没有原始密钥与完整哈希输入（`key_prefix` 只存前 12 字符作展示用）。

## 日志安全

- 请求日志（`api_request_logs`）与用量记录**不存提示词与请求体**，只存 trace、模型、状态、耗时、token 数、错误类型（设计如此，`record()` 只取显式字段）。
- `gateway/logsafe.py`：`redact()` 脱敏 `pag_sk_…`、`pag_admin_…`、`sk-…`、`Bearer …`、`password=…`、`OPENAI_API_KEY=…` 等；`RedactingFilter` 对 `gateway` logger 的**最终渲染文本**脱敏（格式串与参数分开脱敏会漏网——测试抓到过一次，已修）。
- 日志轮转：默认只走 stdout（生产由容器/journald 接管）；设 `GATEWAY_LOG_FILE` 时加 `RotatingFileHandler`（10 MiB × 5）。
- `seed_dev` 与 `dev_mock_server` 会在 stdout 打印一次测试密钥（本地开发有意为之）；输出不得粘贴进工单/日志/聊天记录。

## 默认配置检查

- `.env` 永不提交（`.gitignore`）；仓库里只有 `.env.example`（占位符，无真实值）；`git ls-files` 密钥扫描干净（测试夹具与开发脚本里的假密钥除外）。
- `SESSION_SECRET` 在 `.env.example` 里是**死配置**（代码里没有任何地方读它），阶段 F 已从模板中删除，避免误导。
- `requirements.txt` 之前缺 PostgreSQL 驱动：`create_engine("postgresql://…")` 会因无驱动直接失败。阶段 F 已补 `psycopg[binary]>=3.2`（已在本机验证可用）。
- 请求体大小上限 20 MiB；上游超时网关强制执行；重试仅流式开始前。
- Docker 镜像：本阶段无 Dockerfile 变更；“密钥不在镜像里”靠 `.env` 不提交 + 密钥只从环境变量注入保证，部署时（阶段 H）须复核镜像层不含 `.env`。

## 依赖漏洞扫描（只报不修大版本，2026-11-14）

- `pip-audit`（`pip-audit 2.10.1`）：**12 个已知漏洞，全部在 pip 24.0 本身**（`PYSEC-2026-1795/1796/2875/2876/196/3721`，修复版本 25.3–26.2）。运行时依赖（fastapi/httpx/pydantic/sqlalchemy/alembic/argon2-cffi/uvicorn/psycopg）**零漏洞**。pip 是安装器、不随应用发布，未改 requirements；升级本机 pip 是运维动作，另行决定。
- `npm audit`（`apps/web`）：**未能运行**——仓库审计端点返回 403 `policy_denied`（`zz_managed_internal_spaces_package_registries`），不是“干净”。需在不受限的网络上重跑。
- `flutter pub audit`：该 Flutter 版本（3.50.0）无此子命令，**未能运行**；Flutter 依赖审计待步骤 5（CI）覆盖。

## 已知限制（诚实记录）

1. **登录限流与速率限制是进程内内存态**：多 worker / 多副本部署时不共享计数。当前部署模型是单实例 uvicorn，可接受；扩容前须改共享存储（Redis/DB）。
2. **管理员会话是固定过期**（12h，不滑动续期）；密码修改与全部撤销是唯一的主动失效路径。
3. **备份文件未加密**，只有 0600/0700 权限保护；备份加密与异地存放是后续工作，阶段 H 部署前须定方案。
4. **管理后台的备份/改密 UI 未做**：本阶段只交付后端接口 + 测试；网页管理控制台的对应页面是后续工作（接口已就绪，见 `apps/api/README.md`）。
5. 旧版 `/admin/budgets` 仍上报**环境变量**预算（未改行为，见任务要求）；`/v1/*` 强制与用量/设置接口已用持久化设置。两者口径不一致是已知项，待后续统一。
6. 审计表无自动清理：保留天数设置（`retention_days`）目前只用于备份剪枝，未接审计/请求日志清理；清理任务是后续工作。
