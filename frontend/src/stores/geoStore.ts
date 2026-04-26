import { create } from 'zustand'
import {
  bus,
  type GeoActionType,
  type GeoAssetPayload,
  type GeoGapPayload,
  type GeoRecommendationPayload,
} from '../events/bus'

// ──────────────────────────────────────────────────────────────────────────
// Generative-Engine Optimization store.
//
// Mirrors what /api/geo/overview returns, but kept fresh by the GEO_*
// SSE events so the dashboard fills in live as the agent loop runs.
// Keyed by brand_id so switching brands doesn't bleed state.
// ──────────────────────────────────────────────────────────────────────────

export type ActionTypeMeta = {
  key: GeoActionType
  label: string
  summary: string
}

export type EnginePlaybookEntry = {
  key: string
  label: string
  retrieval: string
  high_leverage: GeoActionType[]
  note: string
}

export type GeoSummary = {
  gap_count: number
  open_gap_count: number
  recommendation_count: number
  accepted_count: number
  asset_count: number
  published_count: number
}

type ScanStatus = 'idle' | 'scanning' | 'done' | 'unavailable'

type GeneratingStatus = {
  recommendation_id: string
  action_type: GeoActionType
  startedAt: string
  error: string | null
}

type State = {
  brandId: string | null
  fetchedAt: string | null
  loading: boolean
  loadError: string | null
  scanStatus: ScanStatus
  scanError: string | null
  gaps: Record<string, GeoGapPayload>
  recommendations: Record<string, GeoRecommendationPayload>
  assets: Record<string, GeoAssetPayload>
  generating: Record<string, GeneratingStatus>
  actionTypes: ActionTypeMeta[]
  enginePlaybook: EnginePlaybookEntry[]
  summary: GeoSummary
}

type Actions = {
  load: (brandId: string) => Promise<void>
  scan: (brandId: string, topK?: number) => Promise<void>
  accept: (recommendationId: string) => Promise<void>
  reject: (recommendationId: string) => Promise<void>
  publish: (assetId: string, publishUrl?: string) => Promise<void>
  clear: () => void
}

const emptySummary: GeoSummary = {
  gap_count: 0,
  open_gap_count: 0,
  recommendation_count: 0,
  accepted_count: 0,
  asset_count: 0,
  published_count: 0,
}

const initial: State = {
  brandId: null,
  fetchedAt: null,
  loading: false,
  loadError: null,
  scanStatus: 'idle',
  scanError: null,
  gaps: {},
  recommendations: {},
  assets: {},
  generating: {},
  actionTypes: [],
  enginePlaybook: [],
  summary: emptySummary,
}

type OverviewResponse = {
  brand_id: string
  brand_name: string
  fetched_at: string
  gaps: GeoGapPayload[]
  recommendations: (GeoRecommendationPayload & {
    action_summary?: string
  })[]
  assets: GeoAssetPayload[]
  action_types: ActionTypeMeta[]
  engine_playbook: EnginePlaybookEntry[]
  summary: GeoSummary
}

function indexBy<T extends { id: string }>(rows: T[]): Record<string, T> {
  const out: Record<string, T> = {}
  for (const r of rows) out[r.id] = r
  return out
}

function computeSummary(state: State): GeoSummary {
  const gaps = Object.values(state.gaps)
  const recos = Object.values(state.recommendations)
  const assets = Object.values(state.assets)
  return {
    gap_count: gaps.length,
    open_gap_count: gaps.filter((g) => g.status === 'open').length,
    recommendation_count: recos.length,
    accepted_count: recos.filter(
      (r) => r.status === 'accepted' || r.status === 'generated',
    ).length,
    asset_count: assets.length,
    published_count: assets.filter((a) => a.status === 'published').length,
  }
}

export const useGeoStore = create<State & Actions>((set) => ({
  ...initial,

  load: async (brandId: string) => {
    set({ loading: true, loadError: null, brandId })
    try {
      const r = await fetch(
        `/api/geo/overview?brand_id=${encodeURIComponent(brandId)}`,
      )
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j) => j?.detail ?? null)
          .catch(() => null)
        throw new Error(detail ?? `Geo overview failed (${r.status})`)
      }
      const data = (await r.json()) as OverviewResponse
      set({
        brandId: data.brand_id,
        fetchedAt: data.fetched_at,
        loading: false,
        loadError: null,
        gaps: indexBy(data.gaps),
        recommendations: indexBy(data.recommendations),
        assets: indexBy(data.assets),
        actionTypes: data.action_types,
        enginePlaybook: data.engine_playbook,
        summary: data.summary,
      })
    } catch (e) {
      set({
        loading: false,
        loadError: e instanceof Error ? e.message : 'load failed',
      })
    }
  },

  scan: async (brandId: string, topK = 5) => {
    set({ scanStatus: 'scanning', scanError: null })
    try {
      const r = await fetch('/api/geo/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ brand_id: brandId, top_k: topK }),
      })
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j) => j?.detail ?? null)
          .catch(() => null)
        throw new Error(detail ?? `Scan failed (${r.status})`)
      }
      // Lifecycle (scan_started / gap_detected / scan_completed) drives
      // store updates from here — nothing else to do on success.
    } catch (e) {
      set({
        scanStatus: 'unavailable',
        scanError: e instanceof Error ? e.message : 'scan failed',
      })
    }
  },

  accept: async (recommendationId: string) => {
    // Optimistic flip — the backend will also emit asset_generating.
    set((s) => {
      const reco = s.recommendations[recommendationId]
      if (!reco) return s
      return {
        ...s,
        recommendations: {
          ...s.recommendations,
          [recommendationId]: { ...reco, status: 'accepted' },
        },
      }
    })
    try {
      await fetch(`/api/geo/recommendations/${recommendationId}/accept`, {
        method: 'POST',
      })
    } catch {
      // SSE events will reconcile on the next bundle round-trip.
    }
  },

  reject: async (recommendationId: string) => {
    set((s) => {
      const reco = s.recommendations[recommendationId]
      if (!reco) return s
      return {
        ...s,
        recommendations: {
          ...s.recommendations,
          [recommendationId]: { ...reco, status: 'rejected' },
        },
      }
    })
    try {
      await fetch(`/api/geo/recommendations/${recommendationId}/reject`, {
        method: 'POST',
      })
    } catch {
      /* surfaced via geo.action_rejected event on retry */
    }
  },

  publish: async (assetId: string, publishUrl?: string) => {
    try {
      const r = await fetch(`/api/geo/assets/${assetId}/publish`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ publish_url: publishUrl ?? null }),
      })
      if (!r.ok) return
      // The backend emits geo.asset_published which the listener below
      // folds into the store; no need to mutate here.
    } catch {
      /* non-fatal */
    }
  },

  clear: () => set({ ...initial }),
}))

