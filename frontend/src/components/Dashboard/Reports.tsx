import { useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { TopBar } from './TopBar'
import { InitialsAvatar } from '../InitialsAvatar'
import { firstWord, primaryName } from '../../lib/brandName'
import type { Brand, Competitor } from './types'

// Reports — weekly executive brief on visibility, share-of-voice, and the
// competitive surface. Until the analytics warehouse + Peec snapshots are
// wired through, the numbers are stable per-brand-and-week synthesizations
// (see hash-driven helpers at the bottom). The shape mirrors what real
// snapshots will deliver so the swap is one-for-one.

type WeekOffset = 0 | 1 | 2 | 3

const ENGINES = [
  { id: 'chatgpt', name: 'ChatGPT', glyph: '✦' },
  { id: 'claude', name: 'Claude', glyph: '◆' },
  { id: 'gemini', name: 'Gemini', glyph: '◇' },
  { id: 'perplexity', name: 'Perplexity', glyph: '◈' },
  { id: 'grok', name: 'Grok', glyph: '◉' },
] as const

const SOURCES = [
  { id: 'own', label: 'Own site / docs', tint: 'violet' as const },
  { id: 'news', label: 'News & press', tint: 'sky' as const },
  { id: 'reviews', label: 'Reviews & forums', tint: 'amber' as const },
  { id: 'partners', label: 'Partner mentions', tint: 'emerald' as const },
  { id: 'social', label: 'Social posts', tint: 'rose' as const },
] as const

const TINT: Record<
  'violet' | 'sky' | 'amber' | 'emerald' | 'rose',
  { bar: string; chip: string; chipFg: string }
> = {
  violet: { bar: 'var(--color-accent)', chip: '#eef0ff', chipFg: '#5b50e6' },
  sky: { bar: '#4f7cff', chip: '#e0e9ff', chipFg: '#3754c5' },
  amber: { bar: '#e09147', chip: '#fbe8d6', chipFg: '#a35d22' },
  emerald: { bar: '#1f9e6e', chip: '#dcf3e9', chipFg: '#197953' },
  rose: { bar: '#d75477', chip: '#fbe1e8', chipFg: '#a23252' },
}

export function Reports({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const [weekOffset, setWeekOffset] = useState<WeekOffset>(0)

  const week = useMemo(() => weekRange(weekOffset), [weekOffset])
  const kpis = useMemo(
    () => synthKpis(brand.id, weekOffset),
    [brand.id, weekOffset],
  )
  const engineRows = useMemo(
    () => synthEngines(brand.id, weekOffset),
    [brand.id, weekOffset],
  )
  const sources = useMemo(
    () => synthSources(brand.id, weekOffset),
    [brand.id, weekOffset],
  )
  const surges = useMemo(
    () => synthSurges(brand, weekOffset),
    [brand, weekOffset],
  )

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-10">
        <Header
          brand={brand}
          weekLabel={week.label}
          onPrev={() =>
            setWeekOffset((w) => (Math.min(3, w + 1) as WeekOffset))
          }
          onNext={() =>
            setWeekOffset((w) => (Math.max(0, w - 1) as WeekOffset))
          }
          canPrev={weekOffset < 3}
          canNext={weekOffset > 0}
        />

        <KpiStrip kpis={kpis} />

        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1.4fr_1fr]">
          <EngineBreakdown rows={engineRows} brand={brand} />
          <CitedSources sources={sources} />
        </div>

        <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[1.2fr_1fr]">
          <CompetitorSurges
            surges={surges}
            competitors={brand.competitors}
          />
          <StrategicSynthesis brand={brand} kpis={kpis} />
        </div>
      </div>
    </main>
  )
}

// ============================================================== Header

