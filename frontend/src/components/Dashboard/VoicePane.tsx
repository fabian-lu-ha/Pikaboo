import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { TopBar } from './TopBar'
import { firstWord } from '../../lib/brandName'
import {
  reconcileVoiceModel,
  useVoiceModelStore,
  type VoiceModelStatus,
} from '../../stores/voiceModelStore'
import type { Brand } from './types'

// The Voice pane is where the Pioneer / Gemma fine-tuning story lives.
// Three vertically-stacked sections:
//   1. Status hero — animates between idle / building / training / ready
//      and houses the primary CTA ("Train on Pioneer").
//   2. Stage timeline — corpus → upload → train → deploy, fed by live
//      voice.* events from the bus.
//   3. Preview / compare — once the adapter is ready, a draft generated
//      via the Pioneer adapter side-by-side with generic Gemini for the
//      same brief. This is the "voice fidelity diff" demo moment.

type DraftEnvelope = {
  caption?: string
  hashtags?: string[]
  cta?: string
  [k: string]: unknown
}

export function VoicePane({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const status = useVoiceModelStore((s) => s.status)
  const corpus = useVoiceModelStore((s) => s.corpus)
  const training = useVoiceModelStore((s) => s.training)
  const adapterUrl = useVoiceModelStore((s) => s.adapterUrl)
  const modelId = useVoiceModelStore((s) => s.modelId)
  const error = useVoiceModelStore((s) => s.error)
  const setBrandId = useVoiceModelStore((s) => s.setBrand)

  useEffect(() => {
    setBrandId(brand.id)
    void reconcileVoiceModel(brand.id)
  }, [brand.id, setBrandId])

  // Poll while training is in flight. The fine-tune work runs in a
  // detached subprocess (so it survives uvicorn --reload), which means
  // it can't push pyee events to the parent's SSE bus. Polling the
  // status endpoint is the simplest way to render live progress.
  useEffect(() => {
    const inFlight =
      status === 'deep_scraping' ||
      status === 'corpus_building' ||
      status === 'corpus_built' ||
      status === 'training_queued' ||
      status === 'training'
    if (!inFlight) return
    const id = setInterval(() => {
      void reconcileVoiceModel(brand.id)
    }, 2000)
    return () => clearInterval(id)
  }, [brand.id, status])

  const voiceProfile = brand.voice_profile
  const hasVoiceProfile = !!voiceProfile?.tone || !!voiceProfile?.voice_excerpt

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-16 pt-4">
        <Header brand={brand} status={status} />
        <StatusHero
          brand={brand}
          status={status}
          training={training}
          corpus={corpus}
          adapterUrl={adapterUrl}
          modelId={modelId}
          error={error}
          hasVoiceProfile={hasVoiceProfile}
        />
        <StageTimeline
          status={status}
          corpus={corpus}
          training={training}
          adapterUrl={adapterUrl}
          modelId={modelId}
        />
        {status === 'ready' && adapterUrl && (
          <PreviewSection brand={brand} />
        )}
        {status === 'ready' && (
          <BenchmarkSection brand={brand} />
        )}
      </div>
    </main>
  )
}

// --- 3-way benchmark (the prize evidence) -----------------------------------

type BenchCandidate = {
  id: string
  label: string
  model: string
  draft: { caption?: string; hashtags?: string[]; cta?: string } | null
  latency_ms: number
  json_valid: boolean
  error: string | null
  voice_fidelity: number | null
  specificity: number | null
  rationale: string | null
}

type BenchResult = {
  brand_id: string
  brief: string
  platform: string
  judge_model: string
  simulator: boolean
  candidates: BenchCandidate[]
}

function BenchmarkSection({ brand }: { brand: Brand }) {
  const [brief, setBrief] = useState(
    `Announce a small loyalty perk for repeat customers. Keep it on-brand for ${firstWord(
      brand.name,
    )} — concrete, not generic.`,
  )
  const [result, setResult] = useState<BenchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRun() {
    if (loading || !brief.trim()) return
    setLoading(true)
    setError(null)
    try {
      const r = await fetch('/api/finetune/benchmark', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          brand_id: brand.id,
          brief: brief.trim(),
          platform: 'instagram',
        }),
      })
      if (!r.ok) {
        const t = await r.text()
        setError(`benchmark failed (${r.status}): ${t.slice(0, 160)}`)
        return
      }
      const d = (await r.json()) as BenchResult
      setResult(d)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'network')
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.18 }}
      className="mt-12"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-[13px] font-semibold">Benchmark · evidence</h2>
        <span className="text-[11px] text-fg-mute">
          Pioneer adapter vs Gemini Flash vs Gemini Pro · scored by Gemini Pro
          (blind)
        </span>
      </div>
      <p className="mt-1 max-w-2xl text-[12px] text-fg-mute">
        The Pioneer prize asks for evidence the fine-tune beats a general API
        call. Run any brief through three models in parallel — voice fidelity,
        specificity, latency, and JSON validity all measured on the same input.
      </p>
      <div className="panel mt-4 p-5">
        <label className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
          Brief
        </label>
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={3}
          className="mt-2 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-[13px] leading-relaxed text-fg outline-none focus:border-accent"
        />
        <div className="mt-3 flex items-center justify-between">
          <button
            onClick={handleRun}
            disabled={loading || !brief.trim()}
            className="rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-5 py-2 text-[13px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] transition hover:brightness-110 disabled:opacity-50"
          >
            {loading ? 'Running 3-way eval…' : 'Run benchmark'}
          </button>
          {error && <span className="text-[12px] text-red-600">{error}</span>}
        </div>
      </div>
      {result && <BenchmarkResults result={result} />}
    </motion.section>
  )
}

