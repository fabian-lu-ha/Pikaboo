import type { RunTint } from './types'

const TINTS: Record<RunTint, { bg: string; fg: string; icon: string }> = {
  violet: { bg: '#eef0ff', fg: '#5b50e6', icon: '◐' },
  emerald: { bg: '#dcf3e9', fg: '#1f9e6e', icon: '◇' },
  amber: { bg: '#fbe8d6', fg: '#d97a3a', icon: '◫' },
}

export function RunRow({
  tint,
  title,
  sub,
  ago,
  onClick,
}: {
  tint: RunTint
  title: string
  sub: string
  ago: string
  onClick?: () => void
}) {
  const t = TINTS[tint]
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        disabled={!onClick}
        className="flex w-full items-center gap-4 px-5 py-4 text-left transition hover:bg-bg-soft/50 disabled:cursor-default disabled:hover:bg-transparent"
      >
        <span
          className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-sm"
          style={{ background: t.bg, color: t.fg }}
        >
          {t.icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium leading-tight">
            {title}
          </div>
          <div className="mt-0.5 truncate text-[12px] text-fg-mute">{sub}</div>
        </div>
        <span className="shrink-0 text-[12px] text-fg-mute">{ago}</span>
      </button>
    </li>
  )
}
