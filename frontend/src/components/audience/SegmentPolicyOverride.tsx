import { useEffect, useState } from 'react'
import { OfferPolicyEditor } from './OfferPolicyEditor'
import { DEFAULT_OFFER_POLICY, type OfferPolicy } from '../../lib/audience'

type Props = {
  brandId: string
  segmentId: string
}

type OverrideResponse = {
  override: Partial<OfferPolicy>
  effective: OfferPolicy
}

export function SegmentPolicyOverride({ brandId, segmentId }: Props) {
  const [enabled, setEnabled] = useState(false)
  const [override, setOverride] = useState<Partial<OfferPolicy>>({})
  const [effective, setEffective] = useState<OfferPolicy>(DEFAULT_OFFER_POLICY)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch(
      `/api/audience/segments/${encodeURIComponent(
        segmentId,
      )}/offer-policy-override`,
    )
      .then(async (r) => {
        if (!r.ok) throw new Error(`load failed (${r.status})`)
        return (await r.json()) as OverrideResponse
      })
      .then((data) => {
        if (cancelled) return
        const ov = data.override ?? {}
        setOverride(ov)
        setEnabled(Object.keys(ov).length > 0)
        setEffective(data.effective ?? DEFAULT_OFFER_POLICY)
      })
      .catch((e: unknown) => {
        if (cancelled) return
        setError(e instanceof Error ? e.message : 'load failed')
      })
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [segmentId, brandId])

  const save = async (next: Partial<OfferPolicy>) => {
    setSaving(true)
    setError(null)
    try {
      const r = await fetch(
        `/api/audience/segments/${encodeURIComponent(
          segmentId,
        )}/offer-policy-override`,
        {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ override: next }),
        },
      )
      if (!r.ok) throw new Error(`save failed (${r.status})`)
      const data = (await r.json()) as OverrideResponse
      setOverride(data.override ?? {})
      setEffective(data.effective ?? DEFAULT_OFFER_POLICY)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'save failed')
    } finally {
      setSaving(false)
    }
  }

  const toggle = (next: boolean) => {
    setEnabled(next)
    if (!next) {
      void save({})
      setOverride({})
    }
  }

  return (
    <section>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Offer policy override
          </div>
          <p className="mt-1 text-xs text-fg-mute">
            Loosen or tighten the brand's envelope for this segment only.
            VIPs can earn higher discounts; new buyers can be capped.
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-2 text-xs text-fg">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => toggle(e.target.checked)}
            className="h-4 w-4 accent-accent"
          />
          <span>{enabled ? 'enabled' : 'inherit brand'}</span>
        </label>
      </div>
      {enabled && (
        <div className="mt-3 rounded-2xl border border-line bg-bg-card p-4">
          {loading ? (
            <div className="text-xs text-fg-mute">loading…</div>
          ) : (
            <OfferPolicyEditor
              value={override}
              onChange={(next) => {
                setOverride(next)
                void save(next)
              }}
              defaults={effective}
              compact
            />
          )}
          {saving && (
            <div className="mt-2 text-[10px] text-fg-dim">saving…</div>
          )}
          {error && (
            <div className="mt-2 text-[10px] text-red-500">{error}</div>
          )}
        </div>
      )}
    </section>
  )
}