function BenchmarkResults({ result }: { result: BenchResult }) {
  // Sort: highest voice_fidelity first; nulls last.
  const sorted = [...result.candidates].sort((a, b) => {
    const av = a.voice_fidelity ?? -1
    const bv = b.voice_fidelity ?? -1
    return bv - av
  })
  const winner = sorted[0]?.id
  return (
    <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
      {sorted.map((c) => (
        <BenchCandidateCard
          key={c.id}
          candidate={c}
          isWinner={c.id === winner}
          judgeModel={result.judge_model}
        />
      ))}
    </div>
  )
}

function BenchCandidateCard({
  candidate,
  isWinner,
  judgeModel,
}: {
  candidate: BenchCandidate
  isWinner: boolean
  judgeModel: string
}) {
  const fidelity = candidate.voice_fidelity ?? 0
  const specificity = candidate.specificity ?? 0
  const accent = candidate.id === 'pioneer'
  return (
    <div
      className={`panel relative flex flex-col gap-3 p-5 ${
        accent ? 'ring-1 ring-accent/30' : ''
      }`}
    >
      {isWinner && (
        <span className="absolute -top-2 left-5 rounded-full bg-emerald-500 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white shadow-md">
          ★ Top voice
        </span>
      )}
      <div className="flex items-center justify-between">
        <div>
          <div
            className={`text-[11px] font-medium uppercase tracking-[0.16em] ${
              accent ? 'text-accent' : 'text-fg-mute'
            }`}
          >
            {candidate.label}
          </div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-fg-dim">
            {candidate.model}
          </div>
        </div>
        <div className="text-right text-[10px] text-fg-mute">
          <div>{candidate.latency_ms} ms</div>
          <div className={candidate.json_valid ? 'text-emerald-700' : 'text-red-600'}>
            JSON {candidate.json_valid ? '✓' : '✕'}
          </div>
        </div>
      </div>

      <ScoreBar label="Voice fidelity" value={fidelity} />
      <ScoreBar label="Specificity" value={specificity} muted />

      {candidate.draft?.caption && (
        <p className="line-clamp-4 text-[12.5px] leading-relaxed text-fg">
          {candidate.draft.caption}
        </p>
      )}
      {candidate.rationale && (
        <p className="text-[11px] italic leading-relaxed text-fg-mute">
          “{candidate.rationale}” — {judgeModel}
        </p>
      )}
      {candidate.error && (
        <p className="text-[11px] text-red-600">⚠ {candidate.error}</p>
      )}
    </div>
  )
}

function ScoreBar({
  label,
  value,
  muted,
}: {
  label: string
  value: number
  muted?: boolean
}) {
  const pct = Math.max(0, Math.min(10, value)) * 10
  return (
    <div>
      <div className="flex items-center justify-between text-[10px] text-fg-mute">
        <span>{label}</span>
        <span className="font-mono">{value} / 10</span>
      </div>
      <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-bg-soft">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
          className={`h-full rounded-full ${
            muted ? 'bg-fg-dim/60' : 'bg-gradient-to-r from-accent to-[var(--color-accent-deep)]'
          }`}
        />
      </div>
    </div>
  )
}

function Header({
  brand,
  status,
}: {
  brand: Brand
  status: VoiceModelStatus
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="text-[12px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Voice model · Pioneer × Qwen3
      </div>
      <h1 className="mt-2 text-[36px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
        {firstWord(brand.name)} voice
        <span className="text-fg-dim"> · {labelFor(status)}</span>
      </h1>
      <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
        Train a per-tenant Qwen3 4B Instruct LoRA on{' '}
        <span className="text-fg">{firstWord(brand.name)}</span>'s real posts so
        every draft sounds like the brand — not like a generic AI.
      </p>
    </motion.section>
  )
}

