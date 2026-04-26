import { create } from 'zustand'
import { bus } from '../events/bus'

// Single tenant per running browser session — the dashboard always shows
// the active brand's voice model, so we don't bother keying state by
// brand_id. If a second brand starts a training in another tab we'd need
// to scope this; for the hackathon it's intentionally simple.

export type VoiceModelStatus =
  | 'idle'
  | 'deep_scraping'
  | 'corpus_building'
  | 'corpus_built'
  | 'training_queued'
  | 'training'
  | 'ready'
  | 'failed'

export type VoiceCorpusEntities = {
  source: string
  total: number
  by_label: Record<string, string[]>
}

export type VoiceDeepScrape = {
  domain?: string
  discovered_urls: number
  fetched_pages: number
  text_chunks: number
  by_kind: Record<string, number>
}

export type VoiceCorpusMeta = {
  line_count: number
  breakdown: Record<string, number>
  jsonl_path: string | null
  entities: VoiceCorpusEntities | null
  deep_scrape: VoiceDeepScrape | null
  // Pioneer milestones written by the worker as it advances. The UI
  // uses presence of these to mark each pipeline stage 'done' even
  // after a downstream failure.
  pioneer_project_id?: string | null
  pioneer_training_job_id?: string | null
  current_stage?: string | null
  training_progress?: number | null
  // Live timing fields, written every poll while training is in flight.
  training_progress_percent?: number | null
  current_epoch?: number | null
  total_epochs?: number | null
  started_at?: string | null  // ISO8601, used to compute ETA
  created_at?: string | null
  provider_name?: string | null
  latest_log?: string | null
}

export type VoiceTrainingProgress = {
  job_id: string
  status: string
  stage: string
  progress: number // 0..1
  base_model: string
  simulator: boolean
}

export type VoiceModelState = {
  brandId: string | null
  status: VoiceModelStatus
  corpus: VoiceCorpusMeta | null
  training: VoiceTrainingProgress | null
  modelId: string | null
  adapterUrl: string | null
  simulator: boolean | null
  error: string | null
  upgradedAt: string | null
}

type Actions = {
  setBrand: (brandId: string) => void
  hydrate: (snapshot: Partial<VoiceModelState>) => void
  reset: () => void
}

const initial: VoiceModelState = {
  brandId: null,
  status: 'idle',
  corpus: null,
  training: null,
  modelId: null,
  adapterUrl: null,
  simulator: null,
  error: null,
  upgradedAt: null,
}

export const useVoiceModelStore = create<VoiceModelState & Actions>((set) => ({
  ...initial,
  setBrand: (brandId) => set({ brandId }),
  hydrate: (snapshot) => set(snapshot),
  reset: () => set(initial),
}))

// Hydrate from the backend on first load + after SSE reconnect. The
// status endpoint is the source of truth for terminal states (ready /
// failed) so a refresh while training is mid-flight still picks up.
export async function reconcileVoiceModel(brandId: string): Promise<void> {
  try {
    const r = await fetch(
      `/api/finetune/status?brand_id=${encodeURIComponent(brandId)}`,
    )
    if (!r.ok) return
    const d = (await r.json()) as {
      ok: boolean
      in_progress?: boolean
      status?: VoiceModelStatus | string
      voice_model_id?: string | null
      voice_adapter_url?: string | null
      corpus_meta?: {
        line_count?: number
        breakdown?: Record<string, number>
        jsonl_path?: string
        entities?: VoiceCorpusEntities
        deep_scrape?: VoiceDeepScrape
        current_stage?: string
        training_progress?: number
      }
      simulator?: boolean
    }
    if (!d.ok) return
    const cm = d.corpus_meta as
      | (Partial<VoiceCorpusMeta> & {
          deep_scrape?: VoiceDeepScrape
          entities?: VoiceCorpusEntities
        })
      | undefined
    // Build corpus state even on partial progress — worker writes
    // deep_scrape stats / project id / training job id incrementally
    // so the UI can render stage state during a failed run.
    const corpus: VoiceCorpusMeta | null =
      cm && (
        cm.line_count != null
        || cm.deep_scrape != null
        || cm.pioneer_project_id != null
        || cm.current_stage != null
      )
        ? {
            line_count: cm.line_count ?? 0,
            breakdown: cm.breakdown ?? {},
            jsonl_path: cm.jsonl_path ?? null,
            entities: cm.entities ?? null,
            deep_scrape: cm.deep_scrape ?? null,
            pioneer_project_id: cm.pioneer_project_id ?? null,
            pioneer_training_job_id: cm.pioneer_training_job_id ?? null,
            current_stage: cm.current_stage ?? null,
            training_progress: cm.training_progress ?? null,
            training_progress_percent: cm.training_progress_percent ?? null,
            current_epoch: cm.current_epoch ?? null,
            total_epochs: cm.total_epochs ?? null,
            started_at: cm.started_at ?? null,
            created_at: cm.created_at ?? null,
            provider_name: cm.provider_name ?? null,
            latest_log: cm.latest_log ?? null,
          }
        : null
    // Synthesise the training-progress object from the worker's
    // current_stage / training_progress that it wrote to corpus_meta.
    // The detached worker can't reach the parent's pyee bus, so polling
    // is how the frontend learns about progress.
    const stage = d.corpus_meta?.current_stage
    const progress = d.corpus_meta?.training_progress
    const training =
      stage || typeof progress === 'number'
        ? {
            job_id: d.voice_model_id ?? '',
            status: d.status ?? 'training',
            stage: stage ?? 'working…',
            progress: typeof progress === 'number' ? progress : 0,
            base_model: 'gemma-3-4b-it',
            simulator: false,
          }
        : null

    useVoiceModelStore.setState({
      brandId,
      status: (d.status as VoiceModelStatus) || 'idle',
      corpus,
      training,
      modelId: d.voice_model_id ?? null,
      adapterUrl: d.voice_adapter_url ?? null,
      simulator: d.simulator ?? null,
    })
  } catch {
    // non-fatal; SSE will recover
  }
}

