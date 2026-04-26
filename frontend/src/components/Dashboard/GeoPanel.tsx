import { useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { TopBar } from './TopBar'
import {
  useGeoStore,
  type ActionTypeMeta,
  type EnginePlaybookEntry,
} from '../../stores/geoStore'
import type {
  GeoActionType,
  GeoAssetPayload,
  GeoGapPayload,
  GeoRecommendationPayload,
} from '../../events/bus'
import { firstWord } from '../../lib/brandName'
import type { Brand } from './types'

// ────────────────────────────────────────────────────────────────────────────
// GeoPanel — the GEO Optimization workbench.
//
// Three columns of a closed loop:
//   1. Detected gaps         (Peec → here)
//   2. Recommended actions    (Gemini → here)
//   3. Generated assets       (per-action generator → here)
//
// Plus a per-engine playbook strip at the bottom so the user can see WHY
// each action got recommended for their gap mix.
// ────────────────────────────────────────────────────────────────────────────

const ACTION_TINTS: Record<GeoActionType, { bar: string; bg: string }> = {
  comparison_page: { bar: '#5b50e6', bg: '#eef0ff' },
  definition_first: { bar: '#0a66c2', bg: '#e0e9ff' },
  faq_schema: { bar: '#22a07a', bg: '#dcf3e9' },
  stats_quote: { bar: '#e09147', bg: '#fbe8d6' },
  wikidata_schema: { bar: '#9b3f8a', bg: '#f5e0f0' },
  reddit_draft: { bar: '#ff4500', bg: '#ffe5da' },
}

const ENGINE_TINTS: Record<string, { bar: string; bg: string; label: string }> =
  {
    chatgpt: { bar: '#10a37f', bg: '#10a37f1a', label: 'ChatGPT' },
    perplexity: { bar: '#5b9bd5', bg: '#5b9bd51a', label: 'Perplexity' },
    gemini: { bar: '#4285f4', bg: '#4285f41a', label: 'Gemini' },
    claude: { bar: '#cc785c', bg: '#cc785c1a', label: 'Claude' },
    google_ai_overviews: { bar: '#f4b400', bg: '#f4b4001a', label: 'AI Overviews' },
    grok: { bar: '#1e1e1e', bg: '#1e1e1e1a', label: 'Grok' },
  }

export function GeoPanel({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const load = useGeoStore((s) => s.load)
  const scan = useGeoStore((s) => s.scan)
  const seed = useGeoStore((s) => s.seed)
  const loading = useGeoStore((s) => s.loading)
  const loadError = useGeoStore((s) => s.loadError)
  const scanStatus = useGeoStore((s) => s.scanStatus)
  const scanError = useGeoStore((s) => s.scanError)
  const fetchedAt = useGeoStore((s) => s.fetchedAt)
  const summary = useGeoStore((s) => s.summary)
  const actionTypes = useGeoStore((s) => s.actionTypes)
  const enginePlaybook = useGeoStore((s) => s.enginePlaybook)
  const gaps = useGeoStore((s) => s.gaps)
  const recommendations = useGeoStore((s) => s.recommendations)
  const assets = useGeoStore((s) => s.assets)

  useEffect(() => {
    load(brand.id)
  }, [brand.id, load])

  const orderedGaps = useMemo(
    () =>
      Object.values(gaps).sort((a, b) => (b.gap_score ?? 0) - (a.gap_score ?? 0)),
    [gaps],
  )

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-10">
        <Header
          brand={brand}
          loading={loading}
          fetchedAt={fetchedAt}
          summary={summary}
          scanStatus={scanStatus}
          onScan={() => scan(brand.id)}
          onSeed={() => seed(brand.id)}
        />

        {loadError && <ErrorState message={loadError} />}
        {scanStatus === 'unavailable' ? (
          <PeecNotConnectedBanner
            reason={scanError}
            onConnected={() => {
              // Re-load + auto-rescan so the user sees gaps populate after
              // they finish the OAuth handshake without a second click.
              void load(brand.id)
              void scan(brand.id)
            }}
          />
        ) : (
          scanError && <ErrorState message={scanError} />
        )}

        <SummaryStrip summary={summary} />

        <div className="mt-7 grid grid-cols-1 gap-5 md:grid-cols-3">
          <GapColumn gaps={orderedGaps} />
          <RecommendationColumn
            gaps={orderedGaps}
            recommendations={Object.values(recommendations)}
            actionTypes={actionTypes}
          />
          <AssetColumn assets={Object.values(assets)} />
        </div>

        <PlaybookStrip
          actionTypes={actionTypes}
          enginePlaybook={enginePlaybook}
        />
      </div>
    </main>
  )
}

// ── Header ────────────────────────────────────────────────────────────────

function Header({
  brand,
  loading,
  fetchedAt,
  summary,
  scanStatus,
  onScan,
  onSeed,
}: {
  brand: Brand
  loading: boolean
  fetchedAt: string | null
  summary: ReturnType<typeof useGeoStore.getState>['summary']
  scanStatus: 'idle' | 'scanning' | 'done' | 'unavailable'
  onScan: () => void
  onSeed: () => Promise<{
    seeded: { id: string; text: string; source: string }[]
    error: string | null
  }>
}) {
  const scanning = scanStatus === 'scanning'
  const [seedState, setSeedState] = useState<
    | { kind: 'idle' }
    | { kind: 'seeding' }
    | { kind: 'done'; count: number }
    | { kind: 'error'; message: string }
  >({ kind: 'idle' })

  async function handleSeed() {
    setSeedState({ kind: 'seeding' })
    const { seeded, error } = await onSeed()
    if (error) {
      setSeedState({ kind: 'error', message: error })
    } else {
      setSeedState({ kind: 'done', count: seeded.length })
      window.setTimeout(() => setSeedState({ kind: 'idle' }), 4000)
    }
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-wrap items-end justify-between gap-4 pt-4"
    >
      <div>
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Generative-Engine Optimization
        </div>
        <h1 className="mt-1.5 text-[36px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
          GEO Workbench
        </h1>
        <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
          Closes the loop on Peec — surfaces the prompts {firstWord(brand.name)}{' '}
          loses on, picks the highest-yield action, and drafts the asset that
          fills the gap.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <div className="text-right text-[11px] text-fg-mute">
          {loading ? (
            <span>Loading…</span>
          ) : fetchedAt ? (
            <span>
              Updated{' '}
              {new Date(fetchedAt).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}{' '}
              · {summary.gap_count} gaps tracked
            </span>
          ) : (
            <span>Run a campaign or click scan to populate</span>
          )}
        </div>
        <button
          onClick={handleSeed}
          disabled={seedState.kind === 'seeding'}
          title="Add brand-relevant prompts to the Peec project"
          className="hairline inline-flex items-center gap-2 rounded-xl bg-bg-card px-4 py-2 text-[12.5px] font-medium text-fg-mute hover:text-fg disabled:opacity-60"
        >
          {seedState.kind === 'seeding' && (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-fg/30 border-t-fg/80" />
              Seeding…
            </>
          )}
          {seedState.kind === 'done' && (
            <>✓ Seeded {seedState.count} prompts</>
          )}
          {seedState.kind === 'error' && (
            <span className="text-red-700">Seed failed</span>
          )}
          {seedState.kind === 'idle' && <>＋ Seed prompts</>}
        </button>
        <button
          onClick={onScan}
          disabled={scanning}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110 disabled:opacity-60"
        >
          {scanning ? (
            <>
              <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
              Scanning Peec…
            </>
          ) : (
            <>↻ Scan now</>
          )}
        </button>
      </div>
    </motion.section>
  )
}

function SummaryStrip({
  summary,
}: {
  summary: ReturnType<typeof useGeoStore.getState>['summary']
}) {
  const items = [
    { label: 'Open gaps', value: summary.open_gap_count },
    { label: 'Recommendations', value: summary.recommendation_count },
    { label: 'Assets generated', value: summary.asset_count },
    { label: 'Published', value: summary.published_count },
  ]
  return (
    <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
      {items.map((it) => (
        <motion.div
          key={it.label}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="hairline rounded-2xl bg-bg-card p-4"
        >
          <div className="text-[10.5px] uppercase tracking-[0.16em] text-fg-mute">
            {it.label}
          </div>
          <div className="mt-1 text-[24px] font-semibold leading-tight tabular-nums text-fg">
            {it.value}
          </div>
        </motion.div>
      ))}
    </div>
  )
}

// ── Column 1: Gaps ────────────────────────────────────────────────────────

function GapColumn({ gaps }: { gaps: GeoGapPayload[] }) {
  return (
    <ColumnCard
      title="Detected gaps"
      subtitle="Prompts you lose to a competitor"
    >
      {gaps.length === 0 ? (
        <EmptyState>
          No gaps yet. Run a campaign with Peec connected, or click <em>Scan
          now</em> to detect.
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {gaps.map((g) => (
            <GapCard key={g.id} gap={g} />
          ))}
        </ul>
      )}
    </ColumnCard>
  )
}

function GapCard({ gap }: { gap: GeoGapPayload }) {
  const score = Math.round(((gap.gap_score ?? 0) / 100) * 100)
  const isOpen = gap.status === 'open'
  return (
    <li className="hairline rounded-xl bg-bg-card p-3.5">
      <div className="flex items-start justify-between gap-2">
        <span className="line-clamp-2 text-[12.5px] font-medium text-fg">
          {gap.prompt}
        </span>
        <StatusPill
          tone={
            gap.status === 'addressed'
              ? 'emerald'
              : gap.status === 'dismissed'
                ? 'zinc'
                : 'amber'
          }
        >
          {gap.status}
        </StatusPill>
      </div>
      <div className="mt-2 flex items-center gap-2 text-[11px] text-fg-mute">
        <span>
          winner:{' '}
          <span className="text-fg">{gap.competitor_name ?? '—'}</span>
        </span>
        {gap.competitor_visibility != null && (
          <span>· {gap.competitor_visibility.toFixed(1)}%</span>
        )}
        {isOpen && (
          <span className="ml-auto rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
            score {score}
          </span>
        )}
      </div>
      {gap.engines_present.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {gap.engines_present.map((e) => {
            const tint = ENGINE_TINTS[e]
            const label = tint?.label ?? e
            return (
              <span
                key={e}
                className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px]"
                style={{
                  background: tint?.bg ?? 'rgba(20,20,40,0.05)',
                  color: tint?.bar ?? 'currentColor',
                }}
              >
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: tint?.bar ?? '#888' }}
                />
                {label}
              </span>
            )
          })}
        </div>
      )}
    </li>
  )
}