function StatusHero({
  brand,
  status,
  training,
  corpus,
  adapterUrl,
  modelId,
  error,
  hasVoiceProfile,
}: {
  brand: Brand
  status: VoiceModelStatus
  training: ReturnType<typeof useVoiceModelStore.getState>['training']
  corpus: ReturnType<typeof useVoiceModelStore.getState>['corpus']
  adapterUrl: string | null
  modelId: string | null
  error: string | null
  hasVoiceProfile: boolean
}) {
  const [starting, setStarting] = useState(false)
  const [retrainConfirmOpen, setRetrainConfirmOpen] = useState(false)
  const isInFlight =
    status === 'deep_scraping' ||
    status === 'corpus_building' ||
    status === 'corpus_built' ||
    status === 'training_queued' ||
    status === 'training'
  const isReady = status === 'ready'
  const isFailed = status === 'failed'

  async function handleStart() {
    if (starting || isInFlight) return
    setStarting(true)
    // Optimistic local flip so the UI immediately shows the work is
    // starting — without this the user sees nothing until the next
    // poll (or a manual page refresh) because the worker subprocess
    // can't push events to the parent's SSE bus.
    useVoiceModelStore.setState({
      status: 'deep_scraping',
      error: null,
      corpus: null,
      training: null,
      modelId: null,
      adapterUrl: null,
    })
    try {
      const r = await fetch('/api/finetune/start', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ brand_id: brand.id }),
      })
      if (!r.ok) {
        const t = await r.text()
        useVoiceModelStore.setState({
          status: 'failed',
          error: `start failed: ${t.slice(0, 120)}`,
        })
        return
      }
      // Pull fresh state — the backend already flipped status to
      // deep_scraping inside start_finetune. This kicks the polling
      // useEffect into action immediately.
      await reconcileVoiceModel(brand.id)
    } catch (e) {
      useVoiceModelStore.setState({
        status: 'failed',
        error: e instanceof Error ? e.message : 'network',
      })
    } finally {
      setStarting(false)
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className="relative mt-8 overflow-hidden rounded-3xl bg-gradient-to-br from-accent to-[var(--color-accent-deep)] p-7 text-white shadow-[0_18px_40px_rgba(91,80,230,0.32)]"
    >
      <div
        aria-hidden
        className="pointer-events-none absolute -right-16 -top-20 h-48 w-48 rounded-full bg-white/10 blur-2xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-20 -left-10 h-44 w-44 rounded-full bg-white/5 blur-2xl"
      />
      <div className="relative grid gap-6 md:grid-cols-[1fr_auto] md:items-center">
        <div>
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.16em] text-white/70">
            <span className="grid h-5 w-5 place-items-center rounded-full bg-white/15">
              ◐
            </span>
            <span>Pioneer AI · Qwen3-4B-Instruct · LoRA r=16</span>
          </div>
          <h2 className="mt-3 text-[26px] font-semibold leading-[1.2]">
            {heroTitle(status)}
          </h2>
          <p className="mt-2 max-w-xl text-[13px] leading-relaxed text-white/85">
            {heroSubtitle(status, brand.name, training, corpus)}
          </p>
          {isFailed && error && (
            <p className="mt-3 text-[12px] text-white/95">⚠ {error}</p>
          )}
          {isReady && (modelId || adapterUrl) && (
            <div className="mt-4 flex flex-wrap items-center gap-3 text-[12px] text-white/80">
              {modelId && (
                <span className="rounded-full bg-white/15 px-3 py-1 font-mono text-[11px]">
                  model: {modelId}
                </span>
              )}
              {adapterUrl && (
                <span className="truncate rounded-full bg-white/15 px-3 py-1 font-mono text-[11px]">
                  adapter: {adapterUrl.slice(0, 60)}
                  {adapterUrl.length > 60 && '…'}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-3">
          {!hasVoiceProfile && (
            <div className="rounded-xl bg-white/15 px-4 py-3 text-[12px] text-white/85">
              Finish onboarding first — we need your voice profile.
            </div>
          )}
          {hasVoiceProfile && (status === 'idle' || isFailed) && (
            <button
              onClick={handleStart}
              disabled={starting}
              className="rounded-full bg-white px-6 py-2.5 text-[13px] font-semibold text-accent shadow-[0_8px_22px_rgba(0,0,0,0.18)] transition hover:brightness-105 disabled:opacity-60"
            >
              {starting
                ? 'Starting…'
                : isFailed
                  ? 'Retry training'
                  : 'Train on Pioneer'}
            </button>
          )}
          {isInFlight && (
            <div className="inline-flex items-center gap-2 rounded-full bg-white/15 px-5 py-2 text-[12px] font-medium text-white/95">
              <Spinner className="text-white" />
              {labelFor(status)}…
            </div>
          )}
          {isReady && (
            <div className="flex items-center gap-2">
              <div className="rounded-full bg-emerald-400/95 px-5 py-2 text-[12px] font-semibold text-emerald-900 shadow-[0_8px_22px_rgba(16,185,129,0.35)]">
                ✓ Adapter live
              </div>
              <button
                onClick={() => setRetrainConfirmOpen(true)}
                disabled={starting}
                title="Re-train on the latest data — overwrites the deployed adapter."
                className="rounded-full bg-white/15 px-4 py-2 text-[12px] font-medium text-white transition hover:bg-white/25 disabled:opacity-60"
              >
                {starting ? 'Starting…' : 'Retrain'}
              </button>
            </div>
          )}
        </div>
      </div>
      {isInFlight && training && (
        <TrainingProgress
          training={training}
          corpus={corpus}
        />
      )}
      {retrainConfirmOpen && (
        <RetrainConfirmModal
          onCancel={() => setRetrainConfirmOpen(false)}
          onConfirm={async () => {
            setRetrainConfirmOpen(false)
            await handleStart()
          }}
        />
      )}
    </motion.section>
  )
}

function TrainingProgress({
  training,
  corpus,
}: {
  training: NonNullable<ReturnType<typeof useVoiceModelStore.getState>['training']>
  corpus: ReturnType<typeof useVoiceModelStore.getState>['corpus']
}) {
  // Pull live timing fields the worker writes into corpus_meta on each poll.
  const pct =
    typeof corpus?.training_progress_percent === 'number'
      ? corpus.training_progress_percent
      : Math.round(training.progress * 100)
  const startedAt = corpus?.started_at ?? null
  const epoch = corpus?.current_epoch ?? null
  const totalEpochs = corpus?.total_epochs ?? null
  const latestLog = corpus?.latest_log ?? null

  // ETA: only meaningful once we have some progress + a start timestamp.
  const eta = (() => {
    if (!startedAt || pct < 1) return null
    const startMs = new Date(startedAt).getTime()
    if (!startMs) return null
    const elapsedMs = Date.now() - startMs
    if (elapsedMs <= 0) return null
    const totalMs = elapsedMs * (100 / pct)
    const remainingMs = totalMs - elapsedMs
    return formatDuration(remainingMs)
  })()
  const elapsed = startedAt
    ? formatDuration(Date.now() - new Date(startedAt).getTime())
    : null

  return (
    <div className="relative mt-6">
      <ProgressBar progress={pct / 100} />
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11px] text-white/80">
        <span className="truncate">{training.stage}</span>
        <span className="font-mono">{pct}%</span>
      </div>
      {(epoch != null || elapsed || eta) && (
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] uppercase tracking-[0.14em] text-white/55">
          {epoch != null && (
            <span>
              epoch {epoch}
              {totalEpochs ? ` / ${totalEpochs}` : ''}
            </span>
          )}
          {elapsed && <span>elapsed {elapsed}</span>}
          {eta && <span>eta ~{eta}</span>}
        </div>
      )}
      {latestLog && (
        <div className="mt-2 truncate font-mono text-[11px] text-white/65">
          ▸ {latestLog}
        </div>
      )}
    </div>
  )
}

