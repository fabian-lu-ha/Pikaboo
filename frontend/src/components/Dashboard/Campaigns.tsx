import { useCallback, useEffect, useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { TopBar } from './TopBar'
import { useNav } from './navContext'
import { CampaignDetailDrawer } from './CampaignDetailDrawer'
import { useAgentSessionStore } from '../../stores/agentSessionStore'
import { firstWord, relativeTime } from '../../lib/brandName'
import { bus } from '../../events/bus'
import type { Brand } from './types'

// ─── api shapes ────────────────────────────────────────────────────────────
// Mirrors backend/app/api/campaigns.py. Keep these in sync with the
// CampaignListItem / CampaignStats Pydantic models.

export type LiftBand = 'breakout' | 'strong' | 'modest' | 'negative' | 'unknown'

type CampaignListItem = {
  id: string
  brand_id: string
  title: string
  predicted_lift: number | null
  lift_band: LiftBand
  confidence: string | null
  created_at: string
  channels: string[]
  hero_image_url: string | null
  draft_count: number
  has_blog: boolean
  target_prompts: string[]
}

type CampaignListResponse = {
  items: CampaignListItem[]
  total: number
  offset: number
  limit: number
}

type LiftBandSlice = { band: LiftBand; count: number }
type ChannelSlice = { channel: string; count: number }
type TimelineBucket = { iso: string; count: number; avg_lift: number | null }

type CampaignStats = {
  total: number
  last_7_days: number
  last_30_days: number
  avg_lift: number | null
  median_lift: number | null
  best_lift: number | null
  best_id: string | null
  best_title: string | null
  bundled_share: number
  bands: LiftBandSlice[]
  channels: ChannelSlice[]
  timeline: TimelineBucket[]
}

// ─── presentation tokens ───────────────────────────────────────────────────

const BAND_LABEL: Record<LiftBand, string> = {
  breakout: 'Breakout',
  strong: 'Strong',
  modest: 'Modest',
  negative: 'Negative',
  unknown: 'Unscored',
}

const BAND_THEME: Record<
  LiftBand,
  { fg: string; bg: string; ring: string; dot: string }
> = {
  breakout: {
    fg: 'text-emerald-700',
    bg: 'bg-emerald-50',
    ring: 'ring-emerald-200',
    dot: 'bg-emerald-500',
  },
  strong: {
    fg: 'text-accent',
    bg: 'bg-accent-soft',
    ring: 'ring-[rgba(91,80,230,0.25)]',
    dot: 'bg-accent',
  },
  modest: {
    fg: 'text-amber-700',
    bg: 'bg-amber-50',
    ring: 'ring-amber-200',
    dot: 'bg-amber-500',
  },
  negative: {
    fg: 'text-red-700',
    bg: 'bg-red-50',
    ring: 'ring-red-200',
    dot: 'bg-red-500',
  },
  unknown: {
    fg: 'text-fg-mute',
    bg: 'bg-bg-soft',
    ring: 'ring-line',
    dot: 'bg-fg-dim',
  },
}

const CHANNEL_META: Record<string, { label: string; glyph: string }> = {
  linkedin: { label: 'LinkedIn', glyph: 'in' },
  x: { label: 'X', glyph: '✕' },
  twitter: { label: 'X', glyph: '✕' },
  threads: { label: 'Threads', glyph: '@' },
  instagram: { label: 'Instagram', glyph: '◫' },
  'instagram-post': { label: 'Instagram Post', glyph: '◫' },
  'instagram-video': { label: 'Instagram Video', glyph: '▶' },
  'tiktok-reel': { label: 'TikTok Reel', glyph: '◉' },
  tiktok: { label: 'TikTok', glyph: '◉' },
  carousel: { label: 'Carousel', glyph: '◧' },
  blog: { label: 'Blog', glyph: '✎' },
  email: { label: 'Email', glyph: '✉' },
  newsletter: { label: 'Newsletter', glyph: '✉' },
  youtube: { label: 'YouTube', glyph: '▶' },
  hero_image: { label: 'Hero Image', glyph: '◇' },
}

function channelLabel(c: string) {
  return CHANNEL_META[c]?.label ?? c
}
function channelGlyph(c: string) {
  return CHANNEL_META[c]?.glyph ?? '◌'
}

type SortKey = 'recent' | 'oldest' | 'lift_desc' | 'lift_asc' | 'alpha'

const SORT_LABEL: Record<SortKey, string> = {
  recent: 'Newest',
  oldest: 'Oldest',
  lift_desc: 'Highest lift',
  lift_asc: 'Lowest lift',
  alpha: 'A → Z',
}

// ─── main page ─────────────────────────────────────────────────────────────

export function Campaigns({ brand }: { brand: Brand }) {
  const { navigate } = useNav()
  const restore = useAgentSessionStore((s) => s.restore)
  const [search, setSearch] = useState('')
  const [bandFilter, setBandFilter] = useState<LiftBand | 'all'>('all')
  const [channelFilter, setChannelFilter] = useState<string | 'all'>('all')
  const [sort, setSort] = useState<SortKey>('recent')
  const [view, setView] = useState<'grid' | 'list'>('grid')
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const list = useCampaignList({
    brandId: brand.id,
    q: search,
    band: bandFilter,
    channel: channelFilter,
    sort,
  })
  const stats = useCampaignStats(brand.id)

  function startNewCampaign() {
    useAgentSessionStore.getState().reset()
    navigate('dashboard')
  }

  function restoreToDashboard(id: string) {
    void restore(id)
    navigate('dashboard')
  }

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-16">
        <Header
          brand={brand}
          total={stats?.total ?? list.total}
          onNew={startNewCampaign}
        />

        <StatsHero stats={stats} loading={stats === null} />

        <Toolbar
          bandFilter={bandFilter}
          onBandFilter={setBandFilter}
          channelFilter={channelFilter}
          onChannelFilter={setChannelFilter}
          channels={stats?.channels ?? []}
          sort={sort}
          onSort={setSort}
          view={view}
          onView={setView}
          showing={list.items.length}
          total={list.total}
        />

        <CampaignsBody
          state={list}
          view={view}
          onOpen={setSelectedId}
          onRestore={restoreToDashboard}
          onNew={startNewCampaign}
          onClearFilters={() => {
            setBandFilter('all')
            setChannelFilter('all')
            setSearch('')
          }}
          activeFilters={
            bandFilter !== 'all' || channelFilter !== 'all' || !!search.trim()
          }
        />
      </div>

      <CampaignDetailDrawer
        campaignId={selectedId}
        brandName={brand.name}
        onClose={() => setSelectedId(null)}
        onRestore={(id) => {
          setSelectedId(null)
          restoreToDashboard(id)
        }}
        onDuplicate={(id) => {
          void list.duplicate(id)
        }}
        onDelete={(id) => {
          setSelectedId(null)
          void list.remove(id)
        }}
      />
    </main>
  )
}

