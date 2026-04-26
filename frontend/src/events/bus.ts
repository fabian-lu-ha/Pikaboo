import mitt from 'mitt'
import type { ProposedSegment, Segment } from '../lib/audience'

export type VoiceProfile = {
  tone: string
  recurring_phrases: string[]
  do: string[]
  dont: string[]
  voice_excerpt: string
}

export type CompetitorSuggestion = {
  id: string
  name: string
  url: string | null
  reason: string | null
}

export type PostPlatform =
  | 'youtube'
  | 'instagram'
  | 'tiktok'
  | 'x'
  | 'linkedin'
  | 'other'

export type VideoAnalysis = {
  transcript: string
  key_moments: { timestamp_seconds: number; description: string }[]
  visual_summary: string
  content_summary: string
  style_observations: string[]
  duration_seconds: number | null
}

export type Post = {
  platform: PostPlatform
  caption: string
  media_urls: string[]
  posted_at: string | null
  url: string | null
  likes: number | null
  video_analysis: VideoAnalysis | null
}

export type PaletteRole =
  | 'background'
  | 'primary'
  | 'secondary'
  | 'text'
  | 'link'
  | 'surface'
  | 'ornament'

export type PaletteEntry = {
  hex: string
  role: PaletteRole
}

export type Identity = {
  typography?: {
    body_font: string | null
    body_font_first: string | null
    headline_font: string | null
    headline_font_first: string | null
    mono_font: string | null
    mono_font_first: string | null
    body_size_px: number | null
    h1_size_px: number | null
    h1_weight: number | null
    h1_line_height: number | null
    h1_letter_spacing_em: number
    h2_size_px: number | null
    p_line_height: number | null
  }
  radii?: {
    samples_px: number[]
    dominant_px: number | null
    small_px: number | null
    medium_px: number | null
    large_px: number | null
    has_pill: boolean
  }
  shadows?: string[]
  buttons?: {
    primary?: {
      bg: string | null
      fg: string | null
      radius_px: number | null
      padding: string | null
      font_size_px: number | null
      font_weight: number | null
      border: string | null
      shadow: string | null
    }
  }
  tokens?: {
    css_vars_total: number
    color_vars: number
    space_vars: number
    exposes_design_system: boolean
  }
}

export type StyleProfile = {
  palette_character: string
  composition: string
  mood: string
  typography_feel: string
  photographic_vs_illustrated: string
  distinctive_marks: string[]
  generation_guidance: string[]
}

export type ReferenceBrand = {
  id: string
  url: string
  name: string
  logo_url: string | null
  palette: string[]
  screenshot_urls?: string[]
  voice_excerpt?: string
}

export type LiftPrediction = {
  lift_percent: number
  confidence: string
  factors: string[]
  target_prompts: string[]
  research_basis: string
}

export type PeecSnapshot = {
  brand_id: string
  project_id: string | null
  fetched_at: string
  visibility: number | null
  share_of_voice: number | null
  sentiment: number | null
  visible_on: {
    prompt: string
    rank: number | null
    visibility: number | null
  }[]
  absent_from: {
    prompt: string
    competitor_winning: string | null
    competitor_visibility: number | null
    own_visibility: number | null
  }[]
  cited_domains: { domain: string; citation_count: number | null }[]
}

export type PeecTarget = {
  prompt: string
  competitor_winning: string | null
  own_visibility: number | null
  score: number
}

export type ResearchSource = {
  title: string
  url: string
  snippet: string
  bucket: 'company' | 'news' | 'trend' | 'topic' | 'competitor' | 'campaign' | string
  score: number | null
  published_date: string | null
}

export type ResearchScope = 'brand' | 'campaign'

export type ResearchBundle = {
  fetched_at: string
  sources: ResearchSource[]
  answer: string | null
  error?: string | null
  domain?: string | null
  queries?: { label: string; query: string; bucket: string }[]
  brand_id?: string
  campaign_id?: string
  user_request?: string
}

export type AgentDraft = {
  campaign_id: string
  channel: 'blog' | 'linkedin' | 'hero_image' | string
  title: string
  preview: string
  body: string
}

// ── Generative-Engine Optimization (GEO) types ──────────────────────────
export type GeoActionType =
  | 'comparison_page'
  | 'definition_first'
  | 'faq_schema'
  | 'stats_quote'
  | 'wikidata_schema'
  | 'reddit_draft'

