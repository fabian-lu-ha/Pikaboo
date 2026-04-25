import { create } from 'zustand'
import { bus } from '../events/bus'

type AgentStep = { id: string; label: string; at: string }

type State = {
  steps: AgentStep[]
}

type Actions = {
  reset: () => void
}

export const useAgentStore = create<State & Actions>((set) => ({
  steps: [],
  reset: () => set({ steps: [] }),
}))

bus.on('agent.step', (step) => {
  useAgentStore.setState((s) => ({ steps: [...s.steps, step] }))
})
