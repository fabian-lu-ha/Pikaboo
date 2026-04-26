import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { motion } from 'motion/react'
import { TopBar } from './TopBar'
import { SavedAssets } from './SavedAssets'
import { useNav } from './navContext'
import { firstWord } from '../../lib/brandName'
import { bus } from '../../events/bus'
import {
  usePipelineStore,
  type FlowEdge,
  type FlowNode,
  type PipelineRun,
  type PipelineSummary,
} from '../../stores/pipelineStore'
import type { Brand, ConnectionSummary } from './types'

// ─── Recipes & Assets page ────────────────────────────────────────────────
// Surfaces what's *actually* wired up for this brand: live connection state
// from /api/onboarding/me's `connections` summary, real pipelines from
// /api/pipelines/, and a copilot that calls /api/pipelines/copilot to draft
// new ones. No hardcoded recipes, no canned chat replies, no mock counts.

type SourceState = 'connected' | 'idle' | 'empty'

type Source = {
  id: string
  name: string
  detail: string
  glyph: string
  tint: 'violet' | 'emerald' | 'amber' | 'sky'
  state: SourceState
}

const TINT: Record<
  Source['tint'],
  { bg: string; fg: string }
> = {
  violet: { bg: '#eef0ff', fg: '#5b50e6' },
  emerald: { bg: '#dcf3e9', fg: '#1f9e6e' },
  amber: { bg: '#fbe8d6', fg: '#d97a3a' },
  sky: { bg: '#e0e7ff', fg: '#4338ca' },
}

export function Library({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const sources = useSources(brand)

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-10">
        <div className="grid grid-cols-1 gap-6 pt-4 lg:grid-cols-[1fr_320px]">
          <div className="min-w-0">
            <Header brand={brand} />
            <DataSources sources={sources} />
            <ActiveRecipes brandId={brand.id} />
            <SavedAssets brandId={brand.id} />
          </div>
          <aside className="hidden lg:block">
            <div className="sticky top-4">
              <RecipeCopilot brand={brand} />
            </div>
          </aside>
        </div>
      </div>
    </main>
  )
}

function Header({ brand }: { brand: Brand }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <h1 className="text-[36px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
        Recipes &amp; Assets
      </h1>
      <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
        Manage {firstWord(brand.name)}'s data connections, brand assets, and
        the transformation pipelines that feed every campaign.
      </p>
    </motion.section>
  )
}

function DataSources({ sources }: { sources: Source[] }) {
  const { navigate } = useNav()
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className="mt-8"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-semibold">Data Sources</h2>
        <button
          onClick={() => navigate('settings')}
          className="rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-1.5 text-[12px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110"
        >
          + Add Source
        </button>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {sources.map((s) => (
          <SourceCard key={s.id} source={s} />
        ))}
        <ConnectNewCard onClick={() => navigate('settings')} />
      </div>
    </motion.section>
  )
}

function SourceCard({ source }: { source: Source }) {
  const t = TINT[source.tint]
  return (
    <div className="panel flex flex-col p-5">
      <div className="flex items-start justify-between">
        <span
          className="grid h-9 w-9 place-items-center rounded-lg text-base"
          style={{ background: t.bg, color: t.fg }}
        >
          {source.glyph}
        </span>
        <StatusPill state={source.state} />
      </div>
      <div className="mt-4 text-[13px] font-medium leading-tight">
        {source.name}
      </div>
      <div className="mt-1 text-[12px] text-fg-mute">{source.detail}</div>
    </div>
  )
}

function ConnectNewCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="flex flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-line bg-bg-card/40 px-5 py-6 text-fg-mute transition hover:border-accent hover:text-accent"
    >
      <span className="grid h-9 w-9 place-items-center rounded-full bg-accent-soft text-accent">
        +
      </span>
      <span className="text-[12px] font-medium">Connect New</span>
    </button>
  )
}

function StatusPill({ state }: { state: SourceState }) {
  if (state === 'connected') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Connected
      </span>
    )
  }
  if (state === 'idle') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-soft px-2 py-0.5 text-[10px] font-medium text-fg-mute">
        <span className="h-1.5 w-1.5 rounded-full bg-fg-dim" />
        Idle
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
      <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
      Setup
    </span>
  )
}

// ─── Active Recipes ───────────────────────────────────────────────────────
// Recipes ARE pipelines. We hydrate the store and listen to live save/run
// events so the list reflects the pipeline editor and copilot in real time.

