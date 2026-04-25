import { create } from 'zustand'
import {
  bus,
  type AgentDraft,
  type LiftPrediction,
  type PeecSnapshot,
  type PeecTarget,
} from '../events/bus'

type Step = { id: string; label: string; at: string }

type Status = 'idle' | 'running' | 'bundled' | 'failed'

type ChannelDraftBundle = {
  channel: string
  label: string
  kind: string
  title: string
  body: string
  image_url: string | null
  image_aspect: string | null
}

type CampaignBundle = {
  user_request: string
  drafts?: ChannelDraftBundle[]
  blog?: { title: string; body: string }
  social?: { linkedin: string }
  hero_image_url: string | null
  predicted_lift: LiftPrediction
  target_prompts: string[]
}

type State = {
  campaignId: string | null
  brandId: string | null
  userRequest: string | null
  status: Status
  steps: Step[]
  drafts: AgentDraft[]
  heroImage: string | null
  lift: LiftPrediction | null
  bundle: CampaignBundle | null
  error: string | null
  peec: PeecSnapshot | null
  peecTargets: PeecTarget[]
  peecUnavailable: string | null
}

type Actions = {
  reset: () => void
}

const initial: State = {
  campaignId: null,
  brandId: null,
  userRequest: null,
  status: 'idle',
  steps: [],
  drafts: [],
  heroImage: null,
  lift: null,
  bundle: null,
  error: null,
  peec: null,
  peecTargets: [],
  peecUnavailable: null,
}

export const useAgentSessionStore = create<State & Actions>((set) => ({
  ...initial,
  reset: () => set(initial),
}))

bus.on('chat.submitted', ({ text }) => {
  useAgentSessionStore.setState({
    ...initial,
    userRequest: text,
    status: 'running',
  })
})

bus.on('agent.started', (p) => {
  useAgentSessionStore.setState({
    campaignId: p.campaign_id,
    brandId: p.brand_id,
    userRequest: p.user_request,
    status: 'running',
  })
})

bus.on('agent.step', (p) => {
  useAgentSessionStore.setState((s) => {
    if (p.campaign_id && s.campaignId && p.campaign_id !== s.campaignId) {
      return s
    }
    return {
      steps: [...s.steps, { id: p.id, label: p.label, at: p.at }],
    }
  })
})

bus.on('agent.failed', (p) => {
  useAgentSessionStore.setState({ status: 'failed', error: p.error })
})

bus.on('draft.created', (p) => {
  useAgentSessionStore.setState((s) => {
    if (p.campaign_id && s.campaignId && p.campaign_id !== s.campaignId) {
      return s
    }
    if (p.channel === 'hero_image') {
      return { heroImage: p.body || p.preview || null }
    }
    const without = s.drafts.filter((d) => d.channel !== p.channel)
    return { drafts: [...without, p] }
  })
})

bus.on('lift.predicted', (p) => {
  useAgentSessionStore.setState((s) => {
    if (p.campaign_id && s.campaignId && p.campaign_id !== s.campaignId) {
      return s
    }
    const {
      campaign_id: _id,
      ...lift
    } = p
    return { lift }
  })
})

bus.on('agent.peec_data_fetched', (p) => {
  useAgentSessionStore.setState((s) => {
    if (s.campaignId && p.campaign_id !== s.campaignId) return s
    return {
      peec: p.snapshot,
      peecTargets: p.target_prompts ?? [],
      peecUnavailable: null,
    }
  })
})

bus.on('agent.peec_unavailable', (p) => {
  useAgentSessionStore.setState((s) => {
    if (s.campaignId && p.campaign_id !== s.campaignId) return s
    return { peecUnavailable: p.reason || 'unavailable' }
  })
})

bus.on('campaign.bundled', (p) => {
  useAgentSessionStore.setState((s) => {
    if (s.campaignId && p.campaign_id !== s.campaignId) return s
    return {
      status: 'bundled',
      bundle: p.bundle,
    }
  })
})
