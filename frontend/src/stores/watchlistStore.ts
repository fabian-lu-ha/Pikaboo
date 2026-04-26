import { create } from 'zustand'
import { bus } from '../events/bus'

// Watchlist store — keeps a small in-session memory of the most recent
// `competitor.surged` event per competitor so the row pill can reflect a
// real surge instead of a hash-based placeholder. Pure session state; no
// persistence — restarting the page resets the table, and the Peec
// snapshot in agentSessionStore handles the longer-lived signals.

export type Surge = {
  prompt: string
  delta: number  // share-of-voice / visibility delta — fraction (e.g. 0.12 = +12pp)
  at: number     // wall-clock ms; lets the row decay surges over 24h
}

type State = {
  surges: Record<string, Surge>
}

type Actions = {
  reset: () => void
}

export const useWatchlistStore = create<State & Actions>((set) => ({
  surges: {},
  reset: () => set({ surges: {} }),
}))

// Subscribe at module load. The competitor.surged event is emitted by the
// backend agent when the Peec MCP returns a competitor delta beyond the
// alert threshold; we keep only the latest event per competitor.
bus.on('competitor.surged', (e) => {
  const key = (e.competitor ?? '').toLowerCase().trim()
  if (!key) return
  useWatchlistStore.setState((s) => ({
    surges: {
      ...s.surges,
      [key]: {
        prompt: e.prompt,
        delta: typeof e.delta === 'number' ? e.delta : 0,
        at: Date.now(),
      },
    },
  }))
})
