import { useEffect, useState, type FormEvent } from 'react'
import { motion } from 'motion/react'
import { useOnboardingStore } from '../stores/onboardingStore'
import { bus, type ReferenceBrand } from '../events/bus'
import { InitialsAvatar } from '../components/InitialsAvatar'

type SlotState =
  | { phase: 'idle' }
  | { phase: 'fetching'; url: string }
  | { phase: 'done'; url: string; reference: ReferenceBrand }
  | { phase: 'failed'; url: string; error: string }

const SLOT_COUNT = 3

export function StepReferences({
  onAdvance,
  onSkip,
}: {
  onAdvance: () => void
  onSkip: () => void
}) {
  const brandId = useOnboardingStore((s) => s.brandId)
  const references = useOnboardingStore((s) => s.references)

  const [slots, setSlots] = useState<SlotState[]>(
    Array.from({ length: SLOT_COUNT }, () => ({ phase: 'idle' as const })),
  )
  const [drafts, setDrafts] = useState<string[]>(
    Array.from({ length: SLOT_COUNT }, () => ''),
  )

  // When the bus fires reference_added with a URL we are awaiting, snap that slot to done.
  useEffect(() => {
    function onAdded(p: {
      brand_id: string
      reference: ReferenceBrand
    }) {
      setSlots((prev) =>
        prev.map((s) => {
          if (s.phase !== 'fetching') return s
          if (sameUrl(s.url, p.reference.url)) {
            return { phase: 'done', url: s.url, reference: p.reference }
          }
          return s
        }),
      )
    }
    function onFailed(p: { brand_id: string; url: string; error: string }) {
      setSlots((prev) =>
        prev.map((s) => {
          if (s.phase !== 'fetching') return s
          if (sameUrl(s.url, p.url)) {
            return { phase: 'failed', url: s.url, error: p.error }
          }
          return s
        }),
      )
    }
    bus.on('onboarding.reference_added', onAdded)
    bus.on('onboarding.reference_failed', onFailed)
    return () => {
      bus.off('onboarding.reference_added', onAdded)
      bus.off('onboarding.reference_failed', onFailed)
    }
  }, [])

  // Hydrate from store on mount in case event fired before slot was fetched.
  useEffect(() => {
    if (references.length === 0) return
    setSlots((prev) => {
      const next = [...prev]
      let cursor = 0
      for (const r of references) {
        while (cursor < next.length && next[cursor].phase === 'done') cursor++
        if (cursor >= next.length) break
        next[cursor] = { phase: 'done', url: r.url, reference: r }
        cursor++
      }
      return next
    })
    // we intentionally hydrate once per mount; store updates also drive the
    // bus listener above for the live case.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function submitSlot(idx: number, e: FormEvent) {
    e.preventDefault()
    const value = drafts[idx].trim()
    if (!value || !brandId) return
    const url = ensureScheme(value)
    setSlots((prev) => {
      const next = [...prev]
      next[idx] = { phase: 'fetching', url }
      return next
    })

    try {
      const r = await fetch('/api/onboarding/references', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ brand_id: brandId, url }),
      })
      if (!r.ok) {
        setSlots((prev) => {
          const next = [...prev]
          next[idx] = {
            phase: 'failed',
            url,
            error: `request failed (${r.status})`,
          }
          return next
        })
      }
      // Otherwise the bus event drives the transition to done/failed.
    } catch (err) {
      setSlots((prev) => {
        const next = [...prev]
        next[idx] = {
          phase: 'failed',
          url,
          error: err instanceof Error ? err.message : 'unknown error',
        }
        return next
      })
    }
  }

  function clearSlot(idx: number) {
    setSlots((prev) => {
      const next = [...prev]
      next[idx] = { phase: 'idle' }
      return next
    })
    setDrafts((prev) => {
      const next = [...prev]
      next[idx] = ''
      return next
    })
  }

  const doneCount = slots.filter((s) => s.phase === 'done').length

  return (
    <div className="grid min-h-[calc(100vh-73px)] grid-rows-[1fr_auto]">
      <div className="px-10 py-12">
        <div className="mx-auto w-full max-w-3xl">
          <motion.span
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.1 }}
            className="text-[11px] font-medium uppercase tracking-[0.2em] text-fg-mute"
          >
            Step 02 — Taste calibration
          </motion.span>

          <motion.h1
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.16, duration: 0.5 }}
            className="mt-3 text-5xl font-medium leading-[1.05] tracking-tight"
          >
            Brands you{' '}
            <span
              className="font-serif italic text-accent"
              style={{ fontVariationSettings: '"opsz" 144, "SOFT" 50' }}
            >
              admire.
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.32 }}
            className="mt-4 max-w-xl text-base text-fg-mute"
          >
            Drop up to three brands whose voice or visual you'd love yours to
            sit beside. The agent will read them and weight your output toward
            their best moves.
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.42, duration: 0.5 }}
            className="mt-10 flex flex-col gap-3"
          >
            {slots.map((slot, idx) => (
              <ReferenceSlot
                key={idx}
                index={idx}
                slot={slot}
                draft={drafts[idx]}
                onDraft={(v) =>
                  setDrafts((prev) => {
                    const next = [...prev]
                    next[idx] = v
                    return next
                  })
                }
                onSubmit={(e) => submitSlot(idx, e)}
                onClear={() => clearSlot(idx)}
              />
            ))}
          </motion.div>

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.6 }}
            className="mt-6 text-[11px] text-fg-dim"
          >
            tip · pick brands close to your voice (not just famous ones).
            arc.net, linear.app, posthog.com, vercel.com all give the agent
            something to chew on.
          </motion.p>
        </div>
      </div>

      <div className="sticky bottom-0 flex items-center justify-between border-t border-line bg-bg-card/85 px-10 py-4 backdrop-blur">
        <button
          onClick={onSkip}
          className="text-xs text-fg-mute underline-offset-4 hover:text-fg hover:underline"
        >
          Skip this step
        </button>
        <div className="flex items-center gap-4">
          <span className="text-xs text-fg-mute tabular-nums">
            {doneCount}/{SLOT_COUNT} added
          </span>
          <button
            onClick={onAdvance}
            className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-white shadow-[0_4px_14px_rgba(111,92,255,0.4)] transition hover:brightness-110"
          >
            Continue → Reading you
          </button>
        </div>
      </div>
    </div>
  )
}

