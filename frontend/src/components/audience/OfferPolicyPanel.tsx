import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { OfferPolicyEditor } from './OfferPolicyEditor'
import {
  DEFAULT_OFFER_POLICY,
  type OfferPolicy,
} from '../../lib/audience'
import { bus } from '../../events/bus'

type Props = {
  brandId: string
  open: boolean
  onClose: () => void
}

type PolicyResponse = {
  policy: Partial<OfferPolicy>
  effective: OfferPolicy
}

type ClampFeedEntry = {
  brand_id?: string
  target_kind?: string
  target_id?: string
  field?: string
  proposed?: unknown
  clamped_to?: unknown
  reason?: string
  received_at?: string
}

export function OfferPolicyPanel({ brandId, open, onClose }: Props) {
  const [policy, setPolicy] = useState<Partial<OfferPolicy>>({})
  const [effective, setEffective] = useState<OfferPolicy>(DEFAULT_OFFER_POLICY)
  const [clamps, setClamps] = useState<ClampFeedEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      fetch(
        `/api/audience/brands/${encodeURIComponent(brandId)}/offer-policy`,
      ).then(async (r) => {
        if (!r.ok) throw new Error(`policy load failed (${r.status})`)
        return (await r.json()) as PolicyResponse
      }),
      fetch(
        `/api/audience/policy-clamps?brand_id=${encodeURIComponent(
          brandId,
        )}&limit=50`,
      ).then(async (r) => {
        if (!r.ok) throw new Error(`clamps load failed (${r.status})`)
        return (await r.json()) as { clamps: ClampFeedEntry[] }
      }),
    ])
      .then(([pol, fed]) => {
        if (cancelled) return
        setPolicy(pol.policy ?? {})
        setEffective(pol.effective ?? DEFAULT_OFFER_POLICY)
        setClamps(fed.clamps ?? [])
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'load failed')
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [open, brandId])

  useEffect(() => {
    if (!open) return
    const handler = (e: ClampFeedEntry) => {
      if (e.brand_id && e.brand_id !== brandId) return
      setClamps((prev) =>
        [
          {
            ...e,
            received_at: e.received_at ?? new Date().toISOString(),
          },
          ...prev,
        ].slice(0, 100),
      )
    }
    bus.on('offer.policy_clamped', handler)
    return () => {
      bus.off('offer.policy_clamped', handler)
    }
  }, [open, brandId])

  const save = async (next: Partial<OfferPolicy>) => {
    setSaving(true)
    setError(null)
    try {
      const r = await fetch(
        `/api/audience/brands/${encodeURIComponent(brandId)}/offer-policy`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ policy: next }),
        },
      )
      if (!r.ok) throw new Error(`save failed (${r.status})`)
      const data = (await r.json()) as PolicyResponse
      setPolicy(data.policy ?? {})
      setEffective(data.effective ?? DEFAULT_OFFER_POLICY)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px]"
          />
          <motion.aside
            key="panel"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 240 }}
            className="fixed right-0 top-0 bottom-0 z-50 flex w-[min(560px,100vw)] flex-col bg-bg shadow-2xl"
          >
            <header className="flex items-center justify-between border-b border-line px-6 py-4">
              <div>
                <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
                  Brand settings
                </div>
                <h2 className="mt-1 font-serif text-2xl tracking-tight">
                  Offer policy
                </h2>
                <p className="mt-1 text-xs text-fg-mute">
                  The Freedom-to-Operate envelope. The AI proposes inside this;
                  the validator clamps anything outside.
                </p>
              </div>
              <button
                onClick={onClose}
                className="grid h-8 w-8 place-items-center rounded-full text-fg-mute hover:bg-bg-card hover:text-fg"
                aria-label="Close"
              >
                ✕
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-6 py-5 [scrollbar-width:thin]">
              {loading ? (
                <div className="text-sm text-fg-mute">loading…</div>
              ) : (
                <>
                  <div className="rounded-2xl border border-line bg-bg-card p-4">
                    <OfferPolicyEditor
                      value={policy}
                      onChange={(next) => {
                        setPolicy(next)
                        void save(next)
                      }}
                      defaults={effective}
                    />
                    {saving && (
                      <div className="mt-2 text-[10px] text-fg-dim">
                        saving…
                      </div>
                    )}
                    {error && (
                      <div className="mt-2 text-[10px] text-red-500">
                        {error}
                      </div>
                    )}
                  </div>

                  <section className="mt-6">
                    <div className="flex items-baseline justify-between">
                      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                        Trust dashboard
                      </div>
                      <div className="text-[10px] text-fg-dim">
                        {clamps.length} recent
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-fg-mute">
                      Every time the validator rewrote an LLM-proposed offer.
                      Live updates as new clamps land.
                    </p>
                    {clamps.length === 0 ? (
                      <div className="mt-3 rounded-xl border border-dashed border-line px-4 py-3 text-xs text-fg-mute">
                        No clamps yet. The AI is staying inside the envelope.
                      </div>
                    ) : (
                      <ul className="mt-3 flex flex-col gap-1.5">
                        {clamps.map((c, i) => (
                          <li
                            key={`${c.received_at ?? ''}:${i}`}
                            className="rounded-xl border border-line bg-bg-card px-3 py-2 text-xs"
                          >
                            <div className="flex items-baseline justify-between gap-2">
                              <span className="font-medium text-fg">
                                {c.field ?? 'unknown field'}
                              </span>
                              <span className="text-[10px] text-fg-dim">
                                {formatRelative(c.received_at)}
                              </span>
                            </div>
                            <div className="mt-1 leading-snug text-fg-mute">
                              <span className="text-fg-dim line-through">
                                {String(c.proposed ?? '')}
                              </span>{' '}
                              → <span className="text-fg">
                                {String(c.clamped_to ?? '')}
                              </span>
                            </div>
                            {c.reason && (
                              <div className="mt-0.5 text-[10px] text-fg-dim">
                                {c.reason}
                              </div>
                            )}
                            {(c.target_kind || c.target_id) && (
                              <div className="mt-0.5 text-[10px] text-fg-dim">
                                {c.target_kind} · {c.target_id}
                              </div>
                            )}
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                </>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function formatRelative(iso: string | undefined): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (Number.isNaN(t)) return ''
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000))
  if (sec < 60) return `${sec}s ago`
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`
  return `${Math.round(sec / 86400)}d ago`
}
