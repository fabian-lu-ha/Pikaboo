import { create } from 'zustand'
import { bus } from '../events/bus'

// ─── shapes ────────────────────────────────────────────────────────────────
// Mirrors backend/app/api/pipelines.py.  Kept in this file so consumers
// don't have to import a half-typed second module — the canvas component
// owns the world state and only renders props it derives from these.

export type NodeKind = 'trigger' | 'source' | 'filter' | 'model' | 'destination'

export type NodeTint = 'violet' | 'emerald' | 'amber' | 'sky' | 'rose'

export type FlowNode = {
  id: string
  kind: NodeKind
  label: string
  name: string
  glyph: string
  tint: NodeTint
  x: number
  y: number
  config: Record<string, unknown>
}

export type FlowEdge = { id: string; from: string; to: string }

export type NodeRunStatus = 'pending' | 'running' | 'completed' | 'failed'

export type PipelineSummary = {
  id: string
  brand_id: string
  name: string
  nodes: FlowNode[]
  edges: FlowEdge[]
  created_at: string | null
  updated_at: string | null
}

export type PipelineRun = {
  id: string
  pipeline_id: string
  status: 'running' | 'completed' | 'failed'
  started_at: string | null
  finished_at: string | null
  node_states: Record<string, NodeRunStatus>
  logs: {
    node_id: string
    level: string
    msg?: string
    kind?: string
    preview?: Record<string, unknown>
    at: string
  }[]
  result: Record<string, unknown>
  error: string | null
}

type RunStatus = 'idle' | 'running' | 'completed' | 'failed'

type State = {
  brandId: string | null
  pipelineId: string | null
  name: string
  nodes: FlowNode[]
  edges: FlowEdge[]
  pipelines: PipelineSummary[]
  loading: boolean
  saving: boolean
  savedAt: string | null
  dirty: boolean
  runId: string | null
  runStatus: RunStatus
  nodeStates: Record<string, NodeRunStatus>
  runLogs: PipelineRun['logs']
  runResult: Record<string, unknown> | null
  runError: string | null
}

type Actions = {
  hydrate: (brandId: string) => Promise<void>
  load: (pipelineId: string) => Promise<void>
  selectOrCreate: (brandId: string, seed?: {
    name?: string
    nodes?: FlowNode[]
    edges?: FlowEdge[]
  }) => Promise<void>
  setName: (name: string) => void
  setNodes: (next: FlowNode[] | ((cur: FlowNode[]) => FlowNode[])) => void
  setEdges: (next: FlowEdge[] | ((cur: FlowEdge[]) => FlowEdge[])) => void
  saveNow: () => Promise<void>
  scheduleAutosave: () => void
  run: () => Promise<void>
  reset: () => void
}

const initial: State = {
  brandId: null,
  pipelineId: null,
  name: 'Untitled Pipeline',
  nodes: [],
  edges: [],
  pipelines: [],
  loading: false,
  saving: false,
  savedAt: null,
  dirty: false,
  runId: null,
  runStatus: 'idle',
  nodeStates: {},
  runLogs: [],
  runResult: null,
  runError: null,
}

let autosaveTimer: ReturnType<typeof setTimeout> | null = null

