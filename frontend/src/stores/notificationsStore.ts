import { create } from 'zustand'
import { bus } from '../events/bus'

// Notifications feed — subscribes to high-signal bus events at module load
// and keeps a rolling window of the last MAX entries. Imported by the
// TopBar (always mounted) so the subscriptions are live for the entire
// session. No persistence — the feed reflects this session only.

export type NotifTint = 'violet' | 'emerald' | 'amber' | 'sky' | 'danger'

export type Notification = {
  id: string
  kind: string
  title: string
  detail?: string
  at: number
  glyph: string
  tint: NotifTint
}

type State = {
  items: Notification[]
  unreadCount: number
}

type Actions = {
  markAllRead: () => void
  clear: () => void
}

const MAX = 50

export const useNotificationsStore = create<State & Actions>((set) => ({
  items: [],
  unreadCount: 0,
  markAllRead: () => set({ unreadCount: 0 }),
  clear: () => set({ items: [], unreadCount: 0 }),
}))

let counter = 0
function nextId(prefix: string): string {
  counter += 1
  return `${prefix}-${Date.now()}-${counter}`
}

function add(n: Omit<Notification, 'at'> & { at?: number }) {
  const item: Notification = { ...n, at: n.at ?? Date.now() }
  useNotificationsStore.setState((s) => ({
    items: [item, ...s.items].slice(0, MAX),
    unreadCount: s.unreadCount + 1,
  }))
}

bus.on('agent.started', (e) =>
  add({
    id: nextId('agent-start'),
    kind: 'agent.started',
    title: 'Agent started',
    detail: e.user_request,
    glyph: '◐',
    tint: 'violet',
  }),
)
bus.on('agent.failed', (e) =>
  add({
    id: nextId('agent-fail'),
    kind: 'agent.failed',
    title: 'Agent failed',
    detail: e.error,
    glyph: '✕',
    tint: 'danger',
  }),
)
bus.on('campaign.bundled', (e) =>
  add({
    id: nextId('bundle'),
    kind: 'campaign.bundled',
    title: `Campaign ready: ${e.title}`,
    glyph: '✓',
    tint: 'emerald',
  }),
)
bus.on('lift.predicted', (e) =>
  add({
    id: nextId('lift'),
    kind: 'lift.predicted',
    title: `Predicted lift +${e.lift_percent}%`,
    detail: e.confidence,
    glyph: '↗',
    tint: 'emerald',
  }),
)
bus.on('competitor.surged', (e) =>
  add({
    id: nextId('surge'),
    kind: 'competitor.surged',
    title: `${e.competitor} surged`,
    detail: `${e.delta > 0 ? '+' : ''}${Math.round(e.delta * 100)}% on "${e.prompt}"`,
    glyph: '↗',
    tint: 'amber',
  }),
)
bus.on('linear.pr_merged', (e) =>
  add({
    id: nextId('pr'),
    kind: 'linear.pr_merged',
    title: `${e.pr} merged`,
    detail: e.ship_ready ? 'Ship-ready — draft a launch post?' : undefined,
    glyph: '◫',
    tint: 'sky',
  }),
)
bus.on('video.rendered', (e) =>
  add({
    id: nextId('vid'),
    kind: 'video.rendered',
    title: 'Video rendered',
    detail: `${(e.duration_ms / 1000).toFixed(1)}s clip`,
    glyph: '▶',
    tint: 'violet',
  }),
)
bus.on('video.render_failed', (e) =>
  add({
    id: nextId('vid-fail'),
    kind: 'video.render_failed',
    title: 'Video render failed',
    detail: e.error,
    glyph: '✕',
    tint: 'danger',
  }),
)
bus.on('audience.customers_imported', (e) =>
  add({
    id: nextId('cust-imp'),
    kind: 'audience.customers_imported',
    title: 'Customers imported',
    detail: `${e.customer_count} customers · ${e.product_count} products`,
    glyph: '◉',
    tint: 'emerald',
  }),
)
bus.on('audience.segment_saved', (e) =>
  add({
    id: nextId('seg-saved'),
    kind: 'audience.segment_saved',
    title: `Segment saved: ${e.segment.name}`,
    detail: `${e.segment.customer_ids.length} members`,
    glyph: '◇',
    tint: 'violet',
  }),
)
bus.on('audience.email_dispatched', (e) =>
  add({
    id: nextId('mail'),
    kind: 'audience.email_dispatched',
    title: 'Email dispatched',
    detail: `${e.recipient_count} recipient${e.recipient_count === 1 ? '' : 's'}`,
    glyph: '✉',
    tint: 'emerald',
  }),
)
bus.on('audience.pii_redacted', (e) =>
  add({
    id: nextId('pii'),
    kind: 'audience.pii_redacted',
    title: 'PII scrubbed',
    detail: `${e.entity_count} entities · ${e.entity_types.join(', ')}`,
    glyph: '⛨',
    tint: 'sky',
  }),
)
bus.on('onboarding.completed', () =>
  add({
    id: nextId('onb'),
    kind: 'onboarding.completed',
    title: 'Onboarding complete',
    glyph: '✓',
    tint: 'emerald',
  }),
)
