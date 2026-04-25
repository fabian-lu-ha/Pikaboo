import mitt from 'mitt'

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

export type AgentDraft = {
  campaign_id: string
  channel: 'blog' | 'linkedin' | 'hero_image' | string
  title: string
  preview: string
  body: string
}

export type AgentEvents = {
  'chat.submitted': { text: string }
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
  'linear.pr_merged': { pr: string; ship_ready: boolean }

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
}

export const bus = mitt<AgentEvents>()