function Header({
  brand,
  weekLabel,
  onPrev,
  onNext,
  canPrev,
  canNext,
}: {
  brand: Brand
  weekLabel: string
  onPrev: () => void
  onNext: () => void
  canPrev: boolean
  canNext: boolean
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="flex flex-wrap items-end justify-between gap-4 pt-4"
    >
      <div>
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Weekly Brief
        </div>
        <h1 className="mt-2 text-[36px] font-semibold leading-[1.15] tracking-[-0.02em] text-fg">
          {primaryName(brand.name)} this week
        </h1>
        <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
          Visibility, share-of-voice, and the surges that mattered. Exportable
          to PDF; auto-emailed to your team every Monday.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <div className="hairline inline-flex items-center rounded-full bg-bg-card p-0.5">
          <button
            onClick={onPrev}
            disabled={!canPrev}
            className="grid h-7 w-7 place-items-center rounded-full text-fg-mute transition hover:bg-bg-soft hover:text-fg disabled:opacity-30 disabled:hover:bg-transparent"
            aria-label="Previous week"
          >
            ‹
          </button>
          <span className="px-3 text-[12px] font-medium tabular-nums text-fg">
            {weekLabel}
          </span>
          <button
            onClick={onNext}
            disabled={!canNext}
            className="grid h-7 w-7 place-items-center rounded-full text-fg-mute transition hover:bg-bg-soft hover:text-fg disabled:opacity-30 disabled:hover:bg-transparent"
            aria-label="Next week"
          >
            ›
          </button>
        </div>
        <button className="hairline rounded-full bg-bg-card px-4 py-2 text-[12px] text-fg-mute hover:text-fg">
          ↥ Export PDF
        </button>
        <button className="rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110">
          ↗ Share Brief
        </button>
      </div>
    </motion.section>
  )
}

// ============================================================ KPI strip

type Kpis = {
  visibility: { value: number; delta: number; series: number[] }
  sov: { value: number; delta: number; series: number[] }
  sentiment: { positive: number; neutral: number; negative: number }
}

function KpiStrip({ kpis }: { kpis: Kpis }) {
  return (
    <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-3">
      <KpiCard
        label="AI Visibility"
        value={`${kpis.visibility.value}`}
        unit="/100"
        delta={kpis.visibility.delta}
        series={kpis.visibility.series}
        accent
      />
      <KpiCard
        label="Share of Voice"
        value={`${kpis.sov.value}`}
        unit="%"
        delta={kpis.sov.delta}
        series={kpis.sov.series}
      />
      <SentimentCard breakdown={kpis.sentiment} />
    </div>
  )
}

function KpiCard({
  label,
  value,
  unit,
  delta,
  series,
  accent,
}: {
  label: string
  value: string
  unit: string
  delta: number
  series: number[]
  accent?: boolean
}) {
  const up = delta >= 0
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className={
        accent
          ? 'relative overflow-hidden rounded-2xl bg-gradient-to-br from-accent to-[var(--color-accent-deep)] p-6 text-white shadow-[0_10px_30px_rgba(91,80,230,0.25)]'
          : 'panel relative overflow-hidden p-6'
      }
    >
      {accent && (
        <div
          aria-hidden
          className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-white/10 blur-2xl"
        />
      )}
      <div
        className={`text-[11px] font-medium uppercase tracking-[0.18em] ${
          accent ? 'text-white/70' : 'text-fg-mute'
        }`}
      >
        {label}
      </div>
      <div className="mt-3 flex items-end gap-2">
        <span
          className={`font-semibold leading-none tracking-tight text-[44px] ${
            accent ? 'text-white' : 'text-fg'
          }`}
        >
          {value}
        </span>
        <span
          className={`mb-1.5 text-[13px] ${
            accent ? 'text-white/70' : 'text-fg-mute'
          }`}
        >
          {unit}
        </span>
        <span
          className={`mb-1.5 ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium ${
            up
              ? accent
                ? 'bg-emerald-300/30 text-emerald-100'
                : 'bg-emerald-50 text-emerald-700'
              : accent
                ? 'bg-rose-300/30 text-rose-100'
                : 'bg-rose-50 text-rose-700'
          }`}
        >
          {up ? '▲' : '▼'} {up ? '+' : ''}
          {delta.toFixed(1)}
        </span>
      </div>
      <Sparkline series={series} accent={accent} />
    </motion.div>
  )
}

