"""Personal AI Gateway — core API gateway (Stage B).

Lazy re-exports (PEP 562): importing the `gateway` package stays
light — it must NOT pull in `gateway.main` (FastAPI/httpx) — so the
backup CLI (scripts/backup_db.py) also runs with the system Python,
which has no httpx. `gateway.VERSION` / `gateway.create_app` still
resolve on first access.
"""
from __future__ import annotations

__all__ = ["VERSION", "create_app"]


def __getattr__(name: str):
    if name in __all__:
        from .main import VERSION, create_app

        return {"VERSION": VERSION, "create_app": create_app}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
