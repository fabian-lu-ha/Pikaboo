import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { AgentSession } from '../AgentSession'
import { useAgentSessionStore } from '../../stores/agentSessionStore'
import { bus } from '../../events/bus'
import { firstWord } from '../../lib/brandName'
import { RecentRuns } from './RecentRuns'
import { TopBar } from './TopBar'
import type { Brand } from './types'

// Build 3 suggestion chips tailored to the current brand. Pulls in the
// brand's first name, top competitor, voice tone, and connected channels so
// the chips read like the agent already knows the company.
function buildSuggestions(brand: Brand): string[] {
  const first = firstWord(brand.name)
  const top = brand.competitors[0]?.name
  const tone = brand.voice_profile?.tone
  const channels = Object.keys(brand.handles ?? {}).map((k) => k.toLowerCase())

  const out: string[] = [`What should ${first} post this week?`]

  out.push(
    top
      ? `Counter ${top} with ${first}'s strongest angle`
      : `Launch campaign for ${first}'s newest feature`,
  )

  if (channels.some((c) => c.includes('instagram'))) {
    out.push(`Draft an Instagram series in ${first}'s voice`)
  } else if (channels.some((c) => c.includes('linkedin'))) {
    out.push(`Write a LinkedIn post that nails ${first}'s positioning`)
  } else if (channels.some((c) => c.includes('tiktok'))) {
    out.push(`Outline a 3-reel TikTok hook for ${first}`)
  } else if (tone) {
    out.push(`Plan a campaign that doubles down on our ${tone} tone`)
  } else {
    out.push(`Plan a 5-post launch series for ${first}`)
  }

  return out
}

type FormatId =
  | 'linkedin'
  | 'instagram-post'
  | 'instagram-video'
  | 'tiktok-reel'
  | 'carousel'

const FORMATS: { id: FormatId; label: string; glyph: string }[] = [
  { id: 'linkedin', label: 'LinkedIn Post', glyph: 'in' },
  { id: 'instagram-post', label: 'Instagram Post', glyph: '◫' },
  { id: 'instagram-video', label: 'Instagram Video', glyph: '▶' },
  { id: 'tiktok-reel', label: 'TikTok Reel', glyph: '◉' },
  { id: 'carousel', label: 'Carousel Post', glyph: '◧' },
]

export function Main({ brand }: { brand: Brand }) {
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [formats, setFormats] = useState<FormatId[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const suggestions = useMemo(() => buildSuggestions(brand), [brand])
  const userRequest = useAgentSessionStore((s) => s.userRequest)
  const sessionActive = !!userRequest
  const sessionStatus = useAgentSessionStore((s) => s.status)
  const sessionRunning = sessionStatus === 'running'
  const resetSession = useAgentSessionStore((s) => s.reset)

  // Lock submission while the agent is running. Race-safe — uses the canonical
  // session store status instead of a local flag that clears synchronously.
  const locked = sessionRunning

  function toggleFormat(id: FormatId) {
    setFormats((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : [...s, id],
    )
  }

  async function send(text?: string) {
    if (locked) return
    const message = (text ?? draft).trim()
    if (!message) return
    // Pass the chosen formats as structured data — the backend agent loop
    // uses them to constrain which channels it drafts (linkedin, instagram, …).
    bus.emit('chat.submitted', {
      text: message,
      formats: formats.length > 0 ? [...formats] : undefined,
    })
    setDraft('')
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    send()
  }

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />

      <div className="px-10 pb-10">
        {sessionActive ? (
          <RunHeader
            request={userRequest ?? ''}
            status={sessionStatus}
            onNewSession={resetSession}
          />
        ) : (
          <section className="mt-16 flex flex-col items-center">
            <motion.h1
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5 }}
              className="text-center text-[44px] font-semibold leading-[1.1] tracking-[-0.02em] text-fg"
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
              <div className="hairline rounded-3xl bg-bg-card p-2 shadow-[0_10px_40px_rgba(20,20,40,0.05)]">
                <textarea
                  ref={textareaRef}
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
                  className="block w-full resize-none rounded-2xl bg-transparent px-5 py-4 text-[15px] outline-none placeholder:text-fg-dim disabled:opacity-60"
                />
                <div className="flex items-center justify-between gap-2 px-2 pb-1.5 pt-0.5">
                  <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
                    <FormatPicker
                      value={formats}
                      onToggle={toggleFormat}
                      onClear={() => setFormats([])}
                      disabled={locked}
                    />
                    {formats.map((id) => {
                      const f = FORMATS.find((x) => x.id === id)
                      if (!f) return null
                      return (
                        <span
                          key={id}
                          className="inline-flex items-center gap-1 rounded-full border border-accent bg-accent-soft px-2 py-0.5 text-[10.5px] font-medium text-accent"
                        >
                          {f.label}
                          <button
                            type="button"
                            onClick={() => toggleFormat(id)}
                            aria-label={`Remove ${f.label}`}
                            className="grid h-3.5 w-3.5 place-items-center rounded-full text-[9px] leading-none text-accent/70 hover:bg-accent/15 hover:text-accent"
                          >
                            ✕
                          </button>
                        </span>
                      )
                    })}
                  </div>
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
                      className="grid h-9 w-9 place-items-center rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] text-white shadow-[0_6px_18px_rgba(91,80,230,0.45)] transition hover:brightness-110 disabled:from-accent-dim disabled:to-accent-dim disabled:shadow-none"
                      title="Send"
                    >
                      ↑
                    </button>
                  </div>
                </div>
              </div>
            </motion.form>

            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => {
                    setDraft(s)
                    textareaRef.current?.focus()
                  }}
                  className="hairline rounded-full bg-bg-card px-4 py-2 text-[13px] text-fg-mute transition hover:border-accent hover:text-fg"
                >
                  {s}
                </button>
              ))}
            </div>
          </section>
        )}

        <AgentSession />

        {!sessionActive && <RecentRuns brand={brand} />}
      </div>
    </main>
  )
}

