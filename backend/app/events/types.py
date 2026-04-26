class Events:
    CHAT_SUBMITTED = "chat.submitted"

    ONBOARDING_BASICS_SAVED = "onboarding.basics_saved"
    ONBOARDING_SCRAPING = "onboarding.scraping"
    ONBOARDING_SCRAPED = "onboarding.scraped"
    ONBOARDING_VOICE_DISTILLING = "onboarding.voice_distilling"
    ONBOARDING_VOICE_DISTILLED = "onboarding.voice_distilled"
    ONBOARDING_COMPETITORS_SUGGESTING = "onboarding.competitors_suggesting"
    ONBOARDING_COMPETITORS_SUGGESTED = "onboarding.competitors_suggested"
    ONBOARDING_COMPETITOR_ENRICHED = "onboarding.competitor_enriched"
    ONBOARDING_POSTS_FETCHING = "onboarding.posts_fetching"
    ONBOARDING_POSTS_FETCHED = "onboarding.posts_fetched"
    ONBOARDING_STYLE_ANALYZING = "onboarding.style_analyzing"
    ONBOARDING_STYLE_ANALYZED = "onboarding.style_analyzed"
    ONBOARDING_IDENTITY_EXTRACTED = "onboarding.identity_extracted"
    ONBOARDING_ASSET_UPLOADED = "onboarding.asset_uploaded"
    ONBOARDING_REFERENCE_ADDED = "onboarding.reference_added"
    ONBOARDING_REFERENCE_FAILED = "onboarding.reference_failed"
    ONBOARDING_FAILED = "onboarding.failed"
    ONBOARDING_COMPLETED = "onboarding.completed"

    AGENT_STARTED = "agent.started"
    AGENT_STEP = "agent.step"
    AGENT_FAILED = "agent.failed"
    AGENT_PEEC_DATA_FETCHED = "agent.peec_data_fetched"
    AGENT_PEEC_UNAVAILABLE = "agent.peec_unavailable"
    DRAFT_CREATED = "draft.created"
    LIFT_PREDICTED = "lift.predicted"
    CAMPAIGN_BUNDLED = "campaign.bundled"

    COMPETITOR_SURGED = "competitor.surged"
    LINEAR_PR_MERGED = "linear.pr_merged"
    CHATGPT_CITED = "chatgpt.cited"

    VIDEO_STORYBOARD_SUGGESTED = "video.storyboard_suggested"
    VIDEO_CAST_PROPOSED = "video.cast_proposed"
    VIDEO_INGREDIENT_GENERATING = "video.ingredient_generating"
    VIDEO_INGREDIENT_GENERATED = "video.ingredient_generated"
    VIDEO_INGREDIENT_REGENERATED = "video.ingredient_regenerated"
    VIDEO_CAST_BIBLE_LOCKED = "video.cast_bible_locked"
    VIDEO_FRAME_GENERATING = "video.frame_generating"
    VIDEO_FRAME_GENERATED = "video.frame_generated"
    VIDEO_FRAME_STALE = "video.frame_stale"
    IMAGE_EDIT_STARTED = "image.edit_started"
    IMAGE_EDITED = "image.edited"
    IMAGE_EDIT_FAILED = "image.edit_failed"
    # Per-scene Veo clip generation (the production path; replaces
    # frame_generating / frame_generated for clip-based renders)
    VIDEO_SCENE_GENERATING = "video.scene_generating"
    VIDEO_SCENE_GENERATED = "video.scene_generated"
    VIDEO_RENDER_STARTED = "video.render_started"
    VIDEO_RENDERED = "video.rendered"
    VIDEO_RENDER_FAILED = "video.render_failed"

    KANBAN_CONNECTED = "kanban.connected"
    KANBAN_SYNC_STARTED = "kanban.sync_started"
    KANBAN_SYNCED = "kanban.synced"
    KANBAN_FEATURE_SHIPPED = "kanban.feature_shipped"
    KANBAN_FEATURE_IN_FLIGHT = "kanban.feature_in_flight"
    KANBAN_MARKETING_ACTIVE = "kanban.marketing_active"

    AUDIENCE_CRM_CONNECTED = "audience.crm_connected"
    AUDIENCE_IMPORT_STARTED = "audience.import_started"
    AUDIENCE_CUSTOMERS_IMPORTED = "audience.customers_imported"
    AUDIENCE_SEGMENTS_PROPOSING = "audience.segments_proposing"
    AUDIENCE_SEGMENTS_PROPOSED = "audience.segments_proposed"
    AUDIENCE_SEGMENT_SAVED = "audience.segment_saved"
    AUDIENCE_PII_REDACTED = "audience.pii_redacted"
    AUDIENCE_PERSONALIZING = "audience.personalizing"
    AUDIENCE_PERSONALIZED = "audience.personalized"
    AUDIENCE_EMAIL_DISPATCHED = "audience.email_dispatched"
    AUDIENCE_SHOP_EVENT_TRIGGERED = "audience.shop_event_triggered"
    AUDIENCE_SHOP_AUTO_PERSONALIZED = "audience.shop_auto_personalized"

    ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTING = (
        "onboarding.competitor_products_extracting"
    )
    ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTED = (
        "onboarding.competitor_products_extracted"
    )

    PEEC_MCP_CONNECTED = "peec_mcp.connected"
    PEEC_MCP_DISCONNECTED = "peec_mcp.disconnected"
    PEEC_MCP_TOOL_CALLED = "peec_mcp.tool_called"
    PEEC_MCP_FAILED = "peec_mcp.failed"


KNOWN_EVENTS: tuple[str, ...] = tuple(
    v
    for k, v in vars(Events).items()
    if not k.startswith("_") and isinstance(v, str)
)