function formatDuration(ms: number): string {
  if (!isFinite(ms) || ms < 0) return '—'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.round(s / 60)
  if (m < 60) return `${m}m`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return mm ? `${h}h ${mm}m` : `${h}h`
}

function RetrainConfirmModal({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-md rounded-2xl border border-line bg-bg px-7 py-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-base font-semibold leading-snug text-fg">
          Retrain voice model?
        </h2>
        <p className="mt-2 text-[13px] leading-relaxed text-fg-mute">
          This wipes the current adapter, re-runs deep scrape + corpus
          build, and kicks a fresh LoRA training job on Pioneer. The
          existing adapter is unreachable until the new one deploys
          (~2–10 min on Pioneer's Fireworks GPUs). Drafts in flight may
          fall back to generic Gemini.
        </p>
        <div className="mt-6 flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 rounded-full border border-line bg-bg-card px-4 py-2 text-sm font-medium text-fg transition hover:bg-line/30"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-sm font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] transition hover:brightness-110"
          >
            Yes, retrain
          </button>
        </div>
      </div>
    </div>
  )
}

function ProgressBar({ progress }: { progress: number }) {
  const pct = Math.max(0, Math.min(1, progress)) * 100
  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-white/15">
      <motion.div
        className="h-full rounded-full bg-white"
        initial={{ width: 0 }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
      />
    </div>
  )
}

type Stage = {
  id: string
  title: string
  detail: string
  state: 'pending' | 'active' | 'done' | 'fail'
}

