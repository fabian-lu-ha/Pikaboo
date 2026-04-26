import { useState } from 'react'
import { useNav } from './navContext'
import { useNotificationsStore } from '../../stores/notificationsStore'
import { NotificationsDrawer } from './NotificationsDrawer'
import type { Brand } from './types'

type Props = {
  brand: Brand
  searchValue?: string
  onSearchChange?: (value: string) => void
}

export function TopBar({ searchValue = '', onSearchChange }: Props) {
  const { navigate } = useNav()
  const unread = useNotificationsStore((s) => s.unreadCount)
  const markAllRead = useNotificationsStore((s) => s.markAllRead)
  const [notifOpen, setNotifOpen] = useState(false)

  function openNotifs() {
    setNotifOpen(true)
    markAllRead()
  }

  return (
    <>
      <header className="flex items-center justify-between gap-4 px-8 pt-5 pb-3">
        <div className="hairline flex flex-1 items-center rounded-full bg-bg-card pl-5 pr-2 py-1">
          <span className="text-fg-dim">⌕</span>
          <input
            value={searchValue}
            onChange={(e) => onSearchChange?.(e.target.value)}
            placeholder="Search insights…"
            className="flex-1 bg-transparent px-2 py-1.5 text-[13px] outline-none placeholder:text-fg-dim"
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            aria-label="Notifications"
            onClick={openNotifs}
            className="hairline relative grid h-9 w-9 place-items-center rounded-full bg-bg-card text-fg-mute transition hover:text-accent"
          >
            ◔
            {unread > 0 && (
              <span
                className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[9px] font-semibold text-white shadow-[0_2px_6px_rgba(91,80,230,0.45)]"
                aria-label={`${unread} unread`}
              >
                {unread > 9 ? '9+' : unread}
              </span>
            )}
          </button>
          <button
            aria-label="Settings"
            onClick={() => navigate('settings')}
            className="hairline grid h-9 w-9 place-items-center rounded-full bg-bg-card text-fg-mute transition hover:text-accent"
          >
            ⚙
          </button>
        </div>
      </header>
      <NotificationsDrawer open={notifOpen} onClose={() => setNotifOpen(false)} />
    </>
  )
}
