import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { TopBar } from './TopBar'
import { useNav } from './navContext'
import { InitialsAvatar } from '../InitialsAvatar'
import { InstagramInsights } from './InstagramInsights'
import { firstWord } from '../../lib/brandName'
import type { Brand } from './types'

type Window = '90D' | '6M' | '1Y'

type MarketPosition = {
  score: number | null
  delta: number | null
  percentile: number | null
  share_of_voice: number | null
  sentiment: number | null
  explanation: string
}

type TrajectoryBucket = {
  label: string
  value: number
  iso: string
}

type GrowthTrajectory = {
  metric: string
  metric_label: string
  buckets: TrajectoryBucket[]
  total: number
  delta_pct: number | null
}

type CompetitorRow = {
  id: string
  name: string
  url: string | null
  visibility: number | null
  share_of_voice: number | null
  delta: number | null
  rank_label: string
  has_peec_data: boolean
}

type SynthesisAction = { label: string; rationale: string }

type AISynthesis = {
  summary: string
  actions: SynthesisAction[]
  top_competitor: string | null
  absent_prompts: string[]
}

type DataSources = {
  peec: 'connected' | 'no_data' | 'not_configured'
  peec_transport: 'mcp' | 'rest' | 'none'
  customers_count: number
  campaigns_count: number
  email_sends_count: number
}

type EngineBreakdown = {
  engine: string
  label: string
  visibility: number | null
  share_of_voice: number | null
  rank: number | null
  sample_count: number | null
}

type CitationRow = {
  domain: string
  citation_count: number | null
  rank: number | null
  favicon_url: string | null
}

type PromptDrillDown = {
  prompt: string
  own_rank: number | null
  own_visibility: number | null
  winner: string | null
  winner_visibility: number | null
  engines: string[]
  cited_domains: string[]
  last_seen_at: string | null
}

type Overview = {
  brand_id: string
  brand_name: string
  window: Window
  fetched_at: string
  market_position: MarketPosition | null
  growth_trajectory: GrowthTrajectory
  competitor_radar: CompetitorRow[]
  engine_breakdown: EngineBreakdown[]
  citations: CitationRow[]
  prompt_drilldown: PromptDrillDown[]
  ai_synthesis: AISynthesis | null
  data_sources: DataSources
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: Overview }

type SynthesisState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: AISynthesis | null }

export function Analytics({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const [windowSel, setWindowSel] = useState<Window>('6M')
  const [state, setState] = useState<LoadState>({ kind: 'loading' })
  const [synth, setSynth] = useState<SynthesisState>({ kind: 'idle' })
  const [reloadTick, setReloadTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setState({ kind: 'loading' })
      setSynth({ kind: 'loading' })

      // Fire both in parallel — overview lands ~30ms, synthesis lands
      // 6s+ on a cache miss. Page paints from overview while we wait.
      const overviewP = fetch(
        `/api/analytics/overview?brand_id=${encodeURIComponent(brand.id)}&window=${windowSel}`,
      )
      const synthesisP = fetch(
        `/api/analytics/synthesis?brand_id=${encodeURIComponent(brand.id)}&window=${windowSel}`,
      )

      try {
        const r = await overviewP
        if (cancelled) return
        if (!r.ok) {
          const detail = await r
            .json()
            .then((j) => j?.detail ?? null)
            .catch(() => null)
          setState({
            kind: 'error',
            message: detail ?? `Analytics failed (${r.status})`,
          })
          return
        }
        setState({ kind: 'ok', data: await r.json() })
      } catch (e) {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: e instanceof Error ? e.message : 'Network error',
          })
        }
        return
      }

      try {
        const r = await synthesisP
        if (cancelled) return
        if (!r.ok) {
          setSynth({
            kind: 'error',
            message: `Synthesis unavailable (${r.status})`,
          })
          return
        }
        const data = (await r.json()) as AISynthesis | null
        setSynth({ kind: 'ok', data })
      } catch (e) {
        if (!cancelled) {
          setSynth({
            kind: 'error',
            message: e instanceof Error ? e.message : 'Synthesis failed',
          })
        }
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [brand.id, windowSel, reloadTick])

  const refresh = () => setReloadTick((t) => t + 1)

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-10">
        <Header
          brand={brand}
          window={windowSel}
          state={state}
          synth={synth}
        />

        {state.kind === 'loading' && <LoadingSkeleton />}
        {state.kind === 'error' && <ErrorState message={state.message} />}
        {state.kind === 'ok' && (
          <Body
            brand={brand}
            data={state.data}
            synth={synth}
            window={windowSel}
            onWindow={setWindowSel}
            onPeecConnected={refresh}
          />
        )}

        <InstagramInsights brand={brand} />
      </div>
    </main>
  )
}