function Sparkline({ series, accent }: { series: number[]; accent?: boolean }) {
  const w = 280
  const h = 36
  const max = Math.max(...series)
  const min = Math.min(...series)
  const span = Math.max(1, max - min)
  const step = w / Math.max(1, series.length - 1)
  const points = series
    .map((v, i) => {
      const x = i * step
      const y = h - ((v - min) / span) * h
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const stroke = accent ? 'rgba(255,255,255,0.9)' : 'var(--color-accent)'
  const fill = accent ? 'rgba(255,255,255,0.18)' : 'rgba(91,80,230,0.12)'
  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      className="mt-4 h-10 w-full"
    >
      <polygon
        points={`0,${h} ${points} ${w},${h}`}
        fill={fill}
        stroke="none"
      />
      <polyline
        points={points}
        fill="none"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

function SentimentCard({
  breakdown,
}: {
  breakdown: { positive: number; neutral: number; negative: number }
}) {
  const total =
    breakdown.positive + breakdown.neutral + breakdown.negative || 1
  const pos = (breakdown.positive / total) * 100
  const neu = (breakdown.neutral / total) * 100
  const neg = (breakdown.negative / total) * 100
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1 }}
      className="panel p-6"
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Sentiment Mix
      </div>
      <div className="mt-3 flex items-end gap-2">
        <span className="font-semibold leading-none tracking-tight text-[44px] text-fg">
          {Math.round(pos)}
        </span>
        <span className="mb-1.5 text-[13px] text-fg-mute">% positive</span>
      </div>
      <div className="mt-4 flex h-2 w-full overflow-hidden rounded-full bg-bg-soft">
        <div className="h-full bg-emerald-500" style={{ width: `${pos}%` }} />
        <div className="h-full bg-fg-dim/40" style={{ width: `${neu}%` }} />
        <div className="h-full bg-rose-500" style={{ width: `${neg}%` }} />
      </div>
      <div className="mt-3 flex items-center gap-4 text-[11px] text-fg-mute">
        <Legend dot="bg-emerald-500" label="Positive" value={`${Math.round(pos)}%`} />
        <Legend dot="bg-fg-dim/40" label="Neutral" value={`${Math.round(neu)}%`} />
        <Legend dot="bg-rose-500" label="Negative" value={`${Math.round(neg)}%`} />
      </div>
    </motion.div>
  )
}

function Legend({ dot, label, value }: { dot: string; label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {label}
      <span className="tabular-nums text-fg">{value}</span>
    </span>
  )
}

// ====================================================== Engine breakdown

type EngineRow = {
  id: string
  name: string
  glyph: string
  current: number
  prior: number
  series: number[]
}

function EngineBreakdown({ rows, brand }: { rows: EngineRow[]; brand: Brand }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.12 }}
      className="panel p-6"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-semibold">Visibility by AI Engine</div>
          <p className="mt-1 text-[12px] text-fg-mute">
            How {firstWord(brand.name)} is showing up across the engines you
            track, week-over-week.
          </p>
        </div>
        <button className="text-[11px] font-medium text-accent hover:underline">
          Drill in →
        </button>
      </div>
      <div className="mt-5">
        <div className="grid grid-cols-[1.4fr_repeat(3,minmax(0,1fr))_60px] items-center gap-3 px-1 text-[10px] font-medium uppercase tracking-[0.16em] text-fg-dim">
          <span>Engine</span>
          <span className="text-right">This week</span>
          <span className="text-right">Last week</span>
          <span className="text-right">Δ</span>
          <span className="text-right">Trend</span>
        </div>
        <ul className="mt-2 flex flex-col divide-y divide-[rgba(20,20,40,0.04)]">
          {rows.map((r) => (
            <EngineRowView key={r.id} row={r} />
          ))}
        </ul>
      </div>
    </motion.section>
  )
}

