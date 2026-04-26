import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { bus } from '../../events/bus'

type Props = {
  brandId: string
  open: boolean
  onClose: () => void
}

type TriggerRule = {
  id: string
  label: string
  description: string
  enabled: boolean
  debounce_seconds: number
}

type TriggerFire = {
  brand_id: string
  rule_id: string
  rule_label: string
  customer_id: string | null
  campaign_id: string | null
  fired_at: string
}

type TriggersResponse = {
  rules: TriggerRule[]
  recent_fires: TriggerFire[]
}

export function TriggersPanel({ brandId, open, onClose }: Props) {
  const [rules, setRules] = useState<TriggerRule[]>([])
  const [fires, setFires] = useState<TriggerFire[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(
      `/api/audience/triggers?brand_id=${encodeURIComponent(brandId)}`,
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(`load failed (${r.status})`)
        return (await r.json()) as TriggersResponse
      })
      .then((data) => {
        if (cancelled) return
        setRules(data.rules ?? [])
        setFires(data.recent_fires ?? [])
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
    const handler = (e: TriggerFire) => {
      if (e.brand_id && e.brand_id !== brandId) return
      setFires((prev) =>
        [
          { ...e, fired_at: e.fired_at ?? new Date().toISOString() },
          ...prev,
        ].slice(0, 50),
      )
    }
    bus.on('campaign.trigger_fired', handler)
    return () => {
      bus.off('campaign.trigger_fired', handler)
    }
  }, [open, brandId])

  const toggle = async (ruleId: string, enabled: boolean) => {
    setRules((prev) =>
      prev.map((r) => (r.id === ruleId ? { ...r, enabled } : r)),
    )
    try {
      const r = await fetch(
        `/api/audience/triggers/${encodeURIComponent(ruleId)}`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled }),
        },
      )
      if (!r.ok) throw new Error(`toggle failed (${r.status})`)
    } catch (e: unknown) {
      // Roll back on failure.
      setRules((prev) =>
        prev.map((r) =>
          r.id === ruleId ? { ...r, enabled: !enabled } : r,
        ),
      )
      setError(e instanceof Error ? e.message : 'toggle failed')
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
            className="fixed right-0 top-0 bottom-0 z-50 flex w-[min(520px,100vw)] flex-col bg-bg shadow-2xl"
          >
            <header className="flex items-center justify-between border-b border-line px-6 py-4">
              <div>
                <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
                  Audience
                </div>
                <h2 className="mt-1 font-serif text-2xl tracking-tight">
                  Triggers
                </h2>
                <p className="mt-1 text-xs text-fg-mute">
                  When a customer hits one of these signals, the AI plans a
                  draft campaign automatically. The human still hits "Send".
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
                  <section>
                    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                      Rules
                    </div>
                    <ul className="mt-3 flex flex-col gap-2">
                      {rules.map((r) => (
                        <li
                          key={r.id}
                          className="flex items-start justify-between gap-3 rounded-xl border border-line bg-bg-card px-4 py-3"
                        >
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-fg">
                              {r.label}
                            </div>
                            <p className="mt-0.5 text-xs text-fg-mute">
                              {r.description}
                            </p>
                            <div className="mt-1 text-[10px] text-fg-dim">
                              debounce: {humanizeDebounce(r.debounce_seconds)}
                            </div>
                          </div>
                          <label className="relative inline-flex shrink-0 cursor-pointer items-center">
                            <input
                              type="checkbox"
                              checked={r.enabled}
                              onChange={(e) =>
                                void toggle(r.id, e.target.checked)
                              }
                              className="peer sr-only"
                            />
                            <span className="block h-5 w-9 rounded-full bg-bg-soft transition peer-checked:bg-accent" />
                            <span className="absolute left-0.5 top-0.5 block h-4 w-4 rounded-full bg-white transition peer-checked:translate-x-4" />
                          </label>
                        </li>
                      ))}
                    </ul>
                    {error && (
                      <div className="mt-2 text-[10px] text-red-500">
                        {error}
                      </div>
                    )}
                  </section>

                  <section className="mt-6">
                    <div className="flex items-baseline justify-between">
                      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                        Recent fires
                      </div>
                      <div className="text-[10px] text-fg-dim">
                        {fires.length} recent
                      </div>
                    </div>
                    {fires.length === 0 ? (
                      <div className="mt-3 rounded-xl border border-dashed border-line px-4 py-3 text-xs text-fg-mute">
                        No fires yet. Enabled rules will draft a campaign the
                        next time a matching signal lands.
                      </div>
                    ) : (
                      <ul className="mt-3 flex flex-col gap-1.5">
                        {fires.map((f, i) => (
                          <li
                            key={`${f.fired_at ?? ''}:${f.customer_id}:${i}`}
                            className="rounded-xl border border-line bg-bg-card px-3 py-2 text-xs"
                          >
                            <div className="flex items-baseline justify-between gap-2">
                              <span className="font-medium text-fg">
                                {f.rule_label || f.rule_id}
                              </span>
                              <span className="text-[10px] text-fg-dim">
                                {formatRelative(f.fired_at)}
                              </span>
                            </div>
                            <div className="mt-0.5 truncate text-[10px] text-fg-dim">
                              customer · {f.customer_id}
                            </div>
                            {f.campaign_id && (
                              <div className="mt-0.5 truncate text-[10px] text-fg-dim">
                                campaign · {f.campaign_id}
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

function humanizeDebounce(sec: number): string {
  if (sec < 60) return `${sec}s`
  if (sec < 3600) return `${Math.round(sec / 60)}m`
  if (sec < 86400) return `${Math.round(sec / 3600)}h`
  return `${Math.round(sec / 86400)}d`
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