function Body({
  brand,
  data,
  synth,
  window,
  onWindow,
  onPeecConnected,
}: {
  brand: Brand
  data: Overview
  synth: SynthesisState
  window: Window
  onWindow: (w: Window) => void
  onPeecConnected: () => void
}) {
  const [activePrompt, setActivePrompt] = useState<PromptDrillDown | null>(null)
  const hasEngines = data.engine_breakdown.length > 0
  const hasCitations = data.citations.length > 0
  const hasDrilldown = data.prompt_drilldown.length > 0

  return (
    <>
      <DataSourcesBar sources={data.data_sources} fetchedAt={data.fetched_at} />

      <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-[1fr_1.4fr]">
        <MarketPositionCard
          market={data.market_position}
          sources={data.data_sources}
          onPeecConnected={onPeecConnected}
        />
        <GrowthTrajectoryCard
          growth={data.growth_trajectory}
          window={window}
          onWindow={onWindow}
        />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-[1.6fr_1fr]">
        <CompetitorRadarCard rows={data.competitor_radar} />
        <AISynthesisCard
          brand={brand}
          synth={synth}
          peecStatus={data.data_sources.peec}
        />
      </div>

      {(hasEngines || hasCitations) && (
        <div className="mt-5 grid grid-cols-1 gap-5 md:grid-cols-[1fr_1fr]">
          {hasEngines && (
            <EngineBreakdownCard engines={data.engine_breakdown} />
          )}
          {hasCitations && (
            <CitationSurfaceCard citations={data.citations} />
          )}
        </div>
      )}

      {hasDrilldown && (
        <PromptDrillDownCard
          prompts={data.prompt_drilldown}
          onSelect={setActivePrompt}
        />
      )}

      <PromptDetailModal
        prompt={activePrompt}
        onClose={() => setActivePrompt(null)}
      />
    </>
  )
}