// ─── header ────────────────────────────────────────────────────────────────

function Header({
  brand,
  total,
  onNew,
}: {
  brand: Brand
  total: number
  onNew: () => void
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-wrap items-end justify-between gap-4 pt-4"
    >
      <div className="min-w-0">
        <div className="text-[12px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Campaigns library
        </div>
        <h1 className="mt-1 flex items-center gap-3 text-[36px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
          {firstWord(brand.name)}'s campaigns
          <span className="inline-flex items-center gap-1 rounded-full bg-bg-soft px-2.5 py-1 text-[12px] font-medium text-fg-mute">
            {total} total
          </span>
        </h1>
        <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
          Every draft, ship, and lift the agent has produced for{' '}
          {firstWord(brand.name)}. Filter, restore, duplicate, or open one to
          see the full multi-channel bundle.
        </p>
      </div>
      <button
        onClick={onNew}
        className="flex items-center gap-2 rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2.5 text-[13px] font-medium text-white shadow-[0_8px_22px_rgba(91,80,230,0.35)] transition hover:brightness-110"
      >
        <span className="text-[15px] leading-none">+</span>
        <span>New Campaign</span>
      </button>
    </motion.section>
  )
}

// ─── stats hero ────────────────────────────────────────────────────────────

function StatsHero({
  stats,
  loading,
}: {
  stats: CampaignStats | null
  loading: boolean
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,1fr))_minmax(0,1.4fr)]"
    >
      <StatCard
        label="Total campaigns"
        value={stats ? String(stats.total) : '—'}
        sub={stats ? `${stats.last_30_days} in last 30 days` : ' '}
        loading={loading}
        glyph="✦"
        tint="violet"
      />
      <StatCard
        label="Avg predicted lift"
        value={stats?.avg_lift != null ? `${stats.avg_lift.toFixed(1)}%` : '—'}
        sub={
          stats?.median_lift != null
            ? `Median ${stats.median_lift.toFixed(1)}%`
            : 'No bundled runs yet'
        }
        loading={loading}
        glyph="◐"
        tint="emerald"
        accent={liftAccent(stats?.avg_lift ?? null)}
      />
      <StatCard
        label="Last 7 days"
        value={stats ? String(stats.last_7_days) : '—'}
        sub={stats ? formatBundledShare(stats.bundled_share) : ' '}
        loading={loading}
        glyph="◴"
        tint="amber"
      />
      <StatCard
        label="Best run"
        value={stats?.best_lift != null ? `${stats.best_lift.toFixed(1)}%` : '—'}
        sub={
          stats?.best_title
            ? truncate(stats.best_title, 38)
            : 'No clear winner yet'
        }
        loading={loading}
        glyph="◆"
        tint="sky"
      />
      <TimelineCard timeline={stats?.timeline ?? []} loading={loading} />
    </motion.section>
  )
}

