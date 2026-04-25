import { useState } from 'react'
import { motion } from 'motion/react'
import { useOnboardingStore } from '../stores/onboardingStore'
import { InitialsAvatar } from '../components/InitialsAvatar'

const PLATFORMS = ['x', 'linkedin', 'youtube', 'instagram', 'tiktok'] as const

export function StepReview({ onComplete }: { onComplete: () => void }) {
  const brandId = useOnboardingStore((s) => s.brandId)
  const initialHandles = useOnboardingStore(
    (s) => s.scraped?.handles ?? {},
  )
  const initialCompetitors = useOnboardingStore((s) => s.competitors)

  const [handles, setHandles] = useState<Record<string, string>>(
    initialHandles,
  )
  const [comps, setComps] = useState(initialCompetitors)
  const [submitting, setSubmitting] = useState(false)

  async function finish() {
    if (!brandId) return
    setSubmitting(true)

    await fetch('/api/onboarding/competitors', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        brand_id: brandId,
        competitors: comps.map((c) => ({
          id: c.id,
          name: c.name,
          url: c.url,
          reason: c.reason,
        })),
      }),
    })
    await fetch('/api/onboarding/handles', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ brand_id: brandId, handles }),
    })
    await fetch('/api/onboarding/complete', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ brand_id: brandId }),
    })

    onComplete()
  }

  return (
    <div className="flex flex-col">
      <div className="mx-auto w-full max-w-4xl px-10 py-12">
        <span className="text-[11px] font-medium uppercase tracking-[0.2em] text-fg-mute">
          Step 03 — Confirm
        </span>
        <h1 className="mt-3 text-4xl font-medium leading-tight tracking-tight">
          Anything{' '}
          <span
            className="font-serif italic text-accent"
            style={{ fontVariationSettings: '"opsz" 144, "SOFT" 50' }}
          >
            we missed?
          </span>
        </h1>
        <p className="mt-3 max-w-lg text-base text-fg-mute">
          Your handles, plus competitors. Drop or edit anything that's off.
        </p>

        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mt-8 rounded-2xl border border-line bg-bg-card p-6 shadow-[0_2px_12px_rgba(20,20,40,0.03)]"
        >
          <h2 className="text-[11px] font-medium uppercase tracking-[0.2em] text-fg-mute">
            01 · Social handles
          </h2>
          <div className="mt-5 grid grid-cols-1 gap-x-6 gap-y-4 sm:grid-cols-2">
            {PLATFORMS.map((p) => (
              <label key={p} className="flex flex-col gap-1.5">
                <span className="text-xs font-medium text-fg-mute">{p}</span>
                <input
                  value={handles[p] ?? ''}
                  onChange={(e) =>
                    setHandles({ ...handles, [p]: e.target.value })
                  }
                  placeholder={`https://${p === 'x' ? 'x.com' : `${p}.com`}/...`}
                  className="rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none placeholder:text-fg-dim focus:border-accent"
                />
              </label>
            ))}
          </div>
        </motion.section>

        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.08 }}
          className="mt-5 rounded-2xl border border-line bg-bg-card p-6 shadow-[0_2px_12px_rgba(20,20,40,0.03)]"
        >
          <h2 className="text-[11px] font-medium uppercase tracking-[0.2em] text-fg-mute">
            02 · Competitors
          </h2>
          <ul className="mt-5 flex flex-col gap-2.5">
            {comps.map((c) => (
              <li
                key={c.id}
                className="flex items-center gap-3 rounded-xl border border-line-soft bg-bg-soft/50 p-3"
              >
                <InitialsAvatar name={c.name} size="md" />
                <input
                  value={c.name}
                  onChange={(e) =>
                    setComps(
                      comps.map((x) =>
                        x.id === c.id
                          ? { ...x, name: e.target.value }
                          : x,
                      ),
                    )
                  }
                  className="w-1/3 rounded-md bg-transparent px-2 py-1 text-sm font-medium outline-none focus:bg-bg-card"
                />
                <input
                  value={c.url ?? ''}
                  onChange={(e) =>
                    setComps(
                      comps.map((x) =>
                        x.id === c.id ? { ...x, url: e.target.value } : x,
                      ),
                    )
                  }
                  placeholder="https://…"
                  className="flex-1 rounded-md bg-transparent px-2 py-1 font-mono text-xs text-fg-mute outline-none placeholder:text-fg-dim focus:bg-bg-card"
                />
                <button
                  type="button"
                  onClick={() =>
                    setComps(comps.filter((x) => x.id !== c.id))
                  }
                  className="text-xs text-fg-dim hover:text-danger"
                >
                  remove
                </button>
              </li>
            ))}
          </ul>
        </motion.section>
      </div>

      <div className="sticky bottom-0 flex items-center justify-between border-t border-line bg-bg-card/85 px-10 py-4 backdrop-blur">
        <p className="text-xs text-fg-mute">
          {submitting ? '◐ saving…' : '● ready to ship'}
        </p>
        <button
          onClick={finish}
          disabled={submitting}
          className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-white shadow-[0_4px_14px_rgba(111,92,255,0.4)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          {submitting ? 'Saving…' : 'Open the app →'}
        </button>
      </div>
    </div>
  )
}
