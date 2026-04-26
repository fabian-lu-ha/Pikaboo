import { InitialsAvatar } from '../InitialsAvatar'
import { useAgentSessionStore } from '../../stores/agentSessionStore'
import { useWatchlistStore } from '../../stores/watchlistStore'
import type { Competitor } from './types'

// Real-data status. Priority:
//   1. Recent `competitor.surged` event (< 24h, |delta| > 1pp) — Surging/Slipping
//   2. Peec snapshot says competitor wins one or more of OUR target prompts
//   3. Peec snapshot cites the competitor's domain in the corpus
//   4. Peec data exists but no signal — Stable
//   5. No Peec data yet — Tracked (only placeholder state)
type Status = {
  label: string
  arrow: string
  color: string  // tailwind text color class
  live: boolean  // false only when there's no underlying data yet
}

const SURGE_TTL_MS = 24 * 60 * 60 * 1000

const norm = (s: string) => s.toLowerCase().trim()
// Match a competitor name against a domain like "stripe.com" / "www.linear.app"
const domainMatchesName = (domain: string, name: string): boolean => {
  const dn = domain.toLowerCase().replace(/^www\./, '')
  const stem = norm(name).split(/\s+/)[0]
  if (!stem) return false
  return dn.startsWith(stem + '.') || dn.includes('.' + stem + '.')
}

const fmtPct = (delta: number) => {
  const pct = Math.round(delta * 100)
  return `${pct > 0 ? '+' : ''}${pct}%`
}

export function useCompetitorStatus(name: string): Status {
  const peec = useAgentSessionStore((s) => s.peec)
  const surge = useWatchlistStore((s) => s.surges[norm(name)])

  if (surge && Date.now() - surge.at < SURGE_TTL_MS) {
    if (surge.delta > 0.01) {
      return {
        label: `Surging ${fmtPct(surge.delta)}`,
        arrow: '↗',
        color: 'text-success',
        live: true,
      }
    }
    if (surge.delta < -0.01) {
      return {
        label: `Slipping ${fmtPct(surge.delta)}`,
        arrow: '↘',
        color: 'text-danger',
        live: true,
      }
    }
  }

  if (peec) {
    const targetName = norm(name)
    const wins = peec.absent_from.filter(
      (p) => norm(p.competitor_winning ?? '') === targetName,
    ).length
    if (wins > 0) {
      return {
        label: `Winning ${wins} ${wins === 1 ? 'prompt' : 'prompts'}`,
        arrow: '↗',
        color: 'text-warn',
        live: true,
      }
    }

    const cited = peec.cited_domains.find((d) =>
      domainMatchesName(d.domain, name),
    )
    if (cited && (cited.citation_count ?? 0) > 0) {
      return {
        label: `Cited ${cited.citation_count}×`,
        arrow: '✦',
        color: 'text-accent',
        live: true,
      }
    }

    return {
      label: 'Stable',
      arrow: '→',
      color: 'text-fg-mute',
      live: true,
    }
  }

  return {
    label: 'Tracked',
    arrow: '·',
    color: 'text-fg-dim',
    live: false,
  }
}

export function CompetitorRow({
  competitor,
  onClick,
}: {
  competitor: Competitor
  onClick?: () => void
}) {
  const status = useCompetitorStatus(competitor.name)
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className="-mx-2 flex w-[calc(100%+1rem)] items-center gap-3 rounded-lg px-2 py-1.5 text-left transition hover:bg-bg-soft"
      >
        <InitialsAvatar name={competitor.name} size="md" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium leading-tight">
            {competitor.name}
          </div>
          <div
            className={`mt-0.5 flex items-center gap-1 text-[11px] ${status.color}`}
            title={status.live ? 'Live signal' : 'No Peec data yet'}
          >
            <span>{status.arrow}</span>
            <span className="truncate">{status.label}</span>
          </div>
        </div>
      </button>
    </li>
  )
}
