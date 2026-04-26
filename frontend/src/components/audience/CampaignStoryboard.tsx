import { useEffect, useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import { bus } from '../../events/bus'
import {
  TOUCH_KIND_GLYPHS,
  TOUCH_KIND_LABELS,
  type Campaign,
  type CampaignTouch,
  type Offer,
  type PolicyClamp,
  type Product,
} from '../../lib/audience'
import { PIIShield } from './PIIShield'

type Props = {
  brandId: string
  /** Either customerId or segmentId is required, depending on targetKind. */
  targetKind: 'customer' | 'segment'
  targetId: string
  /** What recipient label to show (e.g. customer name, "12 recipients"). */
  recipientLabel: string
  /** Used by SegmentCampaignBlock to display merge-tag previews. */
  showMergeTags?: boolean
}

type PlanResponse = Campaign & {
  campaign_id?: string
  offer_id?: string
}

type RenderResponse = {
  video_url: string
  audio_url: string | null
  voice_model_id: string | null
  status: string
}

type LaunchResponse = {
  campaign_id: string
  status: string
  first_touch_id: string | null
}

export function CampaignStoryboard({
  brandId,
  targetKind,
  targetId,
  recipientLabel,
  showMergeTags,
}: Props) {
  const products = useAudienceStore((s) => s.products)

  const [planning, setPlanning] = useState(false)
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [angle, setAngle] = useState('')
  const [trigger, setTrigger] = useState<string>('manual')
  const [error, setError] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)
  const [toast, setToast] = useState<string | null>(null)

  // touch_id → render state
  const [renderState, setRenderState] = useState<
    Record<
      string,
      | { status: 'idle' }
      | { status: 'rendering' }
      | { status: 'ready'; video_url: string; voice_model_id: string | null }
      | { status: 'failed'; error: string }
    >
  >({})

  // Listen for video render events on the bus to flip state.
  useEffect(() => {
    function onRendering(p: { touch_id: string }) {
      setRenderState((s) => ({ ...s, [p.touch_id]: { status: 'rendering' } }))
    }
    function onRendered(p: {
      touch_id: string
      video_url: string
      voice_model_id: string | null
    }) {
      setRenderState((s) => ({
        ...s,
        [p.touch_id]: {
          status: 'ready',
          video_url: p.video_url,
          voice_model_id: p.voice_model_id,
        },
      }))
    }
    function onFailed(p: { touch_id: string; error: string }) {
      setRenderState((s) => ({
        ...s,
        [p.touch_id]: { status: 'failed', error: p.error },
      }))
    }
    bus.on('campaign.video_rendering', onRendering)
    bus.on('campaign.video_rendered', onRendered)
    bus.on('campaign.video_render_failed', onFailed)
    return () => {
      bus.off('campaign.video_rendering', onRendering)
      bus.off('campaign.video_rendered', onRendered)
      bus.off('campaign.video_render_failed', onFailed)
    }
  }, [])

  // Reset state when target changes.
  useEffect(() => {
    setCampaign(null)
    setRenderState({})
    setError(null)
  }, [targetKind, targetId])

  function flash(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 1800)
  }

  async function generate() {
    setPlanning(true)
    setError(null)
    bus.emit('campaign.planning', {
      brand_id: brandId,
      target_kind: targetKind,
      target_id: targetId,
      trigger: trigger || null,
    })
    try {
      const res = await fetch('/api/audience/campaigns/plan', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          brand_id: brandId,
          target_kind: targetKind,
          target_id: targetId,
          trigger: trigger || undefined,
          user_prompt: angle.trim() || undefined,
        }),
      })
      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`${res.status}: ${text.slice(0, 120)}`)
      }
      const data = (await res.json()) as PlanResponse
      // Be flexible about API shape: some fields may live at top-level.
      const id = data.id ?? data.campaign_id ?? ''
      setCampaign({ ...data, id })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'plan failed')
    } finally {
      setPlanning(false)
    }
  }

  async function renderVideo(touch: CampaignTouch) {
    if (!campaign) return
    setRenderState((s) => ({ ...s, [touch.id]: { status: 'rendering' } }))
    bus.emit('campaign.video_rendering', {
      brand_id: brandId,
      campaign_id: campaign.id,
      touch_id: touch.id,
      voice_model_id: touch.voice_model_id ?? null,
    })
    try {
      const res = await fetch(
        `/api/audience/touches/${encodeURIComponent(touch.id)}/render-video`,
        {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({}),
        },
      )
      if (!res.ok) throw new Error(`${res.status}`)
      const data = (await res.json()) as RenderResponse
      bus.emit('campaign.video_rendered', {
        brand_id: brandId,
        campaign_id: campaign.id,
        touch_id: touch.id,
        video_url: data.video_url,
        audio_url: data.audio_url,
        voice_model_id: data.voice_model_id,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'render failed'
      bus.emit('campaign.video_render_failed', {
        brand_id: brandId,
        campaign_id: campaign.id,
        touch_id: touch.id,
        error: msg,
      })
    }
  }

  async function launch() {
    if (!campaign) return
    setLaunching(true)
    try {
      const res = await fetch(
        `/api/audience/campaigns/${encodeURIComponent(campaign.id)}/launch`,
        { method: 'POST' },
      )
      if (!res.ok) throw new Error(`${res.status}`)
      const data = (await res.json()) as LaunchResponse
      flash('campaign launched')
      setCampaign((c) =>
        c ? { ...c, status: (data.status as Campaign['status']) ?? 'scheduled' } : c,
      )
    } catch (err) {
      flash(err instanceof Error ? err.message : 'launch failed')
    } finally {
      setLaunching(false)
    }
  }

  return (
    <div className="relative rounded-2xl border border-line bg-bg-card px-5 py-4 shadow-[0_2px_10px_rgba(20,20,40,0.03)]">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          {targetKind === 'customer' ? '1:1 Campaign' : 'Group campaign'}
        </div>
        <span className="text-[11px] text-fg-dim">to {recipientLabel}</span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-[1fr_auto]">
        <textarea
          value={angle}
          onChange={(e) => setAngle(e.target.value)}
          rows={2}
          placeholder="What should this sequence accomplish? (optional — e.g. win-back, new launch in their top category)"
          className="block w-full resize-none rounded-xl border border-line bg-bg-card px-3 py-2 text-sm outline-none placeholder:text-fg-dim focus:border-accent"
        />
        <select
          value={trigger}
          onChange={(e) => setTrigger(e.target.value)}
          className="rounded-xl border border-line bg-bg-card px-3 py-2 text-xs text-fg-mute outline-none focus:border-accent sm:self-start"
          aria-label="Trigger"
        >
          <option value="manual">manual</option>
          <option value="cart_abandoned">cart abandoned</option>
          <option value="subscription_lapsed">subscription lapsed</option>
          <option value="new_arrival_in_category">new arrival</option>
        </select>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          onClick={generate}
          disabled={planning}
          className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          {planning ? 'planning…' : campaign ? 'regenerate' : 'Generate'}
        </button>
        {campaign?.redaction_summary && (
          <PIIShield
            count={campaign.redaction_summary.entity_count}
            types={campaign.redaction_summary.types}
          />
        )}
        {campaign?.policy_clamps && campaign.policy_clamps.length > 0 && (
          <PolicyClampBadge clamps={campaign.policy_clamps} />
        )}
        {error && (
          <span className="text-[11px] text-red-600">· {error}</span>
        )}
      </div>

      {planning && !campaign && <PlanShimmer />}

      <AnimatePresence>
        {campaign && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-4 flex flex-col gap-4 lg:flex-row"
          >
            {/* Left: touches strip */}
            <div className="min-w-0 flex-1">
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                Storyboard · {campaign.touches.length} touch
                {campaign.touches.length === 1 ? '' : 'es'}
              </div>
              <div className="mt-2 -mx-1 flex gap-3 overflow-x-auto px-1 pb-2 [scrollbar-width:thin]">
                {campaign.touches.map((t) => (
                  <TouchCard
                    key={t.id}
                    touch={t}
                    total={campaign.touches.length}
                    showMergeTags={showMergeTags ?? targetKind === 'segment'}
                    renderState={renderState[t.id] ?? { status: 'idle' }}
                    onPlay={() => renderVideo(t)}
                  />
                ))}
              </div>
            </div>

            {/* Right rail: offer */}
            {campaign.offer && (
              <div className="lg:w-[260px] lg:shrink-0">
                <OfferCard offer={campaign.offer} products={products} />
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {campaign && (
        <div className="mt-4 flex items-center justify-end gap-2">
          {campaign.status && campaign.status !== 'draft' && (
            <span className="rounded-full border border-line bg-bg-soft px-2.5 py-1 text-[10px] uppercase tracking-[0.14em] text-fg-mute">
              {campaign.status}
            </span>
          )}
          <button
            onClick={launch}
            disabled={launching || campaign.status === 'sending' || campaign.status === 'done'}
            className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
          >
            {launching ? 'launching…' : 'Send all'}
          </button>
        </div>
      )}

      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="pointer-events-none absolute -top-9 right-3 rounded-md bg-fg/90 px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-bg"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

function PlanShimmer() {
  return (
    <div className="mt-4 flex gap-3 overflow-hidden">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-44 w-56 shrink-0 animate-pulse rounded-xl border border-line bg-bg-soft/60"
        />
      ))}
    </div>
  )
}

function TouchCard({
  touch,
  total,
  showMergeTags,
  renderState,
  onPlay,
}: {
  touch: CampaignTouch
  total: number
  showMergeTags: boolean
  renderState:
    | { status: 'idle' }
    | { status: 'rendering' }
    | { status: 'ready'; video_url: string; voice_model_id: string | null }
    | { status: 'failed'; error: string }
  onPlay: () => void
}) {
  return (
    <div className="flex h-auto w-64 shrink-0 flex-col rounded-xl border border-line bg-bg p-3">
      <div className="flex items-center justify-between">
        <span className="rounded-full border border-line bg-bg-card px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-mute">
          {touch.step_index + 1}/{total}
        </span>
        <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-[0.14em] text-fg-dim">
          <span className="text-accent">{TOUCH_KIND_GLYPHS[touch.kind]}</span>
          {TOUCH_KIND_LABELS[touch.kind]}
        </span>
      </div>

      {touch.kind === 'email' && (
        <EmailTouchBody touch={touch} showMergeTags={showMergeTags} />
      )}
      {touch.kind === 'video' && (
        <VideoTouchBody
          touch={touch}
          renderState={renderState}
          onPlay={onPlay}
        />
      )}
      {touch.kind === 'landing' && (
        <LandingTouchBody touch={touch} showMergeTags={showMergeTags} />
      )}
    </div>
  )
}

function MaybeMergeTagged({
  text,
  showMergeTags,
}: {
  text: string | null | undefined
  showMergeTags: boolean
}) {
  if (!text) return null
  if (!showMergeTags) return <>{text}</>
  // Highlight {customer_name} placeholders in segment previews.
  const parts = text.split(/(\{customer_name\})/g)
  return (
    <>
      {parts.map((p, i) =>
        p === '{customer_name}' ? (
          <span
            key={i}
            className="rounded bg-accent/10 px-1 text-[11px] font-medium text-accent"
          >
            {p}
          </span>
        ) : (
          <span key={i}>{p}</span>
        ),
      )}
    </>
  )
}

function EmailTouchBody({
  touch,
  showMergeTags,
}: {
  touch: CampaignTouch
  showMergeTags: boolean
}) {
  return (
    <div className="mt-2 flex min-h-0 flex-1 flex-col gap-1.5">
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
        Subject
      </div>
      <div className="line-clamp-2 text-xs font-medium text-fg">
        <MaybeMergeTagged text={touch.subject} showMergeTags={showMergeTags} />
      </div>
      <div className="mt-1 line-clamp-4 text-[11px] leading-snug text-fg-mute">
        <MaybeMergeTagged text={touch.body} showMergeTags={showMergeTags} />
      </div>
    </div>
  )
}

function VideoTouchBody({
  touch,
  renderState,
  onPlay,
}: {
  touch: CampaignTouch
  renderState:
    | { status: 'idle' }
    | { status: 'rendering' }
    | { status: 'ready'; video_url: string; voice_model_id: string | null }
    | { status: 'failed'; error: string }
  onPlay: () => void
}) {
  const voiceLabel = useMemo(() => {
    const id = touch.voice_model_id
    if (!id) return 'Default voice — brand voice training'
    return `Brand voice · ${id.slice(0, 8)}`
  }, [touch.voice_model_id])

  return (
    <div className="mt-2 flex min-h-0 flex-1 flex-col gap-1.5">
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
        Voiceover script
      </div>
      <div className="line-clamp-4 text-[11px] leading-snug text-fg-mute">
        {touch.voiceover_script ?? '—'}
      </div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.14em] text-fg-dim">
        {voiceLabel}
      </div>
      <div className="mt-2">
        {renderState.status === 'rendering' ? (
          <div className="flex h-9 items-center justify-center rounded-full bg-bg-soft text-[11px] uppercase tracking-[0.14em] text-fg-mute">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            <span className="ml-2">rendering…</span>
          </div>
        ) : renderState.status === 'ready' ? (
          <video
            src={renderState.video_url}
            controls
            className="h-28 w-full rounded-md border border-line bg-black object-cover"
          />
        ) : renderState.status === 'failed' ? (
          <button
            onClick={onPlay}
            className="w-full rounded-full border border-red-300 bg-red-50 px-3 py-2 text-[11px] uppercase tracking-[0.14em] text-red-600 transition hover:bg-red-100"
          >
            retry render
          </button>
        ) : (
          <button
            onClick={onPlay}
            className="w-full rounded-full bg-accent px-3 py-2 text-[11px] font-medium uppercase tracking-[0.14em] text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110"
          >
            ▶ Play
          </button>
        )}
      </div>
    </div>
  )
}

function LandingTouchBody({
  touch,
  showMergeTags,
}: {
  touch: CampaignTouch
  showMergeTags: boolean
}) {
  return (
    <div className="mt-2 flex min-h-0 flex-1 flex-col gap-1.5">
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
        Headline
      </div>
      <div className="line-clamp-2 font-serif text-base leading-tight tracking-tight">
        <MaybeMergeTagged text={touch.headline} showMergeTags={showMergeTags} />
      </div>
      <div className="mt-1 line-clamp-5 text-[11px] leading-snug text-fg-mute">
        <MaybeMergeTagged text={touch.body} showMergeTags={showMergeTags} />
      </div>
    </div>
  )
}

function OfferCard({ offer, products }: { offer: Offer; products: Product[] }) {
  const offerProducts = useMemo(
    () =>
      offer.product_ids
        .map((id) => products.find((p) => p.id === id))
        .filter((p): p is Product => !!p),
    [offer.product_ids, products],
  )

  const expiresLabel = offer.expires_at
    ? new Date(offer.expires_at).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      })
    : '—'

  const ruleLabel = formatRule(offer)

  return (
    <div className="rounded-xl border border-line bg-bg p-3">
      <div className="flex items-center justify-between">
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Offer
        </div>
        {offer.policy_clamps && offer.policy_clamps.length > 0 && (
          <PolicyClampBadge clamps={offer.policy_clamps} compact />
        )}
      </div>

      <div className="mt-2 flex flex-col gap-2">
        {offerProducts.length > 0 ? (
          offerProducts.map((p) => (
            <div
              key={p.id}
              className="flex items-center gap-2 rounded-lg bg-bg-soft/40 p-1.5"
            >
              {p.image_url ? (
                <img
                  src={p.image_url}
                  alt=""
                  className="h-10 w-10 rounded-md border border-line bg-white object-cover"
                />
              ) : (
                <div className="h-10 w-10 rounded-md border border-line bg-bg-card" />
              )}
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium">{p.name}</div>
                {p.category && (
                  <div className="truncate text-[10px] uppercase tracking-[0.14em] text-fg-dim">
                    {p.category}
                  </div>
                )}
              </div>
            </div>
          ))
        ) : (
          <div className="rounded-lg border border-dashed border-line px-2 py-1.5 text-[11px] text-fg-mute">
            no catalog match
          </div>
        )}
      </div>

      <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-fg-dim">
            Discount
          </div>
          <div className="mt-0.5 font-medium">{ruleLabel}</div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.14em] text-fg-dim">
            Expires
          </div>
          <div className="mt-0.5 font-medium">{expiresLabel}</div>
        </div>
      </div>

      {offer.reasoning && (
        <div className="mt-3 rounded-lg bg-bg-soft/60 px-2.5 py-1.5 text-[11px] leading-snug text-fg-mute">
          {offer.reasoning}
        </div>
      )}
      {offer.why_ours && (
        <div className="mt-2 text-[11px] italic leading-snug text-fg-mute">
          {offer.why_ours}
        </div>
      )}
    </div>
  )
}