function EngineRowView({ row }: { row: EngineRow }) {
  const delta = row.current - row.prior
  const up = delta >= 0
  return (
    <li className="grid grid-cols-[1.4fr_repeat(3,minmax(0,1fr))_60px] items-center gap-3 px-1 py-3">
      <div className="flex items-center gap-3">
        <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent-soft text-[13px] text-accent">
          {row.glyph}
        </span>
        <span className="text-[13px] font-medium leading-tight">{row.name}</span>
      </div>
      <span className="text-right text-[13px] font-semibold tabular-nums text-fg">
        {row.current}
      </span>
      <span className="text-right text-[13px] tabular-nums text-fg-mute">
        {row.prior}
      </span>
      <span
        className={`text-right text-[12px] font-medium tabular-nums ${
          up ? 'text-emerald-600' : 'text-rose-600'
        }`}
      >
        {up ? '+' : ''}
        {delta.toFixed(1)}
      </span>
      <div className="ml-auto w-[60px]">
        <Sparkline series={row.series} />
      </div>
    </li>
  )
}

// ========================================================= Cited sources

type SourceRow = {
  id: string
  label: string
  tint: keyof typeof TINT
  share: number
  delta: number
}

function CitedSources({ sources }: { sources: SourceRow[] }) {
  const max = Math.max(...sources.map((s) => s.share), 1)
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.16 }}
      className="panel p-6"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-semibold">Cited Sources</div>
          <p className="mt-1 text-[12px] text-fg-mute">
            Where the engines are pulling their answers from.
          </p>
        </div>
      </div>
      <ul className="mt-5 flex flex-col gap-3.5">
        {sources.map((s) => {
          const t = TINT[s.tint]
          const pct = (s.share / max) * 100
          const up = s.delta >= 0
          return (
            <li key={s.id}>
              <div className="flex items-center justify-between text-[12px]">
                <span className="flex items-center gap-2">
                  <span
                    className="grid h-5 px-2 place-items-center rounded-full text-[10px] font-medium uppercase tracking-[0.12em]"
                    style={{ background: t.chip, color: t.chipFg }}
                  >
                    {s.label}
                  </span>
                </span>
                <span className="flex items-center gap-3">
                  <span className="tabular-nums text-fg">
                    {s.share.toFixed(0)}%
                  </span>
                  <span
                    className={`tabular-nums text-[11px] ${
                      up ? 'text-emerald-600' : 'text-rose-600'
                    }`}
                  >
                    {up ? '+' : ''}
                    {s.delta.toFixed(1)}
                  </span>
                </span>
              </div>
              <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-bg-soft">
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
                  className="h-full rounded-full"
                  style={{ background: t.bar }}
                />
              </div>
            </li>
          )
        })}
      </ul>
    </motion.section>
  )
}

// ====================================================== Competitor surges

type Surge = {
  id: string
  competitorName: string
  prompt: string
  delta: number
  whenLabel: string
}

