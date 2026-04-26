import {
  ADDON_LABELS,
  DISCOUNT_TYPE_LABELS,
  type AddonKind,
  type DiscountType,
  type OfferPolicy,
} from '../../lib/audience'

type Props = {
  value: Partial<OfferPolicy>
  onChange: (next: Partial<OfferPolicy>) => void
  /** The effective (merged) policy from the API. Greyed-out hints reference this. */
  defaults: OfferPolicy
  /** When true, renders compact for inline use inside drawers. */
  compact?: boolean
}

const ALL_DISCOUNT_TYPES: DiscountType[] = [
  'percent',
  'fixed_amount',
  'free_shipping',
  'bogo',
]

const ALL_ADDONS: AddonKind[] = [
  'free_returns',
  'gift_wrap',
  'expedited_shipping',
]

export function OfferPolicyEditor({ value, onChange, defaults, compact }: Props) {
  function update<K extends keyof OfferPolicy>(key: K, v: OfferPolicy[K]) {
    onChange({ ...value, [key]: v })
  }

  const maxDiscount = value.max_discount_pct ?? defaults.max_discount_pct
  const allowedTypes =
    value.allowed_discount_types ?? defaults.allowed_discount_types
  const allowBundles = value.allow_bundles ?? defaults.allow_bundles
  const maxBundleSize = value.max_bundle_size ?? defaults.max_bundle_size
  const allowedAddons = value.allowed_addons ?? defaults.allowed_addons
  const expirationDays = value.expiration_max_days ?? defaults.expiration_max_days
  const forbidUrgency =
    value.forbid_urgency_language ?? defaults.forbid_urgency_language

  const isExplicit = (k: keyof OfferPolicy) => value[k] !== undefined

  return (
    <div className={`flex flex-col ${compact ? 'gap-3' : 'gap-5'}`}>
      {/* Max discount */}
      <Field
        label="Max discount"
        explicit={isExplicit('max_discount_pct')}
        defaultLabel={`default: ${defaults.max_discount_pct}%`}
      >
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={50}
            value={maxDiscount}
            onChange={(e) => update('max_discount_pct', Number(e.target.value))}
            className="flex-1 accent-accent"
          />
          <span className="w-10 text-right tabular-nums text-sm font-medium">
            {maxDiscount}%
          </span>
        </div>
      </Field>

      {/* Discount types */}
      <Field
        label="Allowed discount types"
        explicit={isExplicit('allowed_discount_types')}
        defaultLabel={`default: ${defaults.allowed_discount_types
          .map((t) => DISCOUNT_TYPE_LABELS[t])
          .join(', ')}`}
      >
        <Chips
          options={ALL_DISCOUNT_TYPES}
          selected={allowedTypes}
          labels={DISCOUNT_TYPE_LABELS}
          onToggle={(opt) => {
            const has = allowedTypes.includes(opt)
            update(
              'allowed_discount_types',
              has ? allowedTypes.filter((x) => x !== opt) : [...allowedTypes, opt],
            )
          }}
        />
      </Field>

      {/* Bundles */}
      <Field
        label="Bundles"
        explicit={isExplicit('allow_bundles') || isExplicit('max_bundle_size')}
        defaultLabel={`default: ${defaults.allow_bundles ? 'allowed' : 'off'}, max ${defaults.max_bundle_size}`}
      >
        <div className="flex items-center gap-4">
          <Toggle
            on={allowBundles}
            onChange={(b) => update('allow_bundles', b)}
            label={allowBundles ? 'Allowed' : 'Off'}
          />
          <div className="flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-[0.14em] text-fg-mute">
              max size
            </span>
            <input
              type="number"
              min={1}
              max={10}
              value={maxBundleSize}
              disabled={!allowBundles}
              onChange={(e) =>
                update(
                  'max_bundle_size',
                  Math.max(1, Math.min(10, Number(e.target.value) || 1)),
                )
              }
              className="w-16 rounded-md border border-line bg-bg-card px-2 py-1 text-sm tabular-nums outline-none focus:border-accent disabled:opacity-50"
            />
          </div>
        </div>
      </Field>

      {/* Addons */}
      <Field
        label="Allowed add-ons"
        explicit={isExplicit('allowed_addons')}
        defaultLabel={`default: ${defaults.allowed_addons
          .map((t) => ADDON_LABELS[t])
          .join(', ') || 'none'}`}
      >
        <Chips
          options={ALL_ADDONS}
          selected={allowedAddons}
          labels={ADDON_LABELS}
          onToggle={(opt) => {
            const has = allowedAddons.includes(opt)
            update(
              'allowed_addons',
              has ? allowedAddons.filter((x) => x !== opt) : [...allowedAddons, opt],
            )
          }}
        />
      </Field>

      {/* Expiration */}
      <Field
        label="Expiration window"
        explicit={isExplicit('expiration_max_days')}
        defaultLabel={`default: ${defaults.expiration_max_days} days`}
      >
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={1}
            max={30}
            value={expirationDays}
            onChange={(e) =>
              update('expiration_max_days', Number(e.target.value))
            }
            className="flex-1 accent-accent"
          />
          <span className="w-12 text-right tabular-nums text-sm font-medium">
            {expirationDays}d
          </span>
        </div>
      </Field>

      {/* Urgency language */}
      <Field
        label="Urgency language"
        explicit={isExplicit('forbid_urgency_language')}
        defaultLabel={`default: ${defaults.forbid_urgency_language ? 'forbidden' : 'allowed'}`}
      >
        <Toggle
          on={forbidUrgency}
          onChange={(b) => update('forbid_urgency_language', b)}
          label={
            forbidUrgency
              ? 'Forbidden ("act now / limited time")'
              : 'Allowed'
          }
        />
      </Field>
    </div>
  )
}

function Field({
  label,
  explicit,
  defaultLabel,
  children,
}: {
  label: string
  explicit: boolean
  defaultLabel: string
  children: React.ReactNode
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          {label}
        </div>
        <span
          className={`text-[10px] uppercase tracking-[0.14em] ${
            explicit ? 'text-fg-dim' : 'text-fg-dim/70 italic'
          }`}
        >
          {defaultLabel}
        </span>
      </div>
      <div className="mt-2">{children}</div>
    </div>
  )
}

function Chips<T extends string>({
  options,
  selected,
  labels,
  onToggle,
}: {
  options: T[]
  selected: T[]
  labels: Record<T, string>
  onToggle: (opt: T) => void
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((opt) => {
        const on = selected.includes(opt)
        return (
          <button
            key={opt}
            type="button"
            onClick={() => onToggle(opt)}
            className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
              on
                ? 'border-accent bg-accent/10 text-accent'
                : 'border-line bg-bg-card text-fg-mute hover:border-accent hover:text-accent'
            }`}
          >
            {labels[opt]}
          </button>
        )
      })}
    </div>
  )
}

function Toggle({
  on,
  onChange,
  label,
}: {
  on: boolean
  onChange: (next: boolean) => void
  label: string
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!on)}
      className="inline-flex items-center gap-2 text-sm"
    >
      <span
        className={`relative inline-block h-5 w-9 rounded-full transition ${
          on ? 'bg-accent' : 'bg-line'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${
            on ? 'left-[18px]' : 'left-0.5'
          }`}
        />
      </span>
      <span className="text-fg-mute">{label}</span>
    </button>
  )
}
