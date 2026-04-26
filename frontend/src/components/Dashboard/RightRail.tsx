import { useState, type FormEvent } from 'react'
import { AnimatePresence } from 'motion/react'
import { CompetitorRow } from './CompetitorRow'
import { CompetitorInsightModal } from './CompetitorInsightModal'
import type { Brand, Competitor } from './types'

export function RightRail({ brand }: { brand: Brand }) {
  const [adding, setAdding] = useState(false)
  const [newName, setNewName] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [optimistic, setOptimistic] = useState<Competitor[]>([])
  const [selected, setSelected] = useState<Competitor | null>(null)

  async function submitAdd(e: FormEvent) {
    e.preventDefault()
    const name = newName.trim()
    if (!name) return
    setSubmitting(true)
    setAddError(null)
    try {
      const r = await fetch('/api/onboarding/competitors/add', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          brand_id: brand.id,
          name,
          url: newUrl.trim() || null,
        }),
      })
      if (r.ok) {
        const c = (await r.json()) as Competitor
        setOptimistic((s) => [...s, c])
        setNewName('')
        setNewUrl('')
        setAdding(false)
      } else {
        const detail = await r.json().then((j) => j?.detail ?? null).catch(() => null)
        setAddError(detail ?? `Failed to add competitor (${r.status})`)
      }
    } catch {
      setAddError('Network error — please try again')
    } finally {
      setSubmitting(false)
    }
  }

  const allCompetitors = [...brand.competitors, ...optimistic]

  return (
    <aside className="px-5 pt-[88px]">
      <div className="panel p-5">
        <div className="flex items-center justify-between">
          <h3 className="text-[13px] font-semibold">Watchlist</h3>
          <button className="text-fg-dim hover:text-fg">⋯</button>
        </div>

        <ul className="mt-5 flex flex-col gap-4">
          {allCompetitors.length === 0 ? (
            <li className="text-xs text-fg-mute">No competitors yet.</li>
          ) : (
            allCompetitors.map((c) => (
              <CompetitorRow
                key={c.id}
                competitor={c}
                onClick={() => setSelected(c)}
              />
            ))
          )}
        </ul>

        {adding ? (
          <form
            onSubmit={submitAdd}
            className="hairline mt-5 flex flex-col gap-2 rounded-xl bg-bg-soft/40 p-3"
          >
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="Name (e.g. Notion)"
              className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
            />
            <input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="URL (optional)"
              className="rounded-md border border-line bg-bg-card px-3 py-2 text-sm outline-none focus:border-accent"
            />
            {addError && (
              <p className="text-xs text-red-500">{addError}</p>
            )}
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setAdding(false); setAddError(null) }}
                className="flex-1 rounded-md border border-line bg-bg-card py-1.5 text-xs text-fg-mute hover:text-fg"
              >
                cancel
              </button>
              <button
                type="submit"
                disabled={!newName.trim() || submitting}
                className="flex-1 rounded-md bg-accent py-1.5 text-xs font-medium text-white disabled:bg-accent-dim"
              >
                {submitting ? 'adding…' : 'add'}
              </button>
            </div>
          </form>
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line py-3 text-[13px] text-fg-mute transition hover:border-accent hover:text-accent"
          >
            <span className="text-accent">+</span> Add Competitor
          </button>
        )}
      </div>
      <AnimatePresence>
        {selected && (
          <CompetitorInsightModal
            competitor={selected}
            onClose={() => setSelected(null)}
          />
        )}
      </AnimatePresence>
    </aside>
  )
}
