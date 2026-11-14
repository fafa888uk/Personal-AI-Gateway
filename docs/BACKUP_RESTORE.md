# Personal AI Gateway — 备份与恢复（阶段 F）

## 设计

| 项目 | SQLite（本地开发） | PostgreSQL（生产） |
|---|---|---|
| 备份方式 | `sqlite3` 在线备份 API（服务运行时也可安全备份） | `pg_dump --format=custom --no-owner` |
| 实现 | `apps/api/gateway/backup.py`（`create_sqlite_backup`） | 同模块（`pg_dump_command` / `run_pg_dump`） |
| 清单 | `manifest.json`（文件名、时间、大小、SHA-256、行数） | 同上（`run_pg_dump` 返回的记录可追加进清单） |
| 权限 | 备份文件 0600、备份目录 0700 | 同样 0600 |
| 保留 | 按天数（管理后台 `retention_days`，默认 90）+ 按数量（`BACKUP_RETENTION_COUNT`，默认 30） | 同上 |
| 恢复 | `scripts/backup_db.py restore`（校验后才写目标） | `pg_restore --clean --if-exists` |

- 备份文件**没有加密**（只有文件权限保护）。加密备份是已记录的后续工作（见 `docs/SECURITY.md`）；不要把备份文件发给第三方或放进公开位置。
- 恢复时**不覆盖非空目标库**，除非显式 `--force`；恢复前先校验备份 SHA-256（有清单时）、恢复后校验 `integrity_check`（SQLite）/ 行数与抽查值。恢复**不可以在运行中的网关上通过 HTTP 触发**——没有恢复接口，恢复只走 CLI。
- 数据库密码**永不出现在命令行**：`pg_dump`/`pg_restore` 的 argv 里是去掉密码的 URL，密码只走 `PGPASSWORD` 环境变量（见 `backup._split_db_password`，有测试覆盖）。管理接口的 501 返回里更是只有命令模板，连 URL 都没有。

## 备份位置

- 未设 `BACKUP_DIR` 时：SQLite 备份放在数据库文件旁的 `backups/` 子目录（开发库 `data/dev.db` → `data/backups/`）；PostgreSQL 放在 `./data/backups`。
- `BACKUP_DIR` 环境变量可覆盖；管理接口 `POST /api/v1/admin/backups` 的保留天数取管理后台持久化的 `retention_days` 设置。

## 操作

```bash
# SQLite：立即备份（系统 python3 即可，不需要 venv）
python3 scripts/backup_db.py backup [--db PATH] [--dir DIR]
python3 scripts/backup_db.py list [--dir DIR]

# SQLite：恢复（默认拒绝覆盖非空目标库；--force 才覆盖）
python3 scripts/backup_db.py restore --backup FILE --target PATH [--force] [--sha256 HEX]

# PostgreSQL：只打印命令（干跑）
python3 scripts/backup_db.py pg-dump [--url URL] [--out FILE]
# PostgreSQL：真跑（需本机或服务器上有 pg_dump；密码走 PGPASSWORD 环境变量）
PGPASSWORD='...' python3 scripts/backup_db.py pg-dump --url "$DATABASE_URL" --out /var/backups/pag.dump --run

# 管理接口（需管理员会话 + CSRF）
GET  /api/v1/admin/backups   # 清单
POST /api/v1/admin/backups   # 立即备份 SQLite；PostgreSQL 返回 501 + 命令模板
```

PostgreSQL 恢复（服务器上）：

```bash
# 先停网关（避免恢复过程中有写入），再恢复，最后重启并核对行数
pg_restore --clean --if-exists --dbname "$DATABASE_URL" /var/backups/pag.dump
```

## 恢复演练（真实跑过，有证据）

演练只在隔离的测试库上做，从不碰生产数据与 `data/dev.db`。

### SQLite 演练 — `scripts/restore_rehearsal.py`

2026-11-14 08:43 CST 实跑，**12/12 检查通过**：

- 隔离目录 `/tmp/pag-restore-rehearsal-akh3sl_9`（跑完已删除）。
- 种子：管理员 1、客户端密钥 1、模型 2（1 个已验证）、定价 1、用量 2、会话 1 + 消息 2、审计 1。
- A 阶段（丢失）：备份 `pag-backup-20261114-004343-2aa6b8.db`（90,112 字节，SHA-256 `15c7222b…`）→ 删除 DB 文件 → 恢复 → `integrity_check ok`，11 张表行数与丢失前完全一致，抽查值一致（模型 `gpt-5.4-mini`、密钥哈希 `ab47748a…`、消息摘要 `56d20eacb01e5911`、管理员 `admin`）。
- B 阶段（损坏）：再备份一次 → 把 DB 文件头 4 KiB 写零并截断 → 确认文件确实不可读 → 无 `--force` 的恢复被拒绝 → `--force` 恢复 → 完整性与行数、抽查值再次一致。
- 保留剪枝：清单按数量剪到最新 1 条，旧条目被正确丢弃。

### PostgreSQL 演练 — `scripts/restore_rehearsal_pg.py`

2026-11-14 08:48 CST 实跑，**11/11 检查通过**。本机实际有 PostgreSQL 16 在线（5432 端口），所以 PG 演练是真实跑的，不是命令 + 文档：

- 隔离：临时角色 + 数据库 `pag_rehearsal_pg`（随机口令，只在内存/环境变量里，演练结束已删库删角色）。
- Alembic 在真实 PostgreSQL 16 上 `upgrade head`：`0001 → 0002 → 0003_admin_auth`，12 张表齐全；`downgrade -1` 再 `upgrade head` 也通过（迁移的 PostgreSQL 实跑至此已验证，不再是“未验证”）。
- 种子与 SQLite 演练相同（管理员 1、密钥 1、用量 2、消息 2）。
- `pg_dump -Fc`：33,448 字节，SHA-256 `ae500f9e…`，文件 0600 → `DROP DATABASE` → 空库重建 → `pg_restore` 退出 0。
- 恢复后：`alembic current` 仍是 `0003_admin_auth (head)`；行数与删除前一致；抽查值一致（密钥哈希 `7bb7293e…`、消息摘要 `274d6ec179fd4a4c`）；外键检查 `chat_messages` 孤儿行 0 条。

### 演练中发现并修好的两个真问题

1. **备份清单幽灵条目**（`backup.py`）：`create_sqlite_backup` 先写备份文件、后读 manifest；manifest 缺失时目录扫描会把刚写好的文件当成一条无哈希的“幽灵条目”再叠加一次，导致清单里同一文件出现两次。已改成先读 manifest 再写文件；演练的剪枝检查因此前失败一次（11/12），修后 12/12。
2. **硬编码外键值的同批插入顺序**（演练脚本）：SQLAlchemy 只按 ORM 关系排序 INSERT，硬编码 `client_key_id=1` 的子表行可能先于父表行插入；SQLite 因默认不强制外键“碰巧通过”，PostgreSQL 正确报 `ForeignKeyViolation`。已改成先 flush 父行、取真实 id 再插子行。**网关本身没有这种写法**（`main.py` 里子表行的外键都取已持久化的 `client.id` / 路径参数 `session_id`），此处只修演练脚本。

## 未验证（不得谎称）

- 生产服务器上的 PostgreSQL 备份/恢复流程未跑过（只有本机演练）；阶段 H 部署时须在服务器上再跑一次真实备份 + 恢复核对。
- 备份文件未加密（只有权限保护）；恢复演练用的都是测试数据，未覆盖真实用户数据量下的耗时。