export const usePipelineStore = create<State & Actions>((set, get) => ({
  ...initial,

  hydrate: async (brandId) => {
    set({ brandId, loading: true })
    try {
      const r = await fetch(
        `/api/pipelines/?brand_id=${encodeURIComponent(brandId)}`,
      )
      if (!r.ok) throw new Error(`status ${r.status}`)
      const data = (await r.json()) as { pipelines: PipelineSummary[] }
      set({ pipelines: data.pipelines, loading: false })
    } catch (e) {
      console.error('pipelines.hydrate failed', e)
      set({ loading: false })
    }
  },

  load: async (pipelineId) => {
    set({ loading: true })
    try {
      const r = await fetch(`/api/pipelines/${encodeURIComponent(pipelineId)}`)
      if (!r.ok) throw new Error(`status ${r.status}`)
      const p = (await r.json()) as PipelineSummary & {
        recent_runs: PipelineRun[]
      }
      const latest = p.recent_runs?.[0]
      set({
        pipelineId: p.id,
        brandId: p.brand_id,
        name: p.name,
        nodes: p.nodes,
        edges: p.edges,
        loading: false,
        savedAt: p.updated_at,
        dirty: false,
        runId: latest?.id ?? null,
        runStatus:
          latest?.status === 'running'
            ? 'running'
            : latest?.status === 'completed'
              ? 'completed'
              : latest?.status === 'failed'
                ? 'failed'
                : 'idle',
        nodeStates: latest?.node_states ?? {},
        runLogs: latest?.logs ?? [],
        runResult: latest?.result ?? null,
        runError: latest?.error ?? null,
      })
    } catch (e) {
      console.error('pipelines.load failed', e)
      set({ loading: false })
    }
  },

  selectOrCreate: async (brandId, seed) => {
    const { pipelines } = get()
    if (pipelines.length > 0) {
      await get().load(pipelines[0].id)
      return
    }
    set({ saving: true, brandId })
    try {
      const body = {
        brand_id: brandId,
        name: seed?.name ?? 'Customer Sentiment Flow',
        nodes: seed?.nodes ?? [],
        edges: seed?.edges ?? [],
      }
      const r = await fetch('/api/pipelines/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`status ${r.status}`)
      const p = (await r.json()) as PipelineSummary
      set({
        pipelineId: p.id,
        name: p.name,
        nodes: p.nodes,
        edges: p.edges,
        savedAt: p.updated_at,
        dirty: false,
        saving: false,
        pipelines: [p, ...pipelines],
      })
    } catch (e) {
      console.error('pipelines.selectOrCreate failed', e)
      set({ saving: false })
    }
  },

  setName: (name) => {
    set({ name, dirty: true })
    get().scheduleAutosave()
  },

  setNodes: (next) => {
    set((s) => ({
      nodes: typeof next === 'function' ? next(s.nodes) : next,
      dirty: true,
    }))
    get().scheduleAutosave()
  },

  setEdges: (next) => {
    set((s) => ({
      edges: typeof next === 'function' ? next(s.edges) : next,
      dirty: true,
    }))
    get().scheduleAutosave()
  },

  scheduleAutosave: () => {
    if (autosaveTimer) clearTimeout(autosaveTimer)
    autosaveTimer = setTimeout(() => {
      void get().saveNow()
    }, 800)
  },

  saveNow: async () => {
    const { pipelineId, name, nodes, edges, brandId } = get()
    if (!brandId) return
    set({ saving: true })
    try {
      if (!pipelineId) {
        const r = await fetch('/api/pipelines/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ brand_id: brandId, name, nodes, edges }),
        })
        if (!r.ok) throw new Error(`status ${r.status}`)
        const p = (await r.json()) as PipelineSummary
        set({
          pipelineId: p.id,
          savedAt: p.updated_at,
          dirty: false,
          saving: false,
          pipelines: [p, ...get().pipelines],
        })
        return
      }
      const r = await fetch(
        `/api/pipelines/${encodeURIComponent(pipelineId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, nodes, edges }),
        },
      )
      if (!r.ok) throw new Error(`status ${r.status}`)
      const p = (await r.json()) as PipelineSummary
      set({
        savedAt: p.updated_at,
        dirty: false,
        saving: false,
      })
    } catch (e) {
      console.error('pipelines.saveNow failed', e)
      set({ saving: false })
    }
  },

  run: async () => {
    const { pipelineId, dirty, nodes } = get()
    if (!pipelineId) return
    if (nodes.length === 0) return
    if (dirty) {
      await get().saveNow()
    }
    set({
      runStatus: 'running',
      runId: null,
      nodeStates: Object.fromEntries(nodes.map((n) => [n.id, 'pending'])),
      runLogs: [],
      runResult: null,
      runError: null,
    })
    try {
      const r = await fetch(
        `/api/pipelines/${encodeURIComponent(pipelineId)}/run`,
        { method: 'POST' },
      )
      if (!r.ok) throw new Error(`status ${r.status}`)
    } catch (e) {
      console.error('pipelines.run failed', e)
      set({
        runStatus: 'failed',
        runError: (e as Error).message,
      })
    }
  },

  reset: () => set({ ...initial }),
}))

// ─── event bus subscriptions ───────────────────────────────────────────────
// The executor emits per-node events as it walks the graph. We mutate
// nodeStates/logs in place so the canvas lights each node up live.

bus.on('pipeline.run_started', (p) => {
  usePipelineStore.setState((s) => {
    if (s.pipelineId !== p.pipeline_id) return s
    return {
      runId: p.run_id,
      runStatus: 'running',
      nodeStates: Object.fromEntries(
        s.nodes.map((n) => [n.id, 'pending'] as const),
      ),
      runLogs: [],
      runResult: null,
      runError: null,
    }
  })
})

bus.on('pipeline.node_started', (p) => {
  usePipelineStore.setState((s) => {
    if (s.pipelineId !== p.pipeline_id) return s
    return {
      nodeStates: { ...s.nodeStates, [p.node_id]: 'running' },
    }
  })
})

bus.on('pipeline.node_completed', (p) => {
  usePipelineStore.setState((s) => {
    if (s.pipelineId !== p.pipeline_id) return s
    return {
      nodeStates: { ...s.nodeStates, [p.node_id]: 'completed' },
      runLogs: [
        ...s.runLogs,
        {
          node_id: p.node_id,
          level: 'info',
          kind: p.kind,
          preview: p.preview,
          at: new Date().toISOString(),
        },
      ],
    }
  })
})

bus.on('pipeline.node_failed', (p) => {
  usePipelineStore.setState((s) => {
    if (s.pipelineId !== p.pipeline_id) return s
    return {
      nodeStates: { ...s.nodeStates, [p.node_id]: 'failed' },
      runLogs: [
        ...s.runLogs,
        {
          node_id: p.node_id,
          level: 'error',
          msg: p.error,
          at: new Date().toISOString(),
        },
      ],
    }
  })
})

bus.on('pipeline.run_completed', (p) => {
  usePipelineStore.setState((s) => {
    if (s.pipelineId !== p.pipeline_id) return s
    return {
      runStatus: 'completed',
      runResult: p.result,
    }
  })
})

bus.on('pipeline.run_failed', (p) => {
  usePipelineStore.setState((s) => {
    if (s.pipelineId !== p.pipeline_id) return s
    return {
      runStatus: 'failed',
      runError: p.error,
    }
  })
})

bus.on('pipeline.saved', (p) => {
  usePipelineStore.setState((s) => {
    // Refresh the listing so the sidebar reflects newly-saved pipelines, but
    // don't clobber the live edit state — the optimistic save already set it.
    if (s.brandId !== p.brand_id) return s
    if (p.kind === 'created' && !s.pipelines.find((x) => x.id === p.pipeline_id)) {
      return {
        pipelines: [
          {
            id: p.pipeline_id,
            brand_id: p.brand_id,
            name: p.name,
            nodes: [],
            edges: [],
            created_at: null,
            updated_at: null,
          } as PipelineSummary,
          ...s.pipelines,
        ],
      }
    }
    return {
      pipelines: s.pipelines.map((row) =>
        row.id === p.pipeline_id ? { ...row, name: p.name } : row,
      ),
    }
  })
})