bus.on('voice.deep_scraping', () => {
  useVoiceModelStore.setState({ status: 'deep_scraping', error: null })
})

bus.on('voice.deep_scraped', (p) => {
  useVoiceModelStore.setState((s) => ({
    corpus: {
      // Pre-build a corpus meta with just the deep-scrape row so the UI
      // can render the discovery stats before the corpus build finishes.
      line_count: s.corpus?.line_count ?? 0,
      breakdown: s.corpus?.breakdown ?? {},
      jsonl_path: s.corpus?.jsonl_path ?? null,
      entities: s.corpus?.entities ?? null,
      deep_scrape: {
        domain: p.domain,
        discovered_urls: p.discovered_urls,
        fetched_pages: p.fetched_pages,
        text_chunks: p.text_chunks,
        by_kind: p.by_kind,
      },
    },
  }))
})

bus.on('voice.corpus_building', () => {
  useVoiceModelStore.setState({ status: 'corpus_building', error: null })
})

bus.on('voice.corpus_built', (p) => {
  // Entities + deep_scrape arrive on the row read; the SSE payload is
  // intentionally light. We refetch the meta so the chip rows populate
  // immediately after build.
  useVoiceModelStore.setState((s) => ({
    status: 'corpus_built',
    corpus: {
      line_count: p.line_count,
      breakdown: p.breakdown,
      jsonl_path: p.jsonl_path,
      entities: s.corpus?.entities ?? null,
      deep_scrape: s.corpus?.deep_scrape ?? null,
    },
  }))
  if (useVoiceModelStore.getState().brandId) {
    void reconcileVoiceModel(useVoiceModelStore.getState().brandId as string)
  }
})

bus.on('voice.corpus_failed', (p) => {
  useVoiceModelStore.setState({ status: 'failed', error: p.error })
})

bus.on('voice.training_queued', (p) => {
  useVoiceModelStore.setState({
    status: 'training_queued',
    simulator: p.simulator,
    training: {
      job_id: p.job_id,
      status: 'queued',
      stage: 'queued for training',
      progress: 0,
      base_model: p.base_model,
      simulator: p.simulator,
    },
  })
})

bus.on('voice.training_progress', (p) => {
  useVoiceModelStore.setState((s) => ({
    status: p.status === 'succeeded' ? s.status : 'training',
    training: s.training
      ? {
          ...s.training,
          status: p.status,
          stage: p.stage,
          progress: p.progress,
        }
      : {
          job_id: p.job_id,
          status: p.status,
          stage: p.stage,
          progress: p.progress,
          base_model: 'gemma-3-4b-it',
          simulator: !!s.simulator,
        },
  }))
})

bus.on('voice.model_ready', (p) => {
  useVoiceModelStore.setState({
    status: 'ready',
    modelId: p.model_id,
    adapterUrl: p.adapter_url,
    simulator: p.simulator,
  })
})

bus.on('voice.model_upgraded', (p) => {
  useVoiceModelStore.setState({
    upgradedAt: new Date().toISOString(),
    modelId: p.model_id ?? null,
  })
})

bus.on('voice.training_failed', (p) => {
  useVoiceModelStore.setState({ status: 'failed', error: p.error })
})