export type GeoGapStatus = 'open' | 'addressed' | 'dismissed'
export type GeoRecommendationStatus =
  | 'proposed'
  | 'accepted'
  | 'rejected'
  | 'generated'
export type GeoAssetStatus = 'draft' | 'published'

export type GeoGapPayload = {
  id: string
  brand_id: string
  prompt: string
  competitor_name: string | null
  competitor_visibility: number | null
  own_visibility: number | null
  gap_score: number
  cited_domains: string[]
  engines_present: string[]
  source_campaign_id: string | null
  detected_at: string
  status: GeoGapStatus
}

export type GeoRecommendationPayload = {
  id: string
  brand_id: string
  gap_id: string
  action_type: GeoActionType
  action_label: string
  confidence: number
  rationale: string | null
  target_engines: string[]
  asset_outline: Record<string, unknown>
  status: GeoRecommendationStatus
  created_at: string
}

export type GeoAssetPayload = {
  id: string
  brand_id: string
  recommendation_id: string
  gap_id: string
  action_type: GeoActionType
  action_label: string
  title: string | null
  body_markdown: string | null
  body_json: Record<string, unknown>
  target_url: string | null
  status: GeoAssetStatus
  publish_url: string | null
  predicted_lift_pct: number | null
  created_at: string
  published_at?: string | null
}

export type VideoAspect = '9:16' | '16:9' | '1:1'

export type CastKind = 'character' | 'setting' | 'prop' | 'product'

export type FocalZone =
  | 'tl'
  | 'tc'
  | 'tr'
  | 'ml'
  | 'mc'
  | 'mr'
  | 'bl'
  | 'bc'
  | 'br'

// Veo model tier — fast (default, ~30-45s/clip) vs. quality (~60-90s/clip,
// hero render). Selected per-scene; the backend resolves to the configured
// veo_fast_model / veo_quality_model identifier.
export type VeoQuality = 'fast' | 'quality'

// Pure-typography bookends rendered by Remotion (no Veo clip).
export type StoryboardTitleCard = {
  text: string
}

export type StoryboardEndCard = {
  headline: string
  cta: string
}

// Motion-graphics overlays Remotion renders on top of each shot. Lifts the
// composition above generic AI-stock-video output. 0-3 effects per shot.
export type EffectKind =
  | 'kinetic_text'
  | 'lower_third'
  | 'brand_stinger'
  | 'spotlight'
  | 'kinetic_lines'
  | 'data_pop'

export type EffectParams = {
  text?: string
  title?: string
  subtitle?: string
  value?: string
  zone?: FocalZone
  size?: 'sm' | 'md' | 'lg'
  color?: 'accent' | 'text' | 'background'
  radius?: 'sm' | 'md' | 'lg'
  pattern?: 'diagonal' | 'horizontal' | 'underline' | 'frame'
  variant?: 'number' | 'bar' | 'dot'
}

export type Effect = {
  id: string
  kind: EffectKind
  params?: EffectParams
  start_ms?: number | null
  duration_ms?: number | null
}

export type CastBinding = {
  type: 'brand_asset' | 'needs_generation'
  asset_index?: number | null
}

export type CastMember = {
  id: string
  kind: CastKind
  role: string
  description: string
  neutral_pose_hint?: string | null
  binding: CastBinding
  canonical_url: string | null
  narrative_purpose?: string
}

export type StoryboardNarrative = {
  premise: string
  arc: string
  tone: string
}

export type CinematicBrief = {
  reference_films: string
  lensing: string
  lighting: string
  palette_grade: string
  pacing: string
  do_not: string
}

export type VoiceName =
  | 'Aoede'
  | 'Charon'
  | 'Fenrir'
  | 'Kore'
  | 'Leda'
  | 'Orus'
  | 'Puck'
  | 'Schedar'
  | 'Vindemiatrix'
  | 'Zephyr'

export type VoiceoverSpec = {
  script: string
  voice_persona: string
  voice_name: VoiceName
}

