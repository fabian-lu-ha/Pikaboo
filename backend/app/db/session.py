from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _apply_migrations() -> None:
    """Lightweight additive migrations for SQLite (ALTER TABLE ADD COLUMN IF NOT EXISTS).

    SQLite does not support IF NOT EXISTS on ALTER TABLE, so we check PRAGMA
    table_info first and only issue the statement when the column is absent.
    Safe to call on every startup — no-ops when the schema is already current.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    # Columns added after the initial create_all, in order of addition.
    _BRANDS_ADDITIVE: list[tuple[str, str]] = [
        ("kanban_connections", "JSON DEFAULT '{}'"),
        ("crm_connections", "JSON DEFAULT '{}'"),
    ]
    _EMAIL_SENDS_ADDITIVE: list[tuple[str, str]] = [
        ("html_body", "TEXT"),
    ]
    with engine.connect() as conn:
        existing = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(brands)")).fetchall()
        }
        for col, col_def in _BRANDS_ADDITIVE:
            if col not in existing:
                conn.execute(
                    text(f"ALTER TABLE brands ADD COLUMN {col} {col_def}")
                )
        # email_sends may not exist on a fresh DB — create_all runs after this
        # function, so PRAGMA returns empty if the table is missing. The for-
        # loop is a no-op in that case and create_all builds the full schema.
        existing_email_sends = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(email_sends)")
            ).fetchall()
        }
        if existing_email_sends:
            for col, col_def in _EMAIL_SENDS_ADDITIVE:
                if col not in existing_email_sends:
                    conn.execute(
                        text(
                            f"ALTER TABLE email_sends ADD COLUMN "
                            f"{col} {col_def}"
                        )
                    )
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
