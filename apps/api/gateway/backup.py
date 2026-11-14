"""Database backup / restore for the gateway (Stage F).

SQLite (local dev) is fully implemented and tested: online backup via
the ``sqlite3`` backup API (safe while the server runs), SHA-256
manifest, retention pruning, and a restore path that verifies
integrity + row counts before reporting success.

PostgreSQL (production) is command + documentation level only: this
module builds the exact ``pg_dump`` / ``pg_restore`` commands and can
run them when ``pg_dump`` exists, but there is no PostgreSQL server or
``pg_dump`` binary on the local dev machine, so the PG path is
explicitly NOT verified locally — see docs/BACKUP_RESTORE.md. Nothing
here pretends otherwise.

Security notes:
- Backup files are chmod 0600 and live in a 0700 directory; the
  manifest records only filenames, sizes and SHA-256 hashes — never
  key material. (Backups are NOT encrypted at rest in v1; encrypting
  them is recorded as follow-up work in docs/SECURITY.md.)
- Restore refuses to overwrite a non-empty target DB unless
  ``force=True`` is passed explicitly, and never restores a backup
  onto itself.
- Database passwords never appear in a command line: pg_dump reads
  ``PGPASSWORD`` from the environment.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "manifest.json"
BACKUP_PREFIX = "pag-backup-"
DEFAULT_RETENTION_DAYS = 30
DEFAULT_RETENTION_COUNT = 30


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_backup_dir(backup_dir: str | None, db_url: str | None = None) -> Path:
    """Where backups live.

    Explicit ``BACKUP_DIR`` wins. Otherwise a SQLite file DB gets a
    ``backups/`` sibling directory next to the DB file; anything else
    falls back to ``./data/backups``.
    """
    if backup_dir:
        return Path(backup_dir).expanduser()
    if db_url and db_url.startswith("sqlite:///"):
        db_path = db_url[len("sqlite:///"):]
        if db_path != ":memory:":
            return Path(db_path).expanduser().parent / "backups"
    return Path("data/backups")


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _manifest_path(backup_dir: Path) -> Path:
    return backup_dir / MANIFEST_NAME


def read_manifest(backup_dir: Path) -> list[dict]:
    """Backup manifest entries, newest first. Missing/corrupt manifest
    degrades to a directory scan (entries without a hash are flagged
    ``sha256: null`` and cannot be integrity-verified on restore)."""
    manifest_file = _manifest_path(backup_dir)
    entries: list[dict] = []
    if manifest_file.exists():
        try:
            data = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(data, list):
                entries = [e for e in data if isinstance(e, dict)]
        except (ValueError, OSError):
            entries = []
    if not entries:
        for f in sorted(backup_dir.glob(BACKUP_PREFIX + "*.db"), reverse=True):
            entries.append({
                "filename": f.name,
                "created_at": None,
                "db_kind": "sqlite",
                "size_bytes": f.stat().st_size,
                "sha256": None,
                "source": None,
            })
        return entries
    entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return entries


def _write_manifest(backup_dir: Path, entries: list[dict]) -> None:
    tmp = backup_dir / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, _manifest_path(backup_dir))


def _table_row_counts(db_path: Path) -> dict[str, int]:
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


def create_sqlite_backup(
    db_path: str | Path,
    backup_dir: str | Path,
    *,
    retention_days: int | None = None,
    retention_count: int | None = None,
    source: str | None = None,
) -> dict:
    """Online SQLite backup. Returns the manifest entry for the backup.

    Uses the sqlite3 backup API (consistent snapshot even while the
    server is writing). The file is chmod 0600; the manifest is
    updated atomically; old backups are pruned by age then count.
    Raises FileNotFoundError if the source DB does not exist.
    """
    db_path = Path(db_path).expanduser()
    if not db_path.exists():
        raise FileNotFoundError(f"database file not found: {db_path}")
    backup_dir = _ensure_dir(Path(backup_dir).expanduser())
    # Read the manifest BEFORE writing the new backup file: when no
    # manifest exists, read_manifest falls back to a directory scan,
    # and a just-written file would otherwise be scanned in as a
    # phantom duplicate entry.
    entries = read_manifest(backup_dir)
    stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    name = f"{BACKUP_PREFIX}{stamp}-{secrets.token_hex(3)}.db"
    target = backup_dir / name
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.chmod(target, 0o600)
    entry = {
        "filename": name,
        "created_at": _utcnow().isoformat(),
        "db_kind": "sqlite",
        "size_bytes": target.stat().st_size,
        "sha256": _sha256_file(target),
        "source": source or str(db_path),
        "row_counts": _table_row_counts(target),
    }
    entries.append(entry)
    entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    pruned = prune_entries(entries, retention_days, retention_count)
    for old in pruned:
        try:
            (backup_dir / old["filename"]).unlink(missing_ok=True)
        except OSError:
            pass
    _write_manifest(backup_dir, entries)
    return entry


def prune_entries(
    entries: list[dict],
    retention_days: int | None = None,
    retention_count: int | None = None,
) -> list[dict]:
    """Remove entries older than retention_days, then beyond
    retention_count (newest kept). Mutates `entries` in place and
    returns the removed ones. A None limit means 'no limit'."""
    removed: list[dict] = []
    if retention_days is not None:
        cutoff = _utcnow().timestamp() - retention_days * 86400
        keep = []
        for e in entries:
            created = e.get("created_at")
            try:
                ts = datetime.fromisoformat(created).timestamp() if created else 0
            except ValueError:
                ts = 0
            if ts and ts < cutoff:
                removed.append(e)
            else:
                keep.append(e)
        entries[:] = keep
    if retention_count is not None and len(entries) > retention_count:
        entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
        removed.extend(entries[retention_count:])
        del entries[retention_count:]
    return removed


def restore_sqlite(
    backup_path: str | Path,
    target_path: str | Path,
    *,
    force: bool = False,
    expected_sha256: str | None = None,
) -> dict:
    """Restore a SQLite backup file to `target_path` and verify it.

    Refuses to overwrite an existing non-empty target unless
    ``force=True``. Verification: SHA-256 (when an expected hash is
    given), ``PRAGMA integrity_check`` == ``ok``, ``PRAGMA
    foreign_key_check`` empty, and per-table row counts. Returns a
    verification report; raises ValueError on any failed check.
    """
    backup_path = Path(backup_path).expanduser()
    target_path = Path(target_path).expanduser()
    if not backup_path.exists():
        raise FileNotFoundError(f"backup file not found: {backup_path}")
    if backup_path.resolve() == target_path.resolve():
        raise ValueError("refusing to restore a backup onto itself")
    if expected_sha256:
        actual = _sha256_file(backup_path)
        if actual != expected_sha256:
            raise ValueError(
                f"backup SHA-256 mismatch: expected {expected_sha256}, got {actual}"
            )
    if target_path.exists() and target_path.stat().st_size > 0 and not force:
        raise ValueError(
            f"target {target_path} already exists and is non-empty; "
            "pass force=True to overwrite"
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(backup_path, target_path)
    os.chmod(target_path, 0o600)
    conn = sqlite3.connect(target_path)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"integrity_check failed: {integrity}")
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise ValueError(f"foreign_key_check violations: {fk_violations}")
    finally:
        conn.close()
    counts = _table_row_counts(target_path)
    return {
        "ok": True,
        "backup": backup_path.name,
        "target": str(target_path),
        "sha256": _sha256_file(target_path),
        "integrity": "ok",
        "foreign_key_violations": 0,
        "row_counts": counts,
    }


# ---------------------------------------------------------------- PostgreSQL
def _split_db_password(database_url: str) -> tuple[str, str | None]:
    """Split a database URL into (url_without_password, password).

    The password must NEVER travel on a command line (visible in
    ``ps``): pg_dump/pg_restore get the clean URL in argv and the
    password via the ``PGPASSWORD`` environment variable instead.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(database_url)
    password = parsed.password
    if password is None:
        return database_url, None
    host = parsed.hostname or ""
    if parsed.port:
        host += f":{parsed.port}"
    user = parsed.username or ""
    netloc = f"{user}@{host}" if user else host
    clean = urlunparse(parsed._replace(netloc=netloc))
    return clean, password