function ReferenceSlot({
  index,
  slot,
  draft,
  onDraft,
  onSubmit,
  onClear,
}: {
  index: number
  slot: SlotState
  draft: string
  onDraft: (v: string) => void
  onSubmit: (e: FormEvent) => void
  onClear: () => void
}) {
  const num = String(index + 1).padStart(2, '0')

  if (slot.phase === 'done') {
    return (
      <ReferenceCard
        num={num}
        reference={slot.reference}
        onClear={onClear}
      />
    )
  }

  if (slot.phase === 'fetching' || slot.phase === 'failed') {
    return (
      <PendingCard
        num={num}
        url={slot.url}
        failed={slot.phase === 'failed'}
        error={slot.phase === 'failed' ? slot.error : undefined}
        onClear={onClear}
      />
    )
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex items-center gap-3 rounded-2xl border border-line bg-bg-card px-1.5 py-1.5 shadow-[0_2px_12px_rgba(20,20,40,0.03)] transition focus-within:border-accent/60 focus-within:shadow-[0_8px_30px_rgba(20,20,40,0.05)]"
    >
      <span className="px-3 font-mono text-[11px] tabular-nums text-fg-dim">
        {num}
      </span>
      <input
        type="text"
        placeholder="https://brand-you-love.com"
        value={draft}
        onChange={(e) => onDraft(e.target.value)}
        className="flex-1 bg-transparent px-2 py-2.5 text-base outline-none placeholder:text-fg-dim"
      />
      <button
        type="submit"
        disabled={!draft.trim()}
        className="grid h-9 w-9 place-items-center rounded-xl bg-accent text-white shadow-[0_3px_12px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        title="Add reference"
      >
        ↵
      </button>
    </form>
  )
}

