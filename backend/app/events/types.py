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


KNOWN_EVENTS: tuple[str, ...] = tuple(
    v
    for k, v in vars(Events).items()
    if not k.startswith("_") and isinstance(v, str)
)