function StageTimeline({
  status,
  corpus,
  adapterUrl,
  modelId,
}: {
  status: VoiceModelStatus
  corpus: ReturnType<typeof useVoiceModelStore.getState>['corpus']
  training: ReturnType<typeof useVoiceModelStore.getState>['training']
  adapterUrl: string | null
  modelId: string | null
}) {
  const stages = useMemo<Stage[]>(() => {
    // Each phase has a "completion marker" written by the worker. We
    // derive done/active/fail/pending from data presence, not just the
    // status enum — so a partial run still lights up the stages it
    // actually completed.
    const failed = status === 'failed'
    const ready = status === 'ready'
    const ds = corpus?.deep_scrape ?? null
    const dsDone = !!ds && (ds.fetched_pages ?? 0) > 0
    const corpusDone = (corpus?.line_count ?? 0) > 0
    const projectDone = !!corpus?.pioneer_project_id
    const trainingKickedOff = !!corpus?.pioneer_training_job_id

    // Phase markers in order — first false one is where it broke (on
    // failure) or where it currently is (mid-run).
    const phaseDone = [
      dsDone,         // 0: discover
      corpusDone,     // 1: corpus
      projectDone,    // 2: register
      trainingKickedOff, // 3: ingest+training-kickoff
      ready,          // 4: deploy
    ]
    // Index of the first NOT-done phase.
    const firstPending = phaseDone.findIndex((d) => !d)
    // -1 means everything done → ready

    const stateFor = (phaseIdx: number): Stage['state'] => {
      if (phaseDone[phaseIdx]) return 'done'
      if (failed && phaseIdx === firstPending) return 'fail'
      // The currently-active phase: status maps to phase ordering.
      const statusToPhase: Record<VoiceModelStatus, number> = {
        idle: -1,
        deep_scraping: 0,
        corpus_building: 1,
        corpus_built: 1,
        training_queued: 2,
        training: 3,
        ready: 4,
        failed: -1,
      }
      const activePhase = statusToPhase[status]
      if (!failed && activePhase === phaseIdx) return 'active'
      return 'pending'
    }

    return [
      {
        id: 'discover',
        title: 'Discover brand surface',
        detail:
          dsDone && ds
            ? `${ds.fetched_pages} pages · ${ds.text_chunks} chunks · ${formatBreakdown(ds.by_kind)}`
            : status === 'deep_scraping'
              ? 'crawling sitemap, RSS, /about, /blog, /pricing…'
              : 'sitemap + RSS + common pages → cleaned text',
        state: stateFor(0),
      },
      {
        id: 'corpus',
        title: 'Build training corpus',
        detail: corpusDone
          ? `${corpus?.line_count} pairs · ${formatBreakdown(corpus?.breakdown ?? {})}`
          : status === 'corpus_building'
            ? 'Gemini reverse-briefs (24-way parallel) + synthesis…'
            : 'collect voice profile + posts + web → JSONL',
        state: stateFor(1),
      },
      {
        id: 'register',
        title: 'Register Pioneer project',
        detail: projectDone
          ? `project ${(corpus?.pioneer_project_id ?? '').slice(0, 8)}… created on api.pioneer.ai`
          : status === 'training_queued'
            ? 'POST api.pioneer.ai/projects'
            : 'one project per tenant brand',
        state: stateFor(2),
      },
      {
        id: 'train',
        title: 'Upload corpus + start LoRA training',
        detail: trainingKickedOff
          ? `job ${(corpus?.pioneer_training_job_id ?? '').slice(0, 8)}… running on Pioneer (Fireworks GPU)`
          : status === 'training_queued' || status === 'training'
            ? 'PUT presigned → process → POST /felix/training-jobs'
            : 'upload JSONL → kick LoRA fine-tune of Qwen3 4B Instruct',
        state: stateFor(3),
      },
      {
        id: 'deploy',
        title: 'Adapter live',
        detail: ready
          ? adapterUrl
            ? `${adapterUrl.slice(0, 60)}${adapterUrl.length > 60 ? '…' : ''}`
            : 'every draft routes through Pioneer /v1/chat/completions'
          : 'every draft will route through trained Qwen3 adapter',
        state: stateFor(4),
      },
    ]
  }, [status, corpus, adapterUrl])

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className="mt-8"
    >
      <h2 className="text-[13px] font-semibold">Pipeline</h2>
      <ol className="panel mt-4 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]">
        {stages.map((s, i) => (
          <StageRow key={s.id} stage={s} index={i + 1} />
        ))}
      </ol>
      {corpus && (
        <CorpusBreakdown corpus={corpus} modelId={modelId} />
      )}
    </motion.section>
  )
}