// ── Column 2: Recommendations ─────────────────────────────────────────────

function RecommendationColumn({
  gaps,
  recommendations,
  actionTypes,
}: {
  gaps: GeoGapPayload[]
  recommendations: GeoRecommendationPayload[]
  actionTypes: ActionTypeMeta[]
}) {
  const accept = useGeoStore((s) => s.accept)
  const reject = useGeoStore((s) => s.reject)
  const generating = useGeoStore((s) => s.generating)

  const gapsById = useMemo(() => {
    const out: Record<string, GeoGapPayload> = {}
    for (const g of gaps) out[g.id] = g
    return out
  }, [gaps])

  const ordered = useMemo(
    () =>
      [...recommendations].sort((a, b) => {
        // Show pending proposals first, then accepted/generated, then rejected.
        const order = (s: string) =>
          s === 'proposed'
            ? 0
            : s === 'accepted'
              ? 1
              : s === 'generated'
                ? 2
                : 3
        const so = order(a.status) - order(b.status)
        if (so !== 0) return so
        return (b.confidence ?? 0) - (a.confidence ?? 0)
      }),
    [recommendations],
  )

  const labelByType = useMemo(() => {
    const out: Record<string, string> = {}
    for (const a of actionTypes) out[a.key] = a.label
    return out
  }, [actionTypes])

  return (
    <ColumnCard
      title="Recommended actions"
      subtitle="One play per gap, picked by the recommender"
    >
      {ordered.length === 0 ? (
        <EmptyState>
          Once gaps are detected, the recommender picks the highest-leverage
          play (comparison page · stats injection · FAQ schema · Wikidata · …).
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {ordered.map((r) => (
            <RecommendationCard
              key={r.id}
              reco={r}
              gap={gapsById[r.gap_id]}
              actionLabel={labelByType[r.action_type] ?? r.action_label}
              isGenerating={Boolean(generating[r.id])}
              onAccept={() => accept(r.id)}
              onReject={() => reject(r.id)}
            />
          ))}
        </ul>
      )}
    </ColumnCard>
  )
}