function CompetitorSurges({
  surges,
  competitors,
}: {
  surges: Surge[]
  competitors: Competitor[]
}) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.2 }}
      className="panel p-6"
    >
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[13px] font-semibold">Competitor Surge Timeline</div>
          <p className="mt-1 text-[12px] text-fg-mute">
            Notable visibility spikes from tracked competitors this week.
          </p>
        </div>
      </div>
      {competitors.length === 0 ? (
        <div className="mt-5 rounded-xl border border-dashed border-line py-8 text-center text-[12px] text-fg-mute">
          No competitors tracked yet — add some from the Watchlist to populate
          this timeline.
        </div>
      ) : (
        <ol className="relative mt-5 flex flex-col gap-4 pl-5">
          <span
            aria-hidden
            className="absolute bottom-1 left-[8px] top-1 w-px bg-line"
          />
          {surges.map((s, i) => (
            <li key={s.id} className="relative">
              <span
                aria-hidden
                className="absolute -left-[18px] top-1.5 grid h-3 w-3 place-items-center rounded-full bg-bg-card shadow-[0_0_0_2px_var(--color-accent)]"
              >
                <span className="h-1.5 w-1.5 rounded-full bg-accent" />
              </span>
              <motion.div
                initial={{ opacity: 0, x: 4 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.3, delay: 0.04 * i }}
                className="flex items-start gap-3"
              >
                <InitialsAvatar name={s.competitorName} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[12.5px] font-medium leading-tight">
                      {s.competitorName}
                    </span>
                    <span className="rounded-full bg-rose-50 px-2 py-0.5 text-[10px] font-medium tabular-nums text-rose-700">
                      +{s.delta.toFixed(1)}%
                    </span>
                    <span className="ml-auto shrink-0 text-[11px] text-fg-dim">
                      {s.whenLabel}
                    </span>
                  </div>
                  <div className="mt-0.5 truncate text-[12px] text-fg-mute">
                    on prompt “{s.prompt}”
                  </div>
                </div>
              </motion.div>
            </li>
          ))}
        </ol>
      )}
    </motion.section>
  )
}

// ===================================================== Strategic synthesis

function StrategicSynthesis({
  brand,
  kpis,
}: {
  brand: Brand
  kpis: Kpis
}) {
  const top = brand.competitors[0]?.name
  const visibilityUp = kpis.visibility.delta >= 0
  return (
    <motion.aside
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.24 }}
      className="rounded-2xl border border-accent/20 bg-accent-soft/60 p-6"
    >
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
        <span className="grid h-5 w-5 place-items-center rounded-full bg-accent text-[10px] text-white">
          ✦
        </span>
        Strategic Synthesis
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-fg">
        {visibilityUp
          ? `${firstWord(brand.name)} climbed ${kpis.visibility.delta.toFixed(1)} points in AI visibility this week`
          : `${firstWord(brand.name)} dipped ${Math.abs(kpis.visibility.delta).toFixed(1)} points in AI visibility this week`}
        {top ? (
          <>
            , while <strong>{top}</strong> made meaningful gains on category
            queries.
          </>
        ) : (
          <>. Bring in 3-5 tracked competitors to make this brief actionable.</>
        )}{' '}
        Below are the moves the agent recommends running next.
      </p>
      <div className="mt-5 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        This week's recommendations
      </div>
      <ul className="mt-3 flex flex-col gap-2">
        {[
          'Publish a comparison post on the prompts where SOV slipped',
          'Re-cite three customer wins on the public site this week',
          'Brief the campaign agent to seed two LinkedIn posts before Friday',
        ].map((b) => (
          <li
            key={b}
            className="flex items-start gap-2.5 text-[12.5px] text-fg"
          >
            <span className="mt-[3px] grid h-3.5 w-3.5 shrink-0 place-items-center rounded-full bg-accent text-[8px] text-white">
              ◆
            </span>
            <span>{b}</span>
          </li>
        ))}
      </ul>
      <button className="mt-5 w-full rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] py-2.5 text-[13px] font-medium text-white shadow-[0_6px_18px_rgba(91,80,230,0.35)] transition hover:brightness-110">
        Queue all recommendations
      </button>
    </motion.aside>
  )
}

// ============================================================== synth data
// Stable per-brand-and-week pseudo-random helpers. The keys include the week
// offset so flipping back/forward through weeks produces consistent numbers
// per week instead of jittering. Replace with real Peec snapshot reads when
// the warehouse lands.

function hash(s: string): number {
  let h = 0
  for (const c of s) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return h
}

function rand(seed: number, mod: number): number {
  return seed % mod
}

