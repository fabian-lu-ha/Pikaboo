import { create } from 'zustand'
import { bus } from '../events/bus'
import type {
  Customer,
  CustomerEvent,
  CustomerStats,
  PersonalizedEmail,
  Product,
  ProposedSegment,
  Segment,
} from '../lib/audience'

type RedactionEntry = {
  id: number
  at: string
  entity_count: number
  types: string[]
}

type ImportSummary = {
  customer_count: number
  product_count: number
  event_count: number
}

type DrawerKind = 'customer' | 'segment' | null

type CustomerDetail = {
  customer: Customer
  events: CustomerEvent[]
  stats: CustomerStats
}

export type ShopEventKind = 'cart_abandoned' | 'subscription_lapsed'

export type ShopFeedEntry = {
  id: number
  at: string
  brand_id: string
  customer_id: string
  kind: ShopEventKind
  payload: Record<string, unknown>
  // populated when shop_auto_personalized arrives
  subject_preview?: string
  recommended_product_ids?: string[]
}

type State = {
  customers: Customer[]
  customersById: Record<string, Customer>
  products: Product[]
  segments: Segment[]
  proposedSegments: ProposedSegment[] | null
  customerDetail: Record<string, CustomerDetail>
  segmentMembers: Record<string, Customer[]>
  importing: boolean
  proposing: boolean
  personalizing: boolean
  loadingCustomers: boolean
  loadingProducts: boolean
  loadingSegments: boolean
  lastImport: ImportSummary | null
  redactionLog: RedactionEntry[]
  personalizedCount: number
  drawerKind: DrawerKind
  drawerCustomerId: string | null
  drawerSegmentId: string | null
  showProposedModal: boolean
  showConnectModal: boolean
  crmConnected: boolean
  shopFeed: ShopFeedEntry[]
  error: string | null
}

type Actions = {
  loadCustomers: (brand_id: string) => Promise<void>
  loadCustomer: (customer_id: string) => Promise<void>
  loadProducts: (brand_id: string) => Promise<void>
  loadSegments: (brand_id: string) => Promise<void>
  loadSegment: (segment_id: string) => Promise<void>
  importFromCRM: (
    brand_id: string,
    provider: string,
    credentials: Record<string, string>,
  ) => Promise<void>
  proposeSegments: (brand_id: string) => Promise<void>
  saveSegment: (
    brand_id: string,
    proposed: ProposedSegment,
  ) => Promise<Segment | null>
  personalize: (
    brand_id: string,
    target_kind: 'customer' | 'segment',
    target_id: string,
    user_prompt?: string,
  ) => Promise<PersonalizedEmail | null>
  dispatch: (
    brand_id: string,
    target_kind: 'customer' | 'segment',
    target_id: string,
    subject: string,
    body: string,
    html_body?: string,
  ) => Promise<{ ok: boolean; send_id: string | null }>
  fireShopTrigger: (
    brand_id: string,
    customer_id: string,
    kind: ShopEventKind,
    payload?: Record<string, unknown>,
  ) => Promise<void>
  openCustomerDrawer: (customer_id: string) => void
  openSegmentDrawer: (segment_id: string) => void
  closeDrawer: () => void
  openConnectModal: () => void
  closeConnectModal: () => void
  closeProposedModal: () => void
  reset: () => void
}

const initial: State = {
  customers: [],
  customersById: {},
  products: [],
  segments: [],
  proposedSegments: null,
  customerDetail: {},
  segmentMembers: {},
  importing: false,
  proposing: false,
  personalizing: false,
  loadingCustomers: false,
  loadingProducts: false,
  loadingSegments: false,
  lastImport: null,
  redactionLog: [],
  personalizedCount: 0,
  drawerKind: null,
  drawerCustomerId: null,
  drawerSegmentId: null,
  showProposedModal: false,
  showConnectModal: false,
  crmConnected: false,
  shopFeed: [],
  error: null,
}

let redactionCounter = 0

function indexCustomers(list: Customer[]): Record<string, Customer> {
  const out: Record<string, Customer> = {}
  for (const c of list) out[c.id] = c
  return out
}

async function safeJson<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const text = await r.text().catch(() => '')
    throw new Error(`${r.status} ${r.statusText}: ${text.slice(0, 120)}`)
  }
  return (await r.json()) as T
}

