import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { motion } from 'motion/react'
import { useEventStream } from './events/useEventStream'
import { OnboardingFlow } from './onboarding/OnboardingFlow'
import { InitialsAvatar } from './components/InitialsAvatar'
import { AgentSession } from './components/AgentSession'
import { useAgentSessionStore } from './stores/agentSessionStore'
import { bus } from './events/bus'

type Competitor = {
  id: string
  name: string
  url: string | null
  reason: string | null
  logo_url: string | null
}

type Brand = {
  id: string
  name: string
  url: string | null
  description: string | null
  logo_url: string | null
  screenshots: string[]
  theme_color: string | null
  palette: string[]
  palette_roles?: { hex: string; role: string }[]
  voice_profile: {
    tone?: string
    voice_excerpt?: string
    recurring_phrases?: string[]
    do?: string[]
    dont?: string[]
  } | null
  handles: Record<string, string>
  competitors: Competitor[]
}

export default function App() {
  useEventStream('/api/events')
  const [brand, setBrand] = useState<Brand | null | undefined>(undefined)

  const refresh = useCallback(async () => {
    const r = await fetch('/api/onboarding/me')
    const d = (await r.json()) as { brand: Brand | null }
    setBrand(d.brand)
  }, [])

  useEffect(() => {
    refresh().catch(() => setBrand(null))
  }, [refresh])

  if (brand === undefined) {
    return (
      <div className="grid h-screen place-items-center font-mono text-xs uppercase tracking-[0.22em] text-fg-mute">
        loading
      </div>
    )
  }

  if (brand === null) {
    return <OnboardingFlow onComplete={() => refresh()} />
  }

  return <Home brand={brand} />
}

const NAV: { id: string; label: string; icon: string; active?: boolean }[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '◫', active: true },
  { id: 'campaigns', label: 'Campaigns', icon: '✦' },
  { id: 'voice', label: 'Voice', icon: '◐' },
  { id: 'library', label: 'Library', icon: '⊞' },
  { id: 'reports', label: 'Reports', icon: '◇' },
]

const SUGGESTIONS = [
  'What should I post this week?',
  'Make a launch campaign for the feature we just shipped',
  'Counter Salesforce on startup CRM',
]

function Home({ brand }: { brand: Brand }) {
  return (
    <div className="grid min-h-screen grid-cols-[260px_1fr_320px]">
      <Sidebar brand={brand} />
      <Main brand={brand} />
      <RightRail brand={brand} />
    </div>
  )
}

