import { useState, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'

type Props = {
  brandId: string
}

type Provider = {
  id: string
  label: string
  needsKey: boolean
  helper: string
  keyPlaceholder?: string
}

const PROVIDERS: Provider[] = [
  {
    id: 'hubspot',
    label: 'HubSpot',
    needsKey: true,
    helper:
      'Paste a Private App access token (Settings → Integrations → Private Apps). Needs the crm.objects.contacts.read, crm.objects.products.read, and oauth scopes.',
    keyPlaceholder: 'pat-eu1-…',
  },
  {
    id: 'mock',
    label: 'Sample data (no signup)',
    needsKey: false,
    helper:
      '30 deterministic customers, 12 products, full event history. Use this to explore without connecting a real CRM.',
  },
  { id: 'shopify', label: 'Shopify (coming soon)', needsKey: true, helper: 'Adapter not wired yet.' },
  { id: 'klaviyo', label: 'Klaviyo (coming soon)', needsKey: true, helper: 'Adapter not wired yet.' },
]

export function ConnectCRMModal({ brandId }: Props) {
  const open = useAudienceStore((s) => s.showConnectModal)
  const close = useAudienceStore((s) => s.closeConnectModal)
  const importFromCRM = useAudienceStore((s) => s.importFromCRM)
  const importing = useAudienceStore((s) => s.importing)
  const error = useAudienceStore((s) => s.error)

  const [providerId, setProviderId] = useState('hubspot')
  const [apiKey, setApiKey] = useState('')

  const provider =
    PROVIDERS.find((p) => p.id === providerId) ?? PROVIDERS[0]
  const disabled = importing || (provider.needsKey && !apiKey.trim())

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (provider.needsKey && !apiKey.trim()) return
    const credentials = provider.needsKey ? { api_key: apiKey.trim() } : {}
    await importFromCRM(brandId, providerId, credentials)
  }

  async function loadSampleData() {
    await importFromCRM(brandId, 'mock', {})
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={importing ? undefined : close}
            className="fixed inset-0 z-40 bg-fg/30 backdrop-blur-[2px]"
          />
          <motion.div
            initial={{ opacity: 0, y: 14, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.3 }}
            className="fixed left-1/2 top-1/2 z-50 w-[480px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-3xl border border-line bg-bg-card p-6 shadow-[0_20px_60px_rgba(20,20,40,0.18)]"
          >
            <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
              Audience · connect CRM
            </div>
            <h3 className="mt-1 font-serif text-2xl tracking-tight">
              Pull in your customers
            </h3>
            <p className="mt-1.5 text-sm text-fg-mute">
              Connect HubSpot to use your real contacts and product catalog.
              PII is redacted before any LLM call.
            </p>

            <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  Provider
                </span>
                <select
                  value={providerId}
                  onChange={(e) => {
                    setProviderId(e.target.value)
                    setApiKey('')
                  }}
                  className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
                <span className="text-[11px] leading-snug text-fg-mute">
                  {provider.helper}
                </span>
              </label>

              {provider.needsKey && (
                <label className="flex flex-col gap-1.5">
                  <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                    Access token
                  </span>
                  <input
                    type="password"
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    placeholder={provider.keyPlaceholder ?? 'sk_…'}
                    className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
                  />
                </label>
              )}

              {error && (
                <div className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-[11px] text-danger">
                  {error}
                </div>
              )}

              <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                <button
                  type="button"
                  onClick={loadSampleData}
                  disabled={importing}
                  className="text-[11px] text-fg-mute underline-offset-2 transition hover:text-accent hover:underline disabled:opacity-60"
                >
                  or load sample data instead
                </button>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={close}
                    disabled={importing}
                    className="rounded-full border border-line bg-bg-card px-4 py-2 text-xs text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
                  >
                    cancel
                  </button>
                  <button
                    type="submit"
                    disabled={disabled}
                    className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
                  >
                    {importing ? 'importing…' : 'connect & import'}
                  </button>
                </div>
              </div>
            </form>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
