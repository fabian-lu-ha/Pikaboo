import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'motion/react'
import { firstWord, relativeTime } from '../../lib/brandName'

// ─── api shape ─────────────────────────────────────────────────────────────
// Mirrors backend/app/api/campaigns.py CampaignDetail — same response the
// dashboard's restore() flow already consumes, so this drawer reuses the
// route and adds no new endpoints.

type LiftPrediction = {
  lift_percent: number
  confidence: string
  factors: string[]
  target_prompts: string[]
  research_basis: string
}

type Draft = {
  channel: string
  label: string
  kind: string
  title: string
  body: string
  image_url: string | null
  image_aspect: string | null
}

type CampaignBundle = {
  user_request?: string
  drafts?: Draft[]
  blog?: { title: string; body: string }
  social?: { linkedin: string }
  hero_image_url?: string | null
  predicted_lift?: LiftPrediction
  target_prompts?: string[]
}

type CampaignDetail = {
  id: string
  brand_id: string
  title: string
  predicted_lift: number | null
  created_at: string
  bundle: CampaignBundle
}

const CHANNEL_META: Record<string, { label: string; glyph: string }> = {
  linkedin: { label: 'LinkedIn', glyph: 'in' },
  x: { label: 'X', glyph: '✕' },
  twitter: { label: 'X', glyph: '✕' },
  threads: { label: 'Threads', glyph: '@' },
  instagram: { label: 'Instagram', glyph: '◫' },
  'instagram-post': { label: 'Instagram Post', glyph: '◫' },
  'instagram-video': { label: 'Instagram Video', glyph: '▶' },
  'tiktok-reel': { label: 'TikTok Reel', glyph: '◉' },
  tiktok: { label: 'TikTok', glyph: '◉' },
  carousel: { label: 'Carousel', glyph: '◧' },
  blog: { label: 'Blog', glyph: '✎' },
  email: { label: 'Email', glyph: '✉' },
  newsletter: { label: 'Newsletter', glyph: '✉' },
  youtube: { label: 'YouTube', glyph: '▶' },
  hero_image: { label: 'Hero Image', glyph: '◇' },
}

function chMeta(c: string) {
  return CHANNEL_META[c] ?? { label: c, glyph: '◌' }
}

// ─── drawer ────────────────────────────────────────────────────────────────

