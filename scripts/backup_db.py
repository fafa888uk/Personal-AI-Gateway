#!/usr/bin/env python3
"""Database backup / restore CLI for Personal AI Gateway (Stage F).

Usage (from the repo root):

    # SQLite backup of the dev DB (or --db PATH):
    python3 scripts/backup_db.py backup [--db PATH] [--dir DIR]
    # List known backups (manifest):
    python3 scripts/backup_db.py list [--dir DIR]
    # Restore a backup into a target DB file (refuses to overwrite a
    # non-empty target unless --force):
    python3 scripts/backup_db.py restore --backup FILE --target PATH [--force]
    # PostgreSQL: print (or --run) the pg_dump command for DATABASE_URL.
    # Needs pg_dump + PGPASSWORD in the environment; never pass a
    # password on the command line, and never paste it here:
    python3 scripts/backup_db.py pg-dump [--url URL] [--out FILE] [--run]

Defaults: --db comes from DATABASE_URL_DEV (or data/dev.db); --dir
defaults to <db-dir>/backups for SQLite, ./data/backups otherwise.
Retention: --retention-days / --retention-count (defaults 30 / 30).
Backup files are chmod 0600; the manifest records only filenames,
sizes and SHA-256 hashes — never key material.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "api"))

from gateway import backup as backup_mod  # noqa: E402
from gateway.config import Settings, load_dotenv  # noqa: E402


def _sqlite_db_path(settings: Settings, override: str | None) -> str:
    if override:
        return override
    url = settings.effective_database_url
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    raise SystemExit(f"not a SQLite database URL: {url}")


def _print(obj: dict) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True))


def main() -> int:
    load_dotenv(".env")
    parser = argparse.ArgumentParser(description="Personal AI Gateway DB backup/restore")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("backup", help="create a SQLite backup now")
    p.add_argument("--db", default=None)
    p.add_argument("--dir", default=None)
    p.add_argument("--retention-days", type=int, default=30)
    p.add_argument("--retention-count", type=int, default=30)

    p = sub.add_parser("list", help="list backups from the manifest")
    p.add_argument("--dir", default=None)
    p.add_argument("--db", default=None)

    p = sub.add_parser("restore", help="restore a SQLite backup (verified)")
    p.add_argument("--backup", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--force", action="store_true",
                   help="overwrite a non-empty target DB")
    p.add_argument("--sha256", default=None,
                   help="expected SHA-256 of the backup file")

    p = sub.add_parser("pg-dump", help="PostgreSQL backup via pg_dump")
    p.add_argument("--url", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--run", action="store_true",
                   help="actually run pg_dump (default: only print the command)")

    args = parser.parse_args()
    settings = Settings.from_env()

    if args.command == "backup":
        db_path = _sqlite_db_path(settings, args.db)
        backup_dir = backup_mod.resolve_backup_dir(
            args.dir or settings.backup_dir or None,
            settings.effective_database_url,
        )
        entry = backup_mod.create_sqlite_backup(
            db_path, backup_dir,
            retention_days=args.retention_days,
            retention_count=args.retention_count,
            source="cli",
        )
        _print({"ok": True, "backup": entry})
        return 0

    if args.command == "list":
        url = settings.effective_database_url
        backup_dir = backup_mod.resolve_backup_dir(
            args.dir or settings.backup_dir or None, url
        )
        kind = "postgres" if url.startswith("postgres") else "sqlite"
        _print({
            "db_kind": kind,
            "backup_dir": str(backup_dir),
            "backups": backup_mod.read_manifest(backup_dir) if backup_dir.exists() else [],
        })
        return 0

    if args.command == "restore":
        try:
            report = backup_mod.restore_sqlite(
                args.backup, args.target,
                force=args.force, expected_sha256=args.sha256,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(f"restore failed: {exc}", file=sys.stderr)
            return 1
        _print(report)
        return 0

    if args.command == "pg-dump":
        url = args.url or settings.database_url
        if not url:
            print("no PostgreSQL DATABASE_URL set (env DATABASE_URL or --url)",
                  file=sys.stderr)
            return 1
        out = args.out or "pag-backup-postgres.dump"
        if not args.run:
            print("Dry run: printing the command only (use --run to execute it).")
            print("Set PGPASSWORD in the environment, never on the command line:")
            print(" ".join(backup_mod.pg_dump_command(url, out)))
            return 0
        result = backup_mod.run_pg_dump(url, out)
        _print(result)
        return 0 if result.get("ok") else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