function Sidebar({ brand }: { brand: Brand }) {
  const resetSession = useAgentSessionStore((s) => s.reset)
  const sessionActive = useAgentSessionStore((s) => !!s.userRequest)
  return (
    <aside className="flex flex-col border-r border-line bg-bg px-5 py-7">
      <div className="flex items-center gap-3 px-2">
        {brand.logo_url ? (
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#f5f1e8] p-1.5">
            <img
              src={brand.logo_url}
              alt=""
              className="max-h-full max-w-full object-contain"
            />
          </div>
        ) : (
          <InitialsAvatar name={brand.name} size="md" />
        )}
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold leading-tight">
            {primaryName(brand.name)}
          </div>
          <div className="truncate text-[11px] text-fg-mute">
            Brand Autopilot
          </div>
        </div>
      </div>

      {brand.palette.length > 0 && (
        <div className="mt-5 flex items-center gap-1.5 px-2">
          {brand.palette.slice(0, 6).map((c, i) => (
            <span
              key={c + i}
              className="h-3.5 w-3.5 rounded-sm border border-line/60"
              style={{ background: c }}
              title={c}
            />
          ))}
        </div>
      )}

      {brand.voice_profile?.tone && (
        <div className="mt-3 px-2">
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Voice
          </div>
          <p className="mt-1 line-clamp-2 text-[11px] leading-snug text-fg-mute">
            {brand.voice_profile.tone}
          </p>
          {(brand.voice_profile.recurring_phrases ?? []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {brand.voice_profile.recurring_phrases!
                .slice(0, 4)
                .map((ph) => (
                  <span
                    key={ph}
                    className="rounded-full border border-line bg-bg-card px-2 py-0.5 text-[10px] text-fg-mute"
                  >
                    {ph}
                  </span>
                ))}
            </div>
          )}
        </div>
      )}

      <nav className="mt-7 flex flex-col gap-0.5">
        {NAV.map((n) => (
          <a
            key={n.id}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${
              n.active
                ? 'bg-bg-card font-medium shadow-[0_1px_0_rgba(20,20,40,0.04)]'
                : 'text-fg-mute hover:bg-bg-card/60'
            }`}
          >
            <span
              className={`text-base ${n.active ? 'text-accent' : 'text-fg-dim'}`}
            >
              {n.icon}
            </span>
            <span>{n.label}</span>
          </a>
        ))}
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        <button
          onClick={() => {
            resetSession()
            window.scrollTo({ top: 0, behavior: 'smooth' })
          }}
          disabled={!sessionActive}
          className="rounded-full bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-[0_4px_14px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          + New Campaign
        </button>
        <div className="flex flex-col gap-2 px-2 text-xs text-fg-mute">
          <button
            onClick={async () => {
              if (
                !confirm(
                  'Delete this brand and re-run onboarding? This wipes the brand row + screenshots + competitors.',
                )
              )
                return
              await fetch('/api/onboarding/me', { method: 'DELETE' })
              window.location.reload()
            }}
            className="text-left hover:text-accent"
          >
            ↻ Re-onboard
          </button>
        </div>
      </div>
    </aside>
  )
}

function Main({ brand }: { brand: Brand }) {
  const [draft, setDraft] = useState('')
  const sessionActive = useAgentSessionStore((s) => !!s.userRequest)
  const sessionRunning = useAgentSessionStore(
    (s) => s.status === 'running',
  )
  const resetSession = useAgentSessionStore((s) => s.reset)

  // Lock submission while the agent is running. Race-safe — uses the canonical
  // session store status instead of a local flag that clears synchronously.
  const locked = sessionRunning

  async function send(text?: string) {
    if (locked) return
    const message = (text ?? draft).trim()
    if (!message) return
    bus.emit('chat.submitted', { text: message })
    setDraft('')
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    send()
  }

  return (
    <main className="flex flex-col px-10 py-7">
      <div className="flex items-center gap-4">
        <div className="flex flex-1 items-center gap-3 rounded-full border border-line bg-bg-card px-5 py-2.5">
          <span className="text-fg-dim">⌕</span>
          <input
            placeholder="Search campaigns, voice notes, drafts…"
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-fg-dim"
          />
        </div>
        <button className="grid h-10 w-10 place-items-center rounded-full bg-bg-card text-fg-mute hover:text-fg">
          ⌘
        </button>
        <button className="grid h-10 w-10 place-items-center rounded-full bg-bg-card text-fg-mute hover:text-fg">
          ⚙
        </button>
      </div>

      <section className="mt-20 flex flex-col items-center">
        <motion.h1
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="text-center text-[34px] font-medium leading-tight tracking-tight"
        >
          What should we ship this week,{' '}
          <span className="text-accent">{firstWord(brand.name)}</span>?
        </motion.h1>

        <motion.form
          onSubmit={handleSubmit}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.05 }}
          className="mt-8 w-full max-w-2xl"
        >
          <div className="rounded-3xl border border-line bg-bg-card p-2 shadow-[0_8px_30px_rgba(20,20,40,0.05)]">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              disabled={locked}
              placeholder={
                locked
                  ? 'agent is working — wait or start a new session'
                  : 'Ask about competitors, paste a URL, or describe a campaign…'
              }
              rows={3}
              className="block w-full resize-none rounded-2xl bg-transparent px-5 py-4 text-base outline-none placeholder:text-fg-dim disabled:opacity-60"
            />
            <div className="flex items-center justify-between px-3 pb-2 pt-1">
              <button
                type="button"
                className="grid h-9 w-9 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
                title="Attach"
              >
                +
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  className="grid h-9 w-9 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
                  title="Voice"
                >
                  ◍
                </button>
                <button
                  type="submit"
                  disabled={!draft.trim() || locked}
                  className="grid h-9 w-9 place-items-center rounded-full bg-accent text-white shadow-[0_4px_14px_rgba(111,92,255,0.4)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
                  title="Send"
                >
                  ↑
                </button>
              </div>
            </div>
          </div>
        </motion.form>

        {!sessionActive && (
          <div className="mt-6 flex flex-wrap justify-center gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                className="rounded-full border border-line bg-bg-card px-4 py-2 text-sm text-fg-mute transition hover:border-accent hover:text-fg"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {sessionActive && (
          <button
            onClick={resetSession}
            className="mt-4 text-[11px] uppercase tracking-[0.18em] text-fg-mute hover:text-accent"
          >
            ← new session
          </button>
        )}
      </section>

      <AgentSession />

      <section className="mt-16">
        <h2 className="text-sm font-medium text-fg-mute">Recent Runs</h2>
        <ul className="mt-4 flex flex-col rounded-2xl border border-line bg-bg-card">
          <RunRow
            tint="violet"
            title="Voice Profile"
            sub={`${primaryName(brand.name)} — captured on onboarding`}
            ago="just now"
          />
          <RunRow
            tint="emerald"
            title="Web Scrape"
            sub={`${primaryName(brand.name)} — ${(brand.screenshots || []).length} frames`}
            ago="just now"
          />
          <RunRow
            tint="amber"
            title="Competitive Field"
            sub={`${brand.competitors.length} competitors mapped`}
            ago="just now"
            last
          />
        </ul>
      </section>
    </main>
  )
}

function RunRow({
  tint,
  title,
  sub,
  ago,
  last,
}: {
  tint: 'violet' | 'emerald' | 'amber'
  title: string
  sub: string
  ago: string
  last?: boolean
}) {
  const tints: Record<string, { bg: string; fg: string; icon: string }> = {
    violet: { bg: '#ece9ff', fg: '#6f5cff', icon: '◐' },
    emerald: { bg: '#dcf3e9', fg: '#22a07a', icon: '◇' },
    amber: { bg: '#fbe8d6', fg: '#d97a3a', icon: '◫' },
  }
  const t = tints[tint]
  return (
    <li
      className={`flex items-center gap-4 px-5 py-4 ${
        last ? '' : 'border-b border-line-soft'
      }`}
    >
      <span
        className="grid h-9 w-9 place-items-center rounded-lg text-sm"
        style={{ background: t.bg, color: t.fg }}
      >
        {t.icon}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium leading-tight">{title}</div>
        <div className="truncate text-xs text-fg-mute">{sub}</div>
      </div>
      <span className="text-xs text-fg-mute">{ago}</span>
    </li>
  )
}

function RightRail({ brand }: { brand: Brand }) {
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [optimistic, setOptimistic] = useState<Competitor[]>([])

  async function submitAdd(e: FormEvent) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setSubmitting(true)
    try {
      const r = await fetch('/api/onboarding/competitors/add', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          brand_id: brand.id,
          name,
          url: newUrl.trim() || null,
        }),
      })
      if (r.ok) {
        const c = (await r.json()) as Competitor
        setOptimistic((s) => [...s, c])
        setNewName('')
        setNewUrl('')
        setAdding(false)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const allCompetitors = [...brand.competitors, ...optimistic]

  return (
    <aside className="px-5 py-7">
      <div className="rounded-2xl border border-line bg-bg-card p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold">Watchlist</h3>
          <button className="text-fg-dim hover:text-fg">⋯</button>
        </div>

        <ul className="mt-5 flex flex-col gap-4">
          {allCompetitors.length === 0 ? (
            <li className="text-xs text-fg-mute">No competitors yet.</li>
          ) : (
            allCompetitors.map((c) => (
              <li key={c.id} className="flex items-center gap-3">
                <InitialsAvatar name={c.name} size="md" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium leading-tight">
                    {c.name}
                  </div>
                  <CompetitorStatus name={c.name} />
                </div>
              </li>
            ))
          )}
        </ul>

        {adding ? (
          <form
            onSubmit={submitAdd}
            className="mt-5 flex flex-col gap-2 rounded-xl border border-line bg-bg-soft/40 p-3"
          >
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Name (e.g. Notion)"
              className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="URL (optional)"
              className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setAdding(false)}
                className="flex-1 rounded-md border border-line bg-bg-card py-1.5 text-xs text-fg-mute hover:text-fg"
              >
                cancel
              </button>
              <button
                type="submit"
                disabled={!newName.trim() || submitting}
                className="flex-1 rounded-md bg-accent py-1.5 text-xs font-medium text-white disabled:bg-accent-dim"
              >
                {submitting ? 'adding…' : 'add'}
              </button>
            </div>
          </form>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line py-3 text-sm text-fg-mute transition hover:border-accent hover:text-accent"
          >
            + Add Competitor
          </button>
        )}
      </div>
    </aside>
  )
}

function CompetitorStatus({ name }: { name: string }) {
  const STATUSES: { label: string; arrow: string; color: string }[] = [
    { label: 'High Activity', arrow: '↗', color: 'text-success' },
    { label: 'Stable', arrow: '→', color: 'text-fg-mute' },
    { label: 'Declining Mention', arrow: '↘', color: 'text-danger' },
    { label: 'New Citation', arrow: '✦', color: 'text-accent' },
  ]
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0
  const s = STATUSES[h % STATUSES.length]
  return (
    <div className={`flex items-center gap-1 text-[11px] ${s.color}`}>
      <span>{s.arrow}</span>
      <span>{s.label}</span>
    </div>
  )
}

function primaryName(s: string): string {
  return s.split(' · ')[0].split(' — ')[0].split(' | ')[0].trim()
}

function firstWord(s: string): string {
  return primaryName(s).split(/\s+/)[0] || s
}
