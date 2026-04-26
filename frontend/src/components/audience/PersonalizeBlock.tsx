import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import { PIIShield } from './PIIShield'
import type { PersonalizedEmail, Product } from '../../lib/audience'

type Props = {
  brandId: string
  targetKind: 'customer' | 'segment'
  targetId: string
  recipientLabel: string
  onDispatched?: () => void
}

export function PersonalizeBlock({
  brandId,
  targetKind,
  targetId,
  recipientLabel,
  onDispatched,
}: Props) {
  const personalize = useAudienceStore((s) => s.personalize)
  const dispatch = useAudienceStore((s) => s.dispatch)
  const personalizing = useAudienceStore((s) => s.personalizing)
  const products = useAudienceStore((s) => s.products)

  const [angle, setAngle] = useState('')
  const [result, setResult] = useState<PersonalizedEmail | null>(null)
  const [editedSubject, setEditedSubject] = useState('')
  const [editedBody, setEditedBody] = useState('')
  const [toast, setToast] = useState<string | null>(null)
  const [dispatching, setDispatching] = useState(false)

  function flash(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 1800)
  }

  async function generate() {
    const r = await personalize(brandId, targetKind, targetId, angle.trim() || undefined)
    if (r) {
      setResult(r)
      setEditedSubject(r.subject)
      setEditedBody(r.body)
    } else {
      flash('generation failed')
    }
  }

  async function send() {
    if (!result) return
    setDispatching(true)
    const out = await dispatch(
      brandId,
      targetKind,
      targetId,
      editedSubject,
      editedBody,
      result.html_body,
    )
    setDispatching(false)
    if (out.ok) {
      flash('queued for send')
      onDispatched?.()
    } else {
      flash('dispatch failed')
    }
  }

  return (
    <div className="relative rounded-2xl border border-line bg-bg-card px-5 py-4 shadow-[0_2px_10px_rgba(20,20,40,0.03)]">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Personalize email
        </div>
        <span className="text-[11px] text-fg-dim">
          to {recipientLabel}
        </span>
      </div>

      <textarea
        value={angle}
        onChange={(e) => setAngle(e.target.value)}
        rows={2}
        placeholder="What angle? (optional — e.g. win-back, new feature, thank-you)"
        className="mt-3 block w-full resize-none rounded-xl border border-line bg-bg-card px-3 py-2 text-sm outline-none placeholder:text-fg-dim focus:border-accent"
      />

      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={generate}
          disabled={personalizing}
          className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          {personalizing ? 'generating…' : result ? 'regenerate' : 'generate'}
        </button>
        {result && (
          <PIIShield
            count={result.redaction_summary.entity_count}
            types={result.redaction_summary.types}
          />
        )}
        {result &&
          typeof result.competitor_catalog_size === 'number' &&
          result.competitor_catalog_size > 0 && (
            <span
              className="rounded-full border border-line bg-bg-soft px-2.5 py-1 text-[10px] uppercase tracking-[0.14em] text-fg-mute"
              title="Competitor catalog factored into the brief"
            >
              {result.competitor_catalog_size} competitor product
              {result.competitor_catalog_size === 1 ? '' : 's'} considered
            </span>
          )}
      </div>

      <AnimatePresence>
        {result && (
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.3 }}
            className="mt-4 space-y-3"
          >
            <div>
              <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                Subject
              </div>
              <input
                value={editedSubject}
                onChange={(e) => setEditedSubject(e.target.value)}
                className="mt-1 block w-full rounded-md border border-line bg-bg-card px-3 py-2 text-sm font-medium outline-none focus:border-accent"
              />
            </div>
            <BodyTabs
              htmlBody={result.html_body}
              editedBody={editedBody}
              setEditedBody={setEditedBody}
            />
            <p className="-mt-1 text-[10px] text-fg-dim">
              HTML preview reflects the last generation. Edit the plain body
              and regenerate to refresh the HTML.
            </p>

            {result.recommended_product_ids.length > 0 && (
              <RecommendedProducts
                products={products}
                ids={result.recommended_product_ids}
              />
            )}

            {result.reasoning && (
              <div className="rounded-xl bg-bg-soft/60 px-3 py-2 text-[11px] leading-snug text-fg-mute">
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
                  Why this works ·{' '}
                </span>
                {result.reasoning}
              </div>
            )}

            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                onClick={send}
                disabled={dispatching || !editedSubject.trim()}
                className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
              >
                {dispatching ? 'queueing…' : 'send'}
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

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

function BodyTabs({
  htmlBody,
  editedBody,
  setEditedBody,
}: {
  htmlBody: string | undefined
  editedBody: string
  setEditedBody: (s: string) => void
}) {
  const [view, setView] = useState<'html' | 'plain'>(htmlBody ? 'html' : 'plain')
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Body
        </div>
        <div className="flex gap-1">
          {htmlBody && (
            <button
              onClick={() => setView('html')}
              className={`rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-[0.14em] transition ${
                view === 'html'
                  ? 'border-accent text-accent'
                  : 'border-line text-fg-mute hover:border-accent hover:text-accent'
              }`}
            >
              html
            </button>
          )}
          <button
            onClick={() => setView('plain')}
            className={`rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-[0.14em] transition ${
              view === 'plain'
                ? 'border-accent text-accent'
                : 'border-line text-fg-mute hover:border-accent hover:text-accent'
            }`}
          >
            plain
          </button>
        </div>
      </div>
      {view === 'html' && htmlBody ? (
        <iframe
          srcDoc={htmlBody}
          title="email preview"
          sandbox=""
          className="mt-1 h-[480px] w-full rounded-md border border-line bg-white"
        />
      ) : (
        <textarea
          value={editedBody}
          onChange={(e) => setEditedBody(e.target.value)}
          rows={8}
          className="mt-1 block w-full resize-y rounded-md border border-line bg-bg-card px-3 py-2 text-sm leading-relaxed outline-none focus:border-accent"
        />
      )}
    </div>
  )
}

function RecommendedProducts({
  products,
  ids,
}: {
  products: Product[]
  ids: string[]
}) {
  const matches = ids
    .map((id) => products.find((p) => p.id === id))
    .filter((p): p is Product => !!p)
  if (matches.length === 0) {
    return (
      <div>
        <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Recommended products
        </div>
        <div className="mt-1.5 flex flex-wrap gap-1.5">
          {ids.map((id) => (
            <span
              key={id}
              className="rounded-full border border-line bg-bg-card px-2.5 py-1 text-[11px] text-fg-mute"
            >
              {id.slice(0, 8)}
            </span>
          ))}
        </div>
      </div>
    )
  }
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Recommended products
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {matches.map((p) => (
          <span
            key={p.id}
            className="rounded-full border border-line bg-bg-card px-2.5 py-1 text-[11px] text-fg-mute"
            title={p.description ?? undefined}
          >
            {p.name}
          </span>
        ))}
      </div>
    </div>
  )
}