export const useAudienceStore = create<State & Actions>((set, get) => ({
  ...initial,

  loadCustomers: async (brand_id) => {
    set({ loadingCustomers: true, error: null })
    try {
      const data = await safeJson<{ customers: Customer[] }>(
        await fetch(
          `/api/audience/customers?brand_id=${encodeURIComponent(brand_id)}&limit=50`,
        ),
      )
      const customers = data.customers ?? []
      set((s) => ({
        customers,
        customersById: { ...s.customersById, ...indexCustomers(customers) },
        loadingCustomers: false,
        crmConnected: s.crmConnected || customers.length > 0,
      }))
    } catch (err) {
      set({
        loadingCustomers: false,
        error: err instanceof Error ? err.message : 'failed to load customers',
      })
    }
  },

  loadCustomer: async (customer_id) => {
    try {
      const data = await safeJson<CustomerDetail>(
        await fetch(`/api/audience/customers/${encodeURIComponent(customer_id)}`),
      )
      set((s) => ({
        customerDetail: { ...s.customerDetail, [customer_id]: data },
        customersById: { ...s.customersById, [customer_id]: data.customer },
      }))
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'failed to load customer',
      })
    }
  },

  loadProducts: async (brand_id) => {
    set({ loadingProducts: true, error: null })
    try {
      const data = await safeJson<{ products: Product[] }>(
        await fetch(
          `/api/audience/products?brand_id=${encodeURIComponent(brand_id)}`,
        ),
      )
      set({ products: data.products ?? [], loadingProducts: false })
    } catch (err) {
      set({
        loadingProducts: false,
        error: err instanceof Error ? err.message : 'failed to load products',
      })
    }
  },

  loadSegments: async (brand_id) => {
    set({ loadingSegments: true, error: null })
    try {
      const data = await safeJson<{ segments: Segment[] }>(
        await fetch(
          `/api/audience/segments?brand_id=${encodeURIComponent(brand_id)}`,
        ),
      )
      set({ segments: data.segments ?? [], loadingSegments: false })
    } catch (err) {
      set({
        loadingSegments: false,
        error: err instanceof Error ? err.message : 'failed to load segments',
      })
    }
  },

  loadSegment: async (segment_id) => {
    try {
      const data = await safeJson<{
        segment: Segment
        customers: Customer[]
      }>(
        await fetch(`/api/audience/segments/${encodeURIComponent(segment_id)}`),
      )
      set((s) => ({
        segments: s.segments.some((sg) => sg.id === segment_id)
          ? s.segments.map((sg) => (sg.id === segment_id ? data.segment : sg))
          : [...s.segments, data.segment],
        segmentMembers: {
          ...s.segmentMembers,
          [segment_id]: data.customers ?? [],
        },
        customersById: {
          ...s.customersById,
          ...indexCustomers(data.customers ?? []),
        },
      }))
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'failed to load segment',
      })
    }
  },

  importFromCRM: async (brand_id, provider, credentials) => {
    set({ importing: true, error: null })
    try {
      await safeJson<{ ok: boolean }>(
        await fetch('/api/audience/connect_crm', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ brand_id, provider, credentials }),
        }),
      )
      bus.emit('audience.crm_connected', { brand_id, provider })
      bus.emit('audience.import_started', { brand_id, provider })
      const summary = await safeJson<{
        ok: boolean
        customer_count: number
        product_count: number
        event_count: number
      }>(
        await fetch('/api/audience/import', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ brand_id, provider }),
        }),
      )
      set({
        importing: false,
        crmConnected: true,
        showConnectModal: false,
        lastImport: {
          customer_count: summary.customer_count,
          product_count: summary.product_count,
          event_count: summary.event_count,
        },
      })
      bus.emit('audience.customers_imported', {
        brand_id,
        provider,
        customer_count: summary.customer_count,
        product_count: summary.product_count,
        event_count: summary.event_count,
      })
      const { loadCustomers, loadProducts, loadSegments } = get()
      await Promise.allSettled([
        loadCustomers(brand_id),
        loadProducts(brand_id),
        loadSegments(brand_id),
      ])
    } catch (err) {
      set({
        importing: false,
        error: err instanceof Error ? err.message : 'import failed',
      })
    }
  },

  proposeSegments: async (brand_id) => {
    set({ proposing: true, error: null, proposedSegments: null })
    bus.emit('audience.segments_proposing', { brand_id })
    try {
      const data = await safeJson<{ segments: ProposedSegment[] }>(
        await fetch('/api/audience/segments/propose', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ brand_id }),
        }),
      )
      const segments = data.segments ?? []
      set({
        proposing: false,
        proposedSegments: segments,
        showProposedModal: segments.length > 0,
      })
      bus.emit('audience.segments_proposed', { brand_id, segments })
    } catch (err) {
      set({
        proposing: false,
        error: err instanceof Error ? err.message : 'propose failed',
      })
    }
  },

  saveSegment: async (brand_id, proposed) => {
    try {
      const data = await safeJson<{ segment: Segment }>(
        await fetch('/api/audience/segments', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            brand_id,
            name: proposed.name,
            description: proposed.description,
            rationale: proposed.rationale,
            customer_ids: proposed.customer_ids,
            source: 'ai_proposed',
          }),
        }),
      )
      set((s) => ({
        segments: [...s.segments, data.segment],
      }))
      bus.emit('audience.segment_saved', { brand_id, segment: data.segment })
      return data.segment
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'save segment failed',
      })
      return null
    }
  },

  personalize: async (brand_id, target_kind, target_id, user_prompt) => {
    set({ personalizing: true, error: null })
    bus.emit('audience.personalizing', { brand_id, target_kind, target_id })
    try {
      const data = await safeJson<PersonalizedEmail>(
        await fetch('/api/audience/personalize', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            brand_id,
            target_kind,
            target_id,
            user_prompt,
          }),
        }),
      )
      set((s) => ({
        personalizing: false,
        personalizedCount: s.personalizedCount + 1,
      }))
      bus.emit('audience.personalized', {
        brand_id,
        target_kind,
        target_id,
        subject_preview: data.subject.slice(0, 80),
        recommended_product_ids: data.recommended_product_ids,
      })
      if (data.redaction_summary) {
        bus.emit('audience.pii_redacted', {
          brand_id,
          entity_count: data.redaction_summary.entity_count,
          entity_types: data.redaction_summary.types,
        })
      }
      return data
    } catch (err) {
      set({
        personalizing: false,
        error: err instanceof Error ? err.message : 'personalize failed',
      })
      return null
    }
  },

  dispatch: async (
    brand_id,
    target_kind,
    target_id,
    subject,
    body,
    html_body,
  ) => {
    try {
      const data = await safeJson<{ ok: boolean; send_id: string }>(
        await fetch('/api/audience/dispatch', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            brand_id,
            target_kind,
            target_id,
            subject,
            body,
            html_body,
          }),
        }),
      )
      const recipientCount =
        target_kind === 'segment'
          ? get().segmentMembers[target_id]?.length ?? 1
          : 1
      bus.emit('audience.email_dispatched', {
        brand_id,
        target_kind,
        target_id,
        recipient_count: recipientCount,
      })
      return { ok: data.ok, send_id: data.send_id ?? null }
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'dispatch failed',
      })
      return { ok: false, send_id: null }
    }
  },

  fireShopTrigger: async (brand_id, customer_id, kind, payload = {}) => {
    try {
      await safeJson<{ ok: boolean }>(
        await fetch('/api/audience/shop_trigger', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ brand_id, customer_id, kind, payload }),
        }),
      )
    } catch (err) {
      set({
        error: err instanceof Error ? err.message : 'shop_trigger failed',
      })
    }
  },

  openCustomerDrawer: (customer_id) => {
    set({
      drawerKind: 'customer',
      drawerCustomerId: customer_id,
      drawerSegmentId: null,
    })
    void get().loadCustomer(customer_id)
  },

  openSegmentDrawer: (segment_id) => {
    set({
      drawerKind: 'segment',
      drawerSegmentId: segment_id,
      drawerCustomerId: null,
    })
    void get().loadSegment(segment_id)
  },

  closeDrawer: () =>
    set({
      drawerKind: null,
      drawerCustomerId: null,
      drawerSegmentId: null,
    }),

  openConnectModal: () => set({ showConnectModal: true }),
  closeConnectModal: () => set({ showConnectModal: false }),
  closeProposedModal: () => set({ showProposedModal: false }),

  reset: () => set(initial),
}))