type RecipeView = {
  id: string
  name: string
  cadence: string
  state: 'live' | 'scheduled' | 'failed' | 'idle'
}

function ActiveRecipes({ brandId }: { brandId: string }) {
  const { navigate } = useNav()
  const pipelines = usePipelineStore((s) => s.pipelines)
  const hydrate = usePipelineStore((s) => s.hydrate)
  const load = usePipelineStore((s) => s.load)
  const [runMeta, setRunMeta] = useState<
    Record<string, { state: RecipeView['state']; cadence: string } | undefined>
  >({})
  const [removing, setRemoving] = useState<Record<string, boolean>>({})
  const [removed, setRemoved] = useState<Set<string>>(new Set())

  // Hydrate the pipeline list and fetch each pipeline's most recent run so
  // the cadence text reflects reality ("3 hours ago", "Failed", etc).
  useEffect(() => {
    let cancelled = false
    void (async () => {
      await hydrate(brandId)
      if (cancelled) return
      const list = usePipelineStore.getState().pipelines
      const results = await Promise.all(
        list.map(async (p) => {
          try {
            const r = await fetch(
              `/api/pipelines/${encodeURIComponent(p.id)}/runs?limit=1`,
            )
            if (!r.ok) return [p.id, undefined] as const
            const data = (await r.json()) as { runs: PipelineRun[] }
            const latest = data.runs[0]
            return [p.id, runMetaFor(latest)] as const
          } catch {
            return [p.id, undefined] as const
          }
        }),
      )
      if (cancelled) return
      const next: Record<string, { state: RecipeView['state']; cadence: string } | undefined> = {}
      for (const [id, meta] of results) next[id] = meta
      setRunMeta(next)
    })()
    return () => {
      cancelled = true
    }
  }, [brandId, hydrate])

  // Live updates: when the copilot creates a pipeline or the editor runs one,
  // reflect it without a full re-fetch. mitt's bus.on returns void, so we
  // hand the handlers to bus.off to clean up on unmount.
  useEffect(() => {
    const onSaved = (p: { brand_id: string; pipeline_id: string; kind: string }) => {
      if (p.brand_id !== brandId) return
      if (p.kind === 'created') {
        setRunMeta((m) => ({ ...m, [p.pipeline_id]: { state: 'idle', cadence: 'Never run' } }))
      }
    }
    const onRun = (p: { pipeline_id: string }) => {
      setRunMeta((m) => ({
        ...m,
        [p.pipeline_id]: { state: 'live', cadence: 'Just ran' },
      }))
    }
    const onFail = (p: { pipeline_id: string; error: string }) => {
      setRunMeta((m) => ({
        ...m,
        [p.pipeline_id]: { state: 'failed', cadence: `Failed · ${p.error}` },
      }))
    }
    const onStart = (p: { pipeline_id: string }) => {
      setRunMeta((m) => ({
        ...m,
        [p.pipeline_id]: { state: 'live', cadence: 'Running…' },
      }))
    }
    bus.on('pipeline.saved', onSaved)
    bus.on('pipeline.run_completed', onRun)
    bus.on('pipeline.run_failed', onFail)
    bus.on('pipeline.run_started', onStart)
    return () => {
      bus.off('pipeline.saved', onSaved)
      bus.off('pipeline.run_completed', onRun)
      bus.off('pipeline.run_failed', onFail)
      bus.off('pipeline.run_started', onStart)
    }
  }, [brandId])

  const recipes: RecipeView[] = useMemo(
    () =>
      pipelines
        .filter((p) => !removed.has(p.id))
        .map((p) => {
          const meta = runMeta[p.id]
          return {
            id: p.id,
            name: p.name,
            cadence: meta?.cadence ?? 'Never run',
            state: meta?.state ?? 'idle',
          }
        }),
    [pipelines, runMeta, removed],
  )

  async function openInEditor(id: string) {
    await load(id)
    navigate('pipeline')
  }

  async function runPipeline(id: string) {
    setRunMeta((m) => ({ ...m, [id]: { state: 'live', cadence: 'Running…' } }))
    try {
      await fetch(`/api/pipelines/${encodeURIComponent(id)}/run`, {
        method: 'POST',
      })
    } catch (e) {
      setRunMeta((m) => ({
        ...m,
        [id]: { state: 'failed', cadence: `Failed · ${(e as Error).message}` },
      }))
    }
  }

  async function removeRecipe(id: string) {
    setRemoving((s) => ({ ...s, [id]: true }))
    try {
      const r = await fetch(`/api/pipelines/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      })
      if (!r.ok) throw new Error(`status ${r.status}`)
      setRemoved((s) => new Set(s).add(id))
      // Also drop it out of the store's listing so other views stay in sync.
      usePipelineStore.setState((s) => ({
        pipelines: s.pipelines.filter((p) => p.id !== id),
        ...(s.pipelineId === id
          ? { pipelineId: null, nodes: [], edges: [], name: 'Untitled Pipeline' }
          : {}),
      }))
    } catch (e) {
      console.error('pipeline delete failed', e)
    } finally {
      setRemoving((s) => ({ ...s, [id]: false }))
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className="mt-8"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-semibold">Active Recipes</h2>
        <button
          onClick={() => navigate('pipeline')}
          className="text-[11px] font-medium text-accent hover:underline"
        >
          Open pipeline →
        </button>
      </div>
      <ul className="panel mt-4 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]">
        {recipes.length === 0 ? (
          <li className="px-5 py-8 text-center text-[12px] text-fg-mute">
            No pipelines yet — ask the Recipe Copilot to draft one, or open the
            AI Pipeline editor.
          </li>
        ) : (
          recipes.map((r) => (
            <RecipeRow
              key={r.id}
              recipe={r}
              busy={!!removing[r.id]}
              onOpen={() => openInEditor(r.id)}
              onRun={() => runPipeline(r.id)}
              onDelete={() => removeRecipe(r.id)}
            />
          ))
        )}
      </ul>
    </motion.section>
  )
}

function runMetaFor(
  run: PipelineRun | undefined,
): { state: RecipeView['state']; cadence: string } | undefined {
  if (!run) return { state: 'idle', cadence: 'Never run' }
  const ts = run.finished_at ?? run.started_at
  const when = ts ? relativeTime(ts) : 'just now'
  if (run.status === 'running') return { state: 'live', cadence: `Running · started ${when}` }
  if (run.status === 'failed')
    return { state: 'failed', cadence: `Failed ${when}${run.error ? ` · ${run.error}` : ''}` }
  return { state: 'live', cadence: `Last run ${when}` }
}

function relativeTime(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return iso
  const diff = Date.now() - t
  const m = Math.round(diff / 60_000)
  if (m < 1) return 'just now'
  if (m < 60) return `${m}m ago`
  const h = Math.round(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.round(h / 24)
  if (d < 30) return `${d}d ago`
  return new Date(iso).toLocaleDateString()
}

function RecipeRow({
  recipe,
  busy,
  onOpen,
  onRun,
  onDelete,
}: {
  recipe: RecipeView
  busy: boolean
  onOpen: () => void
  onRun: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDoc(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDoc)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <li className="flex items-center gap-4 px-5 py-4">
      <button
        onClick={onOpen}
        className="grid h-9 w-9 place-items-center rounded-lg bg-accent-soft text-[14px] text-accent transition hover:brightness-95"
        aria-label="Open in pipeline editor"
      >
        ⚙
      </button>
      <button
        onClick={onOpen}
        className="min-w-0 flex-1 text-left"
      >
        <div className="text-[13px] font-medium leading-tight">
          {recipe.name}
        </div>
        <div className="mt-0.5 truncate text-[12px] text-fg-mute">
          {recipe.cadence}
        </div>
      </button>
      <RecipeStatePill state={recipe.state} />
      <div ref={wrapRef} className="relative">
        <button
          aria-label="More"
          onClick={() => setOpen((o) => !o)}
          disabled={busy}
          className="grid h-7 w-7 place-items-center rounded-md text-fg-dim hover:bg-bg-soft hover:text-fg disabled:opacity-40"
        >
          ⋯
        </button>
        {open && (
          <div className="absolute right-0 top-8 z-20 w-44 overflow-hidden rounded-xl bg-bg-card shadow-[0_8px_24px_rgba(20,20,40,0.12)] hairline">
            <button
              onClick={() => {
                onRun()
                setOpen(false)
              }}
              className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12.5px] hover:bg-bg-soft"
            >
              ▶ Run now
            </button>
            <button
              onClick={() => {
                onOpen()
                setOpen(false)
              }}
              className="flex w-full items-center gap-2 border-t border-line-soft px-3 py-2 text-left text-[12.5px] hover:bg-bg-soft"
            >
              ✎ Edit
            </button>
            <button
              onClick={() => {
                onDelete()
                setOpen(false)
              }}
              className="flex w-full items-center gap-2 border-t border-line-soft px-3 py-2 text-left text-[12.5px] text-red-600 hover:bg-red-50"
            >
              ⌫ Delete
            </button>
          </div>
        )}
      </div>
    </li>
  )
}

function RecipeStatePill({ state }: { state: RecipeView['state'] }) {
  if (state === 'live') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-700">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
        Live
      </span>
    )
  }
  if (state === 'scheduled') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-soft px-2.5 py-1 text-[10px] font-medium text-fg-mute">
        ◷ Scheduled
      </span>
    )
  }
  if (state === 'failed') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-1 text-[10px] font-medium text-red-700">
        ⚠ Failed
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-soft px-2.5 py-1 text-[10px] font-medium text-fg-mute">
      ◌ Idle
    </span>
  )
}

// ─── Recipe Copilot ───────────────────────────────────────────────────────
// Real LLM chat. Calls /api/pipelines/copilot which is grounded in the
// brand's actual connection state and responds with either a clarifying
// question or a concrete pipeline scaffold the user can accept to create.

type CopilotMessage = {
  id: string
  role: 'agent' | 'user'
  text: string
  // When the agent suggests a runnable pipeline, attach the scaffold so the
  // bubble can render an inline "Create pipeline" button.
  suggestion?: SuggestedPipeline
  status?: 'pending' | 'created' | 'error'
}

type SuggestedPipeline = {
  name: string
  summary?: string
  nodes: FlowNode[]
  edges: FlowEdge[]
}

function RecipeCopilot({ brand }: { brand: Brand }) {
  const [draft, setDraft] = useState('')
  const [messages, setMessages] = useState<CopilotMessage[]>(() => [
    {
      id: 'seed-greet',
      role: 'agent',
      text: `Hi — I'm the Recipe Copilot. I can scaffold pipelines for ${firstWord(brand.name)} from your real connections. Try "weekly competitor digest" or "lapsed customer flag".`,
    },
  ])
  const [thinking, setThinking] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const counter = useRef(0)
  const id = (prefix: string) => {
    counter.current += 1
    return `${prefix}-${Date.now()}-${counter.current}`
  }

  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, thinking])

  async function send(text?: string) {
    const value = (text ?? draft).trim()
    if (!value || thinking) return
    const userMsg: CopilotMessage = { id: id('u'), role: 'user', text: value }
    const history = messages
      .filter((m) => m.id !== 'seed-greet')
      .map((m) => ({ role: m.role, text: m.text }))
    setMessages((m) => [...m, userMsg])
    setDraft('')
    setThinking(true)
    try {
      const r = await fetch('/api/pipelines/copilot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          brand_id: brand.id,
          prompt: value,
          history,
        }),
      })
      if (!r.ok) throw new Error(`status ${r.status}`)
      const data = (await r.json()) as {
        reply: string
        suggested_pipeline: SuggestedPipeline | null
      }
      setMessages((m) => [
        ...m,
        {
          id: id('a'),
          role: 'agent',
          text: data.reply,
          suggestion: data.suggested_pipeline ?? undefined,
          status: data.suggested_pipeline ? 'pending' : undefined,
        },
      ])
    } catch (e) {
      setMessages((m) => [
        ...m,
        {
          id: id('a'),
          role: 'agent',
          text: `Couldn't reach the copilot — ${(e as Error).message}. Try again in a moment.`,
        },
      ])
    } finally {
      setThinking(false)
    }
  }

  async function acceptSuggestion(messageId: string) {
    const target = messages.find((m) => m.id === messageId)
    const sug = target?.suggestion
    if (!sug) return
    setMessages((m) =>
      m.map((x) => (x.id === messageId ? { ...x, status: 'pending' } : x)),
    )
    try {
      const r = await fetch('/api/pipelines/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          brand_id: brand.id,
          name: sug.name,
          nodes: sug.nodes,
          edges: sug.edges,
        }),
      })
      if (!r.ok) throw new Error(`status ${r.status}`)
      const created = (await r.json()) as PipelineSummary
      // Optimistically prepend to the store's pipeline list so the
      // ActiveRecipes section shows it before any SSE round-trip.
      usePipelineStore.setState((s) => ({
        pipelines: [created, ...s.pipelines.filter((p) => p.id !== created.id)],
      }))
      setMessages((m) =>
        m.map((x) =>
          x.id === messageId
            ? {
                ...x,
                status: 'created',
                text: `${x.text}\n\nCreated "${created.name}". You can run it from Active Recipes or open it in the pipeline editor.`,
              }
            : x,
        ),
      )
    } catch (e) {
      setMessages((m) =>
        m.map((x) =>
          x.id === messageId
            ? {
                ...x,
                status: 'error',
                text: `${x.text}\n\nCouldn't create the pipeline — ${(e as Error).message}.`,
              }
            : x,
        ),
      )
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    void send()
  }

  return (
    <motion.aside
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.12 }}
      className="relative flex h-[min(60vh,460px)] min-h-[360px] flex-col overflow-hidden rounded-2xl bg-gradient-to-br from-accent to-[var(--color-accent-deep)] text-white shadow-[0_10px_30px_rgba(91,80,230,0.25)]"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-12 -top-16 h-44 w-44 rounded-full bg-white/10 blur-2xl"
      />
      <header className="flex items-center gap-2 px-5 pt-5">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-white/15 text-[12px]">
          ✦
        </span>
        <div className="leading-tight">
          <div className="text-[13px] font-semibold">Recipe Copilot</div>
          <div className="text-[11px] text-white/70">
            {thinking ? 'thinking…' : `Grounded in ${firstWord(brand.name)}'s data`}
          </div>
        </div>
      </header>

      <div
        ref={scrollRef}
        className="mt-5 flex-1 space-y-3 overflow-y-auto overscroll-contain px-5 pb-3 [scrollbar-width:thin]"
      >
        {messages.map((m) =>
          m.role === 'agent' ? (
            <div key={m.id} className="space-y-2">
              <div className="max-w-[88%] whitespace-pre-wrap rounded-2xl rounded-tl-sm bg-white/15 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-white/95">
                {m.text}
              </div>
              {m.suggestion && (
                <SuggestionCard
                  suggestion={m.suggestion}
                  status={m.status ?? 'pending'}
                  onAccept={() => acceptSuggestion(m.id)}
                />
              )}
            </div>
          ) : (
            <div
              key={m.id}
              className="ml-auto max-w-[88%] rounded-2xl rounded-tr-sm bg-white/90 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-fg"
            >
              {m.text}
            </div>
          ),
        )}
        {thinking && (
          <div className="max-w-[88%] rounded-2xl rounded-tl-sm bg-white/15 px-3.5 py-2.5 text-[12.5px] text-white/90">
            <span className="inline-flex gap-0.5 [&>span]:h-1.5 [&>span]:w-1.5 [&>span]:rounded-full [&>span]:bg-white/90">
              <span className="animate-bounce [animation-delay:-0.2s]" />
              <span className="animate-bounce [animation-delay:-0.1s]" />
              <span className="animate-bounce" />
            </span>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="px-3 pb-3">
        <div className="flex items-center gap-2 rounded-full bg-white/15 px-2 py-1 backdrop-blur-sm">
          <input
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={`Ask copilot to build a recipe for ${firstWord(brand.name)}…`}
            disabled={thinking}
            className="flex-1 bg-transparent px-3 py-1.5 text-[12.5px] text-white placeholder:text-white/60 outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!draft.trim() || thinking}
            className="grid h-7 w-7 place-items-center rounded-full bg-white text-accent shadow-[0_2px_8px_rgba(0,0,0,0.15)] transition hover:brightness-105 disabled:bg-white/40 disabled:text-white/70"
            aria-label="Send"
          >
            →
          </button>
        </div>
      </form>
    </motion.aside>
  )
}

