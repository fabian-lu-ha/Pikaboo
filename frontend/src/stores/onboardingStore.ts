import { create } from 'zustand'
import {
  bus,
  type CompetitorSuggestion,
  type Identity,
  type PaletteEntry,
  type Post,
  type ReferenceBrand,
  type StyleProfile,
  type VoiceProfile,
} from '../events/bus'

type ScrapedSnapshot = {
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

type EnrichedCompetitor = CompetitorSuggestion & {
  logo_url?: string | null
}

type ActivityEntry = {
  id: number
  at: string
  label: string
  kind: 'info' | 'event' | 'done' | 'fail'
}

type Phase = 'idle' | 'scraping' | 'distilling' | 'reviewing' | 'failed' | 'done'

type State = {
  brandId: string | null
  url: string | null
  phase: Phase
  scraped: ScrapedSnapshot | null
  voice: VoiceProfile | null
  competitors: EnrichedCompetitor[]
  posts: Post[]
  posts_received: boolean
  identity: Identity | null
  style: StyleProfile | null
  references: ReferenceBrand[]
  assets: string[]
  activity: ActivityEntry[]
  error: string | null
}

type Actions = {
  reset: () => void
  setBrand: (id: string, url: string) => void
}

const initial: State = {
  brandId: null,
  url: null,
  phase: 'idle',
  scraped: null,
  voice: null,
  competitors: [],
  posts: [],
  posts_received: false,
  identity: null,
  style: null,
  references: [],
  assets: [],
  activity: [],
  error: null,
}

export const useOnboardingStore = create<State & Actions>((set) => ({
  ...initial,
  reset: () => set(initial),
  setBrand: (id, url) =>
    set({ brandId: id, url, phase: 'scraping', error: null, activity: [] }),
}))

let activityCounter = 0
function pushActivity(label: string, kind: ActivityEntry['kind'] = 'event') {
  const at = new Date().toTimeString().slice(0, 8)
  useOnboardingStore.setState((s) => ({
    activity: [...s.activity, { id: activityCounter++, at, label, kind }],
  }))
}

bus.on('onboarding.scraping', (p) => {
  useOnboardingStore.setState({ phase: 'scraping' })
  pushActivity(`fetching ${stripScheme(p.url)}`)
})

bus.on('onboarding.scraped', (p) => {
  useOnboardingStore.setState((s) => ({
    phase: s.phase === 'scraping' ? 'distilling' : s.phase,
    scraped: {
      logo_url: p.logo_url,
      screenshots: p.screenshots,
      palette: p.palette,
      palette_roles: p.palette_roles ?? [],
      theme_color: p.theme_color,
      title: p.title,
      description: p.description,
      handles: p.handles,
      product_images: p.product_images,
    },
  }))
  pushActivity(
    `captured ${p.screenshots.length} ${plural(p.screenshots.length, 'frame')} · ${p.palette.length} ${plural(p.palette.length, 'color')}`,
    'done',
  )
})

bus.on('onboarding.voice_distilling', () => {
  pushActivity('analysing voice…')
})

bus.on('onboarding.voice_distilled', (p) => {
  useOnboardingStore.setState({ voice: p.voice_profile })
  const tone = p.voice_profile.tone.split('.')[0].slice(0, 64)
  pushActivity(`voice locked · ${tone.toLowerCase()}`, 'done')
})

bus.on('onboarding.competitors_suggesting', () => {
  pushActivity('scoping the competitive field…')
})

bus.on('onboarding.competitors_suggested', (p) => {
  useOnboardingStore.setState({ competitors: p.competitors })
  pushActivity(
    `${p.competitors.length} competitors · ${p.competitors.map((c) => c.name).join(', ')}`,
    'done',
  )
})

bus.on('onboarding.competitor_enriched', (p) => {
  useOnboardingStore.setState((s) => ({
    competitors: s.competitors.map((c) =>
      c.id === p.competitor_id ? { ...c, logo_url: p.logo_url } : c,
    ),
  }))
})

bus.on('onboarding.posts_fetching', () => {
  pushActivity('fetching recent posts across socials…')
})

bus.on('onboarding.style_analyzing', () => {
  pushActivity('reading the visual style…')
})

bus.on('onboarding.posts_fetched', (p) => {
  useOnboardingStore.setState({ posts: p.posts, posts_received: true })
  if (p.posts.length === 0) {
    pushActivity('no public posts found', 'done')
  } else {
    pushActivity(
      `${p.posts.length} ${plural(p.posts.length, 'post')} · ${summarisePlatforms(p.posts)}`,
      'done',
    )
  }
})

bus.on('onboarding.style_analyzed', (p) => {
  useOnboardingStore.setState({ style: p.style_profile })
  const mood = p.style_profile.mood.split('.')[0].slice(0, 60)
  pushActivity(`visual style read · ${mood.toLowerCase()}`, 'done')
})

bus.on('onboarding.identity_extracted', (p) => {
  useOnboardingStore.setState({ identity: p.identity })
  const tokens = p.identity.tokens?.css_vars_total ?? 0
  const fontFirst = p.identity.typography?.headline_font_first
  const summary = fontFirst
    ? `headline · ${fontFirst}${tokens ? ` · ${tokens} tokens` : ''}`
    : `${tokens} design tokens`
  pushActivity(`identity captured · ${summary}`, 'done')
})

bus.on('onboarding.reference_added', (p) => {
  useOnboardingStore.setState((s) => {
    const exists = s.references.some((r) => r.id === p.reference.id)
    return {
      references: exists
        ? s.references.map((r) =>
            r.id === p.reference.id ? p.reference : r,
          )
        : [...s.references, p.reference],
    }
  })
  pushActivity(`reference added · ${p.reference.name}`, 'done')
})

bus.on('onboarding.reference_failed', (p) => {
  pushActivity(
    `reference failed · ${stripScheme(p.url)} — ${p.error.slice(0, 80)}`,
    'fail',
  )
})

bus.on('onboarding.asset_uploaded', (p) => {
  useOnboardingStore.setState((s) => ({
    assets: s.assets.includes(p.asset_url) ? s.assets : [...s.assets, p.asset_url],
  }))
  pushActivity(`asset uploaded · ${p.name}`, 'done')
})

bus.on('onboarding.failed', (p) => {
  useOnboardingStore.setState({ phase: 'failed', error: p.error })
  pushActivity(`failed · ${p.error.slice(0, 120)}`, 'fail')
})

bus.on('onboarding.completed', () => {
  useOnboardingStore.setState({ phase: 'done' })
  pushActivity('done.', 'done')
})

function stripScheme(u: string) {
  return u.replace(/^https?:\/\//, '').replace(/\/$/, '')
}

function plural(n: number, word: string) {
  return n === 1 ? word : `${word}s`
}

function summarisePlatforms(posts: Post[]): string {
  const counts = new Map<string, number>()
  for (const p of posts) counts.set(p.platform, (counts.get(p.platform) ?? 0) + 1)
  return [...counts.entries()]
    .map(([k, v]) => `${v} ${k}`)
    .join(' · ')
}
