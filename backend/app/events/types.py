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
    # On-demand Tavily-backed intel for a single competitor — fired when
    # the user opens the watchlist modal (or hits POST /competitors/{id}/intel).
    # source_added streams individual citations as they land so the modal
    # populates progressively rather than waiting for the full bundle.
    COMPETITOR_INTEL_REQUESTED = "competitor.intel_requested"
    COMPETITOR_INTEL_SOURCE_ADDED = "competitor.intel_source_added"
    COMPETITOR_INTEL_COMPLETED = "competitor.intel_completed"
    COMPETITOR_INTEL_FAILED = "competitor.intel_failed"
    COMPETITOR_INTEL_UNAVAILABLE = "competitor.intel_unavailable"
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
    # Fired when scene_gen retries a transient Veo 5xx (UNAVAILABLE etc.).
    # Lets the UI render "retrying 2/4..." instead of looking frozen during
    # exponential backoff. The frame is still generating; this is a heads-up.
    VIDEO_SCENE_RETRYING = "video.scene_retrying"
    VIDEO_RENDER_STARTED = "video.render_started"
    VIDEO_RENDERED = "video.rendered"
    VIDEO_RENDER_FAILED = "video.render_failed"
    # canvas_kinetic backdrop generation (nano-banana-pro). Fires only for
    # the hybrid design template; the regular CSS templates skip this.
    VIDEO_CANVAS_GEN_STARTED = "video.canvas_gen_started"
    VIDEO_CANVAS_GEN_COMPLETED = "video.canvas_gen_completed"
    # AI-decided inter-scene transitions. The planner picks one of:
    #   veo_bridge | match_cut | crossfade
    # for each adjacent (i, i+1) pair. veo_bridge is a 4s Veo clip rendered
    # via first-and-last-frame-to-video; match_cut + crossfade are no-ops
    # at the model level (Remotion handles the cut/blend at composite).
    VIDEO_TRANSITIONS_PLANNING = "video.transitions_planning"
    VIDEO_TRANSITIONS_PLANNED = "video.transitions_planned"
    VIDEO_TRANSITION_GENERATING = "video.transition_generating"
    VIDEO_TRANSITION_GENERATED = "video.transition_generated"
    VIDEO_TRANSITION_FAILED = "video.transition_failed"
    # Voiceover lifecycle — fired by the /voiceover endpoint when the user
    # adds (or replaces) a Gemini-TTS narration track on top of a rendered
    # silent video. The final mp4 is a sibling artifact, not a replacement.
    VIDEO_VOICEOVER_GENERATING = "video.voiceover_generating"
    VIDEO_VOICEOVER_GENERATED = "video.voiceover_generated"
    VIDEO_VOICEOVER_FAILED = "video.voiceover_failed"

    # Improvement loop — multimodal Gemini critic reviews v1, proposes
    # weaknesses + concrete mutations; user accepts a subset; system
    # produces v2 via smart partial re-render (Veo only fires for
    # mutations whose target is frame.X.prompt or frame.X.motion).
    VIDEO_CRITIQUING = "video.critiquing"
    VIDEO_CRITIQUED = "video.critiqued"
    VIDEO_IMPROVEMENT_PROPOSED = "video.improvement_proposed"
    VIDEO_IMPROVING_STARTED = "video.improving_started"
    VIDEO_VERSION_RENDERING = "video.version_rendering"
    VIDEO_VERSION_RENDERED = "video.version_rendered"
    VIDEO_IMPROVEMENT_FAILED = "video.improvement_failed"

    # Brand picture book (PIC.md) — the evergreen visual identity layer.
    # Composed once at first image-gen and refreshed on demand. Every
    # image-generation call reads PIC.md and prepends it to the prompt so
    # all images cohere on one style.
    BRAND_PIC_GENERATING = "brand.pic_generating"
    BRAND_PIC_GENERATED = "brand.pic_generated"
    BRAND_PIC_LESSON_APPENDED = "brand.pic_lesson_appended"

    # Asset library AI-describer lifecycle — fires when a row's Gemini-
    # Vision description is being authored / lands / fails. The Library UI
    # uses these to flip an asset card from a shimmer to the real
    # description without polling.
    ASSET_DESCRIBING = "asset.describing"
    ASSET_DESCRIBED = "asset.described"
    ASSET_DESCRIBE_FAILED = "asset.describe_failed"

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

    # Multi-touch 1:1 campaigns (campaign_planner.py). Distinct from the
    # legacy ``campaign.bundled`` event which fires for the agent-loop
    # bundle-style campaign output.
    CAMPAIGN_PLANNING = "campaign.planning"
    CAMPAIGN_PLANNED = "campaign.planned"
    CAMPAIGN_TOUCH_SCHEDULED = "campaign.touch_scheduled"
    CAMPAIGN_TOUCH_SENT = "campaign.touch_sent"
    OFFER_GENERATED = "offer.generated"
    # Fired every time policy_validator.clamp() rewrites an LLM-proposed
    # offer to fit the Freedom-to-Operate envelope. The trust dashboard
    # subscribes to these.
    OFFER_POLICY_CLAMPED = "offer.policy_clamped"
    # Per-customer voice+video renders for individual campaign touches.
    # Distinct from the existing video.render_started / video.rendered /
    # video.voiceover_generated events, which belong to the storyboard
    # video pipeline.
    CAMPAIGN_VIDEO_RENDERING = "campaign.video_rendering"
    CAMPAIGN_VIDEO_RENDERED = "campaign.video_rendered"
    CAMPAIGN_VIDEO_RENDER_FAILED = "campaign.video_render_failed"
    # Trigger-rule fires that auto-create a draft Campaign.
    CAMPAIGN_TRIGGER_FIRED = "campaign.trigger_fired"

    ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTING = (
        "onboarding.competitor_products_extracting"
    )
    ONBOARDING_COMPETITOR_PRODUCTS_EXTRACTED = (
        "onboarding.competitor_products_extracted"
    )

    # Tavily-backed research leg. Fires on onboarding (auto, once per
    # brand) and on the agent loop (auto, once per campaign). The
    # source_added events stream individual citations as they land so the
    # UI can render them progressively rather than waiting for the bundle.
    RESEARCH_REQUESTED = "research.requested"
    RESEARCH_SOURCE_ADDED = "research.source_added"
    RESEARCH_COMPLETED = "research.completed"
    RESEARCH_FAILED = "research.failed"
    RESEARCH_UNAVAILABLE = "research.unavailable"

    PEEC_MCP_CONNECTED = "peec_mcp.connected"
    PEEC_MCP_DISCONNECTED = "peec_mcp.disconnected"
    PEEC_MCP_TOOL_CALLED = "peec_mcp.tool_called"
    PEEC_MCP_FAILED = "peec_mcp.failed"

    # Generative-Engine Optimization (GEO) loop. Closes the gap between
    # Peec's measurement (which prompts we lose on, who wins them) and the
    # asset that fills the gap. Lifecycle:
    #   gap_detected     → one absent prompt + winning competitor surfaced
    #   action_proposed  → recommender picked one action_type with a confidence
    #   action_rejected  → user dismissed the proposal (also clears the row)
    #   asset_generating → user accepted; generator is running (5-30s)
    #   asset_generated  → draft asset (markdown body / JSON-LD / etc) ready
    #   asset_published  → user shipped it (or it was scheduled to a channel)
    GEO_GAP_DETECTED = "geo.gap_detected"
    GEO_ACTION_PROPOSED = "geo.action_proposed"
    GEO_ACTION_REJECTED = "geo.action_rejected"
    GEO_ASSET_GENERATING = "geo.asset_generating"
    GEO_ASSET_GENERATED = "geo.asset_generated"
    GEO_ASSET_PUBLISHED = "geo.asset_published"
    GEO_SCAN_STARTED = "geo.scan_started"
    GEO_SCAN_COMPLETED = "geo.scan_completed"
    GEO_SCAN_UNAVAILABLE = "geo.scan_unavailable"

    # Pioneer-AI / Gemma fine-tuning lifecycle. The whole thing is event-
    # driven so the dashboard can render a live progress card without any
    # polling.
    VOICE_DEEP_SCRAPING = "voice.deep_scraping"
    VOICE_DEEP_SCRAPED = "voice.deep_scraped"
    VOICE_CORPUS_BUILDING = "voice.corpus_building"
    VOICE_CORPUS_BUILT = "voice.corpus_built"
    VOICE_CORPUS_FAILED = "voice.corpus_failed"
    VOICE_TRAINING_QUEUED = "voice.training_queued"
    VOICE_TRAINING_PROGRESS = "voice.training_progress"
    VOICE_MODEL_READY = "voice.model_ready"
    VOICE_MODEL_UPGRADED = "voice.model_upgraded"
    VOICE_TRAINING_FAILED = "voice.training_failed"

    # Pipeline editor — visual node-and-edge workflows. Save fires once on
    # debounced auto-save / Apply Changes; the run.* lifecycle streams per-
    # node progress so the canvas can light each node up as it executes.
    PIPELINE_SAVED = "pipeline.saved"
    PIPELINE_DELETED = "pipeline.deleted"
    PIPELINE_RUN_STARTED = "pipeline.run_started"
    PIPELINE_NODE_STARTED = "pipeline.node_started"
    PIPELINE_NODE_COMPLETED = "pipeline.node_completed"
    PIPELINE_NODE_FAILED = "pipeline.node_failed"
    PIPELINE_RUN_COMPLETED = "pipeline.run_completed"
    PIPELINE_RUN_FAILED = "pipeline.run_failed"


KNOWN_EVENTS: tuple[str, ...] = tuple(
    v
    for k, v in vars(Events).items()
    if not k.startswith("_") and isinstance(v, str)
)
