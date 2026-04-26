from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=True)
    description = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    screenshots = Column(JSON, default=list)
    theme_color = Column(String, nullable=True)
    palette = Column(JSON, default=list)
    palette_roles = Column(JSON, default=list)
    identity = Column(JSON, default=dict)
    voice_profile = Column(JSON, default=dict)
    handles = Column(JSON, default=dict)
    product_images = Column(JSON, default=list)
    pasted_posts = Column(Text, nullable=True)
    recent_posts = Column(JSON, default=list)
    style_profile = Column(JSON, default=dict)
    reference_brands = Column(JSON, default=list)
    assets = Column(JSON, default=list)
    profile = Column(JSON, default=dict)
    kanban_connections = Column(JSON, default=dict)
    crm_connections = Column(JSON, default=dict)
    # Per-provider OAuth-shaped credentials — keyed by provider key
    # (e.g. "instagram"). Each entry holds {ig_user_id, username,
    # access_token, token_kind, expires_at, ...}. Access tokens are
    # never returned through the API surface.
    social_connections = Column(JSON, default=dict)
    # Pioneer-AI-trained per-tenant voice model. status moves
    # idle → corpus_building → corpus_built → training → ready (or failed
    # at any step). adapter_url is the live inference endpoint we POST chat
    # completions to once the model is deployed.
    voice_model_id = Column(String, nullable=True)
    voice_model_status = Column(String, nullable=True, default="idle")
    voice_adapter_url = Column(String, nullable=True)
    voice_corpus_meta = Column(JSON, default=dict)
    # Freedom-to-Operate envelope: hard bounds the LLM-generated offers
    # must respect. Missing keys fall back to module-level defaults in
    # services/audience/policy_validator.py.
    offer_policy = Column(JSON, default=dict)
    # Tavily-backed web research snapshot. Refreshed on onboarding and on
    # explicit ``/api/research/refresh`` calls. Shape matches
    # ``BrandResearch.to_dict()``: { fetched_at, queries, sources[], answer,
    # domain, error }. Used as grounding context in agent draft prompts.
    research = Column(JSON, default=dict)
    onboarded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    competitors = relationship(
        "Competitor", back_populates="brand", cascade="all, delete-orphan"
    )
    kanban_cards = relationship(
        "KanbanCard", back_populates="brand", cascade="all, delete-orphan"
    )
    customers = relationship(
        "Customer", back_populates="brand", cascade="all, delete-orphan"
    )
    products = relationship(
        "Product", back_populates="brand", cascade="all, delete-orphan"
    )
    segments = relationship(
        "Segment", back_populates="brand", cascade="all, delete-orphan"
    )


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String, nullable=False)
    url = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    pattern_library = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="competitors")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(String, ForeignKey("brands.id"), nullable=False)
    title = Column(String, nullable=False)
    bundle = Column(JSON, default=dict)
    predicted_lift = Column(Float, nullable=True)
    # 1:1 personalization fields. ``target_kind`` is "customer" | "segment"
    # | None (legacy bundle-style campaigns predate this column). ``trigger``
    # is the reason this campaign exists: cart_abandoned, subscription_lapsed,
    # new_arrival_in_category, manual.
    target_kind = Column(String, nullable=True)
    target_id = Column(String, nullable=True)
    trigger = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")
    description = Column(Text, nullable=True)
    offer_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand")
    touches = relationship(
        "CampaignTouch",
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignTouch.step_index",
    )


class KanbanCard(Base):
    __tablename__ = "kanban_cards"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    board_id = Column(String, nullable=True)
    board_name = Column(String, nullable=True)
    column = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    labels = Column(JSON, default=list)
    due_date = Column(DateTime, nullable=True)
    moved_at = Column(DateTime, nullable=True)
    url = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="kanban_cards")

    __table_args__ = (
        UniqueConstraint(
            "brand_id",
            "provider",
            "external_id",
            name="ux_kanban_card_external",
        ),
    )


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    attributes = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    signup_at = Column(DateTime, nullable=True)
    last_active_at = Column(DateTime, nullable=True)
    total_spend_cents = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="customers")
    events = relationship(
        "CustomerEvent",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "brand_id", "provider", "external_id", name="ux_customer_external"
        ),
    )