function StatCard({
  label,
  value,
  sub,
  loading,
  glyph,
  tint,
  accent,
}: {
  label: string
  value: string
  sub: string
  loading: boolean
  glyph: string
  tint: 'violet' | 'emerald' | 'amber' | 'sky'
  accent?: string
}) {
  const TINT: Record<
    typeof tint,
    { bg: string; fg: string }
  > = {
    violet: { bg: '#eef0ff', fg: '#5b50e6' },
    emerald: { bg: '#dcf3e9', fg: '#1f9e6e' },
    amber: { bg: '#fbe8d6', fg: '#d97a3a' },
    sky: { bg: '#e0e7ff', fg: '#4338ca' },
  }
  const t = TINT[tint]
  return (
    <div className="panel relative overflow-hidden p-5">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
          {label}
        </div>
        <span
          className="grid h-8 w-8 place-items-center rounded-lg text-[13px]"
          style={{ background: t.bg, color: t.fg }}
        >
          {glyph}
        </span>
      </div>
      <div
        className="mt-3 text-[28px] font-semibold leading-none tracking-[-0.01em]"
        style={accent ? { color: accent } : undefined}
      >
        {loading ? <span className="text-fg-dim">—</span> : value}
      </div>
      <div className="mt-1.5 text-[12px] text-fg-mute">{sub}</div>
    </div>
  )
}

function TimelineCard({
  timeline,
  loading,
}: {
  timeline: TimelineBucket[]
  loading: boolean
}) {
  const max = Math.max(1, ...timeline.map((b) => b.count))
  const peakLift = useMemo(
    () =>
      timeline.reduce<number | null>(
        (acc, b) =>
          b.avg_lift == null ? acc : acc == null ? b.avg_lift : Math.max(acc, b.avg_lift),
        null,
      ),
    [timeline],
  )
  return (
    <div className="panel relative overflow-hidden p-5">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
          Activity · last {timeline.length || 8} weeks
        </div>
        <span className="text-[11px] text-fg-mute">
          {peakLift != null ? `Peak avg lift ${peakLift.toFixed(1)}%` : ' '}
        </span>
      </div>
      <div className="mt-4 flex h-[78px] items-end gap-1.5">
        {(loading || timeline.length === 0
          ? Array.from({ length: 8 }).map(() => ({ iso: '', count: 0, avg_lift: null }))
          : timeline
        ).map((b, i) => {
          const h = Math.round((b.count / max) * 100)
          const lift = b.avg_lift
          const fg =
            lift != null && lift >= 25
              ? '#1f9e6e'
              : lift != null && lift >= 10
                ? '#5b50e6'
                : lift != null && lift >= 0
                  ? '#d97a3a'
                  : lift != null
                    ? '#d44a6a'
                    : '#dde0f3'
          return (
            <div
              key={`${b.iso}-${i}`}
              className="group relative flex flex-1 items-end"
              title={
                b.iso
                  ? `${new Date(b.iso).toLocaleDateString()} — ${b.count} campaigns${
                      lift != null ? ` · avg ${lift.toFixed(1)}%` : ''
                    }`
                  : ''
              }
            >
              <div
                style={{ height: `${Math.max(6, h)}%`, background: fg }}
                className="w-full rounded-t-md transition group-hover:brightness-110"
              />
            </div>
          )
        })}
      </div>
      <div className="mt-2 flex items-center justify-between text-[10px] text-fg-dim">
        <span>{timeline[0]?.iso ? new Date(timeline[0].iso).toLocaleDateString() : ''}</span>
        <span>now</span>
      </div>
    </div>
  )
}

function liftAccent(lift: number | null): string | undefined {
  if (lift == null) return undefined
  if (lift >= 25) return '#1f9e6e'
  if (lift >= 10) return '#5b50e6'
  if (lift >= 0) return '#d97a3a'
  return '#d44a6a'
}