function RecommendationCard({
  reco,
  gap,
  actionLabel,
  isGenerating,
  onAccept,
  onReject,
}: {
  reco: GeoRecommendationPayload
  gap: GeoGapPayload | undefined
  actionLabel: string
  isGenerating: boolean
  onAccept: () => void
  onReject: () => void
}) {
  const tint = ACTION_TINTS[reco.action_type] ?? {
    bar: '#5b50e6',
    bg: '#eef0ff',
  }
  const confidencePct = Math.round((reco.confidence ?? 0) * 100)
  const isClosed =
    reco.status === 'rejected' || reco.status === 'generated'
  const accepted = reco.status === 'accepted' || isGenerating

  return (
    <li
      className="hairline rounded-xl bg-bg-card p-3.5"
      style={{ borderLeft: `3px solid ${tint.bar}` }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em]"
            style={{ background: tint.bg, color: tint.bar }}
          >
            {actionLabel}
          </div>
          {gap && (
            <div className="mt-2 line-clamp-2 text-[12px] text-fg-mute">
              for: <span className="text-fg">"{gap.prompt}"</span>
            </div>
          )}
        </div>
        <StatusPill
          tone={
            reco.status === 'generated'
              ? 'emerald'
              : reco.status === 'accepted'
                ? 'violet'
                : reco.status === 'rejected'
                  ? 'zinc'
                  : 'amber'
          }
        >
          {reco.status}
        </StatusPill>
      </div>
      {reco.rationale && (
        <p className="mt-2 text-[12px] leading-snug text-fg">
          {reco.rationale}
        </p>
      )}
      <div className="mt-2.5 flex items-center justify-between text-[11px] text-fg-mute">
        <span>confidence</span>
        <span className="tabular-nums text-fg">{confidencePct}%</span>
      </div>
      <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-line">
        <div
          className="h-full"
          style={{
            width: `${confidencePct}%`,
            background: tint.bar,
          }}
        />
      </div>
      {reco.target_engines.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {reco.target_engines.map((e) => {
            const t = ENGINE_TINTS[e]
            return (
              <span
                key={e}
                className="rounded-full px-1.5 py-0.5 text-[10px]"
                style={{
                  background: t?.bg ?? 'rgba(20,20,40,0.05)',
                  color: t?.bar ?? '#666',
                }}
              >
                {t?.label ?? e}
              </span>
            )
          })}
        </div>
      )}
      {!isClosed && (
        <div className="mt-3 flex gap-2">
          <button
            onClick={onAccept}
            disabled={accepted}
            className="flex-1 rounded-lg bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-3 py-1.5 text-[12px] font-medium text-white shadow-[0_2px_8px_rgba(91,80,230,0.25)] hover:brightness-110 disabled:opacity-60"
          >
            {accepted
              ? isGenerating
                ? 'Generating…'
                : 'Accepted'
              : 'Accept & generate'}
          </button>
          <button
            onClick={onReject}
            disabled={accepted}
            className="hairline rounded-lg bg-bg-card px-3 py-1.5 text-[12px] text-fg-mute hover:text-fg disabled:opacity-60"
          >
            Skip
          </button>
        </div>
      )}
      {isGenerating && (
        <div className="mt-3 flex items-center gap-2 text-[11px] text-accent">
          <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-accent/40 border-t-accent" />
          drafting asset…
        </div>
      )}
    </li>
  )
}

