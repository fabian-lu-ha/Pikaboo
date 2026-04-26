import { useAudienceStore } from '../../stores/audienceStore'
import { CustomerRow } from './CustomerRow'

export function CustomerList() {
  const customers = useAudienceStore((s) => s.customers)
  const drawerCustomerId = useAudienceStore((s) => s.drawerCustomerId)
  const openCustomerDrawer = useAudienceStore((s) => s.openCustomerDrawer)
  const loading = useAudienceStore((s) => s.loadingCustomers)

  if (loading && customers.length === 0) {
    return (
      <div className="rounded-2xl border border-line bg-bg-card p-6 text-[11px] uppercase tracking-[0.18em] text-fg-mute">
        loading customers…
      </div>
    )
  }

  if (customers.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-line bg-bg-card px-5 py-6 text-sm text-fg-mute">
        No customers yet. Connect a CRM to import your audience.
      </div>
    )
  }

  return (
    <div className="rounded-2xl border border-line bg-bg-card p-2 shadow-[0_2px_10px_rgba(20,20,40,0.03)]">
      <div className="max-h-[calc(100vh-280px)] overflow-y-auto overscroll-contain pr-1 [scrollbar-width:thin]">
        <ul className="flex flex-col gap-1">
          {customers.map((c) => (
            <li key={c.id}>
              <CustomerRow
                customer={c}
                active={c.id === drawerCustomerId}
                onSelect={() => openCustomerDrawer(c.id)}
              />
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}