function formatBundledShare(share: number): string {
  if (share <= 0) return 'No bundled runs yet'
  return `${Math.round(share * 100)}% bundled`
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, n - 1)}…` : s
}

// ─── toolbar ───────────────────────────────────────────────────────────────

function Toolbar({
  bandFilter,
  onBandFilter,
  channelFilter,
  onChannelFilter,
  channels,
  sort,
  onSort,
  view,
  onView,
  showing,
  total,
}: {
  bandFilter: LiftBand | 'all'
  onBandFilter: (b: LiftBand | 'all') => void
  channelFilter: string | 'all'
  onChannelFilter: (c: string | 'all') => void
  channels: ChannelSlice[]
  sort: SortKey
  onSort: (s: SortKey) => void
  view: 'grid' | 'list'
  onView: (v: 'grid' | 'list') => void
  showing: number
  total: number
}) {
  const bands: (LiftBand | 'all')[] = ['all', 'breakout', 'strong', 'modest', 'negative', 'unknown']
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.08 }}
      className="mt-8 flex flex-col gap-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
          Lift band
        </span>
        {bands.map((b) => {
          const isActive = bandFilter === b
          if (b === 'all') {
            return (
              <button
                key="all"
                onClick={() => onBandFilter('all')}
                className={`rounded-full px-3 py-1 text-[11.5px] font-medium transition ${
                  isActive
                    ? 'bg-fg text-white'
                    : 'hairline bg-bg-card text-fg-mute hover:text-fg'
                }`}
              >
                All
              </button>
            )
          }
          const t = BAND_THEME[b]
          return (
            <button
              key={b}
              onClick={() => onBandFilter(b)}
              className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition ${
                isActive
                  ? `${t.bg} ${t.fg} ring-2 ${t.ring}`
                  : 'hairline bg-bg-card text-fg-mute hover:text-fg'
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${t.dot}`} />
              {BAND_LABEL[b]}
            </button>
          )
        })}
      </div>

      {channels.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
            Channel
          </span>
          <button
            onClick={() => onChannelFilter('all')}
            className={`rounded-full px-3 py-1 text-[11.5px] font-medium transition ${
              channelFilter === 'all'
                ? 'bg-fg text-white'
                : 'hairline bg-bg-card text-fg-mute hover:text-fg'
            }`}
          >
            All
          </button>
          {channels.map((c) => {
            const isActive = channelFilter === c.channel
            return (
              <button
                key={c.channel}
                onClick={() => onChannelFilter(c.channel)}
                className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition ${
                  isActive
                    ? 'bg-accent-soft text-accent ring-2 ring-[rgba(91,80,230,0.25)]'
                    : 'hairline bg-bg-card text-fg-mute hover:text-fg'
                }`}
              >
                <span className="grid h-4 w-4 place-items-center rounded-sm text-[10px]">
                  {channelGlyph(c.channel)}
                </span>
                {channelLabel(c.channel)}
                <span className="rounded-full bg-bg-soft px-1.5 text-[10px] text-fg-mute">
                  {c.count}
                </span>
              </button>
            )
          })}
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="text-[12px] text-fg-mute">
          {showing === total
            ? `Showing all ${total} campaigns`
            : `Showing ${showing} of ${total} campaigns`}
        </div>
        <div className="flex items-center gap-3">
          <SortMenu sort={sort} onSort={onSort} />
          <ViewToggle view={view} onView={onView} />
        </div>
      </div>
    </motion.section>
  )
}

function SortMenu({
  sort,
  onSort,
}: {
  sort: SortKey
  onSort: (s: SortKey) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="hairline flex items-center gap-1.5 rounded-full bg-bg-card px-3 py-1 text-[11.5px] font-medium text-fg-mute hover:text-fg"
      >
        <span className="text-fg-dim">⇅</span>
        Sort: <span className="text-fg">{SORT_LABEL[sort]}</span>
        <span className="text-[8px] text-fg-dim">▾</span>
      </button>
      <AnimatePresence>
        {open && (
          <>
            <button
              type="button"
              aria-label="Close sort menu"
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-30 cursor-default"
            />
            <motion.ul
              initial={{ opacity: 0, y: 6, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 6, scale: 0.98 }}
              transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
              className="panel absolute right-0 top-full z-40 mt-2 w-44 overflow-hidden p-1"
            >
              {(Object.keys(SORT_LABEL) as SortKey[]).map((k) => (
                <li key={k}>
                  <button
                    onClick={() => {
                      onSort(k)
                      setOpen(false)
                    }}
                    className={`block w-full rounded-md px-2 py-1.5 text-left text-[12px] transition ${
                      k === sort
                        ? 'bg-accent-soft text-accent'
                        : 'text-fg hover:bg-bg-soft'
                    }`}
                  >
                    {SORT_LABEL[k]}
                  </button>
                </li>
              ))}
            </motion.ul>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

function ViewToggle({
  view,
  onView,
}: {
  view: 'grid' | 'list'
  onView: (v: 'grid' | 'list') => void
}) {
  return (
    <div className="hairline flex items-center rounded-full bg-bg-card p-0.5">
      {(['grid', 'list'] as const).map((v) => (
        <button
          key={v}
          onClick={() => onView(v)}
          className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition ${
            view === v
              ? 'bg-fg text-white'
              : 'text-fg-mute hover:text-fg'
          }`}
          aria-pressed={view === v}
        >
          <span>{v === 'grid' ? '◫' : '☰'}</span>
          {v === 'grid' ? 'Grid' : 'List'}
        </button>
      ))}
    </div>
  )
}

