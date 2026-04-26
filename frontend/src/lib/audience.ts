// Audience domain types — mirrors the shapes returned by /api/audience/*.
// Keep in sync with backend/app/api/audience.py and the agent's serializer.

export type Acquisition = {
  source: string
  campaign: string | null
  utm_source: string
  utm_medium: string
  utm_campaign: string
  utm_content: string
  utm_term: string
  first_touch_url: string
  referrer: string
}

export type Touchpoint = {
  source: string
  campaign: string | null
  at: string
  action: string
}

export type Customer = {
  id: string
  brand_id: string
  provider: string
  external_id: string
  email: string
  name: string | null
  phone: string | null
  city: string | null
  country: string | null
  attributes: Record<string, unknown>
  acquisition?: Partial<Acquisition>
  touchpoints?: Touchpoint[]
  tags: string[]
  signup_at: string | null
  last_active_at: string | null
  total_spend_cents: number
  recent_events?: CustomerEvent[]
}

export const SOURCE_LABELS: Record<string, string> = {
  google_ads: 'Google Ads',
  meta_ads: 'Meta Ads',
  organic_search: 'Organic',
  referral_partner: 'Referral',
  newsletter: 'Newsletter',
  direct: 'Direct',
}

export function acquisitionBadge(acq: Partial<Acquisition> | undefined): string | null {
  if (!acq?.source) return null
  const src = SOURCE_LABELS[acq.source] ?? acq.source
  if (acq.campaign) return `${src} · ${acq.campaign}`
  return src
}

export type CustomerEventKind =
  | 'email_open'
  | 'email_click'
  | 'purchase'
  | 'page_view'
  | 'support_msg'
  | 'cart_abandoned'
  | 'subscription_lapsed'

export type CustomerEvent = {
  id: string
  customer_id: string
  brand_id: string
  kind: CustomerEventKind
  occurred_at: string
  payload: Record<string, unknown>
}

export type Product = {
  id: string
  brand_id: string
  sku: string | null
  name: string
  description: string | null
  price_cents: number
  image_url: string | null
  category: string | null
  tags: string[]
}

export type Segment = {
  id: string
  brand_id: string
  name: string
  description: string | null
  rationale: string | null
  customer_ids: string[]
  source: 'ai_proposed' | 'user_created'
  created_at: string
}

export type ProposedSegment = {
  name: string
  description: string
  rationale: string
  criteria_summary: string
  customer_ids: string[]
}

export type PersonalizedEmail = {
  subject: string
  body: string
  recommended_product_ids: string[]
  reasoning: string
  redaction_summary: { entity_count: number; types: string[] }
  competitor_catalog_size?: number
  html_body?: string
}

export type CustomerStats = {
  total_spend_cents: number
  purchase_count: number
  open_rate: number
}

export const EVENT_GLYPHS: Record<CustomerEventKind, string> = {
  email_open: '✉',
  email_click: '↗',
  purchase: '◆',
  page_view: '◐',
  support_msg: '◇',
  cart_abandoned: '⊗',
  subscription_lapsed: '↧',
}

export const EVENT_LABELS: Record<CustomerEventKind, string> = {
  email_open: 'opened email',
  email_click: 'clicked email',
  purchase: 'purchased',
  page_view: 'viewed page',
  support_msg: 'support message',
  cart_abandoned: 'abandoned cart',
  subscription_lapsed: 'subscription lapsed',
}

export function formatPrice(cents: number, currency = 'EUR'): string {
  const amount = cents / 100
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 0,
    }).format(amount)
  } catch {
    return `€${amount.toFixed(0)}`
  }
}

export function relativeFromIso(iso: string | null, now: number = Date.now()): string {
  if (!iso) return '—'
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return '—'
  const delta = Math.max(0, now - ts)
  const seconds = Math.floor(delta / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.floor(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.floor(months / 12)}y ago`
}
