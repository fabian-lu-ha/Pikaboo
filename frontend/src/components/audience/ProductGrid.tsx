import { motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'
import { formatPrice } from '../../lib/audience'

export function ProductGrid() {
  const products = useAudienceStore((s) => s.products)
  const loading = useAudienceStore((s) => s.loadingProducts)

  if (loading && products.length === 0) {
    return (
      <div className="rounded-2xl border border-line bg-bg-card p-6 text-[11px] uppercase tracking-[0.18em] text-fg-mute">
        loading products…
      </div>
    )
  }

  if (products.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-bg-card px-5 py-6 text-sm text-fg-mute">
        No products imported yet.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {products.map((p, i) => (
        <motion.article
          key={p.id}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: Math.min(i * 0.02, 0.2) }}
          className="overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
        >
          {p.image_url ? (
            <div className="aspect-[4/3] overflow-hidden bg-bg-soft/50">
              <img
                src={p.image_url}
                alt=""
                className="block h-full w-full object-cover"
              />
            </div>
          ) : (
            <div className="grid aspect-[4/3] place-items-center bg-bg-soft/50 text-[11px] uppercase tracking-[0.18em] text-fg-dim">
              no image
            </div>
          )}
          <div className="px-4 py-3">
            <div className="flex items-baseline justify-between gap-2">
              <h4 className="truncate text-sm font-medium">{p.name}</h4>
              <span className="shrink-0 text-sm tabular-nums text-fg">
                {formatPrice(p.price_cents)}
              </span>
            </div>
            {p.category && (
              <div className="mt-1.5 inline-block rounded-full border border-line bg-bg-card px-2 py-0.5 text-[10px] uppercase tracking-[0.14em] text-fg-mute">
                {p.category}
              </div>
            )}
            {p.description && (
              <p className="mt-2 line-clamp-2 text-xs text-fg-mute">
                {p.description}
              </p>
            )}
          </div>
        </motion.article>
      ))}
    </div>
  )
}
