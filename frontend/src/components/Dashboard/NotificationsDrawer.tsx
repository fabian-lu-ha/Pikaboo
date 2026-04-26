import { useEffect } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { useNotificationsStore, type NotifTint } from '../../stores/notificationsStore'
import { relativeTime } from '../../lib/brandName'

const TINT: Record<NotifTint, { bg: string; fg: string }> = {
  violet: { bg: '#eef0ff', fg: '#5b50e6' },
  emerald: { bg: '#dcf3e9', fg: '#1f9e6e' },
  amber: { bg: '#fbe8d6', fg: '#d97a3a' },
  sky: { bg: '#e0e7ff', fg: '#4338ca' },
  danger: { bg: '#fde8ee', fg: '#c2185b' },
}

export function NotificationsDrawer({
  open,
  onClose,
}: {
  open: boolean
  onClose: () => void
}) {
  const items = useNotificationsStore((s) => s.items)
  const clear = useNotificationsStore((s) => s.clear)

  // Esc closes the drawer
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            key="notif-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.18 }}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-fg/15 backdrop-blur-[1px]"
          />
          <motion.aside
            key="notif-drawer"
            initial={{ x: 400, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 400, opacity: 0 }}
            transition={{ duration: 0.28, ease: [0.16, 1, 0.3, 1] }}
            className="fixed right-0 top-0 z-50 flex h-screen w-[380px] max-w-[92vw] flex-col border-l border-line bg-bg-card shadow-[-12px_0_30px_rgba(20,20,40,0.06)]"
          >
            <header className="flex items-center justify-between border-b border-line px-5 py-4">
              <div>
                <div className="text-[14px] font-semibold">Notifications</div>
                <div className="mt-0.5 text-[11px] text-fg-mute">
                  {items.length === 0
                    ? 'No activity yet this session'
                    : `${items.length} event${items.length === 1 ? '' : 's'} this session`}
                </div>
              </div>
              <div className="flex items-center gap-1">
                {items.length > 0 && (
                  <button
                    onClick={clear}
                    className="rounded-md px-2 py-1 text-[11px] text-fg-mute hover:text-accent"
                  >
                    Clear
                  </button>
                )}
                <button
                  onClick={onClose}
                  aria-label="Close"
                  className="grid h-7 w-7 place-items-center rounded-md text-fg-mute hover:bg-bg-soft hover:text-fg"
                >
                  ✕
                </button>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto [scrollbar-width:thin]">
              {items.length === 0 ? (
                <EmptyState />
              ) : (
                <ul className="flex flex-col">
                  {items.map((n) => {
                    const t = TINT[n.tint]
                    return (
                      <li
                        key={n.id}
                        className="flex items-start gap-3 border-b border-line-soft px-5 py-3 last:border-b-0"
                      >
                        <span
                          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg text-[13px]"
                          style={{ background: t.bg, color: t.fg }}
                        >
                          {n.glyph}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="text-[12.5px] font-medium leading-snug">
                            {n.title}
                          </div>
                          {n.detail && (
                            <div className="mt-0.5 truncate text-[11px] text-fg-mute">
                              {n.detail}
                            </div>
                          )}
                        </div>
                        <span className="shrink-0 text-[11px] tabular-nums text-fg-dim">
                          {relativeTime(n.at)}
                        </span>
                      </li>
                    )
                  })}
                </ul>
              )}
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function EmptyState() {
  return (
    <div className="grid h-full place-items-center px-8 text-center">
      <div>
        <div className="mx-auto grid h-10 w-10 place-items-center rounded-full bg-accent-soft text-accent">
          ◔
        </div>
        <p className="mt-3 text-[13px] font-medium">All quiet</p>
        <p className="mt-1 text-[12px] leading-relaxed text-fg-mute">
          Run a campaign, import customers, or watch for competitor surges
          and updates will land here.
        </p>
      </div>
    </div>
  )
}