function Header({
  brand,
  window: win,
  state,
  synth,
}: {
  brand: Brand
  window: Window
  state: LoadState
  synth: SynthesisState
}) {
  const [toast, setToast] = useState<string | null>(null)

  function flash(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 1800)
  }

  function buildReport() {
    if (state.kind !== 'ok') return null
    // ``state.data`` already carries the ``window`` field from the API,
    // so spread it last and override only the synthesis slot.
    return {
      generated_at: new Date().toISOString(),
      brand: { id: brand.id, name: brand.name },
      ...state.data,
      ai_synthesis: synth.kind === 'ok' ? synth.data : null,
    }
  }

  function exportReport() {
    const report = buildReport()
    if (!report) {
      flash('Wait for data to load')
      return
    }
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const stamp = new Date().toISOString().slice(0, 10)
    a.download = `${brand.name.toLowerCase().replace(/\s+/g, '-')}-analytics-${stamp}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    flash('Report downloaded')
  }

  async function shareFindings() {
    if (state.kind !== 'ok') {
      flash('Wait for data to load')
      return
    }
    const d = state.data
    const score = d.market_position?.score
    const lines = [
      `📊 Analysis Results · ${brand.name}`,
      score != null
        ? `Market position: ${score.toFixed(1)}${
            d.market_position?.percentile != null
              ? ` (top ${d.market_position.percentile}%)`
              : ''
          }`
        : 'Market position: connect Peec to populate',
      `${d.growth_trajectory.metric_label}: ${d.growth_trajectory.total} in ${win}`,
      d.competitor_radar.length
        ? `Tracking: ${d.competitor_radar
            .slice(0, 5)
            .map((c) => c.name)
            .join(', ')}`
        : 'No competitors tracked yet',
    ]
    try {
      await navigator.clipboard.writeText(lines.join('\n'))
      flash('Summary copied')
    } catch {
      flash('Clipboard blocked')
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="relative flex flex-wrap items-end justify-between gap-4 pt-4"
    >
      <div>
        <h1 className="text-[36px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
          Analysis Results
        </h1>
        <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
          Live composite of Peec visibility, customer growth, and competitor
          activity for {firstWord(brand.name)}.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={exportReport}
          className="hairline rounded-full bg-bg-card px-4 py-2 text-[12px] text-fg-mute transition hover:text-fg"
        >
          ↥ Export Report
        </button>
        <button
          onClick={shareFindings}
          className="hairline rounded-full bg-bg-card px-4 py-2 text-[12px] text-fg-mute transition hover:text-fg"
        >
          ↗ Share Findings
        </button>
      </div>
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="pointer-events-none absolute right-0 top-0 rounded-md bg-fg/90 px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-bg"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  )
}

function DataSourcesBar({
  sources,
  fetchedAt,
}: {
  sources: DataSources
  fetchedAt: string
}) {
  const peecLabel =
    sources.peec === 'connected'
      ? {
          text:
            sources.peec_transport === 'mcp'
              ? 'Peec MCP live'
              : sources.peec_transport === 'rest'
                ? 'Peec REST live'
                : 'Peec live',
          dot: 'bg-emerald-500',
        }
      : sources.peec === 'no_data'
        ? { text: 'Peec connected · no data', dot: 'bg-amber-500' }
        : { text: 'Peec not connected', dot: 'bg-zinc-400' }
  return (
    <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-fg-mute">
      <span className="inline-flex items-center gap-1.5">
        <span className={`h-1.5 w-1.5 rounded-full ${peecLabel.dot}`} />
        {peecLabel.text}
      </span>
      <span>· {sources.customers_count} customers</span>
      <span>· {sources.campaigns_count} campaigns</span>
      <span>· {sources.email_sends_count} email sends</span>
      <span className="ml-auto">
        Updated{' '}
        {new Date(fetchedAt).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        })}
      </span>
    </div>
  )
}

function MarketPositionCard({
  market,
  sources,
  onPeecConnected,
}: {
  market: MarketPosition | null
  sources: DataSources
  onPeecConnected: () => void
}) {
  const [connecting, setConnecting] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  async function handleConnectPeec() {
    setConnectError(null)
    setConnecting(true)
    try {
      const r = await fetch('/api/peec/mcp/login/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      })
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j) => j?.detail ?? null)
          .catch(() => null)
        throw new Error(detail ?? `start failed (${r.status})`)
      }
      const { auth_url } = (await r.json()) as { auth_url: string }
      const popup = window.open(
        auth_url,
        'peec-mcp-connect',
        'width=560,height=720,resizable=yes',
      )
      if (!popup) {
        setConnectError('Popup blocked — allow popups and retry.')
        setConnecting(false)
        return
      }
      const pollStart = Date.now()
      const pollId = window.setInterval(async () => {
        try {
          const sr = await fetch('/api/peec/mcp/status')
          const status = (await sr.json()) as { connected: boolean }
          if (status.connected) {
            window.clearInterval(pollId)
            try {
              popup.close()
            } catch {
              /* cross-origin close may fail, that's fine */
            }
            setConnecting(false)
            onPeecConnected()
            return
          }
        } catch {
          /* transient — keep polling */
        }
        if (popup.closed || Date.now() - pollStart > 5 * 60_000) {
          window.clearInterval(pollId)
          setConnecting(false)
          if (Date.now() - pollStart > 5 * 60_000) {
            setConnectError('Timed out waiting for Peec consent.')
          }
        }
      }, 1500)
    } catch (e) {
      setConnecting(false)
      setConnectError(e instanceof Error ? e.message : 'Connect failed')
    }
  }

  if (market == null || market.score == null) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.05 }}
        className="relative overflow-hidden rounded-2xl border border-line bg-bg-card p-6"
      >
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Market Position
        </div>
        <p className="mt-3 text-[12.5px] leading-snug text-fg">
          {sources.peec === 'not_configured'
            ? 'Connect Peec to surface live AI-search visibility, per-engine breakdown, citation surface, and prompt-level drill-down.'
            : 'Peec is connected but no visibility data is in the project yet — add prompts to your Peec project.'}
        </p>
        <button
          onClick={handleConnectPeec}
          disabled={connecting}
          className="mt-4 inline-flex items-center gap-2 rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110 disabled:opacity-60"
        >
          {connecting ? (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              Waiting for consent…
            </>
          ) : (
            <>
              {sources.peec === 'not_configured'
                ? 'Connect Peec MCP →'
                : 'Reconnect Peec →'}
            </>
          )}
        </button>
        {connectError && (
          <p className="mt-3 text-[11px] text-red-700">{connectError}</p>
        )}
      </motion.div>
    )
  }
  const score = market.score
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-accent to-[var(--color-accent-deep)] p-6 text-white shadow-[0_10px_30px_rgba(91,80,230,0.25)]"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-10 -top-10 h-44 w-44 rounded-full bg-white/10 blur-2xl"
      />
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-white/70">
            Market Position
          </div>
          <p className="mt-2 max-w-[24ch] text-[12px] leading-snug text-white/75">
            {market.explanation}
          </p>
        </div>
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-white/15 text-white/90">
          ↗
        </span>
      </div>
      <div className="mt-7 flex items-end gap-2">
        <div className="font-semibold leading-none tracking-tight text-[56px]">
          {score.toFixed(1)}
        </div>
        {market.share_of_voice != null && (
          <div className="mb-1.5 rounded-full bg-white/20 px-2 py-0.5 text-[11px] font-medium text-white">
            SoV {market.share_of_voice.toFixed(1)}%
          </div>
        )}
      </div>
      <div className="mt-5 h-1.5 w-full overflow-hidden rounded-full bg-white/15">
        <div
          className="h-full rounded-full bg-white/90"
          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
        />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {market.percentile != null && (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-0.5 text-[10px] font-medium tracking-[0.06em] text-white/90">
            ◆ Top {market.percentile}%
          </div>
        )}
        {market.sentiment != null && (
          <div className="inline-flex items-center gap-1.5 rounded-full bg-white/15 px-2.5 py-0.5 text-[10px] font-medium tracking-[0.06em] text-white/90">
            ☺ Sentiment {market.sentiment.toFixed(2)}
          </div>
        )}
      </div>
    </motion.div>
  )
}

function GrowthTrajectoryCard({
  growth,
  window,
  onWindow,
}: {
  growth: GrowthTrajectory
  window: Window
  onWindow: (w: Window) => void
}) {
  const max = Math.max(...growth.buckets.map((b) => b.value), 1)
  const lastIdx = growth.buckets.length - 1
  const windows: Window[] = ['90D', '6M', '1Y']
  const hasData = growth.total > 0
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.08 }}
      className="panel flex flex-col p-6"
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Growth Trajectory
          </div>
          <div className="mt-1.5 flex items-baseline gap-2">
            <div className="text-[13px] font-semibold text-fg">
              {growth.metric_label}
            </div>
            <div className="text-[12px] text-fg-mute">
              · {growth.total.toLocaleString()} in {window}
            </div>
            {growth.delta_pct != null && (
              <div
                className={`text-[11px] font-medium ${
                  growth.delta_pct >= 0 ? 'text-emerald-600' : 'text-red-600'
                }`}
              >
                {growth.delta_pct >= 0 ? '+' : ''}
                {growth.delta_pct.toFixed(1)}%
              </div>
            )}
          </div>
        </div>
        <div className="hairline flex items-center gap-0.5 rounded-full bg-bg p-0.5">
          {windows.map((w) => (
            <button
              key={w}
              onClick={() => onWindow(w)}
              className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${
                w === window
                  ? 'bg-bg-card text-fg shadow-[0_1px_2px_rgba(20,20,40,0.06)]'
                  : 'text-fg-mute hover:text-fg'
              }`}
            >
              {w}
            </button>
          ))}
        </div>
      </div>
      {hasData ? (
        <div className="mt-5 flex h-36 items-end gap-2.5">
          {growth.buckets.map((b, i) => {
            const h = (b.value / max) * 100
            const active = i === lastIdx
            return (
              <div key={i} className="relative flex-1" style={{ height: '100%' }}>
                <motion.div
                  initial={{ height: 0 }}
                  animate={{ height: `${h}%` }}
                  transition={{
                    duration: 0.45,
                    delay: 0.05 * i,
                    ease: [0.16, 1, 0.3, 1],
                  }}
                  className={`absolute bottom-0 left-0 right-0 rounded-md ${
                    active
                      ? 'bg-gradient-to-b from-accent to-[var(--color-accent-deep)]'
                      : 'bg-accent-soft'
                  }`}
                  title={`${b.label} — ${b.value}`}
                />
                {active && b.value > 0 && (
                  <div className="absolute -top-7 left-1/2 -translate-x-1/2 rounded-md bg-fg px-1.5 py-0.5 text-[10px] font-medium text-white">
                    {b.value}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div className="mt-5 flex h-36 items-center justify-center rounded-xl border border-dashed border-line text-center text-[12px] text-fg-mute">
          No {growth.metric_label.toLowerCase()} in this window yet.
        </div>
      )}
      {hasData && (
        <div className="mt-3 flex justify-between text-[10px] uppercase tracking-[0.16em] text-fg-dim">
          {growth.buckets.map((b, i) => (
            <span key={i} className="flex-1 text-center">
              {b.label}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  )
}

function CompetitorRadarCard({ rows }: { rows: CompetitorRow[] }) {
  const { navigate } = useNav()
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.12 }}
      className="panel p-6"
    >
      <div className="flex items-center justify-between">
        <div className="text-[13px] font-semibold">Competitor Radar</div>
        <button
          onClick={() => navigate('dashboard')}
          className="text-[11px] font-medium text-accent hover:underline"
        >
          View watchlist →
        </button>
      </div>
      {rows.length === 0 ? (
        <div className="mt-5 rounded-xl border border-dashed border-line py-8 text-center text-[12px] text-fg-mute">
          No competitors tracked yet — add some from the Watchlist.
        </div>
      ) : (
        <ul className="mt-5 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]">
          {rows.slice(0, 6).map((c) => (
            <CompetitorRadarRow key={c.id} competitor={c} />
          ))}
        </ul>
      )}
      {rows.length > 0 && rows.every((r) => !r.has_peec_data) && (
        <p className="mt-4 text-[11px] leading-snug text-fg-mute">
          Connect Peec to surface live visibility & share-of-voice per
          competitor.
        </p>
      )}
    </motion.div>
  )
}

function CompetitorRadarRow({ competitor }: { competitor: CompetitorRow }) {
  return (
    <li className="flex items-center gap-4 py-3">
      <InitialsAvatar name={competitor.name} size="md" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium leading-tight">
          {competitor.name}
        </div>
        <div className="mt-0.5 text-[11px] text-fg-mute">
          {competitor.rank_label}
        </div>
      </div>
      <div className="text-right">
        {competitor.visibility != null ? (
          <>
            <div className="text-[13px] font-semibold tabular-nums text-fg">
              {competitor.visibility.toFixed(1)}%
            </div>
            <div className="text-[10px] uppercase tracking-[0.16em] text-fg-dim">
              Visibility
            </div>
          </>
        ) : (
          <div className="text-[11px] text-fg-dim">No Peec data</div>
        )}
      </div>
      {competitor.delta != null && (
        <div
          className={`min-w-14 text-right text-[12px] ${
            competitor.delta >= 0 ? 'text-emerald-600' : 'text-red-600'
          }`}
        >
          {competitor.delta >= 0 ? '+' : ''}
          {competitor.delta.toFixed(1)}%
        </div>
      )}
    </li>
  )
}

function AISynthesisCard({
  brand,
  synth,
  peecStatus,
}: {
  brand: Brand
  synth: SynthesisState
  peecStatus: DataSources['peec']
}) {
  const synthesis = synth.kind === 'ok' ? synth.data : null

  if (synth.kind === 'loading' || synth.kind === 'idle') {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.16 }}
        className="rounded-2xl border border-accent/20 bg-accent-soft/60 p-6"
      >
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
          <span className="grid h-5 w-5 place-items-center rounded-full bg-accent text-[10px] text-white">
            <motion.span
              animate={{ rotate: 360 }}
              transition={{ duration: 2.5, repeat: Infinity, ease: 'linear' }}
            >
              ✦
            </motion.span>
          </span>
          AI Synthesis
          <span className="ml-auto text-[10px] normal-case tracking-normal text-fg-mute">
            thinking…
          </span>
        </div>
        <div className="mt-4 flex flex-col gap-2.5">
          <SynthShimmer width="92%" />
          <SynthShimmer width="78%" />
          <SynthShimmer width="60%" />
        </div>
        <div className="mt-5 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Recommended actions
        </div>
        <div className="mt-3 flex flex-col gap-3">
          <SynthShimmer width="84%" />
          <SynthShimmer width="72%" />
          <SynthShimmer width="80%" />
        </div>
      </motion.div>
    )
  }

  if (synthesis == null) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, delay: 0.16 }}
        className="rounded-2xl border border-accent/20 bg-accent-soft/60 p-6"
      >
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
          <span className="grid h-5 w-5 place-items-center rounded-full bg-accent text-[10px] text-white">
            ✦
          </span>
          AI Synthesis
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-fg-mute">
          {synth.kind === 'error'
            ? synth.message
            : peecStatus === 'connected'
              ? 'Couldn\'t generate a synthesis right now — refresh in a moment.'
              : `Connect Peec and run a campaign to unlock ${firstWord(
                  brand.name,
                )}'s personalized synthesis.`}
        </p>
      </motion.div>
    )
  }
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.16 }}
      className="rounded-2xl border border-accent/20 bg-accent-soft/60 p-6"
    >
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-accent text-[10px] text-white">
          ✦
        </span>
        AI Synthesis
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-fg">
        {synthesis.summary}
      </p>
      <div className="mt-5 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Recommended actions
      </div>
      <ul className="mt-3 flex flex-col gap-2.5">
        {synthesis.actions.map((a, i) => (
          <li key={i} className="flex items-start gap-2.5 text-[12.5px] text-fg">
            <span className="mt-[3px] grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full bg-accent text-[8px] text-white">
              ◆
            </span>
            <span>
              <span className="font-medium">{a.label}</span>
              {a.rationale && (
                <span className="text-fg-mute"> — {a.rationale}</span>
              )}
            </span>
          </li>
        ))}
      </ul>
      {synthesis.absent_prompts.length > 0 && (
        <div className="mt-5 border-t border-accent/15 pt-4">
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Prompts to target
          </div>
          <ul className="mt-2 flex flex-col gap-1.5 text-[12px] text-fg">
            {synthesis.absent_prompts.slice(0, 3).map((p, i) => (
              <li
                key={i}
                className="line-clamp-1 rounded-md bg-white/60 px-2.5 py-1.5"
                title={p}
              >
                "{p}"
              </li>
            ))}
          </ul>
        </div>
      )}
    </motion.div>
  )
}

