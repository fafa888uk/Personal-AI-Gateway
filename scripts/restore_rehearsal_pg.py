#!/usr/bin/env python3
"""PostgreSQL restore rehearsal for Personal AI Gateway (Stage F).

Real pg_dump -> DROP DATABASE -> pg_restore -> verify, on an ISOLATED
scratch database only (``pag_rehearsal_pg`` + a throwaway role of the
same name, both dropped at the end). Never touches the gateway's real
database, never touches data/dev.db, never needs a real OpenAI key.

Requires: a local PostgreSQL server reachable as the ``postgres`` OS
user (``su postgres``), pg_dump/pg_restore/psql on PATH, and the
``psycopg`` driver (apps/api/requirements.txt). If PostgreSQL is not
available on this machine the script prints SKIP and exits 0 — the PG
path is then command + documentation level only (see
docs/BACKUP_RESTORE.md), and nothing here pretends otherwise.

Steps:
  1. Create scratch role + database (random throwaway password, kept
     in memory/env only, never printed).
  2. Alembic upgrade head against the scratch DB (0001 -> 0002 ->
     0003), then seed via the app's own init_db + a few rows.
  3. Record per-table row counts + spot values.
  4. pg_dump -Fc to a temp file (chmod 0600, SHA-256 recorded).
  5. DROP the database, recreate it empty, pg_restore into it.
  6. Verify: alembic version is head, row counts match, spot values
     match, foreign keys hold (checked explicitly).
  7. Drop scratch database + role, remove the dump, unset PGPASSWORD.

Usage: ./.venv/bin/python scripts/restore_rehearsal_pg.py
"""
from __future__ import annotations

import hashlib
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

REPO_ROOT = Path(__file__).resolve().parent.parent
API_DIR = REPO_ROOT / "apps" / "api"
DB_NAME = "pag_rehearsal_pg"
ROLE = "pag_rehearsal_pg"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def su_postgres(sql: str, tmp: Path | None = None) -> subprocess.CompletedProcess:
    """Run SQL as the postgres OS user.

    Statements go through a temp .sql file + ``psql -f``: a single
    ``psql -c`` string wraps everything in one transaction block, and
    DROP/CREATE DATABASE refuse to run inside a transaction.
    """
    if tmp is None:
        tmp = Path(tempfile.mkdtemp(prefix="pag-pg-sql-"))
        cleanup = True
    else:
        cleanup = False
    sql_file = tmp / "rehearsal.sql"
    sql_file.write_text(sql, encoding="utf-8")
    # The file is executed by the postgres OS user: it must own the
    # file (0600, not world-readable — it can contain a throwaway
    # rehearsal password) and the directory must allow traversal.
    import pwd

    try:
        os.chown(sql_file, pwd.getpwnam("postgres").pw_uid, -1)
    except (KeyError, OSError):
        pass
    os.chmod(sql_file, 0o600)
    os.chmod(tmp, 0o711)
    try:
        return run(["su", "postgres", "-c",
                    f"psql -v ON_ERROR_STOP=1 -f {sql_file}"])
    finally:
        if cleanup:
            shutil.rmtree(tmp, ignore_errors=True)


def pg_available() -> tuple[bool, str]:
    for tool in ("pg_dump", "pg_restore", "psql", "su"):
        if shutil.which(tool) is None:
            return False, f"{tool} not found on PATH"
    probe = su_postgres("SELECT 1")
    if probe.returncode != 0:
        return False, "cannot connect as postgres OS user (need local PostgreSQL + su)"
    return True, ""


