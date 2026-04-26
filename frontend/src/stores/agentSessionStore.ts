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

type SessionSnapshot = {
  campaignId: string
  brandId: string | null
  userRequest: string | null
  status: Status
  steps: Step[]
  drafts: AgentDraft[]
  heroImage: string | null
  lift: LiftPrediction | null
  bundle: CampaignBundle | null
  peec: PeecSnapshot | null
  peecTargets: PeecTarget[]
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
  snapshots: Record<string, SessionSnapshot>
}

type Actions = {
  reset: () => void
  restore: (campaignId: string) => Promise<void>
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
  snapshots: {},
}

function snapshotOf(s: State): SessionSnapshot | null {
  if (!s.campaignId) return null
  return {
    campaignId: s.campaignId,
    brandId: s.brandId,
    userRequest: s.userRequest,
    status: s.status,
    steps: s.steps,
    drafts: s.drafts,
    heroImage: s.heroImage,
    lift: s.lift,
    bundle: s.bundle,
    peec: s.peec,
    peecTargets: s.peecTargets,
  }
}

export const useAgentSessionStore = create<State & Actions>((set, get) => ({
  ...initial,
  // ``reset`` clears the active session view but preserves the snapshot map
  // so Recent Runs can still restore prior runs.
  reset: () =>
    set((s) => ({ ...initial, snapshots: s.snapshots })),
  restore: async (campaignId: string) => {
    // Fast path: in-memory snapshot from this browser session.
    const cached = get().snapshots[campaignId]
    if (cached) {
      set({
        campaignId: cached.campaignId,
        brandId: cached.brandId,
        userRequest: cached.userRequest,
        status: cached.status,
        steps: cached.steps,
        drafts: cached.drafts,
        heroImage: cached.heroImage,
        lift: cached.lift,
        bundle: cached.bundle,
        error: null,
        peec: cached.peec,
        peecTargets: cached.peecTargets,
        peecUnavailable: null,
      })
      return
    }

    // Slow path: fetch the campaign + bundle from the backend so historical
    // runs (rendered into Recent Runs from /api/campaigns/recent) restore
    // with the same fidelity as a fresh session.
    try {
      const r = await fetch(
        `/api/campaigns/${encodeURIComponent(campaignId)}`,
      )
      if (!r.ok) throw new Error(`status ${r.status}`)
      const detail = (await r.json()) as {
        id: string
        brand_id: string
        title: string
        bundle: {
          user_request?: string
          drafts?: {
            channel: string
            label: string
            kind: string
            title: string
            body: string
            image_url: string | null
            image_aspect: string | null
          }[]
          hero_image_url?: string | null
          predicted_lift?: LiftPrediction
          target_prompts?: string[]
          blog?: { title: string; body: string }
          social?: { linkedin: string }
        } | null
      }
      const b = detail.bundle ?? {}
      const drafts: AgentDraft[] = (b.drafts ?? []).map((d) => ({
        campaign_id: detail.id,
        channel: d.channel,
        title: d.title,
        preview: d.body.slice(0, 160),
        body: d.body,
      }))
      set({
        campaignId: detail.id,
        brandId: detail.brand_id,
        userRequest: b.user_request ?? detail.title,
        status: 'bundled',
        steps: [],
        drafts,
        heroImage: b.hero_image_url ?? null,
        lift: b.predicted_lift ?? null,
        bundle: b as CampaignBundle,
        error: null,
        peec: null,
        peecTargets: [],
        peecUnavailable: null,
      })
    } catch (e) {
      set({ status: 'failed', error: `restore failed: ${(e as Error).message}` })
    }
  },
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
  // Prefetch image URLs into the browser cache the moment the event lands.
  // By the time the channel card mounts and renders an <img> tag, the bytes
  // are already in cache → the picture appears with no perceptible delay.
  if (
    typeof window !== 'undefined' &&
    (p.channel === 'hero_image' || p.channel.endsWith('_image'))
  ) {
    const url = p.body || p.preview
    if (url) {
      const pre = new Image()
      pre.decoding = 'async'
      // Allow same-origin cookies for /api/storage local-mode URLs.
      pre.src = url
    }
  }

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
    const next: State = { ...s, status: 'bundled', bundle: p.bundle }
    const snap = snapshotOf(next)
    return {
      status: next.status,
      bundle: next.bundle,
      snapshots: snap
        ? { ...s.snapshots, [snap.campaignId]: snap }
        : s.snapshots,
    }
  })
})
