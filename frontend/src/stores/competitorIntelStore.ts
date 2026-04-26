import { create } from 'zustand'
import { bus, type ResearchSource } from '../events/bus'

// Per-competitor Tavily intel state. Map keyed by competitor_id so multiple
// modal opens (or background refreshes) don't trample each other.

export type IntelStatus =
  | 'idle'
  | 'fetching'
  | 'ready'
  | 'unavailable'
  | 'failed'

export type CompetitorIntelEntry = {
  competitorId: string
  status: IntelStatus
  sources: ResearchSource[]
  answer: string | null
  fetchedAt: string | null
  error: string | null
}

type State = {
  byId: Record<string, CompetitorIntelEntry>
}

type Actions = {
  hydrate: (
    competitorId: string,
    payload: {
      sources?: ResearchSource[]
      answer?: string | null
      fetched_at?: string | null
      error?: string | null
    } | null,
  ) => void
  reset: (competitorId?: string) => void
}

function blankEntry(competitorId: string): CompetitorIntelEntry {
  return {
    competitorId,
    status: 'idle',
    sources: [],
    answer: null,
    fetchedAt: null,
    error: null,
  }
}

export const useCompetitorIntelStore = create<State & Actions>((set) => ({
  byId: {},
  hydrate: (competitorId, payload) =>
    set((s) => {
      const sources = (payload?.sources ?? []).filter((x) => x && x.url)
      return {
        byId: {
          ...s.byId,
          [competitorId]: {
            competitorId,
            status: payload?.error
              ? 'failed'
              : sources.length > 0
                ? 'ready'
                : 'idle',
            sources,
            answer: payload?.answer ?? null,
            fetchedAt: payload?.fetched_at ?? null,
            error: payload?.error ?? null,
          },
        },
      }
    }),
  reset: (competitorId) =>
    set((s) =>
      competitorId
        ? { byId: { ...s.byId, [competitorId]: blankEntry(competitorId) } }
        : { byId: {} },
    ),
}))

function patch(
  competitorId: string,
  update: Partial<CompetitorIntelEntry>,
) {
  useCompetitorIntelStore.setState((s) => {
    const current = s.byId[competitorId] ?? blankEntry(competitorId)
    return {
      byId: {
        ...s.byId,
        [competitorId]: { ...current, ...update },
      },
    }
  })
}

bus.on('competitor.intel_requested', (p) => {
  patch(p.competitor_id, {
    status: 'fetching',
    sources: [],
    answer: null,
    error: null,
    fetchedAt: null,
  })
})

bus.on('competitor.intel_source_added', (p) => {
  useCompetitorIntelStore.setState((s) => {
    const current = s.byId[p.competitor_id] ?? blankEntry(p.competitor_id)
    if (current.sources.some((x) => x.url === p.source.url)) return s
    return {
      byId: {
        ...s.byId,
        [p.competitor_id]: {
          ...current,
          status: current.status === 'idle' ? 'fetching' : current.status,
          sources: [...current.sources, p.source],
        },
      },
    }
  })
})

bus.on('competitor.intel_completed', (p) => {
  patch(p.competitor_id, {
    status: p.source_count === 0 ? 'unavailable' : 'ready',
    answer: p.answer,
    sources: p.sources,
    fetchedAt: p.fetched_at,
    error: null,
  })
})

bus.on('competitor.intel_failed', (p) => {
  patch(p.competitor_id, { status: 'failed', error: p.error })
})

bus.on('competitor.intel_unavailable', (p) => {
  patch(p.competitor_id, { status: 'unavailable', error: p.reason })
})