function SuggestionCard({
  suggestion,
  status,
  onAccept,
}: {
  suggestion: SuggestedPipeline
  status: 'pending' | 'created' | 'error'
  onAccept: () => void
}) {
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const n of suggestion.nodes) c[n.kind] = (c[n.kind] ?? 0) + 1
    return c
  }, [suggestion.nodes])

  return (
    <div className="max-w-[88%] rounded-2xl bg-white/95 p-3 text-fg shadow-[0_4px_14px_rgba(20,20,40,0.18)]">
      <div className="flex items-center justify-between">
        <div className="text-[12px] font-semibold">{suggestion.name}</div>
        <div className="text-[10px] text-fg-mute">
          {suggestion.nodes.length} nodes · {suggestion.edges.length} edges
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {Object.entries(counts).map(([kind, n]) => (
          <span
            key={kind}
            className="inline-flex items-center gap-1 rounded-full bg-bg-soft px-2 py-0.5 text-[10px] font-medium text-fg-mute"
          >
            {kind} × {n}
          </span>
        ))}
      </div>
      <button
        onClick={onAccept}
        disabled={status !== 'pending'}
        className="mt-3 w-full rounded-xl bg-accent px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] transition hover:brightness-110 disabled:opacity-60"
      >
        {status === 'created'
          ? '✓ Created'
          : status === 'error'
            ? 'Retry create'
            : 'Create pipeline'}
      </button>
    </div>
  )
}