// ─── body ──────────────────────────────────────────────────────────────────

function CampaignsBody({
  state,
  view,
  onOpen,
  onRestore,
  onNew,
  onClearFilters,
  activeFilters,
}: {
  state: ReturnType<typeof useCampaignList>
  view: 'grid' | 'list'
  onOpen: (id: string) => void
  onRestore: (id: string) => void
  onNew: () => void
  onClearFilters: () => void
  activeFilters: boolean
}) {
  if (state.loading && state.items.length === 0) {
    return <SkeletonGrid view={view} />
  }
  if (state.error) {
    return (
      <div className="panel mt-8 flex flex-col items-center justify-center gap-3 px-8 py-16 text-center">
        <span className="grid h-10 w-10 place-items-center rounded-full bg-red-50 text-red-600">
          ⚠
        </span>
        <div>
          <div className="text-[14px] font-semibold">Couldn't load campaigns</div>
          <div className="mt-1 max-w-md text-[12.5px] text-fg-mute">{state.error}</div>
        </div>
        <button
          onClick={() => state.refresh()}
          className="hairline mt-2 rounded-full bg-bg-card px-4 py-1.5 text-[12px] font-medium text-fg hover:border-accent"
        >
          Retry
        </button>
      </div>
    )
  }
  if (state.items.length === 0) {
    return (
      <EmptyState
        kind={activeFilters ? 'filtered' : 'cold'}
        onClearFilters={onClearFilters}
        onNew={onNew}
      />
    )
  }
  if (view === 'list') {
    return (
      <motion.ul
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
        className="panel mt-6 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]"
      >
        <AnimatePresence mode="popLayout">
          {state.items.map((c) => (
            <ListRow
              key={c.id}
              campaign={c}
              onOpen={() => onOpen(c.id)}
              onRestore={() => onRestore(c.id)}
              onDuplicate={() => state.duplicate(c.id)}
              onDelete={() => state.remove(c.id)}
            />
          ))}
        </AnimatePresence>
      </motion.ul>
    )
  }
  return (
    <motion.section
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
    >
      <AnimatePresence mode="popLayout">
        {state.items.map((c) => (
          <CampaignCard
            key={c.id}
            campaign={c}
            onOpen={() => onOpen(c.id)}
            onRestore={() => onRestore(c.id)}
            onDuplicate={() => state.duplicate(c.id)}
            onDelete={() => state.remove(c.id)}
          />
        ))}
      </AnimatePresence>
    </motion.section>
  )
}

