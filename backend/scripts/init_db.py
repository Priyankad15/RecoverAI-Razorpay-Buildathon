"""
Creates all tables defined in app.db.models against the configured database.

Usage:
    cd backend
    python -m scripts.init_db

This is a lightweight schema-bootstrap step for Phase 1. If/when the schema
needs versioned migrations (e.g. via Alembic), that can be introduced in a
later phase without changing the models themselves.
"""

from app.db.models import AuditLog, CustomerHistory, Payment, Policy, RecoveryAttempt  # noqa: F401
from app.db.session import Base, engine


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    print("Database tables created (or already existed).")


if __name__ == "__main__":
    init_db()
