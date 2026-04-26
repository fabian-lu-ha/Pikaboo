import { useEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'motion/react'
import { InitialsAvatar } from '../InitialsAvatar'
import { useAgentSessionStore } from '../../stores/agentSessionStore'
import { useWatchlistStore } from '../../stores/watchlistStore'
import { useCompetitorIntelStore } from '../../stores/competitorIntelStore'
import { bus, type ResearchSource } from '../../events/bus'
import { useCompetitorStatus } from './CompetitorRow'
import type { Competitor } from './types'

const norm = (s: string) => s.toLowerCase().trim()

const domainMatchesName = (domain: string, name: string): boolean => {
  const dn = domain.toLowerCase().replace(/^www\./, '')
  const stem = norm(name).split(/\s+/)[0]
  if (!stem) return false
  return dn.startsWith(stem + '.') || dn.includes('.' + stem + '.')
}

function timeAgo(ms: number): string {
  const diff = Date.now() - ms
  if (diff < 60_000) return 'just now'
  const m = Math.floor(diff / 60_000)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

export function CompetitorInsightModal({
  competitor,
  onClose,
}: {
  competitor: Competitor
  onClose: () => void
}) {
  const status = useCompetitorStatus(competitor.name)
  const peec = useAgentSessionStore((s) => s.peec)
  const surge = useWatchlistStore((s) => s.surges[norm(competitor.name)])
  const intel = useCompetitorIntelStore((s) => s.byId[competitor.id])

  // Esc closes
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  // On open: hydrate cached intel + auto-refresh if stale or empty. Cached
  // bundles are persisted on Competitor.pattern_library['intel'] so a
  // re-open shows last result instantly while a fresh pull runs.
  useEffect(() => {
    let cancelled = false
    fetch(`/api/competitors/${competitor.id}/intel`)
      .then((r) => (r.ok ? r.json() : null))
      .then(
        (
          d:
            | { intel: Record<string, unknown>; is_stale: boolean }
            | null,
        ) => {
          if (cancelled || !d) return
          const cached = d.intel || {}
          const hasContent =
            Array.isArray(cached.sources) && cached.sources.length > 0
          if (hasContent) {
            useCompetitorIntelStore.getState().hydrate(competitor.id, {
              sources: cached.sources as ResearchSource[],
              answer: (cached.answer as string | null) ?? null,
              fetched_at: (cached.fetched_at as string | null) ?? null,
              error: (cached.error as string | null) ?? null,
            })
          }
          // Always refresh on open if stale OR empty — cheap, gives the
          // user the freshest possible read.
          if (d.is_stale || !hasContent) {
            void fetch(`/api/competitors/${competitor.id}/intel`, {
              method: 'POST',
            })
          }
        },
      )
      .catch(() => {/* non-fatal */})
    return () => {
      cancelled = true
    }
  }, [competitor.id])

  const winningPrompts = useMemo(() => {
    if (!peec) return []
    const target = norm(competitor.name)
    return peec.absent_from.filter(
      (p) => norm(p.competitor_winning ?? '') === target,
    )
  }, [peec, competitor.name])

  const citation = useMemo(() => {
    if (!peec) return null
    return (
      peec.cited_domains.find((d) =>
        domainMatchesName(d.domain, competitor.name),
      ) ?? null
    )
  }, [peec, competitor.name])

  function handleCounterCampaign() {
    bus.emit('chat.submitted', {
      text: `Counter ${competitor.name} — propose a campaign that takes back ground we're losing to them.`,
    })
    onClose()
  }

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="flex max-h-[90vh] w-full max-w-md flex-col overflow-hidden rounded-2xl border border-line bg-bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex shrink-0 items-start gap-3 px-6 pt-6">
          {competitor.logo_url ? (
            <div className="grid h-10 w-10 shrink-0 place-items-center">
              <img
                src={competitor.logo_url}
                alt=""
                className="max-h-full max-w-full object-contain"
              />
            </div>
          ) : (
            <InitialsAvatar name={competitor.name} size="md" />
          )}
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-semibold leading-tight">
              {competitor.name}
            </div>
            {competitor.url && (
              <a
                href={competitor.url.startsWith('http') ? competitor.url : `https://${competitor.url}`}
                target="_blank"
                rel="noopener noreferrer"
                className="block truncate text-[11px] text-fg-mute hover:text-accent"
              >
                {competitor.url.replace(/^https?:\/\//, '')}
              </a>
            )}
            <div
              className={`mt-1.5 inline-flex items-center gap-1 text-[11px] ${status.color}`}
            >
              <span>{status.arrow}</span>
              <span>{status.label}</span>
              {!status.live && (
                <span className="ml-1 text-fg-dim">· no live data yet</span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="grid h-7 w-7 place-items-center rounded-md text-fg-mute hover:bg-bg-soft hover:text-fg"
          >
            ✕
          </button>
        </header>

        <div className="mt-5 flex flex-1 flex-col gap-4 overflow-y-auto overscroll-contain px-6 pb-5 [scrollbar-width:thin]">
          {competitor.reason && (
            <Section label="Why we track them">
              <p className="text-[13px] leading-relaxed text-fg">
                {competitor.reason}
              </p>
            </Section>
          )}

          <IntelSection
            competitor={competitor}
            intel={intel}
          />

          {surge && (
            <Section label="Latest surge">
              <div className="rounded-xl border border-line bg-bg-soft/40 p-3 text-[12.5px]">
                <div
                  className={
                    surge.delta >= 0 ? 'font-medium text-success' : 'font-medium text-danger'
                  }
                >
                  {surge.delta >= 0 ? '↗' : '↘'}{' '}
                  {Math.round(Math.abs(surge.delta) * 100)}pp on{' '}
                  <span className="text-fg">"{surge.prompt}"</span>
                </div>
                <div className="mt-1 text-[11px] text-fg-mute">
                  {timeAgo(surge.at)}
                </div>
              </div>
            </Section>
          )}

          {winningPrompts.length > 0 && (
            <Section
              label={`Winning ${winningPrompts.length} ${winningPrompts.length === 1 ? 'prompt' : 'prompts'} vs. us`}
            >
              <ul className="flex flex-col gap-1.5">
                {winningPrompts.slice(0, 5).map((p, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-[12.5px] leading-snug"
                  >
                    <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-warn" />
                    <span className="min-w-0 flex-1 truncate text-fg">
                      {p.prompt}
                    </span>
                    {p.competitor_visibility != null && (
                      <span className="shrink-0 text-[11px] tabular-nums text-fg-mute">
                        {Math.round(p.competitor_visibility * 100)}%
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Section>
          )}

          {citation && (citation.citation_count ?? 0) > 0 && (
            <Section label="Citation footprint">
              <div className="text-[12.5px] text-fg">
                Cited{' '}
                <span className="font-semibold tabular-nums">
                  {citation.citation_count}×
                </span>{' '}
                in the Peec corpus
                <span className="text-fg-mute"> ({citation.domain})</span>
              </div>
            </Section>
          )}

          {!peec && !surge && !competitor.reason && (
            <div className="rounded-xl border border-dashed border-line bg-bg-soft/40 px-4 py-5 text-center text-[12.5px] text-fg-mute">
              No live insights yet. Insights light up after the first agent
              run pulls a Peec snapshot.
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-line px-6 py-3">
          <button
            onClick={handleCounterCampaign}
            className="w-full rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] py-2.5 text-[13px] font-medium text-white shadow-[0_6px_18px_rgba(91,80,230,0.35)] hover:brightness-110"
          >
            Counter {competitor.name} →
          </button>
        </div>
      </motion.div>
    </motion.div>,
    document.body,
  )
}

function Section({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        {label}
      </div>
      <div className="mt-1.5">{children}</div>
    </div>
  )
}

const BUCKET_LABEL: Record<string, string> = {
  launches: 'Recent launches',
  moves: 'GTM / business moves',
  footprint: 'Positioning',
}

function IntelSection({
  competitor,
  intel,
}: {
  competitor: Competitor
  intel:
    | {
        status: 'idle' | 'fetching' | 'ready' | 'unavailable' | 'failed'
        sources: ResearchSource[]
        answer: string | null
        fetchedAt: string | null
        error: string | null
      }
    | undefined
}) {
  const status = intel?.status ?? 'fetching'
  const sources = intel?.sources ?? []
  const answer = intel?.answer ?? null

  // Group sources by bucket so the modal naturally splits "what they
  // launched" from "what they're doing in general".
  const grouped = useMemo(() => {
    const m = new Map<string, ResearchSource[]>()
    for (const s of sources) {
      const list = m.get(s.bucket) ?? []
      list.push(s)
      m.set(s.bucket, list)
    }
    return m
  }, [sources])

  if (status === 'idle' && sources.length === 0) return null

  return (
    <Section label="Live web intel">
      {answer && (
        <p className="mb-2 rounded-lg border border-line bg-bg-soft/40 px-3 py-2 text-[12.5px] leading-relaxed text-fg">
          {answer}
        </p>
      )}

      {status === 'fetching' && sources.length === 0 && (
        <p className="text-[12px] text-fg-mute">
          <span className="animate-pulse">scanning the web for what {competitor.name} is doing…</span>
        </p>
      )}

      {status === 'unavailable' && sources.length === 0 && (
        <p className="text-[12px] text-fg-mute">
          {intel?.error === 'no api key'
            ? 'Set TAVILY_API_KEY to enable competitor intel.'
            : 'No recent web coverage found.'}
        </p>
      )}

      {status === 'failed' && sources.length === 0 && (
        <p className="text-[12px] text-danger">
          Intel pull failed: {intel?.error ?? 'unknown error'}
        </p>
      )}

      <div className="flex flex-col gap-3">
        <AnimatePresence initial={false}>
          {[...grouped.entries()].map(([bucket, list]) => (
            <motion.div
              key={bucket}
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
            >
              <div className="text-[10px] font-medium uppercase tracking-[0.16em] text-accent">
                {BUCKET_LABEL[bucket] ?? bucket}
              </div>
              <ul className="mt-1 flex flex-col gap-1.5">
                {list.slice(0, 4).map((s) => (
                  <IntelSourceRow key={s.url} source={s} />
                ))}
              </ul>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>

      {intel?.fetchedAt && (
        <p className="mt-2 text-[10px] text-fg-dim">
          fetched {timeAgoIso(intel.fetchedAt)}
          {status === 'fetching' && ' · refreshing…'}
        </p>
      )}
    </Section>
  )
}

function IntelSourceRow({ source }: { source: ResearchSource }) {
  const host = (() => {
    try {
      return new URL(source.url).hostname.replace(/^www\./, '')
    } catch {
      return source.url
    }
  })()
  return (
    <li className="rounded-md border border-line bg-bg-card px-3 py-2 transition hover:border-accent">
      <a
        href={source.url}
        target="_blank"
        rel="noopener noreferrer"
        className="block"
      >
        <div className="flex items-baseline justify-between gap-3 text-[10px] uppercase tracking-[0.14em] text-fg-mute">
          <span>{host}</span>
          {source.published_date && (
            <span>{source.published_date.slice(0, 10)}</span>
          )}
        </div>
        <h5 className="mt-0.5 line-clamp-2 text-[12.5px] font-medium leading-snug text-fg group-hover:text-accent">
          {source.title || source.url}
        </h5>
        {source.snippet && (
          <p className="mt-1 line-clamp-2 text-[11.5px] leading-snug text-fg-dim">
            {source.snippet}
          </p>
        )}
      </a>
    </li>
  )
}

function timeAgoIso(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const sec = Math.max(1, Math.floor((Date.now() - t) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}