function SkeletonGrid({ view }: { view: 'grid' | 'list' }) {
  if (view === 'list') {
    return (
      <div className="panel mt-6 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4 px-5 py-4">
            <div className="h-10 w-10 animate-pulse rounded-lg bg-bg-soft" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-2/3 animate-pulse rounded-full bg-bg-soft" />
              <div className="h-2.5 w-1/3 animate-pulse rounded-full bg-bg-soft/70" />
            </div>
            <div className="h-5 w-16 animate-pulse rounded-full bg-bg-soft" />
          </div>
        ))}
      </div>
    )
  }
  return (
    <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="panel overflow-hidden">
          <div className="h-32 animate-pulse bg-bg-soft" />
          <div className="space-y-3 px-5 py-4">
            <div className="h-3.5 w-3/4 animate-pulse rounded-full bg-bg-soft" />
            <div className="h-2.5 w-1/2 animate-pulse rounded-full bg-bg-soft/70" />
            <div className="flex gap-2">
              <div className="h-5 w-14 animate-pulse rounded-full bg-bg-soft" />
              <div className="h-5 w-20 animate-pulse rounded-full bg-bg-soft" />
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

function EmptyState({
  kind,
  onClearFilters,
  onNew,
}: {
  kind: 'cold' | 'filtered'
  onClearFilters: () => void
  onNew: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="panel mt-6 flex flex-col items-center justify-center gap-4 px-8 py-20 text-center"
    >
      <span className="grid h-12 w-12 place-items-center rounded-2xl bg-accent-soft text-[20px] text-accent">
        ✦
      </span>
      <div>
        <div className="text-[16px] font-semibold">
          {kind === 'cold'
            ? "No campaigns yet — let's ship one"
            : 'No campaigns match those filters'}
        </div>
        <p className="mx-auto mt-2 max-w-sm text-[13px] text-fg-mute">
          {kind === 'cold'
            ? 'Head back to the dashboard, describe what to ship, and the agent will draft a multi-channel campaign in front of you.'
            : 'Try clearing a filter or widening the lift band.'}
        </p>
      </div>
      {kind === 'cold' ? (
        <button
          onClick={onNew}
          className="rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2.5 text-[13px] font-medium text-white shadow-[0_8px_22px_rgba(91,80,230,0.35)] hover:brightness-110"
        >
          Start a campaign
        </button>
      ) : (
        <button
          onClick={onClearFilters}
          className="hairline rounded-full bg-bg-card px-4 py-2 text-[12.5px] font-medium hover:border-accent"
        >
          Clear filters
        </button>
      )}
    </motion.div>
  )
}

// ─── card / row ────────────────────────────────────────────────────────────

function CampaignCard({
  campaign,
  onOpen,
  onRestore,
  onDuplicate,
  onDelete,
}: {
  campaign: CampaignListItem
  onOpen: () => void
  onRestore: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const ts = new Date(campaign.created_at).getTime()
  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
      className="panel group relative flex h-full cursor-pointer flex-col overflow-hidden transition hover:shadow-[0_12px_32px_rgba(20,20,40,0.08)]"
      onClick={onOpen}
    >
      <CardHero campaign={campaign} />
      <div className="flex flex-1 flex-col px-5 pb-5 pt-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-[14px] font-semibold leading-snug tracking-[-0.01em] text-fg">
            {campaign.title}
          </h3>
          <BandPill band={campaign.lift_band} lift={campaign.predicted_lift} />
        </div>
        {campaign.target_prompts.length > 0 && (
          <p className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-fg-mute">
            Target: {campaign.target_prompts[0]}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {campaign.channels.slice(0, 4).map((c) => (
            <ChannelPill key={c} channel={c} />
          ))}
          {campaign.channels.length > 4 && (
            <span className="hairline rounded-full bg-bg-card px-2 py-0.5 text-[10.5px] font-medium text-fg-mute">
              +{campaign.channels.length - 4}
            </span>
          )}
        </div>
        <div className="mt-auto flex items-center justify-between gap-2 pt-4">
          <div className="text-[11.5px] text-fg-mute">
            {relativeTime(ts)} · {campaign.draft_count} drafts
          </div>
          <RowMenu
            onOpen={onOpen}
            onRestore={onRestore}
            onDuplicate={onDuplicate}
            onDelete={onDelete}
          />
        </div>
      </div>
    </motion.article>
  )
}

function CardHero({ campaign }: { campaign: CampaignListItem }) {
  if (campaign.hero_image_url) {
    return (
      <div className="relative aspect-[16/9] w-full overflow-hidden bg-bg-soft">
        <img
          src={campaign.hero_image_url}
          alt=""
          className="h-full w-full object-cover transition group-hover:scale-[1.02]"
        />
        <div
          aria-hidden
          className="absolute inset-0 bg-gradient-to-t from-black/35 via-transparent to-transparent"
        />
      </div>
    )
  }
  // Procedural gradient hero from the campaign id so cards without a
  // hero image still feel distinct and on-brand.
  const hue = hashHue(campaign.id)
  return (
    <div
      className="relative aspect-[16/9] w-full overflow-hidden"
      style={{
        background: `linear-gradient(135deg, hsl(${hue} 70% 92%), hsl(${(hue + 40) % 360} 70% 80%))`,
      }}
    >
      <div className="absolute inset-0 grid place-items-center">
        <span
          className="text-[64px] font-bold leading-none tracking-[-0.04em]"
          style={{ color: `hsl(${hue} 60% 35% / 0.55)` }}
        >
          {(campaign.title || '?').slice(0, 1).toUpperCase()}
        </span>
      </div>
      <div className="absolute right-3 top-3 flex flex-wrap gap-1 justify-end">
        {campaign.channels.slice(0, 3).map((c) => (
          <span
            key={c}
            className="rounded-full bg-white/85 px-2 py-0.5 text-[10px] font-medium text-fg shadow-sm backdrop-blur-sm"
          >
            {channelGlyph(c)}
          </span>
        ))}
      </div>
    </div>
  )
}

function hashHue(s: string): number {
  let h = 0
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return h % 360
}

function ListRow({
  campaign,
  onOpen,
  onRestore,
  onDuplicate,
  onDelete,
}: {
  campaign: CampaignListItem
  onOpen: () => void
  onRestore: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const ts = new Date(campaign.created_at).getTime()
  return (
    <motion.li
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, x: -8 }}
      transition={{ duration: 0.22 }}
      className="group flex items-center gap-4 px-5 py-3.5 transition hover:bg-bg-soft/50"
    >
      <button
        type="button"
        onClick={onOpen}
        className="grid h-10 w-10 shrink-0 place-items-center overflow-hidden rounded-lg"
        aria-label={`Open ${campaign.title}`}
      >
        {campaign.hero_image_url ? (
          <img src={campaign.hero_image_url} alt="" className="h-full w-full object-cover" />
        ) : (
          <span
            className="grid h-full w-full place-items-center text-[13px] font-semibold"
            style={{
              background: `linear-gradient(135deg, hsl(${hashHue(campaign.id)} 70% 92%), hsl(${
                (hashHue(campaign.id) + 40) % 360
              } 70% 78%))`,
              color: `hsl(${hashHue(campaign.id)} 60% 30%)`,
            }}
          >
            {(campaign.title || '?').slice(0, 1).toUpperCase()}
          </span>
        )}
      </button>
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex-1 text-left"
      >
        <div className="truncate text-[13.5px] font-medium leading-tight text-fg">
          {campaign.title}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11.5px] text-fg-mute">
          <span>{relativeTime(ts)}</span>
          <span className="text-fg-dim">•</span>
          <span>{campaign.draft_count} drafts</span>
          {campaign.has_blog && (
            <>
              <span className="text-fg-dim">•</span>
              <span>Includes blog</span>
            </>
          )}
        </div>
      </button>
      <div className="hidden items-center gap-1.5 sm:flex">
        {campaign.channels.slice(0, 3).map((c) => (
          <ChannelPill key={c} channel={c} />
        ))}
        {campaign.channels.length > 3 && (
          <span className="hairline rounded-full bg-bg-card px-2 py-0.5 text-[10.5px] font-medium text-fg-mute">
            +{campaign.channels.length - 3}
          </span>
        )}
      </div>
      <BandPill band={campaign.lift_band} lift={campaign.predicted_lift} />
      <RowMenu
        onOpen={onOpen}
        onRestore={onRestore}
        onDuplicate={onDuplicate}
        onDelete={onDelete}
      />
    </motion.li>
  )
}

function BandPill({
  band,
  lift,
}: {
  band: LiftBand
  lift: number | null
}) {
  const t = BAND_THEME[band]
  const sign = lift != null && lift >= 0 ? '+' : ''
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ${t.bg} ${t.fg}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${t.dot}`} />
      {lift != null ? `${sign}${lift.toFixed(1)}%` : BAND_LABEL[band]}
    </span>
  )
}

function ChannelPill({ channel }: { channel: string }) {
  return (
    <span
      title={channelLabel(channel)}
      className="hairline inline-flex items-center gap-1 rounded-full bg-bg-card px-2 py-0.5 text-[10.5px] font-medium text-fg-mute"
    >
      <span className="text-fg-dim">{channelGlyph(channel)}</span>
      {channelLabel(channel)}
    </span>
  )
}

function RowMenu({
  onOpen,
  onRestore,
  onDuplicate,
  onDelete,
}: {
  onOpen: () => void
  onRestore: () => void
  onDuplicate: () => void
  onDelete: () => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className="relative"
      onClick={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="More"
        className="grid h-7 w-7 place-items-center rounded-md text-fg-dim transition hover:bg-bg-soft hover:text-fg"
      >
        ⋯
      </button>
      <AnimatePresence>
        {open && (
          <>
            <button
              type="button"
              aria-label="Close menu"
              onClick={() => setOpen(false)}
              className="fixed inset-0 z-30 cursor-default"
            />
            <motion.div
              initial={{ opacity: 0, y: 4, scale: 0.97 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 4, scale: 0.97 }}
              transition={{ duration: 0.14 }}
              className="panel absolute right-0 top-8 z-40 w-44 overflow-hidden p-1"
            >
              <MenuItem
                glyph="↗"
                label="Open detail"
                onClick={() => {
                  onOpen()
                  setOpen(false)
                }}
              />
              <MenuItem
                glyph="↺"
                label="Restore in dashboard"
                onClick={() => {
                  onRestore()
                  setOpen(false)
                }}
              />
              <MenuItem
                glyph="⎘"
                label="Duplicate"
                onClick={() => {
                  onDuplicate()
                  setOpen(false)
                }}
              />
              <div className="my-1 h-px bg-line-soft" />
              <MenuItem
                glyph="⌫"
                label="Delete"
                tone="danger"
                onClick={() => {
                  if (confirm('Delete this campaign? This cannot be undone.')) {
                    onDelete()
                  }
                  setOpen(false)
                }}
              />
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}

function MenuItem({
  glyph,
  label,
  onClick,
  tone,
}: {
  glyph: string
  label: string
  onClick: () => void
  tone?: 'danger'
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] transition ${
        tone === 'danger'
          ? 'text-red-600 hover:bg-red-50'
          : 'text-fg hover:bg-bg-soft'
      }`}
    >
      <span className="w-3 text-center text-fg-dim">{glyph}</span>
      {label}
    </button>
  )
}