// ----------------------------------------------------------- run page header

// When a run is active we hide the chat input entirely. This component takes
// over the top of the page: it surfaces the original prompt, an active-state
// oval pill, and a single "New session" escape hatch.
function RunHeader({
  request,
  status,
  onNewSession,
}: {
  request: string
  status: 'idle' | 'running' | 'bundled' | 'failed'
  onNewSession: () => void
}) {
  // Strip the [Format: ...] prefix the dashboard prepends so the header
  // reads cleanly. Format chips can surface again inside AgentSession if
  // we ever wire them through the run state.
  const displayRequest = request.replace(/^\[Format:[^\]]+\]\s*/, '')

  return (
    <motion.section
      key="run-header"
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
      className="mt-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <RunStatusPill status={status} />
            <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
              Current run
            </span>
          </div>
          <h1 className="mt-2 text-[26px] font-semibold leading-[1.2] tracking-[-0.01em] text-fg">
            {displayRequest || 'Untitled run'}
          </h1>
        </div>
        <button
          onClick={onNewSession}
          className="hairline shrink-0 rounded-full bg-bg-card px-4 py-2 text-[12px] font-medium text-fg-mute transition hover:border-accent hover:text-fg"
        >
          ← New session
        </button>
      </div>
    </motion.section>
  )
}

function RunStatusPill({
  status,
}: {
  status: 'idle' | 'running' | 'bundled' | 'failed'
}) {
  const cfg =
    status === 'running'
      ? { label: 'Running', dot: 'bg-accent', text: 'text-accent', bg: 'bg-accent-soft' }
      : status === 'bundled'
        ? { label: 'Bundled', dot: 'bg-success', text: 'text-success', bg: 'bg-emerald-50' }
        : status === 'failed'
          ? { label: 'Failed', dot: 'bg-danger', text: 'text-danger', bg: 'bg-red-50' }
          : { label: 'Idle', dot: 'bg-fg-dim', text: 'text-fg-mute', bg: 'bg-bg-soft' }
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ${cfg.bg} ${cfg.text}`}
    >
      <span className={`relative grid h-1.5 w-1.5 place-items-center`}>
        <span className={`absolute inset-0 rounded-full ${cfg.dot}`} />
        {status === 'running' && (
          <span
            className={`absolute inset-0 rounded-full ${cfg.dot} animate-ping opacity-60`}
          />
        )}
      </span>
      {cfg.label}
    </span>
  )
}

function FormatPicker({
  value,
  onToggle,
  onClear,
  disabled,
}: {
  value: FormatId[]
  onToggle: (id: FormatId) => void
  onClear: () => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const buttonLabel =
    value.length === 0
      ? 'Auto'
      : value.length === 1
        ? FORMATS.find((f) => f.id === value[0])?.label ?? 'Format'
        : `${value.length} formats`

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        className="hairline flex items-center gap-1 rounded-full bg-bg-card px-2.5 py-1 text-[11px] font-medium text-fg-mute transition hover:border-accent hover:text-fg disabled:opacity-50"
        title="Choose output format"
      >
        <span>{buttonLabel}</span>
        <span className="text-[8px] text-fg-dim">▾</span>
      </button>
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.98 }}
            transition={{ duration: 0.16, ease: [0.16, 1, 0.3, 1] }}
            className="panel absolute bottom-full left-0 z-30 mb-2 w-44 overflow-hidden p-1"
          >
            <ul className="flex max-h-40 flex-col overflow-y-auto overscroll-contain [scrollbar-width:thin]">
              {FORMATS.map((f) => {
                const isActive = value.includes(f.id)
                return (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => onToggle(f.id)}
                      className={`block w-full truncate rounded-md border px-2 py-1.5 text-left text-[11.5px] transition ${
                        isActive
                          ? 'border-accent bg-accent-soft text-fg'
                          : 'border-transparent text-fg hover:bg-bg-soft'
                      }`}
                    >
                      {f.label}
                    </button>
                  </li>
                )
              })}
            </ul>
            {value.length > 0 && (
              <button
                type="button"
                onClick={onClear}
                className="mt-1 w-full rounded-md px-2 py-1 text-[10.5px] text-fg-mute hover:bg-bg-soft hover:text-fg"
              >
                Clear all
              </button>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