const ENGINE_TINTS: Record<string, { bar: string; bg: string; label: string }> = {
  chatgpt: { bar: '#10a37f', bg: '#10a37f1a', label: 'ChatGPT' },
  perplexity: { bar: '#5b9bd5', bg: '#5b9bd51a', label: 'Perplexity' },
  gemini: { bar: '#4285f4', bg: '#4285f41a', label: 'Gemini' },
  claude: { bar: '#cc785c', bg: '#cc785c1a', label: 'Claude' },
  copilot: { bar: '#0078d4', bg: '#0078d41a', label: 'Copilot' },
  grok: { bar: '#1e1e1e', bg: '#1e1e1e1a', label: 'Grok' },
  you: { bar: '#5a3aff', bg: '#5a3aff1a', label: 'You.com' },
  unknown: { bar: '#8a8aa0', bg: '#8a8aa01a', label: 'Other' },
}

function EngineBreakdownCard({ engines }: { engines: EngineBreakdown[] }) {
  const max = Math.max(
    ...engines.map((e) => e.visibility ?? 0),
    1,
  )
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.18 }}
      className="panel p-6"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-semibold">Visibility by AI Engine</div>
          <p className="mt-1 text-[11px] text-fg-mute">
            Where your brand surfaces across answer engines.
          </p>
        </div>
        <span className="hairline rounded-full bg-bg px-2.5 py-0.5 text-[10px] uppercase tracking-[0.16em] text-fg-mute">
          Peec MCP
        </span>
      </div>
      <ul className="mt-5 flex flex-col gap-3">
        {engines.map((e) => {
          const tint = ENGINE_TINTS[e.engine] ?? ENGINE_TINTS.unknown
          const pct = e.visibility != null ? Math.max(0, e.visibility) : null
          const w = pct != null ? (pct / max) * 100 : 0
          return (
            <li key={e.engine} className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between text-[12px]">
                <span className="flex items-center gap-2 font-medium text-fg">
                  <span
                    className="grid h-5 w-5 place-items-center rounded-md text-[10px] font-bold text-white"
                    style={{ background: tint.bar }}
                  >
                    {tint.label[0]}
                  </span>
                  {tint.label === 'Other' ? e.label : tint.label}
                </span>
                <span className="tabular-nums text-fg">
                  {pct != null ? `${pct.toFixed(1)}%` : '—'}
                  {e.sample_count != null && (
                    <span className="ml-2 text-[10.5px] text-fg-dim">
                      n={e.sample_count}
                    </span>
                  )}
                </span>
              </div>
              <div
                className="h-2 overflow-hidden rounded-full"
                style={{ background: tint.bg }}
              >
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${w}%` }}
                  transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                  className="h-full rounded-full"
                  style={{ background: tint.bar }}
                />
              </div>
            </li>
          )
        })}
      </ul>
    </motion.div>
  )
}

function CitationSurfaceCard({ citations }: { citations: CitationRow[] }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
      className="panel p-6"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-semibold">Citation Surface</div>
          <p className="mt-1 text-[11px] text-fg-mute">
            Top domains LLMs cite when answering your prompts.
          </p>
        </div>
        <span className="hairline rounded-full bg-bg px-2.5 py-0.5 text-[10px] uppercase tracking-[0.16em] text-fg-mute">
          Peec MCP
        </span>
      </div>
      <ul className="mt-5 grid grid-cols-1 gap-1.5">
        {citations.map((c) => (
          <li
            key={c.domain}
            className="flex items-center gap-3 rounded-md px-2 py-1.5 hover:bg-bg-soft"
          >
            <span className="grid h-6 w-6 place-items-center rounded text-[10px] font-medium text-fg-mute">
              {c.rank ?? '·'}
            </span>
            {c.favicon_url ? (
              <img
                src={c.favicon_url}
                alt=""
                className="h-4 w-4 rounded-sm"
              />
            ) : (
              <span className="grid h-4 w-4 place-items-center rounded-sm bg-accent-soft text-[8px] font-bold text-accent">
                {c.domain.slice(0, 1).toUpperCase()}
              </span>
            )}
            <a
              href={`https://${c.domain.replace(/^https?:\/\//, '')}`}
              target="_blank"
              rel="noopener noreferrer"
              className="min-w-0 flex-1 truncate text-[12.5px] text-fg hover:text-accent"
            >
              {c.domain}
            </a>
            {c.citation_count != null && (
              <span className="tabular-nums text-[11px] text-fg-mute">
                {c.citation_count} cites
              </span>
            )}
          </li>
        ))}
      </ul>
    </motion.div>
  )
}