// Segment-aware storyboard targeting. When the user picks a segment in
// the storyboard panel, /suggest receives this and threads feature_focus
// through cinematic_brief, frames, and voiceover so different segments
// get different ad spots from the same campaign.
export type SegmentTarget = {
  id: string
  name: string
  description: string
  rationale: string
  size: number
  feature_focus: string | null
  feature_stats: Record<string, number>
  contributor_counts: Record<string, number>
}

// Brand-wide feature usage roll-up — returned from
// GET /api/audience/feature-usage. Shown in the segment picker so the
// user sees which features have a cohort big enough to warrant a
// targeted ad spot.
export type FeatureDistributionItem = {
  feature: string
  customer_count: number
  event_count: number
  last_seen: string | null
}

// Segment row as returned by GET /api/audience/segments.
export type AudienceSegment = {
  id: string
  name: string
  description: string | null
  rationale: string | null
  customer_ids: string[]
  size: number
  source: string
  feature_focus: string | null
  feature_stats: Record<string, unknown>
  created_at: string | null
}

export type FrameKind = 'live_action' | 'design_sequence'
export type DesignTemplate =
  | 'gradient_kinetic'
  | 'spec_card'
  | 'ui_zoom'
  | 'code_window'
  | 'logo_reveal'
  | 'comparison_split'
  | 'text_scroll'
  | 'headline_punch'
  | 'word_kinetic'
  | 'canvas_kinetic'

export type StoryboardFrame = {
  id: string
  // Defaults to 'live_action' on legacy storyboards (omitted field).
  kind?: FrameKind
  prompt: string
  caption: string
  duration_ms: number
  cast_refs: string[]
  focal_zone: FocalZone
  motion?: string
  effects?: Effect[]
  // design_sequence-only — picks Remotion template + its params payload.
  template?: DesignTemplate | null
  template_params?: Record<string, unknown> | null
}

