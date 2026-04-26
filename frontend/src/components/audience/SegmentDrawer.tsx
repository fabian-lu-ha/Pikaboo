import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import { InitialsAvatar } from '../InitialsAvatar'
import { PersonalizeBlock } from './PersonalizeBlock'
import { CampaignStoryboard } from './CampaignStoryboard'
import { SegmentPolicyOverride } from './SegmentPolicyOverride'
import type { Customer } from '../../lib/audience'

type Props = {
  brandId: string
}

// Stable empty-array reference so the Zustand selector below never returns a
// fresh `[]` literal on every call — that would trigger an infinite render
// loop via useSyncExternalStore (snapshot would look "changed" each time).
const EMPTY_MEMBERS: Customer[] = []

export function SegmentDrawer({ brandId }: Props) {
  const drawerKind = useAudienceStore((s) => s.drawerKind)
  const segmentId = useAudienceStore((s) => s.drawerSegmentId)
  const close = useAudienceStore((s) => s.closeDrawer)
  const segment = useAudienceStore((s) =>
    segmentId ? s.segments.find((sg) => sg.id === segmentId) ?? null : null,
  )
  const memberRow = useAudienceStore((s) =>
    segmentId ? s.segmentMembers[segmentId] : undefined,
  )
  const members = memberRow ?? EMPTY_MEMBERS
  const openCustomerDrawer = useAudienceStore((s) => s.openCustomerDrawer)

  const open = drawerKind === 'segment' && !!segmentId

  return (
    <AnimatePresence>
      {open && segment && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={close}
            className="fixed inset-0 z-30 bg-fg/15 backdrop-blur-[1px]"
          />
          <motion.aside
            initial={{ x: 480, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 480, opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
            className="fixed right-0 top-0 z-40 flex h-screen w-[520px] max-w-[95vw] flex-col border-l border-line bg-bg shadow-[-12px_0_30px_rgba(20,20,40,0.06)]"
          >
            <header className="border-b border-line px-6 pb-5 pt-6">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                    Segment ·{' '}
                    {segment.source === 'ai_proposed' ? 'agent-proposed' : 'manual'}
                  </div>
                  <h2 className="mt-1 truncate font-serif text-2xl tracking-tight">
                    {segment.name}
                  </h2>
                  {segment.description && (
                    <p className="mt-1 text-xs text-fg-mute">
                      {segment.description}
                    </p>
                  )}
                </div>
                <button
                  onClick={close}
                  className="grid h-8 w-8 place-items-center rounded-full text-fg-mute hover:bg-bg-card hover:text-fg"
                  aria-label="Close"
                >
                  ✕
                </button>
              </div>
              {segment.rationale && (
                <div className="mt-3 rounded-xl bg-bg-soft/60 px-3 py-2 text-[11px] leading-snug text-fg-mute">
                  <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
                    Rationale ·{' '}
                  </span>
                  {segment.rationale}
                </div>
              )}
              <div className="mt-3 text-[11px] uppercase tracking-[0.18em] text-fg-dim">
                {segment.customer_ids.length}{' '}
                {segment.customer_ids.length === 1 ? 'member' : 'members'}
              </div>
            </header>

            <div className="flex-1 overflow-y-auto overscroll-contain px-6 pb-8 [scrollbar-width:thin]">
              <Members
                members={members}
                onSelect={openCustomerDrawer}
              />
              <div className="mt-6">
                <PersonalizeBlock
                  brandId={brandId}
                  targetKind="segment"
                  targetId={segment.id}
                  recipientLabel={`${segment.customer_ids.length} ${
                    segment.customer_ids.length === 1
                      ? 'recipient'
                      : 'recipients'
                  }`}
                />
              </div>
              <div className="mt-8">
                <CampaignStoryboard
                  brandId={brandId}
                  targetKind="segment"
                  targetId={segment.id}
                  recipientLabel={`${segment.customer_ids.length} ${
                    segment.customer_ids.length === 1
                      ? 'recipient'
                      : 'recipients'
                  }`}
                  showMergeTags
                />
              </div>
              <div className="mt-8">
                <SegmentPolicyOverride
                  brandId={brandId}
                  segmentId={segment.id}
                />
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function Members({
  members,
  onSelect,
}: {
  members: Customer[]
  onSelect: (id: string) => void
}) {
  if (members.length === 0) {
    return (
      <section className="mt-6">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Members
        </div>
        <div className="mt-3 rounded-xl border border-dashed border-line px-4 py-3 text-xs text-fg-mute">
          loading…
        </div>
      </section>
    )
  }
  return (
    <section className="mt-6">
      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Members
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-2">
        {members.map((m) => {
          const display = m.name?.trim() || m.email
          return (
            <li key={m.id}>
              <button
                onClick={() => onSelect(m.id)}
                className="flex w-full items-center gap-2.5 rounded-xl border border-line bg-bg-card px-3 py-2 text-left transition hover:border-accent"
              >
                <InitialsAvatar name={display} size="sm" />
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium">{display}</div>
                  <div className="truncate text-[10px] text-fg-dim">
                    {m.email}
                  </div>
                </div>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