class CustomerEvent(Base):
    __tablename__ = "customer_events"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = Column(
        String,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String, nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=_now)
    payload = Column(JSON, default=dict)

    customer = relationship("Customer", back_populates="events")


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    sku = Column(String, nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, nullable=False, default=0)
    image_url = Column(String, nullable=True)
    category = Column(String, nullable=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="products")


class Segment(Base):
    __tablename__ = "segments"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    rationale = Column(Text, nullable=True)
    customer_ids = Column(JSON, default=list)
    source = Column(String, nullable=False, default="ai_proposed")
    # Per-segment override of brand.offer_policy. Shallow-merged on top of
    # brand defaults. None / {} means inherit brand policy unchanged.
    offer_policy_override = Column(JSON, default=dict)
    # Feature-usage signals — populated when the segment is built around
    # heavy users of a particular product feature. ``feature_focus`` is
    # the single dominant feature (the visual hero for any video the
    # storyboard planner generates for this segment); ``feature_stats``
    # is the full per-feature event count across the segment's members
    # so the planner can also reference secondary features as supporting
    # context.
    feature_focus = Column(String, nullable=True)
    feature_stats = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="segments")


class EmailSend(Base):
    __tablename__ = "email_sends"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    target_kind = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    html_body = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="queued")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String, nullable=False, default="Untitled Pipeline")
    nodes = Column(JSON, default=list)
    edges = Column(JSON, default=list)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    runs = relationship(
        "PipelineRun",
        back_populates="pipeline",
        cascade="all, delete-orphan",
    )


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id = Column(String, primary_key=True, default=_uuid)
    pipeline_id = Column(
        String,
        ForeignKey("pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    status = Column(String, nullable=False, default="running")
    started_at = Column(DateTime, default=_now)
    finished_at = Column(DateTime, nullable=True)
    node_states = Column(JSON, default=dict)
    logs = Column(JSON, default=list)
    result = Column(JSON, default=dict)
    error = Column(Text, nullable=True)

    pipeline = relationship("Pipeline", back_populates="runs")


class CampaignTouch(Base):
    """One step in a multi-touch campaign sequence.

    ``kind`` is "email" | "video" | "landing". ``content_json`` carries
    the rendered copy (subject/body for email, voiceover_script for video,
    headline/body for landing). ``send_id`` links to the EmailSend row
    once an email touch dispatches; ``render_cache_key`` keys the
    on-demand video render so re-clicks are idempotent.
    """

    __tablename__ = "campaign_touches"

    id = Column(String, primary_key=True, default=_uuid)
    campaign_id = Column(
        String,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_index = Column(Integer, nullable=False)
    kind = Column(String, nullable=False)
    scheduled_at = Column(DateTime, nullable=True)
    content_json = Column(JSON, default=dict)
    send_id = Column(String, ForeignKey("email_sends.id"), nullable=True)
    render_cache_key = Column(String, nullable=True)
    status = Column(String, nullable=False, default="planned")
    sent_at = Column(DateTime, nullable=True)

    campaign = relationship("Campaign", back_populates="touches")


class Offer(Base):
    """A composed product offer bounded by the brand's offer policy.

    Either ``customer_id`` or ``segment_id`` must be set, never both. The
    LLM proposes; ``policy_validator.clamp`` enforces the envelope and
    records each clamped field in ``policy_clamps`` for the trust
    dashboard.
    """

    __tablename__ = "offers"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = Column(
        String,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=True,
    )
    segment_id = Column(
        String,
        ForeignKey("segments.id", ondelete="CASCADE"),
        nullable=True,
    )
    product_ids = Column(JSON, default=list)
    rule_json = Column(JSON, default=dict)
    copy_json = Column(JSON, default=dict)
    policy_clamps = Column(JSON, default=list)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)


class VideoRender(Base):
    """Cache row for on-demand voice+video renders.

    Looked up by ``cache_key = f"{customer_id}:{campaign_id}:{touch_id}"``.
    The same key in two requests returns the same artifact rather than
    triggering a second TTS+mux. ``voice_model_id = NULL`` means the
    default-TTS fallback was used (brand-voice fine-tune not ready).
    """

    __tablename__ = "video_renders"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = Column(
        String, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id = Column(
        String, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    touch_id = Column(
        String,
        ForeignKey("campaign_touches.id", ondelete="CASCADE"),
        nullable=False,
    )
    cache_key = Column(String, nullable=False, unique=True)
    voice_model_id = Column(String, nullable=True)
    script_text = Column(Text, nullable=True)
    audio_url = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="queued")
    error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)


class Storyboard(Base):
    """Cast bible + director's cinematic brief + voiceover spec for a single
    marketing-video plan, persisted across process restarts.

    A storyboard is the recurring-asset bible the director defines for one
    video: which characters, settings, props, and products must stay
    consistent across all shots; the lensing/lighting/grade brief every shot
    inherits; and the voiceover spec for the final mux. Cast members can be
    expensive (each `needs_generation` ingredient burns one nano-banana-pro
    call) so they MUST survive uvicorn hot reload, deploys, and crashes —
    losing them mid-flow strands the user with a half-rendered storyboard
    they have to redo from scratch.

    The three JSON columns mirror what `CastRegistry` used to keep in-memory:

      - cast: dict[cast_id, CastMember]. CastMember = {id, kind, role,
        description, narrative_purpose, neutral_pose_hint, binding,
        canonical_url}. canonical_url is filled in once the ingredient
        sheet is generated (or right away for brand_asset bindings).
      - cinematic_brief: dict with reference_films, lensing, lighting,
        palette_grade, pacing, do_not. Threaded into every Veo /scene
        prompt so all shots share one auteur look.
      - voiceover: dict with script, voice_persona, voice_name. Read by
        /voiceover when muxing audio onto the silent render.

    brand_id is nullable for now (post_suggest doesn't plumb it through),
    but the FK is in place for the natural future query "show me every
    storyboard for this brand" without a column-rename migration.
    """

    __tablename__ = "storyboards"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String,
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    cast = Column(JSON, default=dict)
    cinematic_brief = Column(JSON, default=dict)
    voiceover = Column(JSON, default=dict)
    # Optional segment this storyboard targets. When set, the planner
    # threads the segment's feature_focus through cinematic_brief, frame
    # prompts, and voiceover script — different segments → different ad
    # spots even when they share the same campaign.
    segment_id = Column(
        String,
        ForeignKey("segments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Full restorable storyboard state — added so the frontend can survive a
    # page reload (or process restart) without re-running /suggest. Each is
    # set at the appropriate step:
    #   /suggest  → narrative, title_card, end_card, aspect, frames (initial)
    #   /frame    → frames[i].image_url   (in-place via update_frame)
    #   /scene    → frames[i].clip_url    (in-place via update_frame)
    #   /render   → video_id, video_url, video_duration_ms
    #   /voiceover→ voiced_video_url
    aspect = Column(String, nullable=True)
    narrative = Column(JSON, default=dict)
    title_card = Column(JSON, nullable=True)
    end_card = Column(JSON, nullable=True)
    frames = Column(JSON, default=list)
    video_id = Column(String, nullable=True)
    video_url = Column(String, nullable=True)
    video_duration_ms = Column(Integer, nullable=True)
    voiced_video_url = Column(String, nullable=True)
    # Append-only version history for the improvement loop. Each entry is
    #   {version_number, frames, video_url, critique, applied_mutations,
    #    created_at}. v1 is auto-recorded on the first /render success;
    # v2+ are produced by /improve. Never rewritten — the UI loads any
    # historical version's frames into the editor for inspection.
    versions = Column(JSON, default=list)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class GeoGap(Base):
    """A single GEO gap: a prompt where the brand is absent but a competitor
    is winning, surfaced from Peec.

    One row per (brand_id, prompt) — re-detecting the same prompt updates
    in place rather than piling duplicates so the dashboard stays clean
    across campaign runs.
    """

    __tablename__ = "geo_gaps"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String,
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    prompt = Column(String, nullable=False)
    competitor_name = Column(String, nullable=True)
    competitor_visibility = Column(Float, nullable=True)
    own_visibility = Column(Float, nullable=True)
    gap_score = Column(Float, nullable=False, default=0.0)
    cited_domains = Column(JSON, default=list)
    engines_present = Column(JSON, default=list)
    source_campaign_id = Column(String, nullable=True)
    detected_at = Column(DateTime, default=_now)
    last_seen_at = Column(DateTime, default=_now, onupdate=_now)
    status = Column(String, nullable=False, default="open")  # open|addressed|dismissed

    __table_args__ = (
        UniqueConstraint("brand_id", "prompt", name="ux_geo_gap_brand_prompt"),
    )


class GeoRecommendation(Base):
    """The agent's proposed action for a single gap.

    ``action_type`` enumerates the playbook the recommender picked from —
    comparison_page | definition_first | faq_schema | stats_quote |
    wikidata_schema | reddit_draft. Confidence is the recommender's own
    score; the user is always shown it so they can reject low-confidence
    proposals.
    """

    __tablename__ = "geo_recommendations"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String,
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gap_id = Column(
        String,
        ForeignKey("geo_gaps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_type = Column(String, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)
    rationale = Column(Text, nullable=True)
    target_engines = Column(JSON, default=list)
    asset_outline = Column(JSON, default=dict)
    status = Column(String, nullable=False, default="proposed")  # proposed|accepted|rejected|generated
    created_at = Column(DateTime, default=_now)


class GeoAsset(Base):
    """Generated GEO content asset: a comparison page, FAQ block, stats
    rewrite, JSON-LD payload, etc. ``body_markdown`` carries human-readable
    drafts; ``body_json`` carries structured payloads (schema, Wikidata
    statements). Either one is set, never both must be.
    """

    __tablename__ = "geo_assets"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String,
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recommendation_id = Column(
        String,
        ForeignKey("geo_recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gap_id = Column(
        String,
        ForeignKey("geo_gaps.id", ondelete="CASCADE"),
        nullable=False,
    )
    action_type = Column(String, nullable=False)
    title = Column(String, nullable=True)
    body_markdown = Column(Text, nullable=True)
    body_json = Column(JSON, default=dict)
    target_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft")  # draft|published
    publish_url = Column(String, nullable=True)
    published_at = Column(DateTime, nullable=True)
    predicted_lift_pct = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_now)


class Asset(Base):
    """Persistent media library — every photo/video the agent generates
    flows through here so the user can reuse it later (re-import an
    ingredient sheet into a new storyboard, drop a rendered scene into a
    different campaign, etc).

    ``kind`` is the broad media type (image|video). ``subkind`` is the
    pipeline stage that produced it (ingredient|frame|scene|render|
    upload) — useful for filtering ("show me only the rendered
    campaigns" vs "show me only the cast sheets I generated"). ``meta``
    is a JSON catch-all so we can record cast_kind, prompt previews,
    aspect ratio, durations, etc without further migrations.
    """

    __tablename__ = "assets"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String,
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String, nullable=False)         # image | video
    subkind = Column(String, nullable=False)      # ingredient | frame | scene | render | upload
    url = Column(String, nullable=False)
    storyboard_id = Column(String, nullable=True, index=True)
    cast_kind = Column(String, nullable=True)     # character | setting | prop | product
    label = Column(String, nullable=True)
    prompt_preview = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    aspect = Column(String, nullable=True)
    meta = Column(JSON, default=dict)
    # AI-authored visual description, populated by services/asset_describe.
    # description = one or two sentences naming concrete subject + setting +
    # lighting; tags = 5-8 single-word entities for filtering / matching;
    # description_status moves idle → pending → ready (or failed). The
    # storyboard planner reads `description` when it picks brand_asset
    # bindings so it can choose the right photo for each cast member.
    description = Column(Text, nullable=True)
    tags = Column(JSON, default=list)
    description_status = Column(String, nullable=True, default="idle")
    created_at = Column(DateTime, default=_now, index=True)

    __table_args__ = (
        UniqueConstraint("brand_id", "url", name="ux_asset_brand_url"),
    )
