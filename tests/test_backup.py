"""Stage F backup tests — SQLite backup/restore/prune + PG command safety.

All against isolated temp databases. No real OpenAI key, no network,
no production data. The full backup -> loss/corruption -> restore ->
verify rehearsal also lives in scripts/restore_rehearsal.py (SQLite)
and scripts/restore_rehearsal_pg.py (PostgreSQL) with printed evidence.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path

from conftest import ADMIN_PASSWORD, ADMIN_USERNAME
from gateway import backup as backup_mod
from gateway.models import AuditEvent


def _login(client, username=ADMIN_USERNAME, password=ADMIN_PASSWORD):
    return client.post("/api/v1/admin/login",
                       json={"username": username, "password": password})


def _authed(client):
    r = _login(client)
    assert r.status_code == 200, r.text
    r = client.get("/api/v1/admin/csrf")
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": r.json()["csrf_token"]}


def _db_path(app) -> Path:
    url = app.state.settings.effective_database_url
    assert url.startswith("sqlite:///")
    return Path(url[len("sqlite:///"): ])


def _seed_db(db_path: Path) -> dict[str, int]:
    """A small throwaway DB with a table + rows; returns row counts."""
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany("INSERT INTO t (v) VALUES (?)", [("a",), ("b",), ("c",)])
    conn.commit()
    counts = {"t": conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]}
    conn.close()
    return counts


# ---------------------------------------------------------------- create/list
def test_create_sqlite_backup_writes_manifest_with_hash(tmp_path):
    db = tmp_path / "app.db"
    _seed_db(db)
    entry = backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    target = tmp_path / "backups" / entry["filename"]
    assert target.exists()
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert entry["db_kind"] == "sqlite"
    assert entry["size_bytes"] == target.stat().st_size
    assert entry["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert entry["row_counts"] == {"t": 3}
    listed = backup_mod.read_manifest(tmp_path / "backups")
    assert [e["filename"] for e in listed] == [entry["filename"]]
    manifest = json.loads((tmp_path / "backups" / "manifest.json").read_text())
    assert manifest[0]["filename"] == entry["filename"]


def test_create_backup_missing_db_raises(tmp_path):
    try:
        backup_mod.create_sqlite_backup(tmp_path / "nope.db", tmp_path / "backups")
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError")


def test_manifest_scan_fallback_without_hash(tmp_path):
    db = tmp_path / "app.db"
    _seed_db(db)
    entry = backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    (tmp_path / "backups" / "manifest.json").unlink()
    listed = backup_mod.read_manifest(tmp_path / "backups")
    assert [e["filename"] for e in listed] == [entry["filename"]]
    assert listed[0]["sha256"] is None  # scan cannot verify integrity


def test_resolve_backup_dir_defaults_next_to_sqlite_db(tmp_path):
    db = tmp_path / "sub" / "app.db"
    assert backup_mod.resolve_backup_dir(None, f"sqlite:///{db}") == tmp_path / "sub" / "backups"
    assert backup_mod.resolve_backup_dir("/x/backups", f"sqlite:///{db}") == Path("/x/backups")
    assert backup_mod.resolve_backup_dir(None, "postgresql://u@h/db") == Path("data/backups")


# ---------------------------------------------------------------- restore
def test_restore_after_delete_verifies_counts(tmp_path):
    db = tmp_path / "app.db"
    before = _seed_db(db)
    entry = backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    db.unlink()
    report = backup_mod.restore_sqlite(
        tmp_path / "backups" / entry["filename"], db,
        expected_sha256=entry["sha256"],
    )
    assert report["ok"] and report["integrity"] == "ok"
    assert report["row_counts"] == before
    assert report["sha256"] == entry["sha256"]


def test_restore_refuses_overwrite_without_force(tmp_path):
    db = tmp_path / "app.db"
    _seed_db(db)
    entry = backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    try:
        backup_mod.restore_sqlite(tmp_path / "backups" / entry["filename"], db)
    except ValueError as exc:
        assert "force=True" in str(exc)
        return
    raise AssertionError("expected ValueError")


def test_restore_wrong_sha_and_self_restore_rejected(tmp_path):
    db = tmp_path / "app.db"
    _seed_db(db)
    entry = backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    backup_file = tmp_path / "backups" / entry["filename"]
    try:
        backup_mod.restore_sqlite(backup_file, tmp_path / "restored.db",
                                  expected_sha256="0" * 64)
    except ValueError as exc:
        assert "SHA-256 mismatch" in str(exc)
    else:
        raise AssertionError("expected ValueError for bad sha")
    try:
        backup_mod.restore_sqlite(backup_file, backup_file, force=True)
    except ValueError as exc:
        assert "onto itself" in str(exc)
    else:
        raise AssertionError("expected ValueError for self-restore")


def test_restore_corrupt_db_requires_force(tmp_path):
    db = tmp_path / "app.db"
    _seed_db(db)
    entry = backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    db.write_bytes(b"\x00" * 4096)  # corrupt in place
    try:
        backup_mod.restore_sqlite(tmp_path / "backups" / entry["filename"], db)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError without force")
    report = backup_mod.restore_sqlite(
        tmp_path / "backups" / entry["filename"], db, force=True,
        expected_sha256=entry["sha256"],
    )
    assert report["ok"] and report["row_counts"] == {"t": 3}


def test_prune_by_count_and_age(tmp_path):
    db = tmp_path / "app.db"
    _seed_db(db)
    for _ in range(3):
        backup_mod.create_sqlite_backup(db, tmp_path / "backups", source="test")
    entries = backup_mod.read_manifest(tmp_path / "backups")
    assert len(entries) == 3
    removed = backup_mod.prune_entries(entries, retention_count=1)
    assert len(entries) == 1 and len(removed) == 2
    # Age prune: backdate two entries far into the past.
    entries = backup_mod.read_manifest(tmp_path / "backups")
    assert len(entries) == 3
    entries[1]["created_at"] = "2000-01-01T00:00:00+00:00"
    entries[2]["created_at"] = "2000-01-01T00:00:00+00:00"
    removed = backup_mod.prune_entries(entries, retention_days=30)
    assert len(entries) == 1 and len(removed) == 2


# ---------------------------------------------------------------- PostgreSQL
def test_pg_commands_never_contain_password():
    url = "postgresql://pag_user:s3cret-pw@db.internal:5432/pagdb"
    for cmd in (backup_mod.pg_dump_command(url, "/tmp/x.dump"),
                backup_mod.pg_restore_command(url, "/tmp/x.dump")):
        assert not any("s3cret-pw" in arg for arg in cmd), cmd
        assert any("db.internal" in arg and "pagdb" in arg for arg in cmd), cmd
        assert any("pag_user" in arg for arg in cmd), cmd
    assert backup_mod.pg_dump_command(url, "/tmp/x.dump")[0] == "pg_dump"


def test_pg_dump_reports_missing_binary_honestly(tmp_path):
    import shutil

    if shutil.which("pg_dump") is not None:
        # This machine has pg_dump; run_pg_dump against an unreachable
        # host must fail honestly instead of reporting success.
        result = backup_mod.run_pg_dump(
            "postgresql://u:p@127.0.0.1:1/nodb", tmp_path / "x.dump")
        assert result["ok"] is False
        assert result["error"] in ("pg_dump_failed", "pg_dump_not_available")
        return
    result = backup_mod.run_pg_dump(
        "postgresql://u:p@127.0.0.1:5432/nodb", tmp_path / "x.dump")
    assert result == {
        "ok": False,
        "error": "pg_dump_not_available",
        "detail": "pg_dump binary not found on this machine; "
        "PostgreSQL backup must run on the server (see docs/BACKUP_RESTORE.md)",
        "command": backup_mod.pg_dump_command(
            "postgresql://u:p@127.0.0.1:5432/nodb", tmp_path / "x.dump"),
    }


# ---------------------------------------------------------------- admin API
def test_admin_backups_list_requires_session(client):
    assert client.get("/api/v1/admin/backups").status_code == 401
    headers = _authed(client)
    r = client.get("/api/v1/admin/backups", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["db_kind"] == "sqlite"
    assert r.json()["backups"] == []


def test_admin_backups_create_sqlite_end_to_end(client, app):
    headers = _authed(client)
    r = client.post("/api/v1/admin/backups")
    assert r.status_code == 403  # session but no CSRF
    r = client.post("/api/v1/admin/backups", headers=headers)
    assert r.status_code == 200, r.text
    entry = r.json()["backup"]
    assert entry["db_kind"] == "sqlite"
    assert entry["sha256"]
    db_dir = _db_path(app).parent
    assert (db_dir / "backups" / entry["filename"]).exists()
    listed = client.get("/api/v1/admin/backups", headers=headers).json()
    assert [b["filename"] for b in listed["backups"]] == [entry["filename"]]
    with app.state.session_factory() as s:
        rows = s.query(AuditEvent).filter(
            AuditEvent.kind == "backup_created").all()
    assert len(rows) == 1
    assert entry["filename"] in (rows[0].detail or "")
    # The audit detail must not contain key material.
    assert "pag_sk_" not in (rows[0].detail or "")


def test_admin_backups_create_uses_real_gateway_db(client, app):
    """The backup covers the app's own DB (tables + counts present)."""
    headers = _authed(client)
    r = client.post("/api/v1/admin/backups", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["backup"]["row_counts"]["model_registry"] >= 2
    assert r.json()["backup"]["row_counts"]["admin_accounts"] == 1


def test_backup_cli_runs_with_system_python(tmp_path):
    """The backup CLI must not need the venv: importing `gateway`
    stays light (lazy __init__), so system python3 can run it."""
    import shutil
    import subprocess

    system_python = shutil.which("python3")
    assert system_python and "venv" not in system_python
    repo = Path(__file__).resolve().parent.parent
    out = subprocess.run(
        [system_python, "scripts/backup_db.py", "list",
         "--dir", str(tmp_path / "bk")],
        cwd=str(repo), capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["backups"] == []
    """Exercise scripts/backup_db.py end to end via subprocess."""
    import subprocess
    import sys

    db = tmp_path / "cli.db"
    _seed_db(db)
    repo = Path(__file__).resolve().parent.parent
    env = dict(os.environ, DATABASE_URL_DEV=f"sqlite:///{db}")
    out = subprocess.run(
        [sys.executable, "scripts/backup_db.py", "backup",
         "--db", str(db), "--dir", str(tmp_path / "bk")],
        cwd=str(repo), capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    entry = json.loads(out.stdout)["backup"]
    db.unlink()
    out = subprocess.run(
        [sys.executable, "scripts/backup_db.py", "restore",
         "--backup", str(tmp_path / "bk" / entry["filename"]),
         "--target", str(db), "--sha256", entry["sha256"]],
        cwd=str(repo), capture_output=True, text=True, env=env)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["row_counts"] == {"t": 3}
