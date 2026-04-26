import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { useNav } from './navContext'
import type { Brand } from './types'

type SeriesPoint = { date: string; value: number }

type RecentMedia = {
  id: string
  caption: string | null
  media_type: string
  media_url: string | null
  permalink: string
  thumbnail_url: string | null
  timestamp: string
  like_count: number | null
  comments_count: number | null
}

type Insights = {
  account: {
    id: string
    username: string
    name: string | null
    biography: string | null
    profile_picture_url: string | null
    followers_count: number | null
    follows_count: number | null
    media_count: number | null
    website: string | null
  }
  series: Record<string, SeriesPoint[]>
  recent_media: RecentMedia[]
  fetched_at: string
}

type Status = {
  connected: boolean
  username?: string | null
}

type LoadState =
  | { kind: 'loading' }
  | { kind: 'disconnected' }
  | { kind: 'error'; message: string }
  | { kind: 'ok'; data: Insights }

export function InstagramInsights({ brand }: { brand: Brand }) {
  const [state, setState] = useState<LoadState>({ kind: 'loading' })

  useEffect(() => {
    let cancelled = false
    async function load() {
      setState({ kind: 'loading' })
      try {
        const sr = await fetch(
          `/api/integrations/instagram/status?brand_id=${encodeURIComponent(brand.id)}`,
        )
        if (cancelled) return
        const status: Status = sr.ok ? await sr.json() : { connected: false }
        if (!status.connected) {
          setState({ kind: 'disconnected' })
          return
        }
        const ir = await fetch(
          `/api/integrations/instagram/insights?brand_id=${encodeURIComponent(brand.id)}`,
        )
        if (cancelled) return
        if (ir.ok) {
          setState({ kind: 'ok', data: await ir.json() })
        } else {
          const detail = await ir
            .json()
            .then((j) => j?.detail ?? null)
            .catch(() => null)
          setState({
            kind: 'error',
            message: detail ?? `Insights failed (${ir.status})`,
          })
        }
      } catch (e) {
        if (!cancelled) {
          setState({
            kind: 'error',
            message: e instanceof Error ? e.message : 'Network error',
          })
        }
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [brand.id])

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.05 }}
      className="mt-8"
    >
      <div className="flex items-end justify-between">
        <div>
          <div className="flex items-center gap-2 text-[13px] font-semibold">
            <span
              className="grid h-5 w-5 place-items-center rounded-md text-[10px] font-bold"
              style={{ background: '#fbe1ec', color: '#c026d3' }}
            >
              ◉
            </span>
            Instagram
          </div>
          {state.kind === 'ok' && (
            <p className="mt-1 text-[11px] text-fg-mute">
              @{state.data.account.username} ·{' '}
              {new Date(state.data.fetched_at).toLocaleTimeString([], {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </p>
          )}
        </div>
      </div>

      <div className="mt-4">
        {state.kind === 'loading' && (
          <div className="panel flex items-center justify-center px-6 py-10 text-[12px] text-fg-mute">
            Loading Instagram insights…
          </div>
        )}
        {state.kind === 'disconnected' && <DisconnectedState />}
        {state.kind === 'error' && <ErrorState message={state.message} />}
        {state.kind === 'ok' && <Connected data={state.data} />}
      </div>
    </motion.section>
  )
}

function DisconnectedState() {
  const { navigate } = useNav()
  return (
    <div className="panel flex flex-col items-start gap-3 px-6 py-5">
      <div>
        <div className="text-[13px] font-medium">Instagram is not connected</div>
        <p className="mt-1 max-w-md text-[12px] leading-snug text-fg-mute">
          Connect a Business Instagram account in Settings → Integrations to
          pull live followers, reach, and per-post performance into Analytics.
        </p>
      </div>
      <button
        onClick={() => navigate('settings')}
        className="rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] hover:brightness-110"
      >
        Open Settings →
      </button>
    </div>
  )
}

function ErrorState({ message }: { message: string }) {
  const { navigate } = useNav()
  return (
    <div className="panel px-6 py-5">
      <div className="text-[13px] font-medium text-red-700">
        Couldn't fetch Instagram insights
      </div>
      <p className="mt-1 text-[12px] leading-snug text-fg-mute">{message}</p>
      <button
        onClick={() => navigate('settings')}
        className="mt-3 hairline rounded-xl bg-bg-card px-4 py-2 text-[12.5px] text-fg-mute hover:text-fg"
      >
        Reconnect in Settings →
      </button>
    </div>
  )
}

function Connected({ data }: { data: Insights }) {
  return (
    <div className="flex flex-col gap-5">
      <ProfileBar data={data} />
      <SeriesGrid series={data.series} />
      <MediaGrid items={data.recent_media} />
    </div>
  )
}

function ProfileBar({ data }: { data: Insights }) {
  const { account } = data
  const fmt = (n: number | null) =>
    n == null ? '—' : new Intl.NumberFormat().format(n)
  return (
    <div className="panel flex flex-wrap items-center gap-4 px-6 py-4">
      {account.profile_picture_url ? (
        <img
          src={account.profile_picture_url}
          alt=""
          className="h-12 w-12 rounded-full object-cover"
        />
      ) : (
        <div className="grid h-12 w-12 place-items-center rounded-full bg-gradient-to-br from-[#fbe1ec] to-[#f9d4e5] text-[16px] font-semibold text-[#c026d3]">
          ◉
        </div>
      )}
      <div className="min-w-0 flex-1">
        <div className="truncate text-[14px] font-semibold leading-tight">
          @{account.username}
        </div>
        {account.biography && (
          <p className="mt-0.5 line-clamp-2 max-w-md text-[12px] leading-snug text-fg-mute">
            {account.biography}
          </p>
        )}
      </div>
      <Stat label="Followers" value={fmt(account.followers_count)} />
      <Stat label="Following" value={fmt(account.follows_count)} />
      <Stat label="Posts" value={fmt(account.media_count)} />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-right">
      <div className="text-[18px] font-semibold leading-none tabular-nums">
        {value}
      </div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.16em] text-fg-mute">
        {label}
      </div>
    </div>
  )
}

const SERIES_LABELS: Record<string, string> = {
  reach: 'Reach',
  profile_views: 'Profile Views',
}

function SeriesGrid({ series }: { series: Record<string, SeriesPoint[]> }) {
  const keys = useMemo(
    () => Object.keys(series).filter((k) => series[k].length > 0),
    [series],
  )
  if (keys.length === 0) {
    return (
      <div className="panel px-6 py-4 text-[12px] text-fg-mute">
        No time-series data returned by Graph API for the selected window. (Some
        metrics require ≥ 100 followers or are gated by Meta App Review.)
      </div>
    )
  }
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {keys.map((k) => (
        <SeriesChart
          key={k}
          label={SERIES_LABELS[k] ?? k}
          points={series[k]}
        />
      ))}
    </div>
  )
}

function SeriesChart({
  label,
  points,
}: {
  label: string
  points: SeriesPoint[]
}) {
  const max = Math.max(...points.map((p) => p.value), 1)
  const total = points.reduce((acc, p) => acc + (p.value || 0), 0)
  return (
    <div className="panel p-5">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          {label}
        </div>
        <div className="text-[12px] font-semibold tabular-nums text-fg">
          {new Intl.NumberFormat().format(total)}
        </div>
      </div>
      <div className="mt-4 flex h-24 items-end gap-1.5">
        {points.map((p, i) => {
          const h = (p.value / max) * 100
          return (
            <div
              key={i}
              className="flex-1"
              title={`${new Date(p.date).toLocaleDateString()} — ${p.value}`}
              style={{ height: '100%' }}
            >
              <div
                className="h-full w-full origin-bottom rounded bg-accent-soft"
                style={{
                  transform: `scaleY(${h / 100})`,
                  background: i === points.length - 1 ? 'var(--color-accent)' : undefined,
                }}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}

function MediaGrid({ items }: { items: RecentMedia[] }) {
  if (items.length === 0) {
    return (
      <div className="panel px-6 py-4 text-[12px] text-fg-mute">
        No recent media yet.
      </div>
    )
  }
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Recent posts
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
        {items.slice(0, 12).map((m) => (
          <MediaCard key={m.id} media={m} />
        ))}
      </div>
    </div>
  )
}

function MediaCard({ media }: { media: RecentMedia }) {
  const thumb = media.thumbnail_url || media.media_url
  const caption = media.caption?.slice(0, 80) ?? ''
  return (
    <a
      href={media.permalink}
      target="_blank"
      rel="noopener noreferrer"
      className="panel group flex flex-col overflow-hidden p-0 transition hover:shadow-[0_8px_24px_rgba(20,20,40,0.08)]"
    >
      <div className="relative aspect-square w-full bg-bg-soft">
        {thumb ? (
          <img
            src={thumb}
            alt=""
            className="absolute inset-0 h-full w-full object-cover"
          />
        ) : (
          <div className="absolute inset-0 grid place-items-center text-fg-dim">
            ◉
          </div>
        )}
        {media.media_type === 'VIDEO' && (
          <span className="absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[9px] font-medium text-white">
            VIDEO
          </span>
        )}
      </div>
      <div className="px-3 py-2.5">
        {caption && (
          <p className="line-clamp-2 text-[11.5px] leading-snug text-fg">
            {caption}
            {(media.caption?.length ?? 0) > 80 ? '…' : ''}
          </p>
        )}
        <div className="mt-1.5 flex items-center gap-3 text-[10.5px] text-fg-mute">
          <span className="tabular-nums">♡ {media.like_count ?? 0}</span>
          <span className="tabular-nums">💬 {media.comments_count ?? 0}</span>
          <span className="ml-auto text-fg-dim">
            {new Date(media.timestamp).toLocaleDateString()}
          </span>
        </div>
      </div>
    </a>
  )
}