// ── Column 3: Generated assets ───────────────────────────────────────────

function AssetColumn({ assets }: { assets: GeoAssetPayload[] }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const ordered = useMemo(
    () =>
      [...assets].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [assets],
  )
  return (
    <ColumnCard
      title="Generated assets"
      subtitle="Drafts ready to ship"
    >
      {ordered.length === 0 ? (
        <EmptyState>
          Once you accept a recommendation, the per-action generator drafts
          the markdown / JSON-LD here.
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-3">
          {ordered.map((a) => (
            <AssetCard
              key={a.id}
              asset={a}
              onOpen={() => setOpenId(a.id)}
            />
          ))}
        </ul>
      )}
      <AssetDrawer
        asset={openId ? ordered.find((a) => a.id === openId) ?? null : null}
        onClose={() => setOpenId(null)}
      />
    </ColumnCard>
  )
}

function AssetCard({
  asset,
  onOpen,
}: {
  asset: GeoAssetPayload
  onOpen: () => void
}) {
  const tint = ACTION_TINTS[asset.action_type] ?? {
    bar: '#5b50e6',
    bg: '#eef0ff',
  }
  return (
    <li className="hairline rounded-xl bg-bg-card p-3.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div
            className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em]"
            style={{ background: tint.bg, color: tint.bar }}
          >
            {asset.action_label}
          </div>
          <h3 className="mt-2 line-clamp-2 text-[13px] font-semibold text-fg">
            {asset.title ?? 'Untitled draft'}
          </h3>
        </div>
        <StatusPill
          tone={asset.status === 'published' ? 'emerald' : 'violet'}
        >
          {asset.status}
        </StatusPill>
      </div>
      {asset.body_markdown && (
        <p className="mt-2 line-clamp-3 text-[12px] leading-snug text-fg-mute">
          {asset.body_markdown.replace(/[#*_>`]/g, '').slice(0, 240)}
        </p>
      )}
      <div className="mt-2.5 flex items-center justify-between text-[11px] text-fg-mute">
        <span>
          {asset.predicted_lift_pct != null
            ? `predicted lift ${asset.predicted_lift_pct.toFixed(1)}%`
            : 'lift TBD'}
        </span>
        <button
          onClick={onOpen}
          className="font-medium text-accent hover:underline"
        >
          Open →
        </button>
      </div>
    </li>
  )
}

function AssetDrawer({
  asset,
  onClose,
}: {
  asset: GeoAssetPayload | null
  onClose: () => void
}) {
  const publish = useGeoStore((s) => s.publish)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    if (asset) document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [asset, onClose])

  return (
    <AnimatePresence>
      {asset && (
        <motion.div
          key="overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-40 flex items-stretch justify-end bg-fg/30"
          onClick={onClose}
        >
          <motion.aside
            key="panel"
            initial={{ x: 60, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 60, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            onClick={(e) => e.stopPropagation()}
            className="flex w-full max-w-2xl flex-col bg-bg-card shadow-[0_24px_60px_rgba(20,20,40,0.18)]"
          >
            <header className="flex items-start justify-between gap-3 border-b border-line p-6">
              <div className="min-w-0">
                <div className="text-[10px] uppercase tracking-[0.18em] text-fg-mute">
                  {asset.action_label}
                </div>
                <h2 className="mt-1 line-clamp-2 text-[18px] font-semibold leading-snug text-fg">
                  {asset.title ?? 'Untitled draft'}
                </h2>
                {asset.predicted_lift_pct != null && (
                  <p className="mt-2 text-[12px] text-fg-mute">
                    Predicted citation lift{' '}
                    <span className="text-fg">
                      {asset.predicted_lift_pct.toFixed(1)}%
                    </span>
                  </p>
                )}
              </div>
              <button
                onClick={onClose}
                className="grid h-8 w-8 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
              >
                ×
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-6 py-5">
              <pre className="whitespace-pre-wrap font-mono text-[12px] leading-relaxed text-fg">
                {asset.body_markdown ??
                  JSON.stringify(asset.body_json, null, 2)}
              </pre>
            </div>

            <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line p-5">
              <div className="text-[11px] text-fg-mute">
                {asset.status === 'published' && asset.published_at
                  ? `Published ${new Date(asset.published_at).toLocaleString()}`
                  : 'Draft — review before shipping'}
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={async () => {
                    if (!asset.body_markdown) return
                    try {
                      await navigator.clipboard.writeText(asset.body_markdown)
                      setCopied(true)
                      setTimeout(() => setCopied(false), 1400)
                    } catch {
                      /* clipboard blocked */
                    }
                  }}
                  className="hairline rounded-full bg-bg-card px-3 py-1.5 text-[12px] text-fg-mute hover:text-fg"
                >
                  {copied ? '✓ Copied' : '⧉ Copy markdown'}
                </button>
                <button
                  onClick={() => publish(asset.id)}
                  disabled={asset.status === 'published'}
                  className="rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-1.5 text-[12px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110 disabled:opacity-60"
                >
                  {asset.status === 'published' ? 'Published' : 'Mark published'}
                </button>
              </div>
            </footer>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

// ── Playbook strip ────────────────────────────────────────────────────────

function PlaybookStrip({
  actionTypes,
  enginePlaybook,
}: {
  actionTypes: ActionTypeMeta[]
  enginePlaybook: EnginePlaybookEntry[]
}) {
  const [tab, setTab] = useState<'actions' | 'engines'>('actions')
  if (actionTypes.length === 0 && enginePlaybook.length === 0) return null
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay: 0.15 }}
      className="mt-7 rounded-2xl border border-accent/20 bg-accent-soft/40 p-6"
    >
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
            Playbook reference
          </div>
          <p className="mt-1 max-w-xl text-[12.5px] text-fg-mute">
            Why each action moves the needle, and how the per-engine biases
            shift the recommender's choice.
          </p>
        </div>
        <div className="hairline flex items-center gap-0.5 rounded-full bg-bg p-0.5">
          <button
            onClick={() => setTab('actions')}
            className={`rounded-full px-3 py-1 text-[11px] font-medium ${
              tab === 'actions'
                ? 'bg-bg-card text-fg shadow-[0_1px_2px_rgba(20,20,40,0.06)]'
                : 'text-fg-mute hover:text-fg'
            }`}
          >
            Actions
          </button>
          <button
            onClick={() => setTab('engines')}
            className={`rounded-full px-3 py-1 text-[11px] font-medium ${
              tab === 'engines'
                ? 'bg-bg-card text-fg shadow-[0_1px_2px_rgba(20,20,40,0.06)]'
                : 'text-fg-mute hover:text-fg'
            }`}
          >
            Per-engine biases
          </button>
        </div>
      </div>
      {tab === 'actions' ? (
        <ul className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {actionTypes.map((a) => {
            const tint = ACTION_TINTS[a.key] ?? {
              bar: '#5b50e6',
              bg: '#eef0ff',
            }
            return (
              <li
                key={a.key}
                className="rounded-xl bg-bg-card p-3.5"
                style={{ borderLeft: `3px solid ${tint.bar}` }}
              >
                <div
                  className="inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em]"
                  style={{ background: tint.bg, color: tint.bar }}
                >
                  {a.label}
                </div>
                <p className="mt-2 text-[12px] leading-snug text-fg">
                  {a.summary}
                </p>
              </li>
            )
          })}
        </ul>
      ) : (
        <ul className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {enginePlaybook.map((e) => {
            const t = ENGINE_TINTS[e.key]
            return (
              <li key={e.key} className="rounded-xl bg-bg-card p-3.5">
                <div className="flex items-center gap-2">
                  <span
                    className="grid h-5 w-5 place-items-center rounded-md text-[10px] font-bold text-white"
                    style={{ background: t?.bar ?? '#5b50e6' }}
                  >
                    {e.label[0]}
                  </span>
                  <span className="text-[13px] font-semibold text-fg">
                    {e.label}
                  </span>
                </div>
                <p className="mt-1.5 text-[11.5px] text-fg-mute">
                  {e.retrieval}
                </p>
                <p className="mt-2 text-[12px] text-fg">{e.note}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {e.high_leverage.map((h) => {
                    const at = ACTION_TINTS[h]
                    return (
                      <span
                        key={h}
                        className="rounded-full px-1.5 py-0.5 text-[10px]"
                        style={{
                          background: at?.bg ?? '#eef0ff',
                          color: at?.bar ?? '#5b50e6',
                        }}
                      >
                        {h.replace(/_/g, ' ')}
                      </span>
                    )
                  })}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </motion.section>
  )
}

// ── Shared atoms ──────────────────────────────────────────────────────────

function ColumnCard({
  title,
  subtitle,
  children,
}: {
  title: string
  subtitle: string
  children: React.ReactNode
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="panel flex flex-col p-5"
    >
      <div>
        <div className="text-[13px] font-semibold text-fg">{title}</div>
        <p className="mt-1 text-[11px] text-fg-mute">{subtitle}</p>
      </div>
      <div className="mt-4 flex-1">{children}</div>
    </motion.div>
  )
}

function EmptyState({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line bg-bg p-5 text-[12px] leading-snug text-fg-mute">
      {children}
    </div>
  )
}

function StatusPill({
  tone,
  children,
}: {
  tone: 'amber' | 'emerald' | 'violet' | 'zinc'
  children: React.ReactNode
}) {
  const cls =
    tone === 'emerald'
      ? 'bg-emerald-100 text-emerald-700'
      : tone === 'violet'
        ? 'bg-accent-soft text-accent'
        : tone === 'zinc'
          ? 'bg-zinc-100 text-zinc-600'
          : 'bg-amber-100 text-amber-700'
  return (
    <span
      className={`shrink-0 rounded-full px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] ${cls}`}
    >
      {children}
    </span>
  )
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="mt-4 panel px-5 py-4">
      <div className="text-[12px] font-medium text-red-700">{message}</div>
    </div>
  )
}

function PeecNotConnectedBanner({
  reason,
  onConnected,
}: {
  reason: string | null
  onConnected: () => void
}) {
  const [connecting, setConnecting] = useState(false)
  const [connectError, setConnectError] = useState<string | null>(null)

  async function handleConnect() {
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
              /* cross-origin close may fail */
            }
            setConnecting(false)
            onConnected()
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

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="mt-4 flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-accent/20 bg-accent-soft/50 px-5 py-4"
    >
      <div className="min-w-0">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
          Peec not connected
        </div>
        <p className="mt-1 max-w-xl text-[12.5px] leading-snug text-fg">
          GEO needs a live Peec project to detect gaps.{' '}
          {reason && reason !== 'peec snapshot unavailable' && (
            <span className="text-fg-mute">({reason}) </span>
          )}
          Connect Peec MCP to unlock gap detection, recommendations, and
          per-engine playbook biasing.
        </p>
        {connectError && (
          <p className="mt-2 text-[11px] text-red-700">{connectError}</p>
        )}
      </div>
      <button
        onClick={handleConnect}
        disabled={connecting}
        className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110 disabled:opacity-60"
      >
        {connecting ? (
          <>
            <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-white/40 border-t-white" />
            Waiting for consent…
          </>
        ) : (
          <>Connect Peec MCP →</>
        )}
      </button>
    </motion.div>
  )
}