function PendingCard({
  num,
  url,
  failed,
  error,
  onClear,
}: {
  num: string
  url: string
  failed: boolean
  error?: string
  onClear: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`flex items-center gap-4 rounded-2xl border px-4 py-3 ${
        failed
          ? 'border-danger/30 bg-danger/5'
          : 'border-line bg-bg-card'
      }`}
    >
      <span className="font-mono text-[11px] tabular-nums text-fg-dim">
        {num}
      </span>
      <div className="h-10 w-10 shrink-0 animate-pulse rounded-xl bg-bg-soft" />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{stripScheme(url)}</div>
        <div
          className={`mt-0.5 font-mono text-[10px] uppercase tracking-wider ${
            failed ? 'text-danger' : 'text-accent'
          }`}
        >
          {failed
            ? `✕ failed${error ? ` · ${error.slice(0, 60)}` : ''}`
            : '◐ fetching…'}
        </div>
      </div>
      <button
        type="button"
        onClick={onClear}
        className="text-xs text-fg-dim hover:text-fg"
      >
        {failed ? 'retry' : 'remove'}
      </button>
    </motion.div>
  )
}

function ReferenceCard({
  num,
  reference,
  onClear,
}: {
  num: string
  reference: ReferenceBrand
  onClear: () => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="grid grid-cols-[auto_auto_1fr_auto_auto] items-center gap-4 rounded-2xl border border-line bg-bg-card px-4 py-3"
    >
      <span className="font-mono text-[11px] tabular-nums text-fg-dim">
        {num}
      </span>
      {reference.logo_url ? (
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f5f1e8] p-1.5">
          <img
            src={reference.logo_url}
            alt=""
            className="max-h-full max-w-full object-contain"
          />
        </div>
      ) : (
        <InitialsAvatar name={reference.name} size="md" />
      )}
      <div className="min-w-0">
        <div className="truncate text-sm font-medium leading-tight">
          {reference.name}
        </div>
        <div className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-wider text-fg-mute">
          {stripScheme(reference.url)}
        </div>
      </div>
      <div className="flex items-center gap-1">
        {reference.palette.slice(0, 5).map((c, i) => (
          <span
            key={c + i}
            className="h-5 w-5 rounded-md border border-line"
            style={{ background: c }}
          />
        ))}
      </div>
      {reference.screenshot_urls?.[0] ? (
        <div className="hidden h-12 w-20 overflow-hidden rounded-md border border-line bg-bg-soft sm:block">
          <img
            src={reference.screenshot_urls[0]}
            alt=""
            className="h-full w-full object-cover"
          />
        </div>
      ) : (
        <div className="hidden h-12 w-20 rounded-md border border-line bg-bg-soft sm:block" />
      )}
      <button
        type="button"
        onClick={onClear}
        className="col-span-5 mt-1 justify-self-end text-[11px] text-fg-dim hover:text-fg sm:col-span-1 sm:mt-0"
      >
        replace
      </button>
    </motion.div>
  )
}

function ensureScheme(u: string): string {
  if (/^https?:\/\//i.test(u)) return u
  return `https://${u}`
}

function stripScheme(u: string): string {
  return u.replace(/^https?:\/\//, '').replace(/\/$/, '')
}

function sameUrl(a: string, b: string): boolean {
  const norm = (u: string) => {
    try {
      const url = new URL(u.startsWith('http') ? u : `https://${u}`)
      return url.host.toLowerCase().replace(/^www\./, '')
    } catch {
      return stripScheme(u).toLowerCase()
    }
  }
  return norm(a) === norm(b)
}
