import { create } from 'zustand'
import {
  bus,
  type ResearchBundle,
  type ResearchScope,
  type ResearchSource,
} from '../events/bus'

type ScopeState = {
  scopeId: string | null
  status: 'idle' | 'fetching' | 'ready' | 'unavailable' | 'failed'
  sources: ResearchSource[]
  answer: string | null
  error: string | null
  fetchedAt: string | null
  query: string | null
}

type State = {
  brand: ScopeState
  campaign: ScopeState
}

type Actions = {
  reset: (scope?: ResearchScope) => void
  hydrateBrand: (bundle: ResearchBundle) => void
}

const emptyScope: ScopeState = {
  scopeId: null,
  status: 'idle',
  sources: [],
  answer: null,
  error: null,
  fetchedAt: null,
  query: null,
}

const initial: State = {
  brand: { ...emptyScope },
  campaign: { ...emptyScope },
}

export const useResearchStore = create<State & Actions>((set) => ({
  ...initial,
  reset: (scope) =>
    set((s) =>
      scope
        ? { ...s, [scope]: { ...emptyScope } }
        : { ...initial },
    ),
  hydrateBrand: (bundle) =>
    set((s) => ({
      ...s,
      brand: {
        scopeId: bundle.brand_id ?? null,
        status: bundle.error ? 'failed' : bundle.sources.length ? 'ready' : 'idle',
        sources: bundle.sources ?? [],
        answer: bundle.answer ?? null,
        error: bundle.error ?? null,
        fetchedAt: bundle.fetched_at ?? null,
        query: null,
      },
    })),
}))

function patchScope(
  scope: ResearchScope,
  patch: Partial<ScopeState>,
  scopeId?: string,
) {
  useResearchStore.setState((s) => {
    const current = s[scope]
    // If a new scope_id starts (new campaign), reset before patching.
    const sameScope = !scopeId || !current.scopeId || current.scopeId === scopeId
    const base: ScopeState = sameScope ? current : { ...emptyScope }
    return {
      ...s,
      [scope]: {
        ...base,
        ...(scopeId ? { scopeId } : {}),
        ...patch,
      },
    }
  })
}

bus.on('research.requested', (p) => {
  patchScope(
    p.scope,
    {
      status: 'fetching',
      sources: [],
      answer: null,
      error: null,
      fetchedAt: null,
      query: p.user_request ?? p.brand_name ?? null,
    },
    p.scope_id,
  )
})

bus.on('research.source_added', (p) => {
  useResearchStore.setState((s) => {
    const current = s[p.scope]
    if (current.scopeId && current.scopeId !== p.scope_id) return s
    if (current.sources.some((x) => x.url === p.source.url)) return s
    return {
      ...s,
      [p.scope]: {
        ...current,
        scopeId: current.scopeId ?? p.scope_id,
        status: current.status === 'idle' ? 'fetching' : current.status,
        sources: [...current.sources, p.source],
      },
    }
  })
})

bus.on('research.completed', (p) => {
  patchScope(
    p.scope,
    {
      status: p.source_count === 0 ? 'unavailable' : 'ready',
      sources: p.sources,
      answer: p.answer,
      fetchedAt: p.fetched_at,
      error: null,
    },
    p.scope_id,
  )
})

bus.on('research.failed', (p) => {
  patchScope(
    p.scope,
    { status: 'failed', error: p.error },
    p.scope_id,
  )
})

bus.on('research.unavailable', (p) => {
  patchScope(
    p.scope,
    { status: 'unavailable', error: p.reason },
    p.scope_id,
  )
})
