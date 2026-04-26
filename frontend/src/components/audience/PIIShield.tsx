import { useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'

type Props = {
  count: number
  types: string[]
  size?: 'sm' | 'md'
}

export function PIIShield({ count, types, size = 'sm' }: Props) {
  const [hovering, setHovering] = useState(false)
  const padding = size === 'md' ? 'px-3 py-1.5' : 'px-2.5 py-1'
  const text = size === 'md' ? 'text-[11px]' : 'text-[10px]'
  return (
    <span
      onMouseEnter={() => setHovering(true)}
      onMouseLeave={() => setHovering(false)}
      onFocus={() => setHovering(true)}
      onBlur={() => setHovering(false)}
      tabIndex={0}
      className={`relative inline-flex items-center gap-1.5 rounded-full border border-emerald-300/60 bg-emerald-50/70 ${padding} ${text} font-medium uppercase tracking-[0.16em] text-emerald-700 outline-none focus-visible:border-emerald-500`}
    >
      <ShieldGlyph />
      {count} PII {count === 1 ? 'entity' : 'entities'} scrubbed
      <AnimatePresence>
        {hovering && (
          <motion.span
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 4 }}
            transition={{ duration: 0.15 }}
            role="tooltip"
            className="pointer-events-none absolute left-0 top-full z-20 mt-2 w-64 rounded-xl border border-line bg-bg-card px-3 py-2.5 text-left text-[11px] normal-case tracking-normal text-fg-mute shadow-[0_8px_24px_rgba(20,20,40,0.08)]"
          >
            <div className="font-medium text-fg">
              Names, emails, phones never reach the LLM
            </div>
            <div className="mt-1 leading-snug">
              Each entity is replaced with a placeholder before generation, then
              re-hydrated client-side.
            </div>
            {types.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {types.map((t) => (
                  <span
                    key={t}
                    className="rounded-md border border-line bg-bg-soft/60 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-mute"
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
          </motion.span>
        )}
      </AnimatePresence>
    </span>
  )
}

function ShieldGlyph() {
  return (
    <svg
      viewBox="0 0 14 14"
      width="11"
      height="11"
      aria-hidden="true"
      className="fill-current"
    >
      <path d="M7 0.6 1.4 2.4v4.2c0 3.4 2.5 5.6 5.6 6.8 3.1-1.2 5.6-3.4 5.6-6.8V2.4L7 0.6Zm-0.7 9.1L3.6 7l1-1 1.7 1.7 3.1-3.1 1 1-4.1 4.1Z" />
    </svg>
  )
}