function StageRow({ stage, index }: { stage: Stage; index: number }) {
  const isActive = stage.state === 'active'
  const dot =
    stage.state === 'done'
      ? 'bg-emerald-500'
      : isActive
        ? 'bg-accent'
        : stage.state === 'fail'
          ? 'bg-red-500'
          : 'bg-fg-dim/50'
  const ring =
    stage.state === 'done' ? 'ring-4 ring-emerald-500/15' : ''
  return (
    <li
      className={`flex items-start gap-4 px-5 py-4 transition-colors ${
        isActive ? 'bg-accent/[0.04]' : ''
      }`}
    >
      {isActive ? (
        <Spinner className="mt-0.5 text-accent" />
      ) : (
        <div className={`mt-1 grid h-3 w-3 place-items-center rounded-full ${dot} ${ring}`} />
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[13px] font-medium leading-tight">
          <span className="text-fg-dim">0{index}.</span>
          <span>{stage.title}</span>
        </div>
        <div className="mt-0.5 text-[12px] text-fg-mute">{stage.detail}</div>
      </div>
      <StagePill state={stage.state} />
    </li>
  )
}

function Spinner({ className = '' }: { className?: string }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      className={`animate-spin ${className}`}
      aria-hidden
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeOpacity="0.2"
        strokeWidth="3"
      />
      <path
        d="M21 12a9 9 0 0 1-9 9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  )
}

function StagePill({ state }: { state: Stage['state'] }) {
  if (state === 'done') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-[10px] font-medium text-emerald-700">
        ✓ Done
      </span>
    )
  }
  if (state === 'active') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-2.5 py-1 text-[10px] font-medium text-accent">
        <Spinner className="text-accent" />
        Running
      </span>
    )
  }
  if (state === 'fail') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-red-50 px-2.5 py-1 text-[10px] font-medium text-red-700">
        ✕ Failed
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-bg-soft px-2.5 py-1 text-[10px] font-medium text-fg-mute">
      Waiting
    </span>
  )
}

function CorpusBreakdown({
  corpus,
  modelId,
}: {
  corpus: NonNullable<ReturnType<typeof useVoiceModelStore.getState>['corpus']>
  modelId: string | null
}) {
  const entries = Object.entries(corpus.breakdown).sort((a, b) => b[1] - a[1])
  return (
    <div className="panel mt-4 p-5">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
            Training corpus
          </div>
          <div className="mt-1 text-[15px] font-semibold">
            {corpus.line_count} instruction → response pairs
          </div>
        </div>
        {modelId && (
          <span className="rounded-full bg-bg-soft px-3 py-1 font-mono text-[11px] text-fg-mute">
            model · {modelId}
          </span>
        )}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        {entries.map(([source, n]) => (
          <span
            key={source}
            className="inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1 text-[11px] text-accent"
          >
            <span className="font-semibold">{n}</span>
            <span className="text-accent/80">{source.replace(/_/g, ' ')}</span>
          </span>
        ))}
      </div>
      {corpus.deep_scrape && corpus.deep_scrape.fetched_pages > 0 && (
        <DeepScrapeRow stats={corpus.deep_scrape} />
      )}
      {corpus.entities && corpus.entities.total > 0 && (
        <EntitiesRow entities={corpus.entities} />
      )}
      {corpus.jsonl_path && (
        <div className="mt-4 rounded-lg bg-bg-soft px-3 py-2 font-mono text-[11px] text-fg-mute">
          {corpus.jsonl_path}
        </div>
      )}
    </div>
  )
}