function formatRule(offer: Offer): string {
  const r = offer.rule
  if (!r || !r.discount_type) return '—'
  switch (r.discount_type) {
    case 'percent':
      return `${r.discount_value ?? 0}% off`
    case 'fixed_amount':
      return `€${((r.discount_value ?? 0) / 100).toFixed(0)} off`
    case 'free_shipping':
      return 'Free shipping'
    case 'bogo':
      return 'BOGO'
    default:
      return String(r.discount_type)
  }
}

function PolicyClampBadge({
  clamps,
  compact,
}: {
  clamps: PolicyClamp[]
  compact?: boolean
}) {
  const [hover, setHover] = useState(false)
  if (clamps.length === 0) return null
  return (
    <span
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      tabIndex={0}
      onFocus={() => setHover(true)}
      onBlur={() => setHover(false)}
      className={`relative inline-flex items-center gap-1 rounded-full border border-amber-300/60 bg-amber-50 ${
        compact ? 'px-2 py-0.5' : 'px-2.5 py-1'
      } text-[10px] font-medium uppercase tracking-[0.16em] text-amber-700`}
    >
      <span aria-hidden>⚠</span>
      {clamps.length} field{clamps.length === 1 ? '' : 's'} clamped
      <AnimatePresence>
        {hover && (
          <motion.span
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15 }}
            role="tooltip"
            className="pointer-events-none absolute right-0 top-full z-30 mt-2 w-64 rounded-xl border border-line bg-bg-card px-3 py-2.5 text-left text-[11px] normal-case tracking-normal text-fg-mute shadow-[0_8px_24px_rgba(20,20,40,0.08)]"
          >
            <div className="mb-1.5 font-medium text-fg">
              Policy validator clamped {clamps.length} field
              {clamps.length === 1 ? '' : 's'}
            </div>
            <ul className="flex flex-col gap-1.5">
              {clamps.slice(0, 5).map((c, i) => (
                <li key={i} className="leading-snug">
                  <span className="font-medium text-fg">{c.field}</span>:{' '}
                  <span className="line-through text-fg-dim">
                    {String(c.proposed)}
                  </span>{' '}
                  → <span className="text-fg">{String(c.clamped)}</span>
                  {c.reason && (
                    <div className="text-[10px] text-fg-dim">{c.reason}</div>
                  )}
                </li>
              ))}
            </ul>
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}
