# Personal AI Gateway — 个人 AI 中转站

Private, single-admin OpenAI-compatible AI gateway. Independent project:
no connection to FAFA ONE or any other project.

- Web chat (Next.js + TypeScript + Tailwind)
- API gateway (Python 3 + FastAPI + httpx) proxying the official OpenAI API
- PostgreSQL + SQLAlchemy + Alembic (production); SQLite for local dev only
- Caddy reverse proxy, Docker Compose deployment
- Domain: `ai.fafa888.uk` (A record -> 3.12.156.80, to be created by the owner)

See `docs/ARCHITECTURE.md` and `docs/PLAN.md`.
Status: Stage A (init) — see `docs/STATUS.md` for per-stage evidence.
