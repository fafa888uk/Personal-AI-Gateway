"""Database engine/session helpers + registry seeding."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import AdminAccount, Base, ModelRegistry


def make_engine(settings: Settings):
    url = settings.effective_database_url
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(url, **kwargs)


def make_session_factory(settings: Settings) -> sessionmaker[Session]:
    return sessionmaker(bind=make_engine(settings), autoflush=False, expire_on_commit=False)


def init_db(settings: Settings) -> sessionmaker[Session]:
    """Create tables if missing and seed the model registry.

    Production uses Alembic migrations for schema changes; create_all here
    is idempotent and only ensures a fresh dev DB is usable.
    """
    factory = make_session_factory(settings)
    engine = factory.kw["bind"]
    # Local SQLite dev DB: make sure the parent directory exists.
    url = settings.effective_database_url
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            os.makedirs(parent, exist_ok=True)
    Base.metadata.create_all(engine)
    with factory() as session:
        seed_registry(session, settings.candidate_models)
        seed_admin(session, settings)
        session.commit()
    return factory


def seed_admin(session: Session, settings: Settings) -> AdminAccount | None:
    """Seed the single admin console account from env, once.

    Only if the admin_accounts table is empty AND ADMIN_PASSWORD is set.
    The password is hashed with Argon2id; plaintext is never stored or
    logged. An existing account is never overwritten or re-hashed.
    """
    from .auth import hash_admin_password

    existing = session.query(AdminAccount).first()
    if existing is not None:
        return None
    if not settings.admin_password:
        return None
    row = AdminAccount(
        username=settings.admin_username or "admin",
        password_hash=hash_admin_password(settings.admin_password),
    )
    session.add(row)
    return row


def seed_registry(session: Session, candidates: list[str]) -> list[ModelRegistry]:
    """Insert candidate models that are not yet in the registry.

    All candidates start as pending/unverified, disabled-visibility-wise:
    they are NOT returned by /v1/models and NOT callable until a real
    verification marks them available.
    """
    created = []
    for order, name in enumerate(candidates):
        existing = (
            session.query(ModelRegistry)
            .filter(ModelRegistry.canonical_name == name)
            .first()
        )
        if existing is not None:
            continue
        pinned = None
        # Pinned-version grouping: "gpt-5.4-2026-03-05" -> group "gpt-5.4".
        parts = name.split("-")
        if len(parts) >= 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
            pinned = "-".join(parts[:-1])
        row = ModelRegistry(
            canonical_name=name,
            aliases=[],
            enabled=True,
            is_default=(order == 0),
            sort_order=order,
            pinned_group=pinned,
            verification_status="pending",
        )
        session.add(row)
        created.append(row)
    return created


def resolve_model(session: Session, name: str) -> ModelRegistry | None:
    """Resolve a client-supplied model name (canonical or alias)."""
    row = (
        session.query(ModelRegistry)
        .filter(ModelRegistry.canonical_name == name)
        .first()
    )
    if row is not None:
        return row
    for candidate in session.query(ModelRegistry).all():
        if name in (candidate.aliases or []):
            return candidate
    return None


def list_verified_models(session: Session) -> list[ModelRegistry]:
    """Only verified-enabled models are visible/callable."""
    return (
        session.query(ModelRegistry)
        .filter(
            ModelRegistry.enabled.is_(True),
            ModelRegistry.verification_status == "available",
        )
        .order_by(ModelRegistry.sort_order, ModelRegistry.canonical_name)
        .all()
    )
