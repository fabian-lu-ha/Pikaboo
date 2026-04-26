import { useMemo, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import {
  EVENT_GLYPHS,
  EVENT_LABELS,
  SOURCE_LABELS,
  acquisitionBadge,
  formatPrice,
  relativeFromIso,
  type Customer,
  type CustomerEvent,
  type Touchpoint,
} from '../../lib/audience'
import { PersonalizeBlock } from './PersonalizeBlock'
import { CampaignStoryboard } from './CampaignStoryboard'

type Props = {
  brandId: string
}

export function CustomerDrawer({ brandId }: Props) {
  const drawerKind = useAudienceStore((s) => s.drawerKind)
  const customerId = useAudienceStore((s) => s.drawerCustomerId)
  const close = useAudienceStore((s) => s.closeDrawer)
  const detail = useAudienceStore((s) =>
    customerId ? s.customerDetail[customerId] : undefined,
  )
  const fallback = useAudienceStore((s) =>
    customerId ? s.customersById[customerId] : undefined,
  )

  const open = drawerKind === 'customer' && !!customerId
  const customer = detail?.customer ?? fallback ?? null
  const events = detail?.events ?? customer?.recent_events ?? []
  const stats = detail?.stats

  const [maskEmail, setMaskEmail] = useState(false)

  return (
    <AnimatePresence>
      {open && customer && (
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
            className="fixed right-0 top-0 z-40 flex h-screen w-[480px] max-w-[92vw] flex-col border-l border-line bg-bg shadow-[-12px_0_30px_rgba(20,20,40,0.06)]"
          >
            <Header customer={customer} maskEmail={maskEmail} setMaskEmail={setMaskEmail} onClose={close} />
            <div className="flex-1 overflow-y-auto overscroll-contain px-6 pb-8 [scrollbar-width:thin]">
              {stats && <StatsRow stats={stats} />}
              {customer.tags.length > 0 && (
                <Section label="Tags">
                  <div className="flex flex-wrap gap-1.5">
                    {customer.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded-full border border-line bg-bg-card px-2.5 py-1 text-[11px] text-fg-mute"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                </Section>
              )}
              {(customer.touchpoints?.length ?? 0) > 0 && (
                <Section label="Acquisition journey">
                  <JourneyTimeline
                    badge={acquisitionBadge(customer.acquisition)}
                    touchpoints={customer.touchpoints ?? []}
                  />
                </Section>
              )}
              <Section label="Activity timeline">
                <Timeline events={events} />
              </Section>
              <div className="mt-6">
                <PersonalizeBlock
                  brandId={brandId}
                  targetKind="customer"
                  targetId={customer.id}
                  recipientLabel={
                    customer.name?.trim() ||
                    (maskEmail ? maskEmailString(customer.email) : customer.email)
                  }
                />
              </div>
              <div className="mt-8">
                <CampaignStoryboard
                  brandId={brandId}
                  targetKind="customer"
                  targetId={customer.id}
                  recipientLabel={
                    customer.name?.trim() ||
                    (maskEmail ? maskEmailString(customer.email) : customer.email)
                  }
                />
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  )
}

function Header({
  customer,
  maskEmail,
  setMaskEmail,
  onClose,
}: {
  customer: Customer
  maskEmail: boolean
  setMaskEmail: (b: boolean) => void
  onClose: () => void
}) {
  const display = customer.name?.trim() || customer.email
  return (
    <header className="border-b border-line px-6 pb-5 pt-6">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Customer
          </div>
          <h2 className="mt-1 truncate font-serif text-2xl tracking-tight">
            {display}
          </h2>
          <div className="mt-1 flex items-center gap-2 text-xs text-fg-mute">
            <span className="truncate">
              {maskEmail ? maskEmailString(customer.email) : customer.email}
            </span>
            <button
              onClick={() => setMaskEmail(!maskEmail)}
              className="rounded-md border border-line bg-bg-card px-1.5 py-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-mute hover:border-accent hover:text-accent"
              title="Toggle email masking"
            >
              {maskEmail ? 'reveal' : 'mask'}
            </button>
          </div>
        </div>
        <button
          onClick={onClose}
          className="grid h-8 w-8 place-items-center rounded-full text-fg-mute hover:bg-bg-card hover:text-fg"
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="mt-3 grid grid-cols-3 gap-3 text-[11px]">
        <Meta label="City">{customer.city ?? '—'}</Meta>
        <Meta label="Signup">
          {customer.signup_at
            ? new Date(customer.signup_at).toLocaleDateString()
            : '—'}
        </Meta>
        <Meta label="Spend">{formatPrice(customer.total_spend_cents)}</Meta>
      </div>
    </header>
  )
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
        {label}
      </div>
      <div className="mt-0.5 truncate text-xs text-fg">{children}</div>
    </div>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="mt-6">
      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        {label}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function StatsRow({
  stats,
}: {
  stats: { total_spend_cents: number; purchase_count: number; open_rate: number }
}) {
  return (
    <div className="mt-5 grid grid-cols-3 gap-3 rounded-2xl border border-line bg-bg-card p-4">
      <Stat
        value={formatPrice(stats.total_spend_cents)}
        label="lifetime spend"
      />
      <Stat value={String(stats.purchase_count)} label="purchases" />
      <Stat
        value={`${Math.round(stats.open_rate * 100)}%`}
        label="open rate"
      />
    </div>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="font-serif text-2xl tracking-tight">{value}</div>
      <div className="mt-0.5 text-[10px] uppercase tracking-[0.18em] text-fg-mute">
        {label}
      </div>
    </div>
  )
}

function JourneyTimeline({
  badge,
  touchpoints,
}: {
  badge: string | null
  touchpoints: Touchpoint[]
}) {
  if (touchpoints.length === 0) return null
  return (
    <div className="rounded-2xl border border-line bg-bg-card p-4">
      {badge && (
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-line bg-bg-soft px-2.5 py-1 text-[11px] text-fg-mute">
          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
          first touch · {badge}
        </div>
      )}
      <ol className="flex flex-col gap-2">
        {touchpoints.map((t, i) => (
          <li key={`${t.at}-${i}`} className="flex items-start gap-3 text-xs">
            <span
              className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${
                i === 0 ? 'bg-accent' : 'bg-fg-dim'
              }`}
              aria-hidden
            />
            <div className="min-w-0 flex-1">
              <div className="text-fg">
                {SOURCE_LABELS[t.source] ?? t.source}
                {t.campaign ? ` · ${t.campaign}` : ''}
              </div>
              <div className="mt-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-dim">
                {t.action} — {new Date(t.at).toLocaleDateString()}
              </div>
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}

function Timeline({ events }: { events: CustomerEvent[] }) {
  const grouped = useMemo(() => groupByDay(events), [events])
  if (events.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-line px-4 py-3 text-xs text-fg-mute">
        No events yet.
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-4">
      {grouped.map((g) => (
        <div key={g.day}>
          <div className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-dim">
            {g.day}
          </div>
          <ul className="mt-2 flex flex-col gap-1.5">
            {g.events.map((e) => (
              <li
                key={e.id}
                className="flex items-center gap-3 rounded-lg bg-bg-soft/40 px-3 py-2 text-xs"
              >
                <span
                  className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-bg-card text-[12px] text-accent"
                  aria-hidden="true"
                >
                  {EVENT_GLYPHS[e.kind] ?? '·'}
                </span>
                <span className="flex-1 truncate text-fg">
                  {EVENT_LABELS[e.kind] ?? e.kind}
                  <PayloadHint payload={e.payload} />
                </span>
                <span className="shrink-0 text-[10px] uppercase tracking-[0.14em] text-fg-dim">
                  {relativeFromIso(e.occurred_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}

function PayloadHint({ payload }: { payload: Record<string, unknown> }) {
  const subject = payload['subject']
  const product = payload['product_name'] ?? payload['product']
  const url = payload['url']
  const hint =
    typeof subject === 'string'
      ? subject
      : typeof product === 'string'
        ? product
        : typeof url === 'string'
          ? url
          : null
  if (!hint) return null
  return <span className="ml-1 text-fg-mute"> · {hint.slice(0, 60)}</span>
}

function groupByDay(events: CustomerEvent[]) {
  const byDay = new Map<string, CustomerEvent[]>()
  const sorted = [...events].sort(
    (a, b) => Date.parse(b.occurred_at) - Date.parse(a.occurred_at),
  )
  for (const e of sorted) {
    const day = formatDay(e.occurred_at)
    const list = byDay.get(day) ?? []
    list.push(e)
    byDay.set(day, list)
  }
  return [...byDay.entries()].map(([day, events]) => ({ day, events }))
}

function formatDay(iso: string): string {
  const ts = Date.parse(iso)
  if (Number.isNaN(ts)) return 'unknown'
  const d = new Date(ts)
  const today = new Date()
  const isToday = d.toDateString() === today.toDateString()
  if (isToday) return 'Today'
  const yesterday = new Date(today.getTime() - 86400_000)
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday'
  return d.toLocaleDateString(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

function maskEmailString(email: string): string {
  const [user, domain] = email.split('@')
  if (!domain) return '••••@••••'
  const u = user.length <= 2 ? '••' : user[0] + '•••' + user.slice(-1)
  return `${u}@${domain}`
}