// ──────────────────────────────────────────────────────────────────────────
// Bus listeners — mutate the store as events arrive over the SSE channel.
// We scope every listener by brandId so simultaneous brands don't pollute
// each other (the dashboard only loads one at a time today, but the
// guarantee is cheap to keep).
// ──────────────────────────────────────────────────────────────────────────

function brandMatches(brandId: string | null, eventBrand: string | null): boolean {
  if (!brandId) return false
  return brandId === eventBrand
}

bus.on('geo.scan_started', (p) => {
  const s = useGeoStore.getState()
  if (!brandMatches(s.brandId, p.brand_id)) return
  useGeoStore.setState({ scanStatus: 'scanning', scanError: null })
})

bus.on('geo.scan_completed', (p) => {
  const s = useGeoStore.getState()
  if (!brandMatches(s.brandId, p.brand_id)) return
  useGeoStore.setState({
    scanStatus: 'done',
    fetchedAt: new Date().toISOString(),
  })
})

bus.on('geo.scan_unavailable', (p) => {
  const s = useGeoStore.getState()
  if (!brandMatches(s.brandId, p.brand_id)) return
  useGeoStore.setState({
    scanStatus: 'unavailable',
    scanError: p.reason,
  })
})

bus.on('geo.gap_detected', (p) => {
  useGeoStore.setState((s) => {
    if (!brandMatches(s.brandId, p.brand_id)) return s
    const next: State = {
      ...s,
      gaps: { ...s.gaps, [p.id]: p },
    }
    return { ...next, summary: computeSummary(next) }
  })
})

bus.on('geo.action_proposed', (p) => {
  useGeoStore.setState((s) => {
    if (!brandMatches(s.brandId, p.brand_id)) return s
    const next: State = {
      ...s,
      recommendations: { ...s.recommendations, [p.id]: p },
    }
    return { ...next, summary: computeSummary(next) }
  })
})

bus.on('geo.action_rejected', (p) => {
  useGeoStore.setState((s) => {
    const reco = s.recommendations[p.id]
    if (!reco) return s
    if (!brandMatches(s.brandId, p.brand_id)) return s
    const next: State = {
      ...s,
      recommendations: {
        ...s.recommendations,
        [p.id]: { ...reco, status: 'rejected' },
      },
    }
    return { ...next, summary: computeSummary(next) }
  })
})

bus.on('geo.asset_generating', (p) => {
  useGeoStore.setState((s) => {
    if (!brandMatches(s.brandId, p.brand_id)) return s
    const generating = { ...s.generating }
    if (p.status === 'failed') {
      delete generating[p.recommendation_id]
    } else {
      generating[p.recommendation_id] = {
        recommendation_id: p.recommendation_id,
        action_type: p.action_type,
        startedAt: new Date().toISOString(),
        error: p.error ?? null,
      }
    }
    return { ...s, generating }
  })
})

bus.on('geo.asset_generated', (p) => {
  useGeoStore.setState((s) => {
    if (!brandMatches(s.brandId, p.brand_id)) return s
    const generating = { ...s.generating }
    delete generating[p.recommendation_id]
    const recommendations = { ...s.recommendations }
    const reco = recommendations[p.recommendation_id]
    if (reco) {
      recommendations[p.recommendation_id] = { ...reco, status: 'generated' }
    }
    const gaps = { ...s.gaps }
    const gap = gaps[p.gap_id]
    if (gap) gaps[p.gap_id] = { ...gap, status: 'addressed' }
    const next: State = {
      ...s,
      generating,
      recommendations,
      gaps,
      assets: { ...s.assets, [p.id]: p },
    }
    return { ...next, summary: computeSummary(next) }
  })
})

bus.on('geo.asset_published', (p) => {
  useGeoStore.setState((s) => {
    if (!brandMatches(s.brandId, p.brand_id)) return s
    const next: State = {
      ...s,
      assets: { ...s.assets, [p.id]: p },
    }
    return { ...next, summary: computeSummary(next) }
  })
})

// Allow `void useGeoStore` side-effect imports — the listeners above
// need to be registered before the SSE stream starts dispatching events.
export type GeoStoreSnapshot = State & Actions
