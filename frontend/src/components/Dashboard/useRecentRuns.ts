import { useEffect, useState } from 'react'
import { bus } from '../../events/bus'
import type { Brand, RunEntry, RunTint } from './types'

type ApiRun = {
  id: string
  brand_id: string
  title: string
  predicted_lift: number | null
  created_at: string
}

const TINTS: RunTint[] = ['violet', 'emerald', 'amber']

function tintFor(id: string): RunTint {
  // Stable tint per campaign id so colors don't shuffle on re-render.
  let h = 0
  for (const c of id) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return TINTS[h % TINTS.length]
}

function subFor(run: { predicted_lift: number | null; status?: string }): string {
  if (run.status === 'running') return 'running…'
  if (run.status === 'failed') return 'failed'
  if (run.predicted_lift != null) {
    const sign = run.predicted_lift >= 0 ? '+' : ''
    return `Predicted lift: ${sign}${run.predicted_lift.toFixed(1)}%`
  }
  return 'Bundled'
}

// Subscribe to live agent events and reflect the most recent campaign runs
// for the active brand. On mount, hydrate from the backend so we show all
// past runs — not just ones from this browser session.
export function useRecentRuns(brand: Brand): RunEntry[] {
  const [entries, setEntries] = useState<RunEntry[]>([])

  useEffect(() => {
    let cancelled = false
    fetch(`/api/campaigns/recent?brand_id=${encodeURIComponent(brand.id)}&limit=10`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.statusText)))
      .then((rows: ApiRun[]) => {
        if (cancelled) return
        setEntries(
          rows.map((r) => ({
            id: r.id,
            tint: tintFor(r.id),
            title: r.title || 'Campaign',
            sub: subFor({ predicted_lift: r.predicted_lift }),
            ts: new Date(r.created_at).getTime(),
          })),
        )
      })
      .catch(() => {
        // Backend unreachable — leave empty so the empty state shows
        // instead of stale fake data.
      })
    return () => {
      cancelled = true
    }
  }, [brand.id])

  useEffect(() => {
    const onStarted = (p: {
      campaign_id: string
      brand_id: string
      user_request: string
    }) => {
      if (p.brand_id !== brand.id) return
      setEntries((prev) =>
        [
          {
            id: p.campaign_id,
            tint: tintFor(p.campaign_id),
            title: p.user_request || 'Campaign',
            sub: 'running…',
            ts: Date.now(),
          },
          ...prev.filter((e) => e.id !== p.campaign_id),
        ].slice(0, 10),
      )
    }
    const onBundled = (p: {
      campaign_id: string
      brand_id: string
      title: string
      bundle: { predicted_lift?: { lift_percent?: number } }
    }) => {
      if (p.brand_id !== brand.id) return
      const lift = p.bundle?.predicted_lift?.lift_percent ?? null
      setEntries((prev) =>
        prev.map((e) =>
          e.id === p.campaign_id
            ? {
                ...e,
                title: p.title || e.title,
                sub: subFor({ predicted_lift: lift }),
              }
            : e,
        ),
      )
    }
    const onFailed = (p: { campaign_id?: string }) => {
      if (!p.campaign_id) return
      setEntries((prev) =>
        prev.map((e) =>
          e.id === p.campaign_id
            ? { ...e, sub: subFor({ predicted_lift: null, status: 'failed' }) }
            : e,
        ),
      )
    }

    bus.on('agent.started', onStarted)
    bus.on('campaign.bundled', onBundled)
    bus.on('agent.failed', onFailed)
    return () => {
      bus.off('agent.started', onStarted)
      bus.off('campaign.bundled', onBundled)
      bus.off('agent.failed', onFailed)
    }
  }, [brand.id])

  return entries
}