export type AgentEvents = {
  'chat.submitted': { text: string; formats?: string[] }
  'agent.started': {
    campaign_id: string
    brand_id: string
    user_request: string
  }
  'agent.step': {
    campaign_id: string
    id: string
    label: string
    at: string
  }
  'agent.failed': { error: string; campaign_id?: string }
  'agent.peec_data_fetched': {
    campaign_id: string
    brand_id: string | null
    snapshot: PeecSnapshot
    target_prompts: PeecTarget[]
  }
  'agent.peec_unavailable': { campaign_id: string; reason: string }

  'research.requested': {
    scope: ResearchScope
    scope_id: string
    brand_id?: string | null
    brand_name?: string
    url?: string | null
    user_request?: string
  }
  'research.source_added': {
    scope: ResearchScope
    scope_id: string
    source: ResearchSource
  }
  'research.completed': {
    scope: ResearchScope
    scope_id: string
    brand_id?: string | null
    source_count: number
    answer: string | null
    sources: ResearchSource[]
    fetched_at: string
  }
  'research.failed': {
    scope: ResearchScope
    scope_id: string
    brand_id?: string | null
    error: string
  }
  'research.unavailable': {
    scope: ResearchScope
    scope_id: string
    brand_id?: string | null
    reason: string
  }
  'draft.created': AgentDraft
  'lift.predicted': { campaign_id: string } & LiftPrediction
  'campaign.bundled': {
    campaign_id: string
    brand_id: string
    title: string
    bundle: {
      user_request: string
      drafts?: {
        channel: string
        label: string
        kind: string
        title: string
        body: string
        image_url: string | null
        image_aspect: string | null
      }[]
      blog?: { title: string; body: string }
      social?: { linkedin: string }
      hero_image_url: string | null
      predicted_lift: LiftPrediction
      target_prompts: string[]
    }
  }
  'competitor.surged': { competitor: string; prompt: string; delta: number }
  'competitor.intel_requested': {
    competitor_id: string
    competitor_name: string
    url: string | null
  }
  'competitor.intel_source_added': {
    competitor_id: string
    source: ResearchSource
  }
  'competitor.intel_completed': {
    competitor_id: string
    competitor_name: string
    source_count: number
    answer: string | null
    sources: ResearchSource[]
    fetched_at: string
  }
  'competitor.intel_failed': { competitor_id: string; error: string }
  'competitor.intel_unavailable': { competitor_id: string; reason: string }
  'linear.pr_merged': { pr: string; ship_ready: boolean }

  'video.storyboard_suggested': {
    storyboard_id: string
    aspect: VideoAspect
    cast: CastMember[]
    frames: StoryboardFrame[]
    narrative?: StoryboardNarrative
    cinematic_brief?: CinematicBrief
    voiceover?: VoiceoverSpec
    title_card?: StoryboardTitleCard | null
    end_card?: StoryboardEndCard | null
    segment?: SegmentTarget | null
  }
  'video.cast_proposed': {
    storyboard_id: string
    cast: CastMember[]
  }
  'video.ingredient_generating': {
    storyboard_id: string
    cast_id: string
    kind: CastKind
    regenerate?: boolean
  }
  'video.ingredient_generated': {
    storyboard_id: string
    cast_id: string
    canonical_url: string
    kind: CastKind
    from_brand_asset?: boolean
  }
  'video.ingredient_regenerated': {
    storyboard_id: string
    cast_id: string
    canonical_url: string
    previous_url: string | null
    kind: CastKind
  }
  'video.cast_bible_locked': { storyboard_id: string }
  'video.frame_generating': {
    storyboard_id: string | null
    frame_id: string | null
    cast_refs: string[]
  }
  'video.frame_generated': {
    storyboard_id: string | null
    frame_id: string | null
    image_url: string
    aspect: VideoAspect
    prompt_preview: string
    cast_refs: string[]
  }
  'video.frame_stale': {
    storyboard_id: string
    frame_id: string
    cast_id: string
  }
  'video.scene_generating': {
    storyboard_id: string
    frame_id: string
    cast_refs: string[]
    duration_ms: number
    quality?: VeoQuality
    from_keyframe?: boolean
  }
  'video.scene_generated': {
    storyboard_id: string
    frame_id: string
    clip_url: string
    aspect: VideoAspect
    cast_refs: string[]
    duration_ms: number
    quality?: VeoQuality
    from_keyframe?: boolean
  }
  'video.scene_retrying': {
    storyboard_id: string
    frame_id: string
    phase: 'submit' | 'poll'
    attempt: number
    max_attempts: number
    delay_s: number
    reason: string
  }
  'video.render_started': Record<string, never>
  'video.rendered': {
    video_id?: string
    video_url: string
    duration_ms: number
  }
  'video.render_failed': { error: string }
  'video.voiceover_generating': {
    video_id: string
    storyboard_id: string
    voice_name: VoiceName
    word_count: number
  }
  'video.voiceover_generated': {
    video_id: string
    storyboard_id: string
    video_url: string
    voice_name: VoiceName
    script: string
  }
  'video.voiceover_failed': { video_id: string; error: string }

  // Improvement loop — multimodal Gemini critic + version-aware re-render.
  'video.critiquing': {
    storyboard_id: string
    video_url: string
    frame_count: number
  }
  'video.critiqued': {
    storyboard_id: string
    weakness_count: number
    mutation_count: number
    summary: string
    error?: string | null
  }
  'video.improvement_proposed': {
    storyboard_id: string
    mutations: {
      id: string
      target: string
      cost: 'free' | 'render' | 'veo'
      estimated_seconds: number
    }[]
  }
  'video.improving_started': {
    storyboard_id: string
    mutation_count: number
  }
  'video.version_rendering': {
    storyboard_id: string
    frame_count: number
  }
  'video.version_rendered': {
    storyboard_id: string
    version_number: number
    video_url: string
    duration_ms: number
    refired_frame_ids: string[]
    applied_mutation_ids: string[]
  }
  'video.improvement_failed': {
    storyboard_id: string
    phase: 'apply' | 'render' | 'store'
    error: string
  }

  // Asset-library AI-describer lifecycle. Library page listens to these
  // to flip a card from a shimmer to the real description without
  // polling.
  'asset.describing': { asset_id: string; brand_id: string | null }
  'asset.described': {
    asset_id: string
    brand_id: string | null
    description: string | null
    tags: string[]
    cast_kind: 'character' | 'setting' | 'prop' | 'product' | null
  }
  'asset.describe_failed': { asset_id: string; reason: string }

  'onboarding.basics_saved': { brand_id: string; url: string }
  'onboarding.scraping': { brand_id: string; url: string }
  'onboarding.scraped': {
    brand_id: string
    logo_url: string | null
    screenshots: string[]
    palette: string[]
    palette_roles: PaletteEntry[]
    theme_color: string | null
    title: string | null
    description: string | null
    handles: Record<string, string>
    product_images: string[]
  }
  'onboarding.voice_distilling': { brand_id: string }
  'onboarding.voice_distilled': {
    brand_id: string
    voice_profile: VoiceProfile
  }
  'onboarding.competitors_suggesting': { brand_id: string }
  'onboarding.competitors_suggested': {
    brand_id: string
    competitors: CompetitorSuggestion[]
  }
  'onboarding.competitor_enriched': {
    brand_id: string
    competitor_id: string
    logo_url: string | null
  }
  'onboarding.identity_extracted': { brand_id: string; identity: Identity }
  'onboarding.posts_fetching': { brand_id: string }
  'onboarding.posts_fetched': { brand_id: string; posts: Post[] }
  'onboarding.style_analyzing': { brand_id: string }
  'onboarding.style_analyzed': {
    brand_id: string
    style_profile: StyleProfile
  }
  'onboarding.reference_added': {
    brand_id: string
    reference: ReferenceBrand
  }
  'onboarding.reference_failed': {
    brand_id: string
    url: string
    error: string
  }
  'onboarding.asset_uploaded': {
    brand_id: string
    asset_url: string
    name: string
  }
  'onboarding.failed': { brand_id: string; error: string }
  'onboarding.completed': { brand_id: string }

  'audience.crm_connected': { brand_id: string; provider: string }
  'audience.import_started': { brand_id: string; provider: string }
  'audience.customers_imported': {
    brand_id: string
    provider: string
    customer_count: number
    product_count: number
    event_count: number
  }
  'audience.segments_proposing': { brand_id: string }
  'audience.segments_proposed': {
    brand_id: string
    segments: ProposedSegment[]
  }
  'audience.segment_saved': { brand_id: string; segment: Segment }
  'audience.pii_redacted': {
    brand_id: string
    entity_count: number
    entity_types: string[]
  }
  'audience.personalizing': {
    brand_id: string
    target_kind: 'customer' | 'segment'
    target_id: string
  }
  'audience.personalized': {
    brand_id: string
    target_kind: 'customer' | 'segment'
    target_id: string
    subject_preview: string
    recommended_product_ids: string[]
  }
  'audience.email_dispatched': {
    brand_id: string
    target_kind: 'customer' | 'segment'
    target_id: string
    recipient_count: number
  }
  'audience.shop_event_triggered': {
    brand_id: string
    customer_id: string
    kind: 'cart_abandoned' | 'subscription_lapsed'
    event_id: string
    payload: Record<string, unknown>
  }
  'audience.shop_auto_personalized': {
    brand_id: string
    customer_id: string
    trigger_kind: 'cart_abandoned' | 'subscription_lapsed'
    subject_preview: string
    recommended_product_ids: string[]
  }

  'onboarding.competitor_products_extracting': {
    brand_id: string
    competitor_id: string
    url: string
  }
  'onboarding.competitor_products_extracted': {
    brand_id: string
    competitor_id: string
    product_count: number
  }

  // Pioneer-AI per-tenant Gemma fine-tuning lifecycle. The corpus stage
  // is the demo's *moat moment* — every sub-event below is rendered live
  // in the Voice pane.
  'voice.deep_scraping': { brand_id: string; url: string }
  'voice.deep_scraped': {
    brand_id: string
    domain: string
    discovered_urls: number
    fetched_pages: number
    text_chunks: number
    by_kind: Record<string, number>
  }
  'voice.corpus_building': { brand_id: string }
  'voice.corpus_built': {
    brand_id: string
    line_count: number
    breakdown: Record<string, number>
    jsonl_path: string
  }
  'voice.corpus_failed': { brand_id: string; error: string }
  'voice.training_queued': {
    brand_id: string
    job_id: string
    base_model: string
    method: string
    corpus_lines: number
    simulator: boolean
  }
  'voice.training_progress': {
    brand_id: string
    job_id: string
    status: string
    progress: number
    stage: string
  }
  'voice.model_ready': {
    brand_id: string
    model_id: string
    adapter_url: string
    base_model: string
    corpus_lines: number
    simulator: boolean
  }
  'voice.model_upgraded': {
    brand_id: string
    deployment_id: string
    model_id: string | null
    metrics: Record<string, unknown>
  }
  'voice.training_failed': { brand_id: string; error: string }

  // Pipeline editor lifecycle. ``pipeline.saved`` fires on every persisted
  // change; the run.* events stream node-by-node so the canvas can light
  // each box up live as the executor walks the graph.
  'pipeline.saved': {
    pipeline_id: string
    brand_id: string
    name: string
    node_count: number
    edge_count: number
    kind: 'created' | 'updated'
  }
  'pipeline.deleted': { pipeline_id: string; brand_id: string }
  'pipeline.run_started': {
    pipeline_id: string
    run_id: string
    brand_id: string
    node_count: number
  }
  'pipeline.node_started': {
    pipeline_id: string
    run_id: string
    node_id: string
    kind: string
    name: string | null
  }
  'pipeline.node_completed': {
    pipeline_id: string
    run_id: string
    node_id: string
    kind: string
    preview: Record<string, unknown>
  }
  'pipeline.node_failed': {
    pipeline_id: string
    run_id: string
    node_id: string
    error: string
  }
  'pipeline.run_completed': {
    pipeline_id: string
    run_id: string
    duration_ms: number
    result: Record<string, unknown>
  }
  'pipeline.run_failed': {
    pipeline_id: string
    run_id: string
    error: string
  }

  // 1:1 personalized campaigns & custom offers
  'campaign.planning': {
    brand_id: string
    target_kind: 'customer' | 'segment'
    target_id: string
    trigger?: string | null
  }
  'campaign.planned': {
    brand_id: string
    campaign_id: string
    target_kind: 'customer' | 'segment'
    target_id: string
    touch_count: number
    offer_id: string | null
  }
  'campaign.touch_scheduled': {
    brand_id: string
    campaign_id: string
    touch_id: string
    step_index: number
    kind: 'email' | 'video' | 'landing'
    scheduled_at: string | null
  }
  'campaign.touch_sent': {
    brand_id: string
    campaign_id: string
    touch_id: string
    kind: 'email' | 'video' | 'landing'
    send_id: string | null
  }
  'campaign.video_rendering': {
    brand_id: string
    campaign_id: string
    touch_id: string
    voice_model_id: string | null
  }
  'campaign.video_rendered': {
    brand_id: string
    campaign_id: string
    touch_id: string
    video_url: string
    audio_url: string | null
    voice_model_id: string | null
  }
  'campaign.video_render_failed': {
    brand_id: string
    campaign_id: string
    touch_id: string
    error: string
  }
  'campaign.trigger_fired': {
    brand_id: string
    rule_id: string
    rule_label: string
    customer_id: string | null
    campaign_id: string | null
    fired_at: string
  }

  'offer.generated': {
    brand_id: string
    offer_id: string
    customer_id: string | null
    segment_id: string | null
    product_ids: string[]
    discount_type: string | null
    discount_value: number | null
  }
  'offer.policy_clamped': {
    brand_id: string
    offer_id: string | null
    customer_id: string | null
    segment_id: string | null
    field: string
    proposed: unknown
    clamped: unknown
    reason: string
    clamped_at: string
  }

  // Generative-Engine Optimization lifecycle. The campaign loop fires
  // gap_detected + action_proposed automatically once Peec returns;
  // accept/reject are user-driven from the GeoPanel; asset_generating /
  // generated stream the Gemini draft as it lands; published is the
  // terminal state once the user has shipped it.
  'geo.gap_detected': GeoGapPayload
  'geo.action_proposed': GeoRecommendationPayload
  'geo.action_rejected': {
    id: string
    brand_id: string
    gap_id: string
    action_type: GeoActionType
  }
  'geo.asset_generating': {
    recommendation_id: string
    brand_id: string
    gap_id: string
    action_type: GeoActionType
    error?: string
    status?: 'failed'
  }
  'geo.asset_generated': GeoAssetPayload
  'geo.asset_published': GeoAssetPayload
  'geo.scan_started': {
    brand_id: string
    source_campaign_id: string | null
  }
  'geo.scan_completed': {
    brand_id: string
    gap_count: number
    source_campaign_id: string | null
  }
  'geo.scan_unavailable': {
    brand_id: string
    reason: string
  }
}

export const bus = mitt<AgentEvents>()