// ─── Connection summary → source cards ────────────────────────────────────
// One source of truth: brand.connections from /api/onboarding/me. The shape
// is computed server-side so we don't have to hit four endpoints from the
// client to describe one page.

function useSources(brand: Brand): Source[] {
  const conn: ConnectionSummary | undefined = brand.connections
  const kanbanProviders = conn?.kanban.providers ?? []
  const kanbanCards = conn?.kanban.card_count ?? 0
  const crmProviders = conn?.crm.providers ?? []
  const customerCount = conn?.crm.customer_count ?? 0
  const socialProviders = conn?.social.providers ?? []
  const handles = brand.handles ?? {}
  const competitorCount = brand.competitors.length

  const kanbanLastSync = mostRecent(
    kanbanProviders.map((p) => p.last_synced_at),
  )
  const crmLastSync = mostRecent(crmProviders.map((p) => p.last_synced_at))

  return [
    {
      id: 'kanban',
      name: 'Kanban Boards',
      detail: kanbanProviders.length
        ? `${humanProviderList(kanbanProviders.map((p) => p.provider))} · ${kanbanCards} cards${
            kanbanLastSync ? ` · synced ${relativeTime(kanbanLastSync)}` : ''
          }`
        : 'Trello / Linear / Notion — not connected',
      glyph: '◫',
      tint: 'violet',
      state: kanbanProviders.length ? 'connected' : 'empty',
    },
    {
      id: 'crm',
      name: 'CRM / Audience',
      detail: crmProviders.length
        ? `${humanProviderList(crmProviders.map((p) => p.provider))} · ${customerCount} customers${
            crmLastSync ? ` · synced ${relativeTime(crmLastSync)}` : ''
          }`
        : customerCount > 0
          ? `${customerCount} customers (mock import)`
          : 'HubSpot / Klaviyo — not connected',
      glyph: '◉',
      tint: 'emerald',
      state: crmProviders.length || customerCount > 0 ? 'connected' : 'empty',
    },
    {
      id: 'social',
      name: 'Social Handles',
      detail:
        socialProviders.length > 0
          ? socialProviders
              .map((p) =>
                p.username
                  ? `${p.provider}: @${p.username.replace(/^@/, '')}`
                  : p.provider,
              )
              .join(' · ')
          : Object.keys(handles).length > 0
            ? Object.entries(handles)
                .map(([k, v]) => `${k}: ${v}`)
                .join(' · ')
            : 'IG · LinkedIn · X · TikTok — not connected',
      glyph: '◐',
      tint: 'amber',
      state:
        socialProviders.length > 0
          ? 'connected'
          : Object.keys(handles).length > 0
            ? 'idle'
            : 'empty',
    },
    {
      id: 'competitors',
      name: 'Competitor Set',
      detail:
        competitorCount > 0
          ? `${competitorCount} tracked · feeds digests + PEEC snapshots`
          : 'No competitors yet — add some during onboarding',
      glyph: '◇',
      tint: 'sky',
      state: competitorCount > 0 ? 'connected' : 'empty',
    },
  ]
}

function humanProviderList(providers: string[]): string {
  return providers.map((p) => p[0].toUpperCase() + p.slice(1)).join(', ')
}

function mostRecent(values: (string | null | undefined)[]): string | null {
  let best: number | null = null
  let chosen: string | null = null
  for (const v of values) {
    if (!v) continue
    const t = new Date(v).getTime()
    if (Number.isNaN(t)) continue
    if (best === null || t > best) {
      best = t
      chosen = v
    }
  }
  return chosen
}