// ─── data hooks ────────────────────────────────────────────────────────────

type ListState = {
  items: CampaignListItem[]
  total: number
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  remove: (id: string) => Promise<void>
  duplicate: (id: string) => Promise<void>
}

function useCampaignList(args: {
  brandId: string
  q: string
  band: LiftBand | 'all'
  channel: string | 'all'
  sort: SortKey
}): ListState {
  const { brandId, q, band, channel, sort } = args
  const [items, setItems] = useState<CampaignListItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        brand_id: brandId,
        sort,
        offset: '0',
        limit: '60',
      })
      if (q.trim()) params.set('q', q.trim())
      if (band !== 'all') params.set('band', band)
      if (channel !== 'all') params.set('channel', channel)
      const r = await fetch(`/api/campaigns/list?${params.toString()}`)
      if (!r.ok) throw new Error(`status ${r.status}`)
      const data = (await r.json()) as CampaignListResponse
      setItems(data.items)
      setTotal(data.total)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Network error')
    } finally {
      setLoading(false)
    }
  }, [brandId, q, band, channel, sort])

  // Debounce search so each keystroke doesn't fire a fresh request.
  useEffect(() => {
    const t = setTimeout(() => {
      void load()
    }, 180)
    return () => clearTimeout(t)
  }, [load])

  // Live updates: when a fresh campaign bundles or fails, re-pull so the
  // grid reflects new lift numbers and titles without a manual refresh.
  useEffect(() => {
    const onBundled = (p: { brand_id: string }) => {
      if (p.brand_id !== brandId) return
      void load()
    }
    bus.on('campaign.bundled', onBundled)
    return () => {
      bus.off('campaign.bundled', onBundled)
    }
  }, [brandId, load])

  const remove = useCallback(
    async (id: string) => {
      const prev = items
      setItems((xs) => xs.filter((x) => x.id !== id))
      setTotal((t) => Math.max(0, t - 1))
      try {
        const r = await fetch(`/api/campaigns/${encodeURIComponent(id)}`, {
          method: 'DELETE',
        })
        if (!r.ok) throw new Error(`status ${r.status}`)
      } catch (e) {
        // Roll back the optimistic deletion if the server rejects.
        setItems(prev)
        setTotal(prev.length)
        setError(e instanceof Error ? e.message : 'Delete failed')
      }
    },
    [items],
  )

  const duplicate = useCallback(
    async (id: string) => {
      try {
        const r = await fetch(
          `/api/campaigns/${encodeURIComponent(id)}/duplicate`,
          { method: 'POST' },
        )
        if (!r.ok) throw new Error(`status ${r.status}`)
        await load()
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Duplicate failed')
      }
    },
    [load],
  )

  return { items, total, loading, error, refresh: load, remove, duplicate }
}

function useCampaignStats(brandId: string): CampaignStats | null {
  const [stats, setStats] = useState<CampaignStats | null>(null)

  // Wrapped in an async IIFE so the only setState call lives on the awaited
  // microtask — keeps `react-hooks/set-state-in-effect` quiet without the
  // overhead of useCallback. Both the initial load and the bus-triggered
  // refetch route through the same fetcher.
  useEffect(() => {
    let cancelled = false
    async function fetchStats() {
      try {
        const r = await fetch(
          `/api/campaigns/stats?brand_id=${encodeURIComponent(brandId)}`,
        )
        if (cancelled || !r.ok) return
        const data = (await r.json()) as CampaignStats
        if (!cancelled) setStats(data)
      } catch {
        // soft-fail; stats hero will show em-dashes
      }
    }
    void fetchStats()
    const onBundled = (p: { brand_id: string }) => {
      if (p.brand_id !== brandId) return
      void fetchStats()
    }
    bus.on('campaign.bundled', onBundled)
    return () => {
      cancelled = true
      bus.off('campaign.bundled', onBundled)
    }
  }, [brandId])

  return stats
}
