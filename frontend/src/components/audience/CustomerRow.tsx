import { motion } from 'motion/react'
import { InitialsAvatar } from '../InitialsAvatar'
import {
  acquisitionBadge,
  formatPrice,
  relativeFromIso,
  type Customer,
} from '../../lib/audience'

type Props = {
  customer: Customer
  active: boolean
  onSelect: () => void
}

export function CustomerRow({ customer, active, onSelect }: Props) {
  const display = customer.name?.trim() || customer.email
  const badge = acquisitionBadge(customer.acquisition)
  return (
    <motion.button
      type="button"
      onClick={onSelect}
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition ${
        active
          ? 'border-accent bg-accent-soft/40 shadow-[0_2px_10px_rgba(111,92,255,0.08)]'
          : 'border-transparent hover:border-line hover:bg-bg-soft/50'
      }`}
    >
      <InitialsAvatar name={display} size="sm" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <div className="truncate text-sm font-medium leading-tight">
            {display}
          </div>
          <div className="shrink-0 text-[11px] tabular-nums text-fg-mute">
            {formatPrice(customer.total_spend_cents)}
          </div>
        </div>
        <div className="mt-0.5 flex items-baseline justify-between gap-2">
          <div className="truncate text-[11px] text-fg-dim">
            {customer.email}
          </div>
          <div className="shrink-0 text-[10px] uppercase tracking-[0.14em] text-fg-dim">
            {relativeFromIso(customer.last_active_at)}
          </div>
        </div>
        {(customer.tags.length > 0 || badge) && (
          <div className="mt-1.5 flex flex-wrap items-center gap-1">
            {badge && (
              <span
                className="rounded-full border border-line bg-bg-soft px-1.5 py-0.5 text-[10px] text-fg-mute"
                title="Acquisition source"
              >
                {badge}
              </span>
            )}
            {customer.tags.slice(0, 3).map((t) => (
              <span
                key={t}
                className="rounded-full border border-line bg-bg-card px-1.5 py-0.5 text-[10px] text-fg-mute"
              >
                {t}
              </span>
            ))}
            {customer.tags.length > 3 && (
              <span className="text-[10px] text-fg-dim">
                +{customer.tags.length - 3}
              </span>
            )}
          </div>
        )}
      </div>
    </motion.button>
  )
}