function weekRange(offset: number): { label: string } {
  const now = new Date()
  // Snap to ISO week: most recent Monday.
  const day = now.getUTCDay() || 7 // Mon=1..Sun=7
  const monday = new Date(now)
  monday.setUTCDate(now.getUTCDate() - (day - 1) - offset * 7)
  const sunday = new Date(monday)
  sunday.setUTCDate(monday.getUTCDate() + 6)
  const fmt = (d: Date) =>
    d.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      timeZone: 'UTC',
    })
  return { label: `${fmt(monday)} – ${fmt(sunday)}` }
}

function synthKpis(brandId: string, offset: number): Kpis {
  const h = hash(`${brandId}:vis:${offset}`)
  const visBase = 60 + rand(h, 30)
  const visDelta = (rand(h >>> 4, 90) - 30) / 10 // -3.0 to +6.0
  const visSeries = makeSeries(h, 7, 50, 95)

  const sovHash = hash(`${brandId}:sov:${offset}`)
  const sovBase = 14 + rand(sovHash, 22)
  const sovDelta = (rand(sovHash >>> 4, 70) - 25) / 10
  const sovSeries = makeSeries(sovHash, 7, 8, 38)

  const sentHash = hash(`${brandId}:sent:${offset}`)
  const positive = 50 + rand(sentHash, 30)
  const negative = 6 + rand(sentHash >>> 4, 14)
  const neutral = Math.max(0, 100 - positive - negative)

  return {
    visibility: { value: visBase, delta: visDelta, series: visSeries },
    sov: { value: sovBase, delta: sovDelta, series: sovSeries },
    sentiment: { positive, neutral, negative },
  }
}

function synthEngines(brandId: string, offset: number): EngineRow[] {
  return ENGINES.map((e, i) => {
    const h = hash(`${brandId}:engine:${e.id}:${offset}`)
    const current = 40 + rand(h, 50)
    const prior = current - ((rand(h >>> 4, 120) - 50) / 10)
    const series = makeSeries(h ^ (i * 7919), 8, 30, 95)
    return {
      id: e.id,
      name: e.name,
      glyph: e.glyph,
      current,
      prior: Math.round(prior),
      series,
    }
  })
}

function synthSources(brandId: string, offset: number): SourceRow[] {
  return SOURCES.map((s) => {
    const h = hash(`${brandId}:src:${s.id}:${offset}`)
    return {
      id: s.id,
      label: s.label,
      tint: s.tint,
      share: 8 + rand(h, 36),
      delta: (rand(h >>> 4, 80) - 30) / 10,
    }
  })
}

function synthSurges(brand: Brand, offset: number): Surge[] {
  const prompts = [
    'best AI marketing tools',
    'alternatives to legacy CRM',
    'fastest video ad generator',
    'enterprise-grade analytics',
    'open-source data warehouse',
  ]
  const weekday = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
  const list = brand.competitors.length > 0 ? brand.competitors : []
  return list.slice(0, 5).map((c) => {
    const h = hash(`${brand.id}:surge:${c.id}:${offset}`)
    const promptIdx = rand(h, prompts.length)
    const dayIdx = rand(h >>> 5, weekday.length)
    return {
      id: `${c.id}-surge`,
      competitorName: c.name,
      prompt: prompts[promptIdx],
      delta: 4 + rand(h >>> 7, 18),
      whenLabel: `${weekday[dayIdx]} · ${9 + (rand(h >>> 9, 8))}:00`,
    }
  })
}

function makeSeries(
  seed: number,
  len: number,
  lo: number,
  hi: number,
): number[] {
  const out: number[] = []
  let v = lo + ((seed >>> 0) % Math.max(1, hi - lo))
  for (let i = 0; i < len; i++) {
    const drift = ((seed >>> (i % 24)) % 14) - 7
    v = Math.max(lo, Math.min(hi, v + drift))
    out.push(v)
  }
  return out
}