function DeepScrapeRow({
  stats,
}: {
  stats: NonNullable<
    NonNullable<
      ReturnType<typeof useVoiceModelStore.getState>['corpus']
    >['deep_scrape']
  >
}) {
  const KIND_LABEL: Record<string, string> = {
    common: 'common pages',
    sitemap: 'sitemap',
    rss: 'RSS / Atom',
    homepage_link: 'homepage links',
  }
  const entries = Object.entries(stats.by_kind).sort((a, b) => b[1] - a[1])
  return (
    <div className="mt-5 border-t border-line/60 pt-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
            Brand surface · deep scrape
          </div>
          <div className="mt-1 text-[12px] text-fg-mute">
            {stats.fetched_pages} pages · {stats.text_chunks} text chunks fed
            into the corpus alongside social posts.
          </div>
        </div>
        {stats.domain && (
          <span className="rounded-full bg-bg-soft px-3 py-1 font-mono text-[11px] text-fg-mute">
            {stats.domain.replace(/^https?:\/\//, '')}
          </span>
        )}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        {entries.map(([kind, n]) => (
          <span
            key={kind}
            className="inline-flex items-center gap-1.5 rounded-full bg-bg-soft px-3 py-1 text-[11px] text-fg"
          >
            <span className="font-semibold">{n}</span>
            <span className="text-fg-mute">
              {KIND_LABEL[kind] ?? kind.replace(/_/g, ' ')}
            </span>
          </span>
        ))}
      </div>
    </div>
  )
}

function EntitiesRow({
  entities,
}: {
  entities: NonNullable<
    NonNullable<
      ReturnType<typeof useVoiceModelStore.getState>['corpus']
    >['entities']
  >
}) {
  // Per-label display order — kept stable so the chip row doesn't jump
  // around as different brands surface different label mixes.
  const ORDER = [
    'product_name',
    'character_or_mascot',
    'signature_topic',
    'recurring_phrase',
    'tone_marker',
  ]
  const sourceLabel =
    entities.source === 'gliner2'
      ? 'GLiNER2'
      : entities.source === 'gemini_fallback'
        ? 'GLiNER2 fallback (Gemini)'
        : entities.source

  return (
    <div className="mt-5 border-t border-line/60 pt-4">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
            Brand vocabulary · extracted via {sourceLabel}
          </div>
          <div className="mt-1 text-[12px] text-fg-mute">
            {entities.total} entities — fed back into synthetic-pair generation
            so the LoRA learns your real product names, not generic stand-ins.
          </div>
        </div>
      </div>
      <div className="mt-3 flex flex-col gap-2">
        {ORDER.filter((label) => (entities.by_label[label]?.length ?? 0) > 0).map(
          (label) => (
            <div key={label} className="flex flex-wrap items-center gap-2">
              <span className="min-w-[140px] text-[11px] font-medium text-fg-mute">
                {label.replace(/_/g, ' ')}
              </span>
              <div className="flex flex-wrap gap-1.5">
                {(entities.by_label[label] ?? []).slice(0, 8).map((ent) => (
                  <span
                    key={`${label}:${ent}`}
                    className="rounded-full bg-bg-soft px-2.5 py-0.5 text-[11px] text-fg"
                  >
                    {ent}
                  </span>
                ))}
              </div>
            </div>
          ),
        )}
      </div>
    </div>
  )
}

function PreviewSection({ brand }: { brand: Brand }) {
  const [brief, setBrief] = useState(
    `Announce a limited drop of our new product. Audience is loyal customers; ${firstWord(
      brand.name,
    )}-style energy.`,
  )
  const [pioneerDraft, setPioneerDraft] = useState<DraftEnvelope | null>(null)
  const [geminiDraft, setGeminiDraft] = useState<DraftEnvelope | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [fallback, setFallback] = useState(false)

  async function handleRun() {
    if (loading || !brief.trim()) return
    setLoading(true)
    setError(null)
    setPioneerDraft(null)
    setGeminiDraft(null)
    setFallback(false)
    try {
      const callPreview = (mode: 'pioneer' | 'generic') =>
        fetch('/api/finetune/preview', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            brand_id: brand.id,
            brief: brief.trim(),
            platform: 'instagram',
            mode,
          }),
        }).then(async (r) => {
          if (!r.ok) throw new Error(`${mode} preview ${r.status}`)
          return (await r.json()) as {
            source: string
            draft: DraftEnvelope
          }
        })

      const [pioneer, generic] = await Promise.all([
        callPreview('pioneer'),
        callPreview('generic'),
      ])
      setPioneerDraft(pioneer.draft)
      setGeminiDraft(generic.draft)
      setFallback(pioneer.source === 'gemini_fallback')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'network')
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.15 }}
      className="mt-10"
    >
      <h2 className="text-[13px] font-semibold">Voice fidelity test</h2>
      <p className="mt-1 text-[12px] text-fg-mute">
        Same brief, two models. Pioneer-trained adapter on the left vs.
        generic Gemini on the right.
      </p>
      <div className="panel mt-4 p-5">
        <label className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
          Brief
        </label>
        <textarea
          value={brief}
          onChange={(e) => setBrief(e.target.value)}
          rows={3}
          className="mt-2 w-full rounded-lg border border-line bg-bg-soft px-3 py-2 text-[13px] leading-relaxed text-fg outline-none focus:border-accent"
        />
        <div className="mt-3 flex items-center justify-between">
          <button
            onClick={handleRun}
            disabled={loading || !brief.trim()}
            className="rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-5 py-2 text-[13px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] transition hover:brightness-110 disabled:opacity-50"
          >
            {loading ? 'Generating…' : 'Generate both'}
          </button>
          {error && <span className="text-[12px] text-red-600">{error}</span>}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <DraftCard
          label="Pioneer adapter"
          accent
          draft={pioneerDraft}
          loading={loading}
          fallback={fallback}
          placeholder="Brand voice, instruction-tuned. Click Generate."
        />
        <DraftCard
          label="Generic Gemini"
          draft={geminiDraft}
          loading={loading}
          placeholder="Same brief, no brand voice. Click Generate."
        />
      </div>
    </motion.section>
  )
}

