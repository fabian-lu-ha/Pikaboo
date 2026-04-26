import { motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'

type Props = {
  brandId: string
}

export function ShopFeed({ brandId }: Props) {
  const feed = useAudienceStore((s) => s.shopFeed)
  const customers = useAudienceStore((s) => s.customers)
  const customersById = useAudienceStore((s) => s.customersById)
  const fire = useAudienceStore((s) => s.fireShopTrigger)
  const open = useAudienceStore((s) => s.openCustomerDrawer)

  const fireCart = () => {
    const c = customers[0]
    if (!c) return
    void fire(brandId, c.id, 'cart_abandoned', {
      value_cents: 7900,
      product_ids: ['p_apparel_tee'],
    })
  }

  const fireLapsed = () => {
    const c = customers.find((c) => (c.tags ?? []).includes('lapsed')) ?? customers[1]
    if (!c) return
    void fire(brandId, c.id, 'subscription_lapsed', {
      product_id: 'p_digital_workshop',
      lapsed_days: 14,
    })
  }

  return (
    <section className="rounded-2xl border border-line bg-bg-card p-4">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Shop feed
        </h3>
        <div className="flex gap-1">
          <button
            onClick={fireCart}
            disabled={customers.length === 0}
            className="rounded-full border border-line bg-bg-soft px-2.5 py-1 text-[10px] uppercase tracking-[0.14em] text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-40"
            title="Fire a test cart_abandoned event for the first customer"
          >
            ⊗ cart
          </button>
          <button
            onClick={fireLapsed}
            disabled={customers.length === 0}
            className="rounded-full border border-line bg-bg-soft px-2.5 py-1 text-[10px] uppercase tracking-[0.14em] text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-40"
            title="Fire a test subscription_lapsed event"
          >
            ↧ lapsed
          </button>
        </div>
      </div>
      {feed.length === 0 ? (
        <div className="rounded-xl border border-dashed border-line px-3 py-2.5 text-[11px] text-fg-mute">
          Fire a test event to see the auto-personalize loop run.
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {feed.map((e) => {
            const customer = customersById[e.customer_id]
            const display =
              customer?.name?.trim() ||
              customer?.email ||
              e.customer_id.slice(-6)
            return (
              <motion.li
                key={e.id}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2 }}
                className="rounded-xl border border-line bg-bg-soft/40 px-3 py-2"
              >
                <button
                  onClick={() => open(e.customer_id)}
                  className="flex w-full items-baseline justify-between gap-2 text-left"
                >
                  <div className="min-w-0 truncate text-[11px]">
                    <span className="text-fg-dim">{e.at}</span>{' '}
                    <span className="font-mono text-fg-mute">{e.kind}</span>{' '}
                    · <span className="text-fg">{display}</span>
                  </div>
                </button>
                {e.subject_preview ? (
                  <div className="mt-1 truncate text-[11px] text-accent">
                    ✓ {e.subject_preview}
                  </div>
                ) : (
                  <div className="mt-1 text-[11px] italic text-fg-dim">
                    drafting…
                  </div>
                )}
              </motion.li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
