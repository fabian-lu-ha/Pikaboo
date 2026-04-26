import { motion, AnimatePresence } from 'motion/react'
import { useResearchStore } from '../stores/researchStore'
import type { ResearchSource } from '../events/bus'

type Props = {
  scope: 'brand' | 'campaign'
  /** Optional title override; defaults match scope. */
  title?: string
  /** Cap the number of sources rendered. Default 8. */
  max?: number
}

const SCOPE_TITLES: Record<Props['scope'], string> = {
  brand: 'Brand research',
  campaign: 'Live web research',
}

const BUCKET_GLYPH: Record<string, string> = {
  company: '◯',
  news: '⊙',
  trend: '◊',
  topic: '◇',
  competitor: '⊕',
  campaign: '⊛',
}

export function ResearchCard({ scope, title, max = 8 }: Props) {
  const state = useResearchStore((s) => s[scope])
  if (state.status === 'idle') return null

  const heading = title ?? SCOPE_TITLES[scope]
  const sources = state.sources.slice(0, max)
  const fetching = state.status === 'fetching'
  const unavailable = state.status === 'unavailable'
  const failed = state.status === 'failed'

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
    >
      <header className="flex items-center justify-between border-b border-line-soft px-5 py-3">
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          <span
            className={
              fetching
                ? 'text-accent animate-pulse'
                : failed
                  ? 'text-danger'
                  : unavailable
                    ? 'text-fg-dim'
                    : 'text-success'
            }
          >
            {fetching ? '◐' : failed ? '✕' : unavailable ? '○' : '●'}
          </span>
          <span>{heading}</span>
          {fetching && <span className="text-fg-dim">· searching the web…</span>}
        </div>
        {state.fetchedAt && !fetching && (
          <time className="text-[10px] text-fg-dim">
            {timeAgo(state.fetchedAt)}
          </time>
        )}
      </header>

      {state.answer && (
        <p className="border-b border-line-soft px-5 py-3 text-[13px] leading-relaxed text-fg">
          {state.answer}
        </p>
      )}

      {(unavailable || failed) && sources.length === 0 && (
        <p className="px-5 py-4 text-[12px] text-fg-dim">
          {failed
            ? `Web research failed: ${state.error || 'unknown error'}`
            : state.error === 'no api key'
              ? 'Set TAVILY_API_KEY to enable live web research.'
              : 'No web sources found for this query.'}
        </p>
      )}

      <ul className="divide-y divide-line-soft">
        <AnimatePresence initial={false}>
          {sources.map((s) => (
            <SourceRow key={s.url} source={s} />
          ))}
        </AnimatePresence>
        {fetching && sources.length === 0 && (
          <li className="px-5 py-3 text-[11px] text-fg-dim">
            <span className="animate-pulse">scanning sources…</span>
          </li>
        )}
      </ul>
    </motion.section>
  )
}

function SourceRow({ source }: { source: ResearchSource }) {
  const host = hostOf(source.url)
  const glyph = BUCKET_GLYPH[source.bucket] ?? '◇'
  return (
    <motion.li
      initial={{ opacity: 0, x: -4 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25 }}
      className="px-5 py-3"
    >
      <a
        href={source.url}
        target="_blank"
        rel="noreferrer noopener"
        className="block group"
      >
        <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-fg-mute">
          <span className="text-accent">{glyph}</span>
          <span>{source.bucket}</span>
          <span className="text-fg-dim">· {host}</span>
          {source.published_date && (
            <span className="text-fg-dim">
              · {source.published_date.slice(0, 10)}
            </span>
          )}
        </div>
        <h4 className="mt-1 text-[13px] font-medium leading-snug text-fg group-hover:text-accent">
          {source.title || source.url}
        </h4>
        {source.snippet && (
          <p className="mt-1 line-clamp-2 text-[12px] leading-snug text-fg-dim">
            {source.snippet}
          </p>
        )}
      </a>
    </motion.li>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

function timeAgo(iso: string): string {
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const sec = Math.max(1, Math.floor((Date.now() - t) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`
  return `${Math.floor(sec / 86400)}d ago`
}