export function CampaignDetailDrawer({
  campaignId,
  brandName,
  onClose,
  onRestore,
  onDuplicate,
  onDelete,
}: {
  campaignId: string | null
  brandName: string
  onClose: () => void
  onRestore: (id: string) => void
  onDuplicate: (id: string) => void
  onDelete: (id: string) => void
}) {
  const open = !!campaignId
  const [detail, setDetail] = useState<CampaignDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeChannel, setActiveChannel] = useState<string | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  // Wrapped in an async IIFE so the initial setState pass happens on the
  // first microtask, sidestepping React 19's set-state-in-effect lint while
  // still showing the skeleton immediately on open.
  useEffect(() => {
    if (!campaignId) return
    let cancelled = false
    async function loadDetail() {
      setLoading(true)
      setError(null)
      setDetail(null)
      setActiveChannel(null)
      setShowRaw(false)
      try {
        const r = await fetch(
          `/api/campaigns/${encodeURIComponent(campaignId!)}`,
        )
        if (cancelled) return
        if (!r.ok) throw new Error(`status ${r.status}`)
        const d = (await r.json()) as CampaignDetail
        if (cancelled) return
        setDetail(d)
        const first = (d.bundle.drafts ?? [])[0]
        if (first) setActiveChannel(first.channel)
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Network error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void Promise.resolve().then(loadDetail)
    return () => {
      cancelled = true
    }
  }, [campaignId])

  // Esc to close.
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  function copyText(key: string, text: string) {
    void navigator.clipboard.writeText(text).then(() => {
      setCopied(key)
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1400)
    })
  }

  function exportJson() {
    if (!detail) return
    const blob = new Blob([JSON.stringify(detail, null, 2)], {
      type: 'application/json',
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${detail.title.replace(/[^a-z0-9-]+/gi, '-').toLowerCase()}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="drawer-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.18 }}
          className="fixed inset-0 z-50 flex justify-end bg-black/30 backdrop-blur-[2px]"
          onClick={onClose}
        >
          <motion.aside
            key="drawer-panel"
            role="dialog"
            aria-modal="true"
            aria-label="Campaign detail"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            className="relative flex h-full w-full max-w-[640px] flex-col bg-bg shadow-[-12px_0_40px_rgba(20,20,40,0.18)]"
            onClick={(e) => e.stopPropagation()}
          >
            <DrawerHeader
              detail={detail}
              loading={loading}
              brandName={brandName}
              onClose={onClose}
            />

            <div className="flex-1 overflow-y-auto px-6 pb-8">
              {loading && !detail && <DrawerSkeleton />}
              {error && !loading && (
                <div className="panel mt-6 flex flex-col items-center gap-3 px-6 py-12 text-center">
                  <span className="grid h-10 w-10 place-items-center rounded-full bg-red-50 text-red-600">
                    ⚠
                  </span>
                  <div className="text-[14px] font-semibold">Couldn't load campaign</div>
                  <div className="max-w-md text-[12.5px] text-fg-mute">{error}</div>
                </div>
              )}
              {detail && (
                <DrawerBody
                  detail={detail}
                  activeChannel={activeChannel}
                  setActiveChannel={setActiveChannel}
                  showRaw={showRaw}
                  setShowRaw={setShowRaw}
                  copied={copied}
                  copyText={copyText}
                />
              )}
            </div>

            {detail && (
              <DrawerFooter
                onRestore={() => onRestore(detail.id)}
                onDuplicate={() => onDuplicate(detail.id)}
                onDelete={() => {
                  if (confirm('Delete this campaign? This cannot be undone.')) {
                    onDelete(detail.id)
                  }
                }}
                onExport={exportJson}
              />
            )}
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  )
}

// ─── header ────────────────────────────────────────────────────────────────

function DrawerHeader({
  detail,
  loading,
  brandName,
  onClose,
}: {
  detail: CampaignDetail | null
  loading: boolean
  brandName: string
  onClose: () => void
}) {
  return (
    <header className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-line bg-bg/95 px-6 py-4 backdrop-blur-md">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[10.5px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          <span>Campaign · {firstWord(brandName)}</span>
          {detail && (
            <span className="hairline rounded-full bg-bg-card px-2 py-0.5 text-[10px] normal-case tracking-normal text-fg-mute">
              {relativeTime(new Date(detail.created_at).getTime())}
            </span>
          )}
        </div>
        <h2 className="mt-1 truncate text-[18px] font-semibold leading-snug">
          {detail?.title ?? (loading ? 'Loading…' : 'Campaign')}
        </h2>
      </div>
      <button
        onClick={onClose}
        aria-label="Close"
        className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-fg-mute hover:bg-bg-soft hover:text-fg"
      >
        ✕
      </button>
    </header>
  )
}

function DrawerSkeleton() {
  return (
    <div className="space-y-4 pt-6">
      <div className="h-32 animate-pulse rounded-xl bg-bg-soft" />
      <div className="h-20 animate-pulse rounded-xl bg-bg-soft" />
      <div className="h-40 animate-pulse rounded-xl bg-bg-soft" />
    </div>
  )
}

// ─── body ──────────────────────────────────────────────────────────────────

function DrawerBody({
  detail,
  activeChannel,
  setActiveChannel,
  showRaw,
  setShowRaw,
  copied,
  copyText,
}: {
  detail: CampaignDetail
  activeChannel: string | null
  setActiveChannel: (c: string | null) => void
  showRaw: boolean
  setShowRaw: (b: boolean) => void
  copied: string | null
  copyText: (key: string, text: string) => void
}) {
  const bundle = detail.bundle
  const drafts = bundle.drafts ?? []
  const lift =
    bundle.predicted_lift ??
    (detail.predicted_lift != null
      ? {
          lift_percent: detail.predicted_lift,
          confidence: 'estimated',
          factors: [],
          target_prompts: bundle.target_prompts ?? [],
          research_basis: '',
        }
      : null)
  const active = drafts.find((d) => d.channel === activeChannel) ?? drafts[0] ?? null

  return (
    <div className="space-y-6 pt-6">
      {bundle.hero_image_url && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.32 }}
          className="relative overflow-hidden rounded-2xl bg-bg-soft"
        >
          <img
            src={bundle.hero_image_url}
            alt=""
            className="block w-full object-cover"
          />
        </motion.div>
      )}

      {bundle.user_request && (
        <section>
          <Label>Original prompt</Label>
          <p className="mt-2 rounded-2xl bg-accent-soft px-4 py-3 text-[13.5px] leading-relaxed text-fg">
            {bundle.user_request}
          </p>
        </section>
      )}

      {lift && <LiftBlock lift={lift} />}

      {drafts.length > 0 && (
        <section>
          <div className="flex items-center justify-between">
            <Label>Drafts · {drafts.length}</Label>
            {active && (
              <button
                onClick={() =>
                  copyText(`draft-${active.channel}`, formatDraftForCopy(active))
                }
                className="hairline rounded-full bg-bg-card px-2.5 py-1 text-[11px] font-medium text-fg-mute hover:text-fg"
              >
                {copied === `draft-${active.channel}` ? '✓ Copied' : 'Copy draft'}
              </button>
            )}
          </div>

          <div className="mt-3 flex flex-wrap gap-1.5">
            {drafts.map((d) => {
              const m = chMeta(d.channel)
              const isActive = d.channel === active?.channel
              return (
                <button
                  key={d.channel}
                  onClick={() => setActiveChannel(d.channel)}
                  className={`flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-medium transition ${
                    isActive
                      ? 'bg-accent text-white shadow-[0_4px_12px_rgba(91,80,230,0.35)]'
                      : 'hairline bg-bg-card text-fg-mute hover:text-fg'
                  }`}
                >
                  <span>{m.glyph}</span>
                  {m.label}
                </button>
              )
            })}
          </div>

          {active && (
            <motion.article
              key={active.channel}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22 }}
              className="panel mt-4 overflow-hidden"
            >
              {active.image_url && (
                <div className="bg-bg-soft">
                  <img
                    src={active.image_url}
                    alt=""
                    className="block w-full object-cover"
                  />
                </div>
              )}
              <div className="px-5 py-4">
                {active.title && (
                  <h3 className="text-[15px] font-semibold leading-snug tracking-[-0.01em]">
                    {active.title}
                  </h3>
                )}
                <p className="mt-2 whitespace-pre-wrap text-[13px] leading-relaxed text-fg">
                  {active.body}
                </p>
              </div>
            </motion.article>
          )}
        </section>
      )}

      {bundle.blog?.body && (
        <section>
          <Label>Blog post</Label>
          <article className="panel mt-3 px-5 py-4">
            <h3 className="text-[15px] font-semibold leading-snug tracking-[-0.01em]">
              {bundle.blog.title}
            </h3>
            <div className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap text-[13px] leading-relaxed text-fg [scrollbar-width:thin]">
              {bundle.blog.body}
            </div>
            <div className="mt-3 flex justify-end">
              <button
                onClick={() => copyText('blog', `${bundle.blog?.title}\n\n${bundle.blog?.body}`)}
                className="hairline rounded-full bg-bg-card px-2.5 py-1 text-[11px] font-medium text-fg-mute hover:text-fg"
              >
                {copied === 'blog' ? '✓ Copied' : 'Copy blog'}
              </button>
            </div>
          </article>
        </section>
      )}

      <section>
        <button
          onClick={() => setShowRaw(!showRaw)}
          className="flex items-center gap-2 text-[11.5px] font-medium uppercase tracking-[0.16em] text-fg-mute hover:text-fg"
        >
          <span>{showRaw ? '▾' : '▸'}</span>
          Raw bundle JSON
        </button>
        {showRaw && (
          <pre className="mt-3 max-h-80 overflow-auto rounded-xl bg-fg p-4 text-[11px] leading-relaxed text-[#dde0f3] [scrollbar-width:thin]">
            {JSON.stringify(bundle, null, 2)}
          </pre>
        )}
      </section>
    </div>
  )
}