function DraftCard({
  label,
  accent,
  draft,
  loading,
  fallback,
  placeholder,
}: {
  label: string
  accent?: boolean
  draft: DraftEnvelope | null
  loading: boolean
  fallback?: boolean
  placeholder?: string
}) {
  return (
    <div
      className={`panel relative flex min-h-[180px] flex-col p-5 ${
        accent ? 'ring-1 ring-accent/30' : ''
      }`}
    >
      <div className="flex items-center justify-between">
        <span
          className={`text-[11px] font-medium uppercase tracking-[0.16em] ${
            accent ? 'text-accent' : 'text-fg-mute'
          }`}
        >
          {label}
        </span>
        {fallback && (
          <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-700">
            Gemini fallback
          </span>
        )}
      </div>
      <AnimatePresence mode="wait">
        {loading ? (
          <motion.div
            key="loading"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="mt-3 flex h-full items-center text-[12px] text-fg-mute"
          >
            generating…
          </motion.div>
        ) : draft ? (
          <motion.div
            key="draft"
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            className="mt-3 flex flex-col gap-3"
          >
            {draft.caption && (
              <p className="text-[13.5px] leading-relaxed text-fg">
                {String(draft.caption)}
              </p>
            )}
            {Array.isArray(draft.hashtags) && draft.hashtags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {draft.hashtags.map((tag) => (
                  <span
                    key={String(tag)}
                    className="rounded-full bg-bg-soft px-2 py-0.5 text-[11px] text-fg-mute"
                  >
                    #{String(tag).replace(/^#/, '')}
                  </span>
                ))}
              </div>
            )}
            {draft.cta && (
              <div className="text-[12px] font-medium text-accent">
                → {String(draft.cta)}
              </div>
            )}
          </motion.div>
        ) : (
          <motion.div
            key="empty"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="mt-3 flex h-full items-center text-[12px] text-fg-dim"
          >
            {placeholder || 'No draft yet.'}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function labelFor(status: VoiceModelStatus): string {
  switch (status) {
    case 'idle':
      return 'not yet trained'
    case 'deep_scraping':
      return 'discovering brand surface'
    case 'corpus_building':
      return 'building corpus'
    case 'corpus_built':
      return 'corpus ready'
    case 'training_queued':
      return 'queued on Pioneer'
    case 'training':
      return 'training on Pioneer'
    case 'ready':
      return 'live'
    case 'failed':
      return 'failed'
  }
}

function heroTitle(status: VoiceModelStatus): string {
  switch (status) {
    case 'idle':
      return 'Train a voice model that drafts like you.'
    case 'deep_scraping':
      return 'Discovering every page you write on…'
    case 'corpus_building':
      return 'Building your training corpus…'
    case 'corpus_built':
      return 'Corpus is ready — uploading to Pioneer.'
    case 'training_queued':
      return 'Pioneer queued the job.'
    case 'training':
      return 'Pioneer is fine-tuning Qwen3 4B on your voice.'
    case 'ready':
      return 'Your voice model is live.'
    case 'failed':
      return 'Training hit a snag.'
  }
}

function heroSubtitle(
  status: VoiceModelStatus,
  brandName: string,
  training: ReturnType<typeof useVoiceModelStore.getState>['training'],
  corpus: ReturnType<typeof useVoiceModelStore.getState>['corpus'],
): string {
  const name = firstWord(brandName)
  switch (status) {
    case 'idle':
      return `One click. We deep-scrape ${name}'s site, ingest every social post, distil the voice, ship it to Pioneer for LoRA fine-tuning, and route every future draft through the trained adapter.`
    case 'deep_scraping':
      return `Crawling sitemap, RSS, and the usual suspects (/about, /blog, /pricing, /features…). Each page is dechromed and chunked into post-sized brand-voice samples.`
    case 'corpus_building':
      return `Reverse-engineering a brief for every real chunk we collected and synthesising more grounded in ${name}'s voice profile. Targeting 300 pairs.`
    case 'corpus_built':
      return corpus
        ? `${corpus.line_count} pairs ready. Uploading to Pioneer's fine-tune service.`
        : 'Corpus uploaded.'
    case 'training_queued':
      return 'Pioneer agent has the file. About to start LoRA fine-tuning on Qwen3 4B.'
    case 'training':
      return training
        ? `${training.stage} — ${Math.round(training.progress * 100)}%`
        : 'Fine-tuning in progress.'
    case 'ready':
      return `Every draft the agent generates for ${name} now flows through this adapter. Inference is JSON-shaped, ~2× cheaper than GPT-4o.`
    case 'failed':
      return "Check the logs and retry. Pioneer's API can be flaky around launch."
  }
}

function formatBreakdown(b: Record<string, number>): string {
  const entries = Object.entries(b).sort((a, b) => b[1] - a[1])
  if (entries.length === 0) return 'no sources'
  return entries
    .slice(0, 4)
    .map(([k, n]) => `${n} ${k.replace(/_/g, ' ')}`)
    .join(' · ')
}
