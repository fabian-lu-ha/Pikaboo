// Shared types for the Dashboard module. The Brand shape mirrors what
// /api/onboarding/me returns; keep in sync with backend/app/api/onboarding.py.

export type Competitor = {
  id: string
  name: string
  url: string | null
  reason: string | null
  logo_url: string | null
}

export type ConnectionSummary = {
  kanban: {
    providers: {
      provider: string
      selected_boards: string[]
      last_synced_at: string | null
    }[]
    card_count: number
  }
  crm: {
    providers: { provider: string; last_synced_at: string | null }[]
    customer_count: number
  }
  social: {
    providers: {
      provider: string
      username: string | null
      connected_at: string | null
    }[]
  }
}

export type Brand = {
  id: string
  name: string
  url: string | null
  description: string | null
  logo_url: string | null
  screenshots: string[]
  theme_color: string | null
  palette: string[]
  palette_roles?: { hex: string; role: string }[]
  voice_profile: {
    tone?: string
    voice_excerpt?: string
    recurring_phrases?: string[]
    do?: string[]
    dont?: string[]
  } | null
  handles: Record<string, string>
  connections?: ConnectionSummary
  competitors: Competitor[]
}

export type RunTint = 'violet' | 'emerald' | 'amber'

export type RunEntry = {
  id: string
  tint: RunTint
  title: string
  sub: string
  ts: number
}
