import { useState, type FormEvent } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useAudienceStore } from '../../stores/audienceStore'

type Props = {
  brandId: string
}

const PROVIDERS = [
  { id: 'mock', label: 'Mock CRM (demo)' },
  { id: 'shopify', label: 'Shopify' },
  { id: 'hubspot', label: 'HubSpot' },
  { id: 'klaviyo', label: 'Klaviyo' },
]

export function ConnectCRMModal({ brandId }: Props) {
  const open = useAudienceStore((s) => s.showConnectModal)
  const close = useAudienceStore((s) => s.closeConnectModal)
  const importFromCRM = useAudienceStore((s) => s.importFromCRM)
  const importing = useAudienceStore((s) => s.importing)
  const error = useAudienceStore((s) => s.error)

  const [provider, setProvider] = useState('mock')
  const [apiKey, setApiKey] = useState('')

  async function submit(e: FormEvent) {
    e.preventDefault()
    await importFromCRM(brandId, provider, apiKey ? { api_key: apiKey } : {})
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
            className="fixed left-1/2 top-1/2 z-50 w-[460px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-3xl border border-line bg-bg-card p-6 shadow-[0_20px_60px_rgba(20,20,40,0.18)]"
          >
            <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
              Audience · connect CRM
            </div>
            <h3 className="mt-1 font-serif text-2xl tracking-tight">
              Pull in your customers
            </h3>
            <p className="mt-1.5 text-sm text-fg-mute">
              The agent pulls customers, products, and event history. PII is
              redacted before any LLM call.
            </p>

            <form onSubmit={submit} className="mt-5 flex flex-col gap-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  Provider
                </span>
                <select
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
                >
                  {PROVIDERS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                  API key (optional for mock)
                </span>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk_…"
                  className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
                />
              </label>

              {error && (
                <div className="rounded-md border border-danger/40 bg-danger/5 px-3 py-2 text-[11px] text-danger">
                  {error}
                </div>
              )}

              <div className="mt-1 flex justify-end gap-2">
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
                  disabled={importing}
                  className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
                >
                  {importing ? 'importing…' : 'connect & import'}
                </button>
              </div>
            </form>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
