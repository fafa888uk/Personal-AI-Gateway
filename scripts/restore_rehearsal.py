#!/usr/bin/env python3
"""Restore rehearsal for Personal AI Gateway (Stage F).

Real backup -> loss/corruption -> restore -> verify, on an ISOLATED
test database only. Never touches data/dev.db, never touches any
production data, never needs a network or a real OpenAI key.

Steps (all inside a fresh temp dir, removed at the end):
  1. Build a fresh SQLite DB (init_db + seed): admin account, 1 client
     key, 2 models (1 verified), 1 pricing rule, 2 usage records,
     1 chat session + 2 messages, 1 audit event.
  2. Record per-table row counts + spot values (model name, key hash,
     message content).
  3. Phase A (loss): back up, DELETE the DB file, restore, verify
     integrity + row counts + spot values.
  4. Phase B (corruption): back up again, overwrite the DB file with
     garbage, restore with force, verify again.
  5. Print a numbered PASS/FAIL log and exit 0 only if every check
     passed. The temp dir is deleted afterwards; the printed log is
     the evidence (also recorded in docs/BACKUP_RESTORE.md).

Usage: python3 scripts/restore_rehearsal.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from gateway import backup as backup_mod  # noqa: E402
from gateway.auth import generate_client_key, hash_client_key  # noqa: E402
from gateway.config import Settings  # noqa: E402
from gateway.db import init_db  # noqa: E402
from gateway.models import (  # noqa: E402
    AuditEvent,
    ChatMessage,
    ChatSession,
    ClientKey,
    ModelRegistry,
    PricingRule,
    UsageRecord,
)

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    CHECKS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def _counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            t: conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            for t in tables
        }
    finally:
        conn.close()


def _spot_values(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        model = conn.execute(
            "SELECT canonical_name FROM model_registry "
            "WHERE verification_status='available' ORDER BY id LIMIT 1"
        ).fetchone()
        key_hash = conn.execute(
            "SELECT key_hash FROM client_keys ORDER BY id LIMIT 1"
        ).fetchone()
        msg = conn.execute(
            "SELECT content FROM chat_messages ORDER BY id LIMIT 1"
        ).fetchone()
        admin = conn.execute(
            "SELECT username FROM admin_accounts ORDER BY id LIMIT 1"
        ).fetchone()
        return {
            "model": model[0] if model else "",
            "key_hash": key_hash[0] if key_hash else "",
            "message": hashlib.sha256((msg[0] if msg else "").encode()).hexdigest()[:16],
            "admin": admin[0] if admin else "",
        }
    finally:
        conn.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="pag-restore-rehearsal-"))
    print(f"rehearsal dir (isolated, deleted at end): {tmp}")
    try:
        db_path = tmp / "rehearsal.db"
        backup_dir = tmp / "backups"
        settings = Settings(
            openai_api_key="mock-key-not-real",
            database_url="",
            database_url_dev=f"sqlite:///{db_path}",
            admin_username="admin",
            admin_password="rehearsal-admin-pass-1",
            admin_key="rehearsal-admin-key",
            candidate_models=["gpt-5.4-mini", "gpt-5.4-nano"],
        )
        print("step 1: build isolated test DB and seed data")
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
            s.add(UsageRecord(trace_id="rehearsal-1", client_key_id=key_id,
                              model="gpt-5.4-mini", tokens_in=100, tokens_out=50,
                              cost_usd=0.0002, cost_status="exact"))
            s.add(UsageRecord(trace_id="rehearsal-2", client_key_id=key_id,
                              model="gpt-5.4-mini", tokens_in=200, tokens_out=80,
                              cost_usd=0.0004, cost_status="exact"))
            sess = ChatSession(client_key_id=key_id, title="rehearsal chat",
                               model="gpt-5.4-mini")
            s.add(sess)
            s.flush()
            s.add(ChatMessage(session_id=sess.id, role="user",
                              content="rehearsal: hello, gateway"))
            s.add(ChatMessage(session_id=sess.id, role="assistant",
                              content="rehearsal: hello back", tokens_in=12,
                              tokens_out=7))
            s.add(AuditEvent(kind="rehearsal_seed", detail="seeded"))
            s.commit()
        before_counts = _counts(db_path)
        before_spot = _spot_values(db_path)
        check("seeded DB has expected rows",
              before_counts.get("usage_records") == 2
              and before_counts.get("chat_messages") == 2
              and before_counts.get("client_keys") == 1
              and before_counts.get("admin_accounts") == 1,
              f"counts={before_counts}")
        print(f"  seed: client_key_id={key_id} key_prefix={raw_key[:12]}...")

        print("step 2: phase A — backup, DELETE the DB file, restore")
        entry_a = backup_mod.create_sqlite_backup(db_path, backup_dir, source="rehearsal-A")
        print(f"  backup file: {entry_a['filename']} sha256={entry_a['sha256'][:16]}... "
              f"size={entry_a['size_bytes']} bytes")
        check("backup manifest lists the backup",
              any(e["filename"] == entry_a["filename"]
                  for e in backup_mod.read_manifest(backup_dir)))
        db_path.unlink()
        check("DB file deleted (simulated loss)", not db_path.exists())
        report_a = backup_mod.restore_sqlite(
            backup_dir / entry_a["filename"], db_path,
            expected_sha256=entry_a["sha256"],
        )
        check("phase A restore integrity ok", report_a["integrity"] == "ok")
        check("phase A row counts match pre-loss",
              report_a["row_counts"] == before_counts,
              f"restored={report_a['row_counts']}")
        check("phase A spot values match pre-loss",
              _spot_values(db_path) == before_spot,
              f"spot={_spot_values(db_path)}")

        print("step 3: phase B — backup, CORRUPT the DB file, force-restore")
        entry_b = backup_mod.create_sqlite_backup(db_path, backup_dir, source="rehearsal-B")
        with open(db_path, "r+b") as f:
            f.write(b"\x00" * 4096)
            f.truncate(4096)
        try:
            _counts(db_path)
            corrupted = False
        except Exception:
            corrupted = True
        check("DB file is actually unreadable after corruption", corrupted)
        try:
            backup_mod.restore_sqlite(backup_dir / entry_b["filename"], db_path)
            refused = False
        except ValueError:
            refused = True
        check("restore without --force refuses a non-empty target", refused)
        report_b = backup_mod.restore_sqlite(
            backup_dir / entry_b["filename"], db_path, force=True,
            expected_sha256=entry_b["sha256"],
        )
        check("phase B restore integrity ok", report_b["integrity"] == "ok")
        check("phase B row counts match pre-corruption",
              report_b["row_counts"] == before_counts)
        check("phase B spot values match pre-corruption",
              _spot_values(db_path) == before_spot)

        print("step 4: retention pruning on the rehearsal manifest")
        entries = backup_mod.read_manifest(backup_dir)
        removed = backup_mod.prune_entries(entries, retention_days=None, retention_count=1)
        check("prune to newest 1 keeps 1 entry and drops the older",
              len(entries) == 1 and len(removed) == 1,
              f"kept={entries[0]['filename']}")

        failed = [c for c in CHECKS if not c[1]]
        print(f"rehearsal result: {len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
        return 0 if not failed else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        print("rehearsal dir removed.")


if __name__ == "__main__":
    raise SystemExit(main())
