import { motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'

type Props = {
  brandId: string
}

export function SegmentList({ brandId }: Props) {
  const segments = useAudienceStore((s) => s.segments)
  const proposing = useAudienceStore((s) => s.proposing)
  const proposeSegments = useAudienceStore((s) => s.proposeSegments)
  const openSegmentDrawer = useAudienceStore((s) => s.openSegmentDrawer)
  const drawerSegmentId = useAudienceStore((s) => s.drawerSegmentId)

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Segments · {segments.length}
        </div>
        <button
          onClick={() => proposeSegments(brandId)}
          disabled={proposing}
          className="rounded-full bg-accent px-4 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          {proposing ? 'thinking…' : '+ Propose with AI'}
        </button>
      </div>

      {segments.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-line bg-bg-card px-5 py-6 text-sm text-fg-mute">
          No segments yet. Let the agent propose some, or build them manually
          from the customer list.
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {segments.map((seg) => (
            <motion.li
              key={seg.id}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <button
                onClick={() => openSegmentDrawer(seg.id)}
                className={`flex w-full flex-col gap-1.5 rounded-2xl border px-5 py-4 text-left shadow-[0_2px_10px_rgba(20,20,40,0.03)] transition ${
                  seg.id === drawerSegmentId
                    ? 'border-accent bg-accent-soft/30'
                    : 'border-line bg-bg-card hover:border-accent/60'
                }`}
              >
                <div className="flex items-baseline justify-between gap-3">
                  <h4 className="font-serif text-lg leading-tight tracking-tight">
                    {seg.name}
                  </h4>
                  <span className="shrink-0 rounded-full border border-line bg-bg-card px-2.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-mute">
                    {seg.customer_ids.length}{' '}
                    {seg.customer_ids.length === 1 ? 'member' : 'members'}
                  </span>
                </div>
                {seg.description && (
                  <p className="line-clamp-2 text-sm text-fg-mute">
                    {seg.description}
                  </p>
                )}
                <div className="mt-1 flex items-center justify-between text-[10px] uppercase tracking-[0.14em] text-fg-dim">
                  <span>
                    {seg.source === 'ai_proposed' ? 'agent-proposed' : 'manual'}
                  </span>
                  <span>open →</span>
                </div>
              </button>
            </motion.li>
          ))}
        </ul>
      )}
    </div>
  )
}