def pg_dump_command(database_url: str, output_path: str | Path) -> list[str]:
    """The pg_dump command for a PostgreSQL backup.

    Custom format (``-Fc``) + file output. The database password is
    NEVER part of the command: pg_dump reads ``PGPASSWORD`` from the
    environment (or .pgpass). The caller must set it, never log it.
    """
    clean_url, _ = _split_db_password(database_url)
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--file",
        str(output_path),
        clean_url,
    ]


def pg_restore_command(database_url: str, backup_path: str | Path) -> list[str]:
    clean_url, _ = _split_db_password(database_url)
    return [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--dbname",
        clean_url,
        str(backup_path),
    ]


def run_pg_dump(
    database_url: str, output_path: str | Path, *, timeout_s: float = 600.0
) -> dict:
    """Run pg_dump if the binary exists. Returns a result dict; when
    pg_dump is absent (local dev has no PostgreSQL tooling) the result
    says so honestly instead of faking a backup."""
    if shutil.which("pg_dump") is None:
        return {
            "ok": False,
            "error": "pg_dump_not_available",
            "detail": "pg_dump binary not found on this machine; "
            "PostgreSQL backup must run on the server (see docs/BACKUP_RESTORE.md)",
            "command": pg_dump_command(database_url, output_path),
        }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _, password = _split_db_password(database_url)
    run_env = dict(os.environ)
    if password is not None:
        # Password travels via environment, never argv (see above).
        run_env["PGPASSWORD"] = password
    proc = subprocess.run(
        pg_dump_command(database_url, output_path),
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=run_env,
    )
    if proc.returncode != 0:
        from .logsafe import redact

        return {
            "ok": False,
            "error": "pg_dump_failed",
            "detail": redact((proc.stderr or "").strip())[-500:],
            "command": pg_dump_command(database_url, output_path),
        }
    os.chmod(output_path, 0o600)
    return {
        "ok": True,
        "db_kind": "postgres",
        "filename": output_path.name,
        "size_bytes": output_path.stat().st_size,
        "sha256": _sha256_file(output_path),
    }