function LiftBlock({ lift }: { lift: LiftPrediction }) {
  const sign = lift.lift_percent >= 0 ? '+' : ''
  const color =
    lift.lift_percent >= 25
      ? '#1f9e6e'
      : lift.lift_percent >= 10
        ? '#5b50e6'
        : lift.lift_percent >= 0
          ? '#d97a3a'
          : '#d44a6a'
  // Bar fill is normalized so a lift of 50% reaches the midpoint of the
  // bar and 100% fills it — clamped so weird outliers don't blow it out.
  const fill = Math.max(2, Math.min(100, Math.abs(lift.lift_percent) * 2))
  return (
    <section className="panel relative overflow-hidden p-5">
      <Label>Predicted lift</Label>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div
          className="text-[34px] font-semibold leading-none tracking-[-0.02em]"
          style={{ color }}
        >
          {sign}
          {lift.lift_percent.toFixed(1)}%
        </div>
        {lift.confidence && (
          <span className="hairline rounded-full bg-bg-card px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.12em] text-fg-mute">
            {lift.confidence}
          </span>
        )}
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-bg-soft">
        <div
          className="h-full rounded-full transition-[width]"
          style={{ width: `${fill}%`, background: color }}
        />
      </div>
      {lift.factors.length > 0 && (
        <ul className="mt-4 space-y-1.5 text-[12.5px] leading-relaxed text-fg">
          {lift.factors.map((f, i) => (
            <li key={i} className="flex items-start gap-2">
              <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
              {f}
            </li>
          ))}
        </ul>
      )}
      {lift.target_prompts.length > 0 && (
        <div className="mt-4">
          <div className="text-[10.5px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Target prompts
          </div>
          <ul className="mt-2 space-y-1.5 text-[12.5px] leading-snug text-fg-mute">
            {lift.target_prompts.slice(0, 5).map((t, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-[3px] text-fg-dim">›</span>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}
      {lift.research_basis && (
        <div className="mt-4 rounded-lg bg-bg-soft px-3 py-2 text-[11.5px] italic leading-relaxed text-fg-mute">
          {lift.research_basis}
        </div>
      )}
    </section>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
      {children}
    </div>
  )
}

function formatDraftForCopy(d: Draft): string {
  const head = d.title ? `${d.title}\n\n` : ''
  return `${head}${d.body}`
}

// ─── footer ────────────────────────────────────────────────────────────────

function DrawerFooter({
  onRestore,
  onDuplicate,
  onDelete,
  onExport,
}: {
  onRestore: () => void
  onDuplicate: () => void
  onDelete: () => void
  onExport: () => void
}) {
  return (
    <footer className="sticky bottom-0 z-10 flex flex-wrap items-center justify-between gap-2 border-t border-line bg-bg/95 px-6 py-3 backdrop-blur-md">
      <div className="flex items-center gap-1.5">
        <button
          onClick={onDuplicate}
          className="hairline flex items-center gap-1.5 rounded-full bg-bg-card px-3 py-1.5 text-[12px] font-medium text-fg hover:border-accent"
          title="Clone this campaign as a new entry"
        >
          ⎘ Duplicate
        </button>
        <button
          onClick={onExport}
          className="hairline flex items-center gap-1.5 rounded-full bg-bg-card px-3 py-1.5 text-[12px] font-medium text-fg hover:border-accent"
          title="Download bundle as JSON"
        >
          ↓ Export
        </button>
        <button
          onClick={onDelete}
          className="hairline flex items-center gap-1.5 rounded-full bg-bg-card px-3 py-1.5 text-[12px] font-medium text-red-600 hover:bg-red-50"
        >
          ⌫ Delete
        </button>
      </div>
      <button
        onClick={onRestore}
        className="flex items-center gap-1.5 rounded-full bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_6px_18px_rgba(91,80,230,0.45)] hover:brightness-110"
      >
        ↺ Restore in dashboard
      </button>
    </footer>
  )
}
