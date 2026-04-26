import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import { ConnectCRMModal } from './ConnectCRMModal'
import { CustomerList } from './CustomerList'
import { CustomerDrawer } from './CustomerDrawer'
import { SegmentList } from './SegmentList'
import { SegmentDrawer } from './SegmentDrawer'
import { ProposedSegmentsModal } from './ProposedSegmentsModal'
import { ProductGrid } from './ProductGrid'
import { AudienceActivityFeed } from './AudienceActivityFeed'
import { ShopFeed } from './ShopFeed'
import { OfferPolicyPanel } from './OfferPolicyPanel'
import { TriggersPanel } from './TriggersPanel'

type Tab = 'customers' | 'segments' | 'products'

type Props = {
  brandId: string
  brandName: string
}

export function AudiencePane({ brandId, brandName }: Props) {
  const [tab, setTab] = useState<Tab>('customers')
  const [policyOpen, setPolicyOpen] = useState(false)
  const [triggersOpen, setTriggersOpen] = useState(false)

  const customers = useAudienceStore((s) => s.customers)
  const products = useAudienceStore((s) => s.products)
  const segments = useAudienceStore((s) => s.segments)
  const lastImport = useAudienceStore((s) => s.lastImport)
  const crmConnected = useAudienceStore((s) => s.crmConnected)
  const importing = useAudienceStore((s) => s.importing)

  const loadCustomers = useAudienceStore((s) => s.loadCustomers)
  const loadProducts = useAudienceStore((s) => s.loadProducts)
  const loadSegments = useAudienceStore((s) => s.loadSegments)
  const openConnectModal = useAudienceStore((s) => s.openConnectModal)
  const importFromCRM = useAudienceStore((s) => s.importFromCRM)

  useEffect(() => {
    loadCustomers(brandId)
    loadProducts(brandId)
    loadSegments(brandId)
  }, [brandId, loadCustomers, loadProducts, loadSegments])

  const totalEvents =
    lastImport?.event_count ??
    customers.reduce((acc, c) => acc + (c.recent_events?.length ?? 0), 0)

  return (
    <main className="flex flex-col px-10 py-7">
      <motion.header
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex flex-wrap items-end justify-between gap-4"
      >
        <div>
          <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Audience
          </div>
          <h1 className="mt-1 font-serif text-4xl tracking-tight">
            Who you talk to, and what to say next
          </h1>
          <p className="mt-1.5 text-sm text-fg-mute">
            {brandName} ·{' '}
            <span className="tabular-nums">{customers.length}</span> customers
            · <span className="tabular-nums">{products.length}</span> products
            · <span className="tabular-nums">{totalEvents}</span> events
            {segments.length > 0 && (
              <>
                {' '}
                · <span className="tabular-nums">{segments.length}</span>{' '}
                segments
              </>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {crmConnected ? (
            <button
              onClick={() => importFromCRM(brandId, 'mock', {})}
              disabled={importing}
              className="rounded-full border border-line bg-bg-card px-4 py-2 text-xs text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
            >
              {importing ? 'syncing…' : '↻ Sync now'}
            </button>
          ) : null}
          <button
            onClick={() => setTriggersOpen(true)}
            className="rounded-full border border-line bg-bg-card px-4 py-2 text-xs text-fg-mute transition hover:border-accent hover:text-accent"
          >
            Triggers
          </button>
          <button
            onClick={() => setPolicyOpen(true)}
            className="rounded-full border border-line bg-bg-card px-4 py-2 text-xs text-fg-mute transition hover:border-accent hover:text-accent"
          >
            Offer policy
          </button>
          <button
            onClick={openConnectModal}
            className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110"
          >
            {crmConnected ? '+ Connect another CRM' : 'Connect CRM'}
          </button>
        </div>
      </motion.header>

      <div className="mt-6 flex items-center gap-1 border-b border-line">
        <TabButton active={tab === 'customers'} onClick={() => setTab('customers')}>
          Customers
        </TabButton>
        <TabButton active={tab === 'segments'} onClick={() => setTab('segments')}>
          Segments
        </TabButton>
        <TabButton active={tab === 'products'} onClick={() => setTab('products')}>
          Products
        </TabButton>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
        <section className="min-w-0">
          {tab === 'customers' && <CustomerList />}
          {tab === 'segments' && <SegmentList brandId={brandId} />}
          {tab === 'products' && <ProductGrid />}
        </section>
        <aside className="flex flex-col gap-4">
          <ShopFeed brandId={brandId} />
          <AudienceActivityFeed />
        </aside>
      </div>

      <ConnectCRMModal brandId={brandId} />
      <ProposedSegmentsModal brandId={brandId} />
      <CustomerDrawer brandId={brandId} />
      <SegmentDrawer brandId={brandId} />
      <OfferPolicyPanel
        brandId={brandId}
        open={policyOpen}
        onClose={() => setPolicyOpen(false)}
      />
      <TriggersPanel
        brandId={brandId}
        open={triggersOpen}
        onClose={() => setTriggersOpen(false)}
      />
    </main>
  )
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`relative px-4 py-2.5 text-sm transition ${
        active ? 'text-fg' : 'text-fg-mute hover:text-fg'
      }`}
    >
      {children}
      {active && (
        <motion.span
          layoutId="audience-tab-underline"
          className="absolute inset-x-3 -bottom-px h-[2px] rounded-full bg-accent"
        />
      )}
    </button>
  )
}
