import { useEffect, useMemo, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { createPortal } from 'react-dom'
import { TopBar } from './TopBar'
import { useNav } from './navContext'
import { primaryName } from '../../lib/brandName'
import type { Brand } from './types'

type SectionId =
  | 'profile'
  | 'voice'
  | 'integrations'
  | 'notifications'
  | 'privacy'
  | 'danger'

const SECTIONS: { id: SectionId; label: string; glyph: string }[] = [
  { id: 'profile', label: 'Profile', glyph: '◐' },
  { id: 'voice', label: 'Voice', glyph: '◑' },
  { id: 'integrations', label: 'Integrations', glyph: '⊞' },
  { id: 'notifications', label: 'Notifications', glyph: '◔' },
  { id: 'privacy', label: 'Privacy & PII', glyph: '◇' },
  { id: 'danger', label: 'Danger Zone', glyph: '⚠' },
]

export function Settings({ brand }: { brand: Brand }) {
  const [search, setSearch] = useState('')
  const [section, setSection] = useState<SectionId>('profile')

  return (
    <main className="flex flex-col">
      <TopBar brand={brand} searchValue={search} onSearchChange={setSearch} />
      <div className="px-10 pb-10">
        <Header />
        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[220px_1fr]">
          <SectionNav active={section} onSelect={setSection} />
          <div>
            <motion.div
              key={section}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.25 }}
            >
              {section === 'profile' && <ProfileSection brand={brand} />}
              {section === 'voice' && <VoiceSection brand={brand} />}
              {section === 'integrations' && <IntegrationsSection brand={brand} />}
              {section === 'notifications' && <NotificationsSection />}
              {section === 'privacy' && <PrivacySection brand={brand} />}
              {section === 'danger' && <DangerSection />}
            </motion.div>
          </div>
        </div>
      </div>
    </main>
  )
}

function Header() {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
      className="pt-4"
    >
      <h1 className="text-[36px] font-semibold leading-[1.15] tracking-[-0.02em]">
        Settings
      </h1>
      <p className="mt-2 max-w-xl text-[13px] text-fg-mute">
        Tune your brand profile, integrations, and how Brand Autopilot
        behaves on your behalf.
      </p>
    </motion.section>
  )
}

