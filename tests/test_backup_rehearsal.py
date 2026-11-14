"""Stage G backup-rehearsal tests — wire the Stage F rehearsal scripts
into the test suite.

Both scripts run ONLY against isolated scratch data (a temp-dir
SQLite DB, resp. a scratch PostgreSQL database + role that the script
creates and drops itself, ``pag_rehearsal_pg``). They never touch
data/dev.db or any production data, and they never need a real OpenAI
key. Each script exits 0 only if every internal check passed, so the
test asserts on the exit code plus the printed PASS summary.

PostgreSQL: the rehearsal needs a local server reachable as the
``postgres`` OS user (``su postgres``) plus pg_dump/pg_restore/psql on
PATH — that is exactly what the script's own pg_available() probes.
If it is not available here the test SKIPS with an explicit reason
and never pretends the PG rehearsal ran.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SQLITE_SCRIPT = REPO_ROOT / "scripts" / "restore_rehearsal.py"
PG_SCRIPT = REPO_ROOT / "scripts" / "restore_rehearsal_pg.py"


def _run(script: Path, timeout_s: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )


def test_sqlite_restore_rehearsal_end_to_end():
    """Real backup -> loss -> restore -> verify, then corruption ->
    force-restore -> verify, on an isolated temp SQLite DB."""
    assert SQLITE_SCRIPT.exists()
    out = _run(SQLITE_SCRIPT, timeout_s=300)
    assert out.returncode == 0, (
        f"restore_rehearsal.py exited {out.returncode}\n"
        f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    )
    assert "FAIL" not in out.stdout, out.stdout
    assert "checks passed" in out.stdout, out.stdout
    assert "rehearsal dir removed." in out.stdout


def _load_pg_module():
    spec = importlib.util.spec_from_file_location(
        "restore_rehearsal_pg", PG_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_postgres_restore_rehearsal_end_to_end():
    """Real pg_dump -> DROP DATABASE -> pg_restore -> verify, on the
    isolated scratch database ``pag_rehearsal_pg`` only.

    Skipped (not faked as passing) when this machine has no local
    PostgreSQL reachable as the postgres OS user.
    """
    assert PG_SCRIPT.exists()
    module = _load_pg_module()
    available, why = module.pg_available()
    if not available:
        pytest.skip(f"PG 不可达，未实跑: {why}")
    assert module.DB_NAME == "pag_rehearsal_pg"
    assert module.ROLE == "pag_rehearsal_pg"
    out = _run(PG_SCRIPT, timeout_s=600)
    assert out.returncode == 0, (
        f"restore_rehearsal_pg.py exited {out.returncode}\n"
        f"stdout:\n{out.stdout}\nstderr:\n{out.stderr}"
    )
    assert "FAIL" not in out.stdout, out.stdout
    assert "checks passed" in out.stdout, out.stdout
    assert "scratch database + role dropped" in out.stdout
