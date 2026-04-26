import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import { InitialsAvatar } from '../InitialsAvatar'
import type { Customer, ProposedSegment } from '../../lib/audience'

type Props = {
  brandId: string
}

export function ProposedSegmentsModal({ brandId }: Props) {
  const open = useAudienceStore((s) => s.showProposedModal)
  const proposed = useAudienceStore((s) => s.proposedSegments) ?? []
  const close = useAudienceStore((s) => s.closeProposedModal)
  const saveSegment = useAudienceStore((s) => s.saveSegment)
  const customersById = useAudienceStore((s) => s.customersById)
  const openSegmentDrawer = useAudienceStore((s) => s.openSegmentDrawer)
  const [savingIdx, setSavingIdx] = useState<number | null>(null)
  const [savedIdx, setSavedIdx] = useState<Record<number, string>>({})

  async function save(idx: number, p: ProposedSegment) {
    setSavingIdx(idx)
    const seg = await saveSegment(brandId, p)
    setSavingIdx(null)
    if (seg) setSavedIdx((s) => ({ ...s, [idx]: seg.id }))
  }

  async function saveAndUse(idx: number, p: ProposedSegment) {
    const existing = savedIdx[idx]
    if (existing) {
      close()
      openSegmentDrawer(existing)
      return
    }
    setSavingIdx(idx)
    const seg = await saveSegment(brandId, p)
    setSavingIdx(null)
    if (seg) {
      setSavedIdx((s) => ({ ...s, [idx]: seg.id }))
      close()
      openSegmentDrawer(seg.id)
    }
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={close}
            className="fixed inset-0 z-40 bg-fg/30 backdrop-blur-[2px]"
          />
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
            className="fixed left-1/2 top-1/2 z-50 flex w-[760px] max-w-[95vw] -translate-x-1/2 -translate-y-1/2 flex-col rounded-3xl border border-line bg-bg-card shadow-[0_20px_60px_rgba(20,20,40,0.18)]"
          >
            <header className="flex items-center justify-between border-b border-line-soft px-6 py-4">
              <div>
                <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  Agent · proposed segments
                </div>
                <h3 className="mt-1 font-serif text-2xl tracking-tight">
                  {proposed.length} segment{proposed.length === 1 ? '' : 's'} that look high-intent
                </h3>
              </div>
              <button
                onClick={close}
                className="grid h-8 w-8 place-items-center rounded-full text-fg-mute hover:bg-bg-soft hover:text-fg"
                aria-label="Close"
              >
                ✕
              </button>
            </header>
            <div className="max-h-[70vh] overflow-y-auto px-6 py-5 [scrollbar-width:thin]">
              <ul className="flex flex-col gap-3">
                {proposed.map((p, idx) => (
                  <ProposedRow
                    key={`${p.name}-${idx}`}
                    proposed={p}
                    customersById={customersById}
                    saved={!!savedIdx[idx]}
                    saving={savingIdx === idx}
                    onSave={() => save(idx, p)}
                    onUse={() => saveAndUse(idx, p)}
                  />
                ))}
              </ul>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}

function ProposedRow({
  proposed,
  customersById,
  saved,
  saving,
  onSave,
  onUse,
}: {
  proposed: ProposedSegment
  customersById: Record<string, Customer>
  saved: boolean
  saving: boolean
  onSave: () => void
  onUse: () => void
}) {
  const [showRationale, setShowRationale] = useState(false)
  const previewCustomers = proposed.customer_ids
    .slice(0, 5)
    .map((id) => customersById[id])
    .filter(Boolean) as Customer[]

  return (
    <li className="rounded-2xl border border-line bg-bg px-5 py-4">
      <div className="flex items-baseline justify-between gap-3">
        <h4 className="font-serif text-lg tracking-tight">{proposed.name}</h4>
        <span className="rounded-full border border-line bg-bg-card px-2.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-mute">
          {proposed.customer_ids.length}{' '}
          {proposed.customer_ids.length === 1 ? 'member' : 'members'}
        </span>
      </div>
      <p className="mt-1 text-sm text-fg-mute">{proposed.description}</p>

      {proposed.criteria_summary && (
        <div className="mt-2 text-[11px] text-fg-dim">
          <span className="uppercase tracking-[0.14em]">Criteria · </span>
          {proposed.criteria_summary}
        </div>
      )}

      {previewCustomers.length > 0 && (
        <div className="mt-3 flex items-center gap-2">
          <div className="flex -space-x-2">
            {previewCustomers.map((c) => (
              <span key={c.id} className="rounded-full ring-2 ring-bg-card">
                <InitialsAvatar
                  name={c.name?.trim() || c.email}
                  size="sm"
                />
              </span>
            ))}
          </div>
          {proposed.customer_ids.length > previewCustomers.length && (
            <span className="text-[10px] uppercase tracking-[0.14em] text-fg-dim">
              +{proposed.customer_ids.length - previewCustomers.length} more
            </span>
          )}
        </div>
      )}

      <button
        onClick={() => setShowRationale((v) => !v)}
        className="mt-3 text-[11px] uppercase tracking-[0.14em] text-fg-mute hover:text-accent"
      >
        {showRationale ? '− hide rationale' : '+ rationale'}
      </button>
      <AnimatePresence initial={false}>
        {showRationale && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 rounded-xl bg-bg-soft/60 px-3 py-2 text-[12px] leading-snug text-fg-mute">
              {proposed.rationale}
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="mt-4 flex items-center justify-end gap-2">
        <button
          onClick={onSave}
          disabled={saving || saved}
          className="rounded-full border border-line bg-bg-card px-4 py-2 text-xs text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
        >
          {saved ? 'saved' : saving ? 'saving…' : 'save'}
        </button>
        <button
          onClick={onUse}
          disabled={saving}
          className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          {saved ? 'open' : 'use as campaign'}
        </button>
      </div>
    </li>
  )
}
