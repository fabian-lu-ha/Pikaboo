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
        ("voice_model_id", "TEXT"),
        ("voice_model_status", "TEXT DEFAULT 'idle'"),
        ("voice_adapter_url", "TEXT"),
        ("voice_corpus_meta", "JSON DEFAULT '{}'"),
        # Per-provider OAuth-shaped credentials (Instagram, etc). Stored as a
        # nested JSON map keyed by provider. Access tokens are present here
        # but are NEVER returned by any API response — strip in serialization.
        ("social_connections", "JSON DEFAULT '{}'"),
        # Tavily research snapshot — see Brand.research column comment.
        ("research", "JSON DEFAULT '{}'"),
        # Hard policy envelope for LLM-generated offers — see policy_validator.py.
        ("offer_policy", "JSON DEFAULT '{}'"),
    ]
    _EMAIL_SENDS_ADDITIVE: list[tuple[str, str]] = [
        ("html_body", "TEXT"),
    ]
    _CAMPAIGNS_ADDITIVE: list[tuple[str, str]] = [
        ("target_kind", "TEXT"),
        ("target_id", "TEXT"),
        ("trigger", "TEXT"),
        ("status", "TEXT DEFAULT 'draft'"),
        ("description", "TEXT"),
        ("offer_id", "TEXT"),
    ]
    _SEGMENTS_ADDITIVE: list[tuple[str, str]] = [
        ("offer_policy_override", "JSON DEFAULT '{}'"),
        # Feature-usage segmentation columns — see Segment model comments.
        ("feature_focus", "TEXT"),
        ("feature_stats", "JSON DEFAULT '{}'"),
    ]
    # Columns added to ``storyboards`` so a storyboard's full restorable
    # state survives reload — frames (with image_url/clip_url), narrative,
    # bookends, aspect, and the post-render artifacts. Brand model already
    # has its own additive list above; this is the storyboard equivalent.
    _STORYBOARDS_ADDITIVE: list[tuple[str, str]] = [
        ("aspect", "TEXT"),
        ("narrative", "JSON DEFAULT '{}'"),
        ("title_card", "JSON"),
        ("end_card", "JSON"),
        ("frames", "JSON DEFAULT '[]'"),
        ("video_id", "TEXT"),
        ("video_url", "TEXT"),
        ("video_duration_ms", "INTEGER"),
        ("voiced_video_url", "TEXT"),
        # Append-only version history for the improvement loop. Each entry
        # is a JSON dict carrying the storyboard frames + critique + applied
        # mutations for that version. Legacy rows default to []; v1 is
        # auto-recorded on the first successful /render.
        ("versions", "JSON DEFAULT '[]'"),
        # Optional FK to segments.id — set when the storyboard was built
        # for a feature-usage-driven audience segment so the rehydrate
        # path can re-show "this video targets segment X".
        ("segment_id", "TEXT"),
    ]
    # AI-described asset library — Gemini Vision authors a description +
    # tags + cast_kind hint per asset so the planner can pick the right
    # one per cast slot.
    _ASSETS_ADDITIVE: list[tuple[str, str]] = [
        ("description", "TEXT"),
        ("tags", "JSON DEFAULT '[]'"),
        ("description_status", "TEXT DEFAULT 'idle'"),
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
        existing_campaigns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(campaigns)")
            ).fetchall()
        }
        if existing_campaigns:
            for col, col_def in _CAMPAIGNS_ADDITIVE:
                if col not in existing_campaigns:
                    conn.execute(
                        text(
                            f"ALTER TABLE campaigns ADD COLUMN "
                            f"{col} {col_def}"
                        )
                    )
        existing_segments = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(segments)")
            ).fetchall()
        }
        if existing_segments:
            for col, col_def in _SEGMENTS_ADDITIVE:
                if col not in existing_segments:
                    conn.execute(
                        text(
                            f"ALTER TABLE segments ADD COLUMN "
                            f"{col} {col_def}"
                        )
                    )
        existing_storyboards = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(storyboards)")
            ).fetchall()
        }
        if existing_storyboards:
            for col, col_def in _STORYBOARDS_ADDITIVE:
                if col not in existing_storyboards:
                    conn.execute(
                        text(
                            f"ALTER TABLE storyboards ADD COLUMN "
                            f"{col} {col_def}"
                        )
                    )
        existing_assets = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(assets)")
            ).fetchall()
        }
        if existing_assets:
            for col, col_def in _ASSETS_ADDITIVE:
                if col not in existing_assets:
                    conn.execute(
                        text(
                            f"ALTER TABLE assets ADD COLUMN {col} {col_def}"
                        )
                    )
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
