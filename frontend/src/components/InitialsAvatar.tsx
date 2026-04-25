type Size = 'sm' | 'md' | 'lg'

const PALETTE: { bg: string; fg: string }[] = [
  { bg: '#2a2540', fg: '#ffffff' },
  { bg: '#3b5b48', fg: '#ffffff' },
  { bg: '#c2826b', fg: '#ffffff' },
  { bg: '#6f5cff', fg: '#ffffff' },
  { bg: '#5a7ba8', fg: '#ffffff' },
  { bg: '#996a85', fg: '#ffffff' },
  { bg: '#3d6e6e', fg: '#ffffff' },
  { bg: '#a5763d', fg: '#ffffff' },
]

const SIZE: Record<Size, string> = {
  sm: 'h-8 w-8 text-[10px]',
  md: 'h-10 w-10 text-xs',
  lg: 'h-14 w-14 text-base',
}

function initials(name: string): string {
  const parts = name
    .replace(/[·•|—–-]+/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1)
    return (parts[0].slice(0, 2) || '?').toUpperCase()
  return (parts[0][0] + parts[1][0]).toUpperCase()
}

function pickColor(name: string) {
  let h = 0
  for (const c of name) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

export function InitialsAvatar({
  name,
  size = 'md',
}: {
  name: string
  size?: Size
}) {
  const { bg, fg } = pickColor(name)
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full font-medium tracking-tight ${SIZE[size]}`}
      style={{ background: bg, color: fg }}
    >
      {initials(name)}
    </span>
  )
}