function SectionNav({
  active,
  onSelect,
}: {
  active: SectionId
  onSelect: (id: SectionId) => void
}) {
  return (
    <nav className="flex flex-col gap-1">
      {SECTIONS.map((s) => {
        const isActive = s.id === active
        const isDanger = s.id === 'danger'
        return (
          <button
            key={s.id}
            onClick={() => onSelect(s.id)}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] transition ${
              isActive
                ? isDanger
                  ? 'bg-red-50 font-medium text-red-700'
                  : 'bg-accent-soft font-medium text-fg'
                : isDanger
                  ? 'text-red-500/70 hover:bg-red-50/60'
                  : 'text-fg-mute hover:bg-accent-soft/40'
            }`}
          >
            <span
              className={`w-4 text-center text-[14px] ${
                isActive
                  ? isDanger
                    ? 'text-red-500'
                    : 'text-accent'
                  : 'text-fg-dim'
              }`}
            >
              {s.glyph}
            </span>
            {s.label}
          </button>
        )
      })}
    </nav>
  )
}

function Card({
  title,
  subtitle,
  children,
  footer,
  tone = 'default',
}: {
  title: string
  subtitle?: string
  children: React.ReactNode
  footer?: React.ReactNode
  tone?: 'default' | 'danger'
}) {
  const danger = tone === 'danger'
  return (
    <section
      className={`panel ${danger ? 'border-red-200/80' : ''}`}
      style={
        danger
          ? { borderColor: 'rgba(212,74,106,0.4)' }
          : undefined
      }
    >
      <header className="border-b border-line-soft px-6 py-4">
        <div
          className={`text-[13px] font-semibold ${danger ? 'text-red-600' : 'text-fg'}`}
        >
          {title}
        </div>
        {subtitle && (
          <p className="mt-0.5 text-[12px] text-fg-mute">{subtitle}</p>
        )}
      </header>
      <div className="px-6 py-5">{children}</div>
      {footer && (
        <footer className="flex items-center justify-end gap-2 border-t border-line-soft px-6 py-3">
          {footer}
        </footer>
      )}
    </section>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-1 gap-2 py-3 first:pt-0 last:pb-0 sm:grid-cols-[180px_1fr] sm:items-start sm:gap-6">
      <div>
        <div className="text-[12px] font-medium text-fg">{label}</div>
        {hint && (
          <div className="mt-0.5 text-[11px] leading-snug text-fg-mute">
            {hint}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  )
}

function PrimaryButton({
  children,
  onClick,
  disabled,
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="rounded-xl bg-gradient-to-b from-accent to-[var(--color-accent-deep)] px-4 py-2 text-[12.5px] font-medium text-white shadow-[0_4px_14px_rgba(91,80,230,0.3)] transition hover:brightness-110 disabled:from-accent-dim disabled:to-accent-dim disabled:shadow-none"
    >
      {children}
    </button>
  )
}

function GhostButton({
  children,
  onClick,
}: {
  children: React.ReactNode
  onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="hairline rounded-xl bg-bg-card px-4 py-2 text-[12.5px] text-fg-mute transition hover:text-fg"
    >
      {children}
    </button>
  )
}

// ============================================================== Profile

function ProfileSection({ brand }: { brand: Brand }) {
  const [name, setName] = useState(brand.name)
  const [url, setUrl] = useState(brand.url ?? '')
  const [description, setDescription] = useState(brand.description ?? '')
  const [saved, setSaved] = useState(false)

  const dirty =
    name !== brand.name ||
    url !== (brand.url ?? '') ||
    description !== (brand.description ?? '')

  function save() {
    // No backend write yet — show a transient confirmation. Real persistence
    // can route through /api/onboarding/me PATCH when that endpoint exists.
    setSaved(true)
    setTimeout(() => setSaved(false), 1500)
  }

  return (
    <Card
      title="Brand profile"
      subtitle="What the agent uses to introduce and represent your brand."
      footer={
        <>
          {saved && (
            <span className="text-[11px] text-emerald-600">Saved locally</span>
          )}
          <GhostButton
            onClick={() => {
              setName(brand.name)
              setUrl(brand.url ?? '')
              setDescription(brand.description ?? '')
            }}
          >
            Reset
          </GhostButton>
          <PrimaryButton onClick={save} disabled={!dirty}>
            Save changes
          </PrimaryButton>
        </>
      }
    >
      <Field label="Name">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        />
      </Field>
      <div className="border-t border-line-soft" />
      <Field label="Website" hint="Used for asset extraction + brand voice.">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://"
          className="hairline w-full rounded-lg bg-bg-card px-3 py-2 text-[13px] outline-none focus:border-accent"
        />
      </Field>
      <div className="border-t border-line-soft" />
      <Field label="Short description" hint="One sentence the agent can quote.">
        <textarea
          rows={3}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          className="hairline w-full resize-none rounded-lg bg-bg-card px-3 py-2 text-[13px] leading-snug outline-none focus:border-accent"
        />
      </Field>
      <div className="border-t border-line-soft" />
      <Field label="Logo">
        <div className="flex items-center gap-3">
          {brand.logo_url ? (
            <img
              src={brand.logo_url}
              alt=""
              className="h-12 w-12 rounded-xl bg-bg object-contain p-1.5 ring-1 ring-line"
            />
          ) : (
            <div className="grid h-12 w-12 place-items-center rounded-xl bg-fg text-[16px] font-semibold text-white">
              {primaryName(brand.name).slice(0, 1).toUpperCase()}
            </div>
          )}
          <GhostButton>Upload new</GhostButton>
        </div>
      </Field>
    </Card>
  )
}

// ================================================================ Voice

function VoiceSection({ brand }: { brand: Brand }) {
  const v = brand.voice_profile
  const { navigate } = useNav()
  return (
    <Card
      title="Voice profile"
      subtitle="Distilled from your real posts during onboarding. Edit on the Voice page."
      footer={
        <>
          <GhostButton onClick={() => navigate('voice')}>
            Re-run distillation
          </GhostButton>
          <PrimaryButton onClick={() => navigate('voice')}>
            Open voice studio →
          </PrimaryButton>
        </>
      }
    >
      {v?.tone ? (
        <>
          <Field label="Tone">
            <p className="text-[13px] leading-relaxed text-fg">{v.tone}</p>
          </Field>
          {(v.recurring_phrases ?? []).length > 0 && (
            <>
              <div className="border-t border-line-soft" />
              <Field label="Recurring phrases">
                <div className="flex flex-wrap gap-1.5">
                  {(v.recurring_phrases ?? []).slice(0, 8).map((p) => (
                    <span
                      key={p}
                      className="hairline rounded-full bg-bg-card px-2.5 py-0.5 text-[11px] text-fg-mute"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </Field>
            </>
          )}
        </>
      ) : (
        <p className="text-[12px] text-fg-mute">
          No voice distilled yet. Run onboarding to generate one.
        </p>
      )}
    </Card>
  )
}

// ========================================================= Integrations

type SocialPlatform = {
  key: string
  label: string
  glyph: string
  tint: { bg: string; fg: string }
  // Onboarding scrapers can store the same network under different keys —
  // map them all to a single canonical platform.
  aliases: string[]
  urlPrefix: string
}

const SOCIAL_PLATFORMS: SocialPlatform[] = [
  {
    key: 'instagram',
    label: 'Instagram',
    glyph: '◉',
    tint: { bg: '#fbe1ec', fg: '#c026d3' },
    aliases: ['instagram', 'ig'],
    urlPrefix: 'https://instagram.com/',
  },
  {
    key: 'linkedin',
    label: 'LinkedIn',
    glyph: 'in',
    tint: { bg: '#dbeafe', fg: '#0a66c2' },
    aliases: ['linkedin', 'li'],
    urlPrefix: 'https://linkedin.com/company/',
  },
  {
    key: 'x',
    label: 'X / Twitter',
    glyph: '𝕏',
    tint: { bg: '#1f2937', fg: '#f9fafb' },
    aliases: ['x', 'twitter'],
    urlPrefix: 'https://x.com/',
  },
  {
    key: 'tiktok',
    label: 'TikTok',
    glyph: '♪',
    tint: { bg: '#0f172a', fg: '#22d3ee' },
    aliases: ['tiktok', 'tt'],
    urlPrefix: 'https://tiktok.com/@',
  },
  {
    key: 'youtube',
    label: 'YouTube',
    glyph: '▶',
    tint: { bg: '#fee2e2', fg: '#dc2626' },
    aliases: ['youtube', 'yt'],
    urlPrefix: 'https://youtube.com/@',
  },
  {
    key: 'facebook',
    label: 'Facebook',
    glyph: 'f',
    tint: { bg: '#dbeafe', fg: '#1d4ed8' },
    aliases: ['facebook', 'fb', 'meta'],
    urlPrefix: 'https://facebook.com/',
  },
  {
    key: 'threads',
    label: 'Threads',
    glyph: '@',
    tint: { bg: '#0f172a', fg: '#f9fafb' },
    aliases: ['threads'],
    urlPrefix: 'https://threads.net/@',
  },
  {
    key: 'pinterest',
    label: 'Pinterest',
    glyph: 'P',
    tint: { bg: '#fee2e2', fg: '#be123c' },
    aliases: ['pinterest', 'pin'],
    urlPrefix: 'https://pinterest.com/',
  },
]

function findHandle(
  handles: Record<string, string> | undefined,
  aliases: string[],
): string | null {
  if (!handles) return null
  for (const a of aliases) {
    const v = handles[a] ?? handles[a.toLowerCase()] ?? handles[a.toUpperCase()]
    if (v && String(v).trim()) return String(v).trim()
  }
  return null
}

function IntegrationsSection({ brand }: { brand: Brand }) {
  type B = Brand & {
    kanban_connections?: Record<string, unknown>
    crm_connections?: Record<string, unknown>
  }
  const b = brand as B
  const kanban = !!b.kanban_connections && Object.keys(b.kanban_connections).length > 0
  const crm = !!b.crm_connections && Object.keys(b.crm_connections).length > 0

  const rows: { label: string; detail: string; on: boolean }[] = [
    {
      label: 'Kanban (Trello / Linear / Notion)',
      detail: kanban
        ? Object.keys(b.kanban_connections!).join(', ')
        : 'Not connected',
      on: kanban,
    },
    {
      label: 'CRM / Audience',
      detail: crm
        ? Object.keys(b.crm_connections!).join(', ')
        : 'Not connected',
      on: crm,
    },
    {
      label: 'Peec visibility',
      detail: 'Manages itself · controlled by API key in env',
      on: true,
    },
  ]

  return (
    <div className="flex flex-col gap-5">
      <InstagramConnectionCard brand={brand} />

      <Card
        title="Integrations"
        subtitle="Operational data sources Brand Autopilot is wired into."
      >
        <ul className="flex flex-col divide-y divide-line-soft">
          {rows.map((r) => (
            <li
              key={r.label}
              className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
            >
              <div className="min-w-0">
                <div className="text-[13px] font-medium">{r.label}</div>
                <div className="mt-0.5 truncate text-[11px] text-fg-mute">
                  {r.detail}
                </div>
              </div>
              {r.on ? (
                <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                  Connected
                </span>
              ) : (
                <GhostButton>Connect</GhostButton>
              )}
            </li>
          ))}
        </ul>
      </Card>

      <SocialProfilesCard brand={brand} />
    </div>
  )
}

// =================================================== Instagram (Graph API)

type InstagramStatus = {
  connected: boolean
  ig_user_id?: string | null
  username?: string | null
  display_name?: string | null
  profile_picture_url?: string | null
  page_id?: string | null
  connected_at?: string | null
}

function InstagramConnectionCard({ brand }: { brand: Brand }) {
  const [status, setStatus] = useState<InstagramStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [showConnect, setShowConnect] = useState(false)
  const [disconnecting, setDisconnecting] = useState(false)

  const refresh = async () => {
    setLoading(true)
    try {
      const r = await fetch(
        `/api/integrations/instagram/status?brand_id=${encodeURIComponent(brand.id)}`,
      )
      if (r.ok) {
        setStatus(await r.json())
      } else {
        setStatus({ connected: false })
      }
    } catch {
      setStatus({ connected: false })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brand.id])

  async function disconnect() {
    if (!status?.connected) return
    setDisconnecting(true)
    try {
      await fetch(
        `/api/integrations/instagram/disconnect?brand_id=${encodeURIComponent(brand.id)}`,
        { method: 'DELETE' },
      )
      await refresh()
    } finally {
      setDisconnecting(false)
    }
  }

  return (
    <>
      <Card
        title="Instagram"
        subtitle="Connect your Instagram Business account to pull live insights into Analytics."
      >
        {loading ? (
          <div className="text-[12px] text-fg-mute">Loading status…</div>
        ) : status?.connected ? (
          <div className="flex items-center gap-3">
            {status.profile_picture_url ? (
              <img
                src={status.profile_picture_url}
                alt=""
                className="h-12 w-12 rounded-full object-cover"
              />
            ) : (
              <div className="grid h-12 w-12 place-items-center rounded-full bg-gradient-to-br from-[#fbe1ec] to-[#f9d4e5] text-[16px] font-semibold text-[#c026d3]">
                ◉
              </div>
            )}
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium leading-tight">
                @{status.username ?? '—'}
              </div>
              {status.display_name && (
                <div className="mt-0.5 truncate text-[11px] text-fg-mute">
                  {status.display_name}
                </div>
              )}
              {status.connected_at && (
                <div className="mt-0.5 text-[11px] text-fg-dim">
                  Connected {new Date(status.connected_at).toLocaleDateString()}
                </div>
              )}
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
              Connected
            </span>
            <GhostButton onClick={disconnect}>
              {disconnecting ? 'Disconnecting…' : 'Disconnect'}
            </GhostButton>
          </div>
        ) : (
          <div className="flex items-start gap-3">
            <div className="grid h-12 w-12 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#fbe1ec] to-[#f9d4e5] text-[16px] font-semibold text-[#c026d3]">
              ◉
            </div>
            <div className="min-w-0 flex-1">
              <div className="text-[13px] font-medium leading-tight">
                Not connected
              </div>
              <div className="mt-0.5 text-[11px] leading-snug text-fg-mute">
                You'll need a long-lived access token from Meta Business Suite
                with <code className="text-fg">instagram_basic</code>,{' '}
                <code className="text-fg">instagram_manage_insights</code>, and{' '}
                <code className="text-fg">pages_show_list</code> scopes.
              </div>
            </div>
            <PrimaryButton onClick={() => setShowConnect(true)}>
              Connect Instagram
            </PrimaryButton>
          </div>
        )}
      </Card>

      <AnimatePresence>
        {showConnect && (
          <ConnectInstagramModal
            brandId={brand.id}
            onClose={() => setShowConnect(false)}
            onConnected={async () => {
              setShowConnect(false)
              await refresh()
            }}
          />
        )}
      </AnimatePresence>
    </>
  )
}

function ConnectInstagramModal({
  brandId,
  onClose,
  onConnected,
}: {
  brandId: string
  onClose: () => void
  onConnected: () => void
}) {
  const [token, setToken] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  async function submit() {
    const trimmed = token.trim()
    if (!trimmed) {
      setError('Paste a Meta access token to continue.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const r = await fetch('/api/integrations/instagram/connect', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ brand_id: brandId, access_token: trimmed }),
      })
      if (r.ok) {
        onConnected()
      } else {
        const detail = await r
          .json()
          .then((j) => j?.detail ?? null)
          .catch(() => null)
        setError(detail ?? `Connect failed (${r.status})`)
      }
    } catch (e) {
      setError(`Network error: ${e instanceof Error ? e.message : 'unknown'}`)
    } finally {
      setSubmitting(false)
    }
  }

  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="w-full max-w-lg overflow-hidden rounded-2xl border border-line bg-bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="border-b border-line-soft px-6 py-4">
          <div className="text-[14px] font-semibold">Connect Instagram</div>
          <p className="mt-1 text-[12px] leading-snug text-fg-mute">
            Brand Autopilot uses the Meta Graph API to pull insights. Paste a
            long-lived access token below — we'll auto-discover the linked
            Instagram Business Account.
          </p>
        </header>
        <div className="px-6 py-5">
          <div className="rounded-xl bg-bg-soft/60 px-4 py-3 text-[11.5px] leading-relaxed text-fg-mute">
            <div className="font-medium text-fg">How to get a token</div>
            <ol className="mt-1.5 list-decimal pl-4 marker:text-fg-dim">
              <li>
                Open{' '}
                <a
                  href="https://business.facebook.com/settings/system-users"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-accent hover:underline"
                >
                  Meta Business Suite → System Users
                </a>
              </li>
              <li>
                Generate a token with scopes{' '}
                <code className="text-fg">instagram_basic</code>,{' '}
                <code className="text-fg">instagram_manage_insights</code>,{' '}
                <code className="text-fg">pages_show_list</code>,{' '}
                <code className="text-fg">pages_read_engagement</code>
              </li>
              <li>Copy + paste it here. Tokens are stored only for this brand.</li>
            </ol>
          </div>
          <label className="mt-4 block text-[11px] font-medium text-fg-mute">
            Access token
          </label>
          <textarea
            autoFocus
            value={token}
            onChange={(e) => setToken(e.target.value)}
            rows={4}
            placeholder="EAAG..."
            className="hairline mt-1 w-full resize-none rounded-lg bg-bg-card px-3 py-2 font-mono text-[12px] outline-none focus:border-accent"
          />
          {error && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-[12px] leading-snug text-red-700">
              {error}
            </p>
          )}
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-line-soft px-6 py-3">
          <GhostButton onClick={onClose}>Cancel</GhostButton>
          <PrimaryButton onClick={submit} disabled={submitting || !token.trim()}>
            {submitting ? 'Verifying…' : 'Connect'}
          </PrimaryButton>
        </footer>
      </motion.div>
    </motion.div>,
    document.body,
  )
}

function SocialProfilesCard({ brand }: { brand: Brand }) {
  const platforms = SOCIAL_PLATFORMS.map((p) => ({
    ...p,
    handle: findHandle(brand.handles, p.aliases),
  }))
  const connected = platforms.filter((p) => p.handle)
  const disconnected = platforms.filter((p) => !p.handle)
  return (
    <Card
      title="Social profiles"
      subtitle={`${connected.length} of ${platforms.length} connected · which networks the agent can post + scrape from.`}
    >
      <ul className="flex flex-col divide-y divide-line-soft">
        {[...connected, ...disconnected].map((p) => (
          <SocialRow key={p.key} platform={p} />
        ))}
      </ul>
    </Card>
  )
}

function SocialRow({
  platform,
}: {
  platform: SocialPlatform & { handle: string | null }
}) {
  const handle = platform.handle
  const stripped = handle ? handle.replace(/^@+/, '') : null
  const url = stripped ? platform.urlPrefix + stripped : null
  return (
    <li className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
      <span
        className="grid h-9 w-9 shrink-0 place-items-center rounded-lg text-[13px] font-semibold"
        style={{ background: platform.tint.bg, color: platform.tint.fg }}
      >
        {platform.glyph}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium leading-tight">
          {platform.label}
        </div>
        {handle ? (
          url ? (
            <a
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-0.5 inline-block truncate text-[11px] text-fg-mute hover:text-accent"
            >
              @{stripped}
            </a>
          ) : (
            <div className="mt-0.5 truncate text-[11px] text-fg-mute">
              @{stripped}
            </div>
          )
        ) : (
          <div className="mt-0.5 truncate text-[11px] text-fg-dim">
            Not connected
          </div>
        )}
      </div>
      {handle ? (
        <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Connected
        </span>
      ) : (
        <GhostButton>Connect</GhostButton>
      )}
    </li>
  )
}

// ========================================================= Notifications

const NOTIF_PREFS_KEY = 'ba.settings.notifications.v1'

type NotifPrefs = {
  competitor_surge: boolean
  campaign_ready: boolean
  weekly_digest: boolean
  pipeline_failure: boolean
  pii_redacted: boolean
}

const NOTIF_DEFAULTS: NotifPrefs = {
  competitor_surge: true,
  campaign_ready: true,
  weekly_digest: true,
  pipeline_failure: true,
  pii_redacted: false,
}

function loadNotifPrefs(): NotifPrefs {
  try {
    const raw = localStorage.getItem(NOTIF_PREFS_KEY)
    if (!raw) return NOTIF_DEFAULTS
    return { ...NOTIF_DEFAULTS, ...(JSON.parse(raw) as Partial<NotifPrefs>) }
  } catch {
    return NOTIF_DEFAULTS
  }
}

function NotificationsSection() {
  const [prefs, setPrefs] = useState<NotifPrefs>(loadNotifPrefs)
  const [saved, setSaved] = useState(false)
  const initial = useRef(prefs)
  const dirty = useMemo(
    () => JSON.stringify(prefs) !== JSON.stringify(initial.current),
    [prefs],
  )

  function save() {
    try {
      localStorage.setItem(NOTIF_PREFS_KEY, JSON.stringify(prefs))
      initial.current = prefs
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch {
      /* localStorage blocked — best-effort */
    }
  }

  function reset() {
    setPrefs(NOTIF_DEFAULTS)
  }

  const items: { key: keyof typeof prefs; label: string; hint: string }[] = [
    {
      key: 'competitor_surge',
      label: 'Competitor surges',
      hint: 'A tracked competitor jumps in visibility or sentiment.',
    },
    {
      key: 'campaign_ready',
      label: 'Campaign ready',
      hint: 'Agent finishes drafting + bundling a campaign.',
    },
    {
      key: 'weekly_digest',
      label: 'Weekly digest',
      hint: 'Mondays at 09:00 — visibility + share-of-voice deltas.',
    },
    {
      key: 'pipeline_failure',
      label: 'Pipeline failures',
      hint: 'Any active recipe or pipeline node errors out.',
    },
    {
      key: 'pii_redacted',
      label: 'PII redaction events',
      hint: 'Verbose. Shows every redact call. Off by default.',
    },
  ]
  return (
    <Card
      title="Notifications"
      subtitle="What gets surfaced to the activity feed and to Slack/email when wired."
      footer={
        <>
          {saved && (
            <span className="text-[11px] text-emerald-600">Saved</span>
          )}
          <GhostButton onClick={reset}>Reset</GhostButton>
          <PrimaryButton onClick={save} disabled={!dirty}>
            Save preferences
          </PrimaryButton>
        </>
      }
    >
      <ul className="flex flex-col divide-y divide-line-soft">
        {items.map((it) => {
          const on = prefs[it.key]
          return (
            <li
              key={it.key}
              className="flex items-center justify-between gap-3 py-3 first:pt-0 last:pb-0"
            >
              <div className="min-w-0">
                <div className="text-[13px] font-medium">{it.label}</div>
                <div className="mt-0.5 text-[11px] leading-snug text-fg-mute">
                  {it.hint}
                </div>
              </div>
              <Toggle
                checked={on}
                onChange={(v) =>
                  setPrefs((s) => ({ ...s, [it.key]: v }))
                }
              />
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      role="switch"
      aria-checked={checked}
      className={`relative h-5 w-9 shrink-0 rounded-full transition ${
        checked ? 'bg-accent' : 'bg-line'
      }`}
    >
      <span
        className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow-[0_1px_2px_rgba(20,20,40,0.2)] transition ${
          checked ? 'left-[18px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

// ============================================================== Privacy

const PRIVACY_PREFS_KEY = 'ba.settings.privacy.v1'

type PrivacyPrefs = {
  provider: 'regex' | 'google'
  logRedactions: boolean
}

const PRIVACY_DEFAULTS: PrivacyPrefs = {
  provider: 'google',
  logRedactions: true,
}

function loadPrivacyPrefs(): PrivacyPrefs {
  try {
    const raw = localStorage.getItem(PRIVACY_PREFS_KEY)
    if (!raw) return PRIVACY_DEFAULTS
    return { ...PRIVACY_DEFAULTS, ...(JSON.parse(raw) as Partial<PrivacyPrefs>) }
  } catch {
    return PRIVACY_DEFAULTS
  }
}

function PrivacySection({ brand }: { brand: Brand }) {
  const [prefs, setPrefs] = useState<PrivacyPrefs>(loadPrivacyPrefs)
  const [saved, setSaved] = useState(false)
  const [exporting, setExporting] = useState(false)
  const initial = useRef(prefs)
  const dirty = useMemo(
    () => JSON.stringify(prefs) !== JSON.stringify(initial.current),
    [prefs],
  )

  function save() {
    try {
      localStorage.setItem(PRIVACY_PREFS_KEY, JSON.stringify(prefs))
      initial.current = prefs
      setSaved(true)
      setTimeout(() => setSaved(false), 1500)
    } catch {
      /* localStorage blocked — best-effort */
    }
  }

  async function exportJson() {
    setExporting(true)
    try {
      // Pull the canonical brand record from the backend; fall back to the
      // prop if /api/onboarding/me isn't reachable so the button still does
      // something useful.
      let payload: unknown
      try {
        const r = await fetch('/api/onboarding/me')
        payload = r.ok ? await r.json() : brand
      } catch {
        payload = brand
      }
      const wrapped = {
        exported_at: new Date().toISOString(),
        brand_id: brand.id,
        brand_name: brand.name,
        privacy_prefs: prefs,
        notification_prefs: loadNotifPrefs(),
        brand: payload,
      }
      const blob = new Blob([JSON.stringify(wrapped, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const stamp = new Date().toISOString().slice(0, 10)
      a.download = `${brand.name.toLowerCase().replace(/\s+/g, '-')}-export-${stamp}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }

  return (
    <Card
      title="Privacy & PII redaction"
      subtitle="What scrubs personal data before it reaches the campaign LLM."
      footer={
        <>
          {saved && (
            <span className="text-[11px] text-emerald-600">Saved</span>
          )}
          <PrimaryButton onClick={save} disabled={!dirty}>
            Save preferences
          </PrimaryButton>
        </>
      }
    >
      <Field
        label="Redactor"
        hint="Google uses Cloud DLP when GCP_PROJECT_ID is set, else Gemini classifier. Regex is fully local."
      >
        <div className="hairline inline-flex rounded-full bg-bg p-0.5">
          {(['regex', 'google'] as const).map((p) => (
            <button
              key={p}
              onClick={() => setPrefs((s) => ({ ...s, provider: p }))}
              className={`rounded-full px-3 py-1 text-[12px] font-medium capitalize transition ${
                prefs.provider === p
                  ? 'bg-bg-card text-fg shadow-[0_1px_2px_rgba(20,20,40,0.06)]'
                  : 'text-fg-mute hover:text-fg'
              }`}
            >
              {p}
            </button>
          ))}
        </div>
      </Field>
      <div className="border-t border-line-soft" />
      <Field
        label="Log redactions"
        hint="Stream PII redaction events (counts only — never originals) to the activity feed."
      >
        <Toggle
          checked={prefs.logRedactions}
          onChange={(v) => setPrefs((s) => ({ ...s, logRedactions: v }))}
        />
      </Field>
      <div className="border-t border-line-soft" />
      <Field
        label="Export data"
        hint="Download everything Brand Autopilot stores about your brand, plus your saved preferences."
      >
        <GhostButton onClick={exportJson}>
          {exporting ? 'Exporting…' : 'Export JSON'}
        </GhostButton>
      </Field>
    </Card>
  )
}

// =============================================================== Danger

function DangerSection() {
  const { navigate } = useNav()
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  async function reonboard() {
    setDeleting(true)
    try {
      await fetch('/api/onboarding/me', { method: 'DELETE' })
      window.location.reload()
    } finally {
      setDeleting(false)
    }
  }
  return (
    <Card
      title="Danger zone"
      subtitle="Irreversible actions. Read carefully."
      tone="danger"
      footer={
        <GhostButton onClick={() => navigate('dashboard')}>
          Back to dashboard
        </GhostButton>
      }
    >
      <Field
        label="Re-onboard"
        hint="Deletes the current brand record + scraped assets + competitors. Onboarding restarts from scratch."
      >
        {confirming ? (
          <div className="flex items-center gap-2">
            <button
              onClick={reonboard}
              disabled={deleting}
              className="rounded-xl bg-red-500 px-4 py-2 text-[12.5px] font-medium text-white transition hover:bg-red-600 disabled:opacity-60"
            >
              {deleting ? 'Wiping…' : 'Yes, wipe and re-onboard'}
            </button>
            <GhostButton onClick={() => setConfirming(false)}>
              Cancel
            </GhostButton>
          </div>
        ) : (
          <button
            onClick={() => setConfirming(true)}
            className="hairline rounded-xl bg-bg-card px-4 py-2 text-[12.5px] font-medium text-red-600 transition hover:border-red-300 hover:bg-red-50"
          >
            Re-onboard this brand
          </button>
        )}
      </Field>
    </Card>
  )
}