bus.on('audience.customers_imported', (p) => {
  useAudienceStore.setState({
    crmConnected: true,
    lastImport: {
      customer_count: p.customer_count,
      product_count: p.product_count,
      event_count: p.event_count,
    },
  })
})

bus.on('audience.pii_redacted', (p) => {
  useAudienceStore.setState((s) => {
    const at = new Date().toTimeString().slice(0, 8)
    const entry: RedactionEntry = {
      id: redactionCounter++,
      at,
      entity_count: p.entity_count,
      types: p.entity_types,
    }
    const next = [entry, ...s.redactionLog].slice(0, 10)
    return { redactionLog: next }
  })
})

bus.on('audience.segment_saved', (p) => {
  useAudienceStore.setState((s) => {
    if (s.segments.some((sg) => sg.id === p.segment.id)) return s
    return { segments: [...s.segments, p.segment] }
  })
})

bus.on('audience.segments_proposed', (p) => {
  useAudienceStore.setState({
    proposedSegments: p.segments,
    showProposedModal: p.segments.length > 0,
    proposing: false,
  })
})

let shopCounter = 0
bus.on('audience.shop_event_triggered', (p) => {
  useAudienceStore.setState((s) => ({
    shopFeed: [
      {
        id: shopCounter++,
        at: new Date().toLocaleTimeString(),
        brand_id: p.brand_id,
        customer_id: p.customer_id,
        kind: p.kind,
        payload: p.payload ?? {},
      },
      ...s.shopFeed,
    ].slice(0, 25),
  }))
})

bus.on('audience.shop_auto_personalized', (p) => {
  useAudienceStore.setState((s) => ({
    shopFeed: s.shopFeed.map((e) =>
      e.customer_id === p.customer_id && !e.subject_preview
        ? {
            ...e,
            subject_preview: p.subject_preview,
            recommended_product_ids: p.recommended_product_ids,
          }
        : e,
    ),
  }))
})