def main() -> int:
    ok, why = pg_available()
    if not ok:
        print("SKIPPED: PostgreSQL restore rehearsal not possible here:")
        print(f"  {why}")
        print("PG backup remains command + documentation level only.")
        return 0

    tmp = Path(tempfile.mkdtemp(prefix="pag-rehearsal-pg-"))
    password = secrets.token_urlsafe(24)
    url = f"postgresql://{ROLE}:{password}@127.0.0.1:5432/{DB_NAME}"
    env = dict(os.environ, DATABASE_URL=url, PGPASSWORD=password)
    print(f"rehearsal dir (isolated, deleted at end): {tmp}")
    try:
        print("step 1: create scratch role + database")
        r = su_postgres(
            f"DROP DATABASE IF EXISTS {DB_NAME}; "
            f"DROP ROLE IF EXISTS {ROLE}; "
            f"CREATE ROLE {ROLE} LOGIN PASSWORD '{password}' CREATEDB; "
            f"CREATE DATABASE {DB_NAME} OWNER {ROLE};",
            tmp,
        )
        if r.returncode != 0:
            print(r.stdout)
            print(r.stderr, file=sys.stderr)
            return 1
        check("scratch role + database created", True)

        print("step 2: alembic upgrade head + seed via the app stack")
        from gateway import backup as backup_mod  # noqa: E402
        from gateway.auth import generate_client_key, hash_client_key  # noqa: E402
        from gateway.config import Settings  # noqa: E402
        from gateway.db import init_db  # noqa: E402
        from gateway.models import (  # noqa: E402
            AdminAccount, AuditEvent, ChatMessage, ChatSession, ClientKey,
            ModelRegistry, PricingRule, UsageRecord,
        )

        alembic = run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=str(API_DIR), env=env,
        )
        if alembic.returncode != 0:
            print(alembic.stdout)
            print(alembic.stderr, file=sys.stderr)
            return 1
        check("alembic upgrade head on PostgreSQL",
              "0003_admin_auth" in (alembic.stdout + alembic.stderr),
              "0001 -> 0002 -> 0003")

        settings = Settings(
            openai_api_key="mock-key-not-real",
            database_url=url,
            admin_username="admin",
            admin_password="rehearsal-admin-pass-1",
            admin_key="rehearsal-admin-key",
            candidate_models=["gpt-5.4-mini", "gpt-5.4-nano"],
        )
        factory = init_db(settings)
        raw_key = generate_client_key()
        with factory() as s:
            # NOTE: flush the ClientKey first and use its real id for
            # dependent rows. SQLAlchemy only orders INSERTs by ORM
            # relationships, NOT by hardcoded FK values — inserting a
            # child with client_key_id=1 in the same flush as its parent
            # can emit the child INSERT first, which PostgreSQL (correctly)
            # rejects. SQLite only "passed" because it does not enforce
            # FKs by default.
            ck = ClientKey(
                name="rehearsal-client", key_hash=hash_client_key(raw_key),
                allowed_models=["*"], monthly_budget_usd=20.0, enabled=True,
            )
            s.add(ck)
            s.flush()
            key_id = ck.id
            row = s.query(ModelRegistry).filter(
                ModelRegistry.canonical_name == "gpt-5.4-mini").first()
            row.verification_status = "available"
            row.verification_method = "mock-test-only"
            s.add(PricingRule(model="gpt-5.4-mini", input_usd_per_1m=1.0,
                              output_usd_per_1m=2.0))
            s.add(UsageRecord(trace_id="rehearsal-pg-1", client_key_id=key_id,
                              model="gpt-5.4-mini", tokens_in=100, tokens_out=50,
                              cost_usd=0.0002, cost_status="exact"))
            s.add(UsageRecord(trace_id="rehearsal-pg-2", client_key_id=key_id,
                              model="gpt-5.4-mini", tokens_in=200, tokens_out=80,
                              cost_usd=0.0004, cost_status="exact"))
            sess = ChatSession(client_key_id=key_id, title="rehearsal pg chat",
                               model="gpt-5.4-mini")
            s.add(sess)
            s.flush()
            s.add(ChatMessage(session_id=sess.id, role="user",
                              content="rehearsal pg: hello, gateway"))
            s.add(ChatMessage(session_id=sess.id, role="assistant",
                              content="rehearsal pg: hello back", tokens_in=12,
                              tokens_out=7))
            s.add(AuditEvent(kind="rehearsal_seed", detail="seeded"))
            s.commit()

        def snapshot() -> tuple[dict, dict]:
            with factory() as s:
                counts = {
                    "usage_records": s.query(UsageRecord).count(),
                    "chat_messages": s.query(ChatMessage).count(),
                    "client_keys": s.query(ClientKey).count(),
                    "admin_accounts": s.query(AdminAccount).count(),
                }
                msg = s.query(ChatMessage).order_by(ChatMessage.id).first()
                model = s.query(ModelRegistry).filter(
                    ModelRegistry.verification_status == "available").first()
                key = s.query(ClientKey).order_by(ClientKey.id).first()
                spot = {
                    "model": model.canonical_name if model else "",
                    "key_hash": key.key_hash if key else "",
                    "message_sha": hashlib.sha256(
                        (msg.content if msg else "").encode()
                    ).hexdigest()[:16],
                }
            return counts, spot

        before_counts, before_spot = snapshot()
        check("seeded PG DB has expected rows",
              before_counts == {"usage_records": 2, "chat_messages": 2,
                                "client_keys": 1, "admin_accounts": 1},
              f"counts={before_counts}")

        print("step 3: pg_dump (custom format) + record SHA-256")
        dump_path = tmp / "pag-rehearsal-pg.dump"
        result = backup_mod.run_pg_dump(url, dump_path)
        if not result.get("ok"):
            print(result)
            return 1
        check("pg_dump succeeded",
              dump_path.exists() and dump_path.stat().st_size > 0,
              f"size={result['size_bytes']} bytes sha256={result['sha256'][:16]}...")
        check("dump file is 0600", oct(dump_path.stat().st_mode & 0o777) == "0o600")

        print("step 4: DROP the database, recreate empty, pg_restore")
        drop = su_postgres(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{DB_NAME}'; "
            f"DROP DATABASE {DB_NAME}; CREATE DATABASE {DB_NAME} OWNER {ROLE};",
            tmp,
        )
        if drop.returncode != 0:
            print(drop.stdout)
            print(drop.stderr, file=sys.stderr)
            return 1
        check("scratch database dropped + recreated empty", True)
        restore = run(
            backup_mod.pg_restore_command(url, dump_path), env=env,
        )
        if restore.returncode != 0:
            print(restore.stdout)
            print(restore.stderr, file=sys.stderr)
            return 1
        check("pg_restore exit 0", True)

        print("step 5: verify restored data")
        version = run(
            [sys.executable, "-m", "alembic", "current"],
            cwd=str(API_DIR), env=env,
        )
        check("alembic version is head after restore",
              "0003_admin_auth" in version.stdout, version.stdout.strip())
        after_counts, after_spot = snapshot()
        check("row counts match pre-drop", after_counts == before_counts,
              f"restored={after_counts}")
        check("spot values match pre-drop", after_spot == before_spot,
              f"spot={after_spot}")
        fk = run(
            ["su", "postgres", "-c",
             f"psql -d {DB_NAME} -t -c "
             f"\"SELECT COUNT(*) FROM chat_messages m LEFT JOIN chat_sessions s "
             f"ON m.session_id=s.id WHERE s.id IS NULL;\""],
        )
        check("no orphan chat_messages (FK holds)",
              fk.returncode == 0 and fk.stdout.strip() == "0",
              f"orphans={fk.stdout.strip()}")

        failed = [c for c in CHECKS if not c[1]]
        print(f"rehearsal result: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
        return 0 if not failed else 1
    finally:
        su_postgres(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname='{DB_NAME}'; "
            f"DROP DATABASE IF EXISTS {DB_NAME}; DROP ROLE IF EXISTS {ROLE};",
            tmp,
        )
        shutil.rmtree(tmp, ignore_errors=True)
        print("scratch database + role dropped; rehearsal dir removed.")


if __name__ == "__main__":
    raise SystemExit(main())