function PromptDrillDownCard({
  prompts,
  onSelect,
}: {
  prompts: PromptDrillDown[]
  onSelect: (p: PromptDrillDown) => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.22 }}
      className="mt-5 panel p-6"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-semibold">Tracked Prompts</div>
          <p className="mt-1 text-[11px] text-fg-mute">
            Click a prompt to see rank, winning competitor, and engine
            coverage.
          </p>
        </div>
        <span className="hairline rounded-full bg-bg px-2.5 py-0.5 text-[10px] uppercase tracking-[0.16em] text-fg-mute">
          Peec MCP · {prompts.length}
        </span>
      </div>
      <ul className="mt-4 grid grid-cols-1 gap-1.5 md:grid-cols-2">
        {prompts.map((p, i) => {
          const winning =
            p.own_rank != null && p.own_rank <= 3
              ? 'winning'
              : p.own_rank != null && p.own_rank <= 5
                ? 'visible'
                : 'absent'
          return (
            <li key={i}>
              <button
                onClick={() => onSelect(p)}
                className="hairline group flex w-full items-center gap-3 rounded-xl bg-bg-card p-3 text-left transition hover:border-accent/40 hover:shadow-sm"
              >
                <span
                  className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md text-[10px] font-bold ${
                    winning === 'winning'
                      ? 'bg-emerald-100 text-emerald-700'
                      : winning === 'visible'
                        ? 'bg-amber-100 text-amber-700'
                        : 'bg-zinc-100 text-zinc-600'
                  }`}
                >
                  {p.own_rank != null ? `#${p.own_rank}` : '—'}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="line-clamp-2 text-[12.5px] font-medium text-fg group-hover:text-accent">
                    {p.prompt}
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10.5px] text-fg-mute">
                    {p.winner && (
                      <span>
                        winner: <span className="text-fg">{p.winner}</span>
                      </span>
                    )}
                    {p.engines.length > 0 && (
                      <span>· {p.engines.length} engines</span>
                    )}
                    {p.cited_domains.length > 0 && (
                      <span>· {p.cited_domains.length} domains</span>
                    )}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </motion.div>
  )
}

function PromptDetailModal({
  prompt,
  onClose,
}: {
  prompt: PromptDrillDown | null
  onClose: () => void
}) {
  return (
    <AnimatePresence>
      {prompt && (
        <motion.div
          key="overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-40 grid place-items-center bg-fg/30 px-4"
          onClick={onClose}
        >
          <motion.div
            key="panel"
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="w-full max-w-xl rounded-2xl bg-bg-card p-6 shadow-[0_24px_60px_rgba(20,20,40,0.18)]"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  Prompt drill-down
                </div>
                <h3 className="mt-1.5 text-[16px] font-semibold leading-snug text-fg">
                  "{prompt.prompt}"
                </h3>
              </div>
              <button
                onClick={onClose}
                className="grid h-8 w-8 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
                aria-label="Close"
              >
                ×
              </button>
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3">
              <Metric
                label="Your rank"
                value={prompt.own_rank != null ? `#${prompt.own_rank}` : '—'}
              />
              <Metric
                label="Visibility"
                value={
                  prompt.own_visibility != null
                    ? `${prompt.own_visibility.toFixed(1)}%`
                    : '—'
                }
              />
              <Metric
                label="Winner"
                value={prompt.winner ?? '—'}
                subtle={
                  prompt.winner_visibility != null
                    ? `${prompt.winner_visibility.toFixed(1)}%`
                    : undefined
                }
              />
            </div>
            {prompt.engines.length > 0 && (
              <div className="mt-5">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  Engines covering this prompt
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {prompt.engines.map((eng) => {
                    const tint = ENGINE_TINTS[eng] ?? ENGINE_TINTS.unknown
                    return (
                      <span
                        key={eng}
                        className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px]"
                        style={{
                          background: tint.bg,
                          color: tint.bar,
                        }}
                      >
                        <span
                          className="h-1.5 w-1.5 rounded-full"
                          style={{ background: tint.bar }}
                        />
                        {tint.label === 'Other' ? eng : tint.label}
                      </span>
                    )
                  })}
                </div>
              </div>
            )}
            {prompt.cited_domains.length > 0 && (
              <div className="mt-5">
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  Domains cited on this prompt
                </div>
                <ul className="mt-2 flex flex-col gap-1">
                  {prompt.cited_domains.map((d) => (
                    <li key={d} className="text-[12px] text-fg">
                      <a
                        href={`https://${d.replace(/^https?:\/\//, '')}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-accent hover:underline"
                      >
                        {d}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {prompt.last_seen_at && (
              <p className="mt-5 text-[10.5px] uppercase tracking-[0.16em] text-fg-dim">
                Last seen {new Date(prompt.last_seen_at).toLocaleString()}
              </p>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function Metric({
  label,
  value,
  subtle,
}: {
  label: string
  value: string
  subtle?: string
}) {
  return (
    <div className="hairline rounded-xl bg-bg p-3">
      <div className="text-[10px] uppercase tracking-[0.16em] text-fg-mute">
        {label}
      </div>
      <div className="mt-1 text-[18px] font-semibold leading-tight tabular-nums text-fg">
        {value}
      </div>
      {subtle && (
        <div className="mt-0.5 text-[11px] text-fg-mute">{subtle}</div>
      )}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="mt-6 flex flex-col gap-5">
      <div className="grid grid-cols-1 gap-5 md:grid-cols-[1fr_1.4fr]">
        <Shimmer className="h-52 rounded-2xl" />
        <Shimmer className="h-52 rounded-2xl" />
      </div>
      <div className="grid grid-cols-1 gap-5 md:grid-cols-[1.6fr_1fr]">
        <Shimmer className="h-72 rounded-2xl" />
        <Shimmer className="h-72 rounded-2xl" />
      </div>
    </div>
  )
}

function Shimmer({ className }: { className?: string }) {
  return (
    <div
      className={`relative overflow-hidden bg-bg-card ${className ?? ''}`}
    >
      <motion.div
        animate={{ x: ['-100%', '100%'] }}
        transition={{ duration: 1.4, repeat: Infinity, ease: 'linear' }}
        className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/40 to-transparent"
      />
    </div>
  )
}

function SynthShimmer({ width }: { width: string }) {
  return (
    <div
      className="relative h-3 overflow-hidden rounded-full bg-white/50"
      style={{ width }}
    >
      <motion.div
        animate={{ x: ['-100%', '100%'] }}
        transition={{ duration: 1.6, repeat: Infinity, ease: 'linear' }}
        className="absolute inset-y-0 w-1/2 bg-gradient-to-r from-transparent via-accent/30 to-transparent"
      />
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="mt-6 panel px-6 py-8">
      <div className="text-[13px] font-medium text-red-700">
        Couldn't load analytics
      </div>
      <p className="mt-1 max-w-md text-[12px] leading-snug text-fg-mute">
        {message}
      </p>
    </div>
  )
}

