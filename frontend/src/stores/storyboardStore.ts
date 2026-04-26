import { create } from 'zustand'
import {
  bus,
  type AudienceSegment,
  type CastBinding,
  type CastKind,
  type CastMember,
  type CinematicBrief,
  type DesignTemplate,
  type Effect,
  type FocalZone,
  type FrameKind,
  type SegmentTarget,
  type StoryboardEndCard,
  type StoryboardFrame,
  type StoryboardNarrative,
  type StoryboardTitleCard,
  type VeoQuality,
  type VideoAspect,
  type VoiceoverSpec,
} from '../events/bus'

export type VoiceoverStatus = 'idle' | 'generating' | 'ready' | 'failed'

export type FrameStatus = 'idle' | 'generating' | 'ready' | 'failed'
export type ClipStatus = 'idle' | 'generating' | 'ready' | 'failed'

// Improvement loop — multimodal Gemini critic + smart partial re-render.
export type CritiqueSeverity = 'high' | 'medium' | 'low'
export type CritiqueCategory =
  | 'contrast'
  | 'cut'
  | 'motion'
  | 'composition'
  | 'pacing'
  | 'narrative'
  | 'consistency'
export type MutationCost = 'free' | 'render' | 'veo'

// Source tag for the dual-pass critic. "macro" = the existing thumbnail
// critic (caption/composition/cuts/motion narrative). "effects" = the
// motion-graphics second pass that watches the full video and targets
// the kinetic_text / lower_third / spotlight / etc. layer. Optional so
// older cached plans without the tag still parse.
export type CritiqueSource = 'macro' | 'effects'

export type CritiqueWeakness = {
  id: string
  frame_id: string | null
  transition: string | null
  issue: string
  severity: CritiqueSeverity
  category: CritiqueCategory
  source?: CritiqueSource
}

export type CritiqueMutation = {
  id: string
  weakness_ids: string[]
  target: string
  from: unknown
  to: unknown
  reason: string
  cost: MutationCost
  estimated_seconds: number
  source?: CritiqueSource
}

export type CritiquePlan = {
  storyboard_id: string
  video_url: string
  summary: string
  weaknesses: CritiqueWeakness[]
  mutations: CritiqueMutation[]
  error?: string | null
}

export type ImprovementStatus =
  | 'idle'
  | 'critiquing'
  | 'review'
  | 'applying'
  | 'failed'

export type StoryboardVersion = {
  version_number: number
  video_url: string | null
  summary: string | null
  mutation_count: number
  created_at: string | null
}

export type Frame = {
  id: string
  // 'live_action' (default — Veo clip + caption) or 'design_sequence' (a
  // pure-graphic Remotion template, no Veo). The latter has template +
  // template_params populated and skips clip/keyframe generation entirely.
  kind: FrameKind
  prompt: string
  caption: string
  duration_ms: number
  image_url: string | null
  status: FrameStatus
  error: string | null
  cast_refs: string[]
  focal_zone: FocalZone
  stale: boolean
  motion: string
  clip_url: string | null
  clip_status: ClipStatus
  clip_error: string | null
  // Set while scene_gen is backing off after a transient Veo 5xx. Cleared
  // on success/failure. UI uses it to render "Retrying 2/4..." instead of
  // looking frozen during the exponential backoff sleep.
  clip_retry: {
    phase: 'submit' | 'poll'
    attempt: number
    max_attempts: number
    delay_s: number
    reason: string
  } | null
  // Motion-graphics overlays the planner attached to this shot. The user
  // can preview them in the storyboard panel and toggle individual ones.
  effects: Effect[]
  // design_sequence-only — picks Remotion template + its params payload.
  // Both null on live_action frames (most of them).
  template: DesignTemplate | null
  template_params: Record<string, unknown> | null
}

export type CastSlotStatus = 'idle' | 'generating' | 'ready' | 'failed'

export type CastSlot = CastMember & {
  status: CastSlotStatus
  error: string | null
  narrative_purpose: string
}

export type StoryboardStatus =
  | 'idle'
  | 'suggesting'
  | 'generating_ingredients'
  | 'editing'
  | 'rendering'
  | 'rendered'
  | 'failed'

type RenderFramePayload = {
  id: string
  // Mirrors backend RenderFrameIn.kind. Defaults to live_action if omitted
  // so older clients keep working.
  kind?: FrameKind
  prompt: string
  caption: string
  duration_ms: number
  image_url?: string
  clip_url?: string
  focal_zone: FocalZone
  effects?: Effect[]
  // design_sequence-only — the Remotion template + its params.
  template?: DesignTemplate
  template_params?: Record<string, unknown>
  // Only used when transitions are enabled — the backend pairs frames by
  // frame_id ("f0_f1") to emit transition events the UI can show live.
  frame_id?: string
}

type State = {
  storyboardId: string | null
  status: StoryboardStatus
  aspect: VideoAspect
  // Veo render tier — fast (default, ~30-45s/clip) or quality (~60-90s).
  // Applied to every /scene call from this session.
  videoQuality: VeoQuality
  cast: Record<string, CastSlot>
  frames: Frame[]
  narrative: StoryboardNarrative | null
  cinematicBrief: CinematicBrief | null
  // Pure-typography bookends rendered by Remotion. Optional per planner.
  titleCard: StoryboardTitleCard | null
  endCard: StoryboardEndCard | null
  videoUrl: string | null
  videoDurationMs: number | null
  videoId: string | null
  // Voiceover layer — populated post-render when the user fires
  // /api/video/voiceover. `voicedVideoUrl` is the muxed mp4 served alongside
  // the silent original; the UI prefers it when present.
  voiceover: VoiceoverSpec | null
  voiceoverStatus: VoiceoverStatus
  voiceoverError: string | null
  voicedVideoUrl: string | null
  // Audience targeting — populated when /suggest is called with a
  // segment_id. ``segment`` is the segment context the planner saw
  // (rendered as the "Targeted for: …" banner above the storyboard);
  // ``availableSegments`` is the picker dropdown contents pulled from
  // GET /api/audience/segments.
  segment: SegmentTarget | null
  availableSegments: AudienceSegment[]
  selectedSegmentId: string | null
  // Improvement loop — see actions.requestCritique / applyImprovements.
  improvementStatus: ImprovementStatus
  improvementError: string | null
  pendingCritique: CritiquePlan | null
  // Append-only version index. v1 is recorded automatically on first
  // /render success; v2+ are produced by /improve. The UI shows a
  // chip-strip and lets the user load any version into the editor.
  versions: StoryboardVersion[]
  currentVersion: number
  error: string | null
}

type Actions = {
  setAspect: (aspect: VideoAspect) => void
  setVideoQuality: (q: VeoQuality) => void
  addFrame: () => void
  removeFrame: (id: string) => void
  updateFrame: (id: string, patch: Partial<Omit<Frame, 'id'>>) => void
  suggestFromCampaign: () => Promise<void>
  generateIngredient: (castId: string, variationHint?: string) => Promise<void>
  generateAllIngredients: () => Promise<void>
  regenerateIngredient: (castId: string, variationHint?: string) => Promise<void>
  importIngredient: (castId: string, canonicalUrl: string) => void
  generateFrame: (id: string) => Promise<void>
  generateAllFrames: () => Promise<void>
  generateScene: (frameId: string) => Promise<void>
  generateAllScenes: () => Promise<void>
  renderVideo: () => Promise<void>
  generateVoiceover: () => Promise<void>
  updateVoiceover: (patch: Partial<VoiceoverSpec>) => void
  // Hydrate the store from the backend's persisted Storyboard row so a
  // page reload doesn't lose generated frames, clips, render, or voiced
  // video. No-op when no storyboard exists yet for the latest brand.
  loadLatestStoryboard: () => Promise<void>
  // Audience targeting actions — fetch saved segments (for the picker
  // dropdown) and select one before /suggest. ``suggestFromCampaign``
  // reads ``selectedSegmentId`` and threads it through; clear it via
  // setSelectedSegment(null) to fall back to the legacy generic spot.
  loadSegments: () => Promise<void>
  setSelectedSegment: (segmentId: string | null) => void
  // Improvement loop — open the critic on the current rendered video,
  // hold the structured plan in `pendingCritique`, then materialise v2+
  // when the user accepts a subset.
  requestCritique: () => Promise<void>
  dismissCritique: () => void
  applyImprovements: (approvedMutationIds: string[]) => Promise<void>
  // Load any historical version's full snapshot into the editor.
  loadVersion: (versionNumber: number) => Promise<void>
  reset: () => void
}

const DEFAULT_DURATION_MS = 2500
const MIN_DURATION_MS = 1500
const MAX_DURATION_MS = 4000

const initial: State = {
  storyboardId: null,
  status: 'idle',
  aspect: '9:16',
  videoQuality: 'fast',
  cast: {},
  frames: [],
  narrative: null,
  cinematicBrief: null,
  titleCard: null,
  endCard: null,
  videoUrl: null,
  videoDurationMs: null,
  videoId: null,
  voiceover: null,
  voiceoverStatus: 'idle',
  voiceoverError: null,
  voicedVideoUrl: null,
  segment: null,
  availableSegments: [],
  selectedSegmentId: null,
  improvementStatus: 'idle',
  improvementError: null,
  pendingCritique: null,
  versions: [],
  currentVersion: 1,
  error: null,
}

function newId(): string {
  // crypto.randomUUID is widely available in modern browsers (and node ≥ 19).
  // Fallback to a timestamp+random combo if it's not present (older runtimes).
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `f_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
}

function makeFrame(seed?: Partial<StoryboardFrame>): Frame {
  // Design sequences come pre-rendered by Remotion — no Veo clip, no
  // keyframe pipeline. Mark them ready immediately so the UI doesn't show
  // them as "still pending" / "click animate keyframe" in the editor.
  const isDesign = seed?.kind === 'design_sequence'
  return {
    id: seed?.id ?? newId(),
    kind: seed?.kind ?? 'live_action',
    prompt: seed?.prompt ?? '',
    caption: seed?.caption ?? '',
    duration_ms: seed?.duration_ms ?? DEFAULT_DURATION_MS,
    image_url: null,
    status: isDesign ? 'ready' : 'idle',
    error: null,
    cast_refs: seed?.cast_refs ?? [],
    focal_zone: seed?.focal_zone ?? 'mc',
    stale: false,
    motion: seed?.motion ?? '',
    clip_url: null,
    clip_status: isDesign ? 'ready' : 'idle',
    clip_error: null,
    clip_retry: null,
    template: seed?.template ?? null,
    template_params: seed?.template_params ?? null,
    effects: seed?.effects ?? [],
  }
}

function makeCastSlot(member: CastMember): CastSlot {
  // Cast members already bound to a brand asset arrive ready — no canonical
  // sheet generation needed. The rest start idle.
  const isReady =
    member.binding.type === 'brand_asset' && !!member.canonical_url
  return {
    ...member,
    status: isReady ? 'ready' : 'idle',
    error: null,
    narrative_purpose: member.narrative_purpose ?? '',
  }
}

function clampDuration(ms: number): number {
  if (Number.isNaN(ms)) return DEFAULT_DURATION_MS
  return Math.max(MIN_DURATION_MS, Math.min(MAX_DURATION_MS, Math.round(ms)))
}

function castSlotsFromList(list: CastMember[]): Record<string, CastSlot> {
  const out: Record<string, CastSlot> = {}
  for (const m of list) {
    out[m.id] = makeCastSlot(m)
  }
  return out
}

function allCastReady(cast: Record<string, CastSlot>): boolean {
  const values = Object.values(cast)
  if (values.length === 0) return true
  return values.every((c) => c.status === 'ready' && !!c.canonical_url)
}

export const useStoryboardStore = create<State & Actions>((set, get) => ({
  ...initial,

  setAspect: (aspect) => set({ aspect }),

  setVideoQuality: (videoQuality) => set({ videoQuality }),

  addFrame: () =>
    set((s) => ({
      frames: [...s.frames, makeFrame()],
      status: s.status === 'idle' ? 'editing' : s.status,
    })),

  removeFrame: (id) =>
    set((s) => ({
      frames: s.frames.filter((f) => f.id !== id),
    })),

  updateFrame: (id, patch) =>
    set((s) => ({
      frames: s.frames.map((f) => {
        if (f.id !== id) return f
        const next = { ...f, ...patch }
        if (patch.duration_ms !== undefined) {
          next.duration_ms = clampDuration(patch.duration_ms)
        }
        return next
      }),
    })),

  suggestFromCampaign: async () => {
    const { selectedSegmentId } = get()
    set({ status: 'suggesting', error: null })
    try {
      // Empty body still works (legacy generic spot). When a segment is
      // selected, the planner threads its feature_focus through every
      // layer — different segment → different ad spot.
      const reqBody = selectedSegmentId
        ? JSON.stringify({ segment_id: selectedSegmentId })
        : '{}'
      const r = await fetch('/api/video/suggest', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: reqBody,
      })
      if (!r.ok) throw new Error(`suggest failed: ${r.status}`)
      const data = (await r.json()) as {
        storyboard_id: string
        aspect: VideoAspect
        cast: CastMember[]
        frames: StoryboardFrame[]
        narrative?: StoryboardNarrative
        cinematic_brief?: CinematicBrief
        voiceover?: VoiceoverSpec
        title_card?: StoryboardTitleCard | null
        end_card?: StoryboardEndCard | null
        segment?: SegmentTarget | null
      }
      set({
        storyboardId: data.storyboard_id,
        aspect: data.aspect,
        cast: castSlotsFromList(data.cast ?? []),
        frames: (data.frames ?? []).map((f) => makeFrame(f)),
        narrative: data.narrative ?? null,
        cinematicBrief: data.cinematic_brief ?? null,
        voiceover: data.voiceover ?? null,
        voiceoverStatus: 'idle',
        voiceoverError: null,
        voicedVideoUrl: null,
        segment: data.segment ?? null,
        titleCard: data.title_card ?? null,
        endCard: data.end_card ?? null,
        status: 'editing',
        videoUrl: null,
        videoDurationMs: null,
        videoId: null,
      })
    } catch (err) {
      set({
        status: 'failed',
        error: err instanceof Error ? err.message : 'suggest failed',
      })
    }
  },

  loadSegments: async () => {
    // Look up the latest brand id from /storyboard/latest's brand_id
    // (cheap, already cached) when the store doesn't have one yet.
    // Falling back to fetching /api/video/storyboard/latest only when
    // necessary keeps this action stateless for callers.
    let brandId: string | null = null
    try {
      const r = await fetch('/api/video/storyboard/latest')
      if (r.ok) {
        const data = (await r.json()) as { brand_id: string | null } | null
        if (data && typeof data.brand_id === 'string') brandId = data.brand_id
      }
    } catch {
      /* fall through — segment picker stays empty */
    }
    if (!brandId) {
      set({ availableSegments: [] })
      return
    }
    try {
      const r = await fetch(
        `/api/audience/segments?brand_id=${encodeURIComponent(brandId)}`,
      )
      if (!r.ok) {
        set({ availableSegments: [] })
        return
      }
      const data = (await r.json()) as { segments: AudienceSegment[] }
      set({ availableSegments: data.segments ?? [] })
    } catch {
      set({ availableSegments: [] })
    }
  },

  setSelectedSegment: (segmentId) => set({ selectedSegmentId: segmentId }),

  generateIngredient: async (castId, variationHint) => {
    const { storyboardId, cast } = get()
    if (!storyboardId) return
    const slot = cast[castId]
    if (!slot) return

    set((s) => ({
      cast: {
        ...s.cast,
        [castId]: { ...s.cast[castId], status: 'generating', error: null },
      },
      // Only escalate to a global "generating ingredients" phase if we're not
      // already mid-render or rendered.
      status:
        s.status === 'rendering' || s.status === 'rendered'
          ? s.status
          : 'generating_ingredients',
    }))

    try {
      const r = await fetch('/api/video/ingredient', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          storyboard_id: storyboardId,
          cast_id: castId,
          variation_hint: variationHint,
        }),
      })
      if (!r.ok) throw new Error(`ingredient ${r.status}`)
      const data = (await r.json()) as {
        storyboard_id: string
        cast_id: string
        canonical_url: string
        kind: CastKind
      }
      set((s) => {
        const nextCast = {
          ...s.cast,
          [castId]: {
            ...s.cast[castId],
            canonical_url: data.canonical_url,
            status: 'ready' as const,
            error: null,
          },
        }
        const nextStatus =
          s.status === 'generating_ingredients' && allCastReady(nextCast)
            ? 'editing'
            : s.status
        return { cast: nextCast, status: nextStatus }
      })
    } catch (err) {
      set((s) => ({
        cast: {
          ...s.cast,
          [castId]: {
            ...s.cast[castId],
            status: 'failed',
            error: err instanceof Error ? err.message : 'ingredient failed',
          },
        },
      }))
    }
  },

  generateAllIngredients: async () => {
    const { cast, generateIngredient } = get()
    const pending = Object.values(cast).filter((c) => c.status !== 'ready')
    if (pending.length === 0) return
    await Promise.allSettled(
      pending.map((c) => generateIngredient(c.id)),
    )
  },

  regenerateIngredient: async (castId, variationHint) => {
    const { storyboardId, cast } = get()
    if (!storyboardId) return
    const slot = cast[castId]
    if (!slot) return

    set((s) => ({
      cast: {
        ...s.cast,
        [castId]: { ...s.cast[castId], status: 'generating', error: null },
      },
      // Mark dependent frames stale up-front so the UI reflects that the
      // current images no longer match the cast bible while we wait.
      frames: s.frames.map((f) =>
        f.cast_refs.includes(castId) ? { ...f, stale: true } : f,
      ),
    }))

    try {
      const r = await fetch('/api/video/regenerate-ingredient', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          storyboard_id: storyboardId,
          cast_id: castId,
          variation_hint: variationHint,
        }),
      })
      if (!r.ok) throw new Error(`regenerate ${r.status}`)
      const data = (await r.json()) as {
        storyboard_id: string
        cast_id: string
        canonical_url: string
        kind: CastKind
      }
      set((s) => ({
        cast: {
          ...s.cast,
          [castId]: {
            ...s.cast[castId],
            canonical_url: data.canonical_url,
            status: 'ready' as const,
            error: null,
          },
        },
      }))
    } catch (err) {
      set((s) => ({
        cast: {
          ...s.cast,
          [castId]: {
            ...s.cast[castId],
            status: 'failed',
            error: err instanceof Error ? err.message : 'regenerate failed',
          },
        },
      }))
    }
  },

  // Set a cast slot's canonical_url directly without hitting the model —
  // used by the "Import from library" picker on each ingredient. Marks
  // it ready so downstream frames pick it up the same way as a freshly
  // generated sheet.
  importIngredient: (castId, canonicalUrl) => {
    set((s) => {
      const slot = s.cast[castId]
      if (!slot) return s
      return {
        cast: {
          ...s.cast,
          [castId]: {
            ...slot,
            canonical_url: canonicalUrl,
            status: 'ready',
            error: null,
          },
        },
      }
    })
  },

  generateFrame: async (id) => {
    const { frames, aspect, storyboardId, updateFrame } = get()
    const frame = frames.find((f) => f.id === id)
    if (!frame) return
    updateFrame(id, { status: 'generating', error: null })
    try {
      const r = await fetch('/api/video/frame', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          prompt: frame.prompt,
          aspect,
          storyboard_id: storyboardId,
          frame_id: frame.id,
          cast_refs: frame.cast_refs,
        }),
      })
      if (!r.ok) throw new Error(`frame ${r.status}`)
      const data = (await r.json()) as {
        image_url: string
        frame_id?: string | null
        cast_refs?: string[]
      }
      // Optimistically apply the response. The SSE event
      // `video.frame_generated` may also arrive and reapply the same payload —
      // that's idempotent here. Clear `stale` since this image now reflects
      // the current cast bible.
      updateFrame(id, {
        image_url: data.image_url,
        status: 'ready',
        error: null,
        stale: false,
      })
    } catch (err) {
      updateFrame(id, {
        status: 'failed',
        error: err instanceof Error ? err.message : 'frame failed',
      })
    }
  },

  generateAllFrames: async () => {
    const { cast, frames, generateFrame } = get()
    if (!allCastReady(cast)) return
    const targets = frames.filter((f) => f.prompt.trim().length > 0)
    if (targets.length === 0) return
    await Promise.allSettled(targets.map((f) => generateFrame(f.id)))
  },

  generateScene: async (frameId) => {
    const { frames, aspect, storyboardId, videoQuality, updateFrame } = get()
    if (!storyboardId) return
    const frame = frames.find((f) => f.id === frameId)
    if (!frame) return
    if (frame.prompt.trim().length === 0) return

    updateFrame(frameId, {
      clip_status: 'generating',
      clip_error: null,
      clip_retry: null,
    })

    try {
      const r = await fetch('/api/video/scene', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          prompt: frame.prompt,
          motion: frame.motion,
          aspect,
          duration_ms: frame.duration_ms,
          storyboard_id: storyboardId,
          frame_id: frame.id,
          cast_refs: frame.cast_refs,
          quality: videoQuality,
          // Image-to-video: pass the keyframe (a still rendered by /frame) as
          // Veo's first frame so composition + cast are locked. Falls back
          // to text-to-video on the backend when image_url is null.
          keyframe_url: frame.image_url ?? undefined,
        }),
      })
      if (!r.ok) throw new Error(`scene ${r.status}`)
      const data = (await r.json()) as {
        clip_url: string
        frame_id?: string | null
        cast_refs?: string[]
      }
      // Optimistically apply. The SSE event `video.scene_generated` may also
      // arrive and reapply the same payload — that's idempotent here. Clear
      // `stale` since this clip now reflects the current cast bible.
      updateFrame(frameId, {
        clip_url: data.clip_url,
        clip_status: 'ready',
        clip_error: null,
        clip_retry: null,
        stale: false,
      })
    } catch (err) {
      updateFrame(frameId, {
        clip_status: 'failed',
        clip_error: err instanceof Error ? err.message : 'scene failed',
        clip_retry: null,
      })
    }
  },

  generateAllScenes: async () => {
    const { storyboardId, frames, generateScene } = get()
    if (!storyboardId) return
    // Two-phase pipeline: only animate frames whose keyframe (image_url) is
    // already rendered. Skip empties and skip un-keyframed frames so the
    // user sees what they're getting before paying for Veo.
    const targets = frames.filter(
      (f) => f.prompt.trim().length > 0 && !!f.image_url,
    )
    if (targets.length === 0) return
    // STAGGERED PARALLEL — best of both worlds.
    //
    // Sequential (one-at-a-time) was reliable but ~12 min for 6 clips on a
    // degraded Veo tier. Naive parallel (all 6 at once) self-DDoSes Google's
    // submit endpoint: each parallel submit gets queued for 41-80s and the
    // SDK 60s deadline trips, surfacing as a 503 retry storm.
    //
    // Spacing submits 1s apart sends Google ~1 RPS on the submit channel —
    // each submit is accepted in normal (~5s) time. Once submitted, each
    // operation renders independently on Google's side and we poll all of
    // them concurrently. End-to-end: ~stagger + max(render) ≈ 90-120s for
    // 6 frames vs 12 min sequential.
    //
    // Fire-and-await: kick generateScene off without `await`, then sleep
    // for the stagger gap. Final Promise.allSettled waits for everything to
    // either finish or fail. One failed scene doesn't abort the rest —
    // generateScene swallows fetch errors into clip_status='failed' itself.
    const SUBMIT_STAGGER_MS = 1000
    const inflight: Promise<void>[] = []
    for (let i = 0; i < targets.length; i++) {
      inflight.push(generateScene(targets[i].id))
      if (i < targets.length - 1) {
        await new Promise((r) => setTimeout(r, SUBMIT_STAGGER_MS))
      }
    }
    await Promise.allSettled(inflight)
  },

  renderVideo: async () => {
    const { frames, aspect, titleCard, endCard, storyboardId } = get()
    if (frames.length === 0) return
    // Each frame must have at least one of clip_url or image_url. Prefer
    // clip_url when both are set — the renderer will pick that up server-side
    // too, but we send only one URL per frame for clarity.
    // Render-readiness gate:
    //   - live_action frames need clip_url OR image_url
    //   - design_sequence frames need template + template_params (no media)
    const notReady = frames.some((f) => {
      if (f.kind === 'design_sequence') return !f.template
      return !f.clip_url && !f.image_url
    })
    if (notReady) return
    set({ status: 'rendering', error: null, videoUrl: null })
    const payload: RenderFramePayload[] = []
    for (const f of frames) {
      const entry: RenderFramePayload = {
        id: f.id,
        kind: f.kind,
        frame_id: f.id,
        prompt: f.prompt,
        caption: f.caption,
        duration_ms: f.duration_ms,
        focal_zone: f.focal_zone,
      }
      if (f.kind === 'design_sequence') {
        if (!f.template) {
          console.warn('[storyboard] skipping design frame with no template:', f.id)
          continue
        }
        entry.template = f.template
        entry.template_params = f.template_params ?? {}
      } else {
        if (!f.clip_url && !f.image_url) {
          console.warn('[storyboard] skipping live_action frame with no media:', f.id)
          continue
        }
        if (f.clip_url) entry.clip_url = f.clip_url
        else if (f.image_url) entry.image_url = f.image_url
      }
      if (f.effects && f.effects.length > 0) {
        entry.effects = f.effects
      }
      payload.push(entry)
    }

    // Bookend payloads — only sent when the planner produced them. Backend
    // accepts both as optional and falls back to clips-only otherwise.
    const renderBody: {
      aspect: VideoAspect
      frames: RenderFramePayload[]
      title_card?: { text: string }
      end_card?: { headline: string; cta: string }
      storyboard_id?: string
    } = { aspect, frames: payload }
    if (titleCard?.text) {
      renderBody.title_card = { text: titleCard.text }
    }
    if (endCard && (endCard.headline || endCard.cta)) {
      renderBody.end_card = {
        headline: endCard.headline,
        cta: endCard.cta,
      }
    }
    // Plumb storyboard_id so the backend can persist video_url onto the
    // storyboard row — without it, reload would lose the rendered video.
    if (storyboardId) {
      renderBody.storyboard_id = storyboardId
    }
    try {
      const r = await fetch('/api/video/render', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(renderBody),
      })
      if (!r.ok) throw new Error(`render ${r.status}`)
      const data = (await r.json()) as {
        video_id: string
        video_url: string
        duration_ms: number
      }
      // SSE `video.rendered` will set the same fields. Optimistic apply keeps
      // UX snappy if the SSE stream is delayed.
      set({
        status: 'rendered',
        videoUrl: data.video_url,
        videoDurationMs: data.duration_ms,
        videoId: data.video_id,
        voiceoverStatus: 'idle',
        voiceoverError: null,
        voicedVideoUrl: null,
      })
    } catch (err) {
      set({
        status: 'failed',
        error: err instanceof Error ? err.message : 'render failed',
      })
    }
  },

  updateVoiceover: (patch) =>
    set((s) => ({
      voiceover: s.voiceover
        ? { ...s.voiceover, ...patch }
        : {
            script: patch.script ?? '',
            voice_persona: patch.voice_persona ?? '',
            voice_name: patch.voice_name ?? 'Charon',
          },
    })),

  generateVoiceover: async () => {
    const {
      storyboardId,
      videoId,
      voiceover,
      voiceoverStatus,
    } = get()
    if (!storyboardId || !videoId) return
    if (voiceoverStatus === 'generating') return
    set({ voiceoverStatus: 'generating', voiceoverError: null })

    try {
      const r = await fetch('/api/video/voiceover', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          storyboard_id: storyboardId,
          video_id: videoId,
          // Send the user-edited script when present so a tweak in the UI
          // textarea actually feeds the TTS instead of being ignored.
          script: voiceover?.script,
          voice_persona: voiceover?.voice_persona,
          voice_name: voiceover?.voice_name,
        }),
      })
      if (!r.ok) {
        const detail = await r.text().catch(() => '')
        throw new Error(detail || `voiceover ${r.status}`)
      }
      const data = (await r.json()) as {
        video_id: string
        video_url: string
        voice_name: VoiceoverSpec['voice_name']
        script: string
      }
      set({
        voiceoverStatus: 'ready',
        voiceoverError: null,
        voicedVideoUrl: data.video_url,
      })
    } catch (err) {
      set({
        voiceoverStatus: 'failed',
        voiceoverError:
          err instanceof Error ? err.message : 'voiceover failed',
      })
    }
  },

  loadLatestStoryboard: async () => {
    try {
      const r = await fetch('/api/video/storyboard/latest')
      if (!r.ok) return
      const data = (await r.json()) as null | {
        storyboard_id: string
        brand_id: string | null
        aspect: VideoAspect
        narrative?: StoryboardNarrative
        cinematic_brief?: CinematicBrief
        voiceover?: VoiceoverSpec
        title_card?: StoryboardTitleCard | null
        end_card?: StoryboardEndCard | null
        cast: CastMember[]
        frames: (StoryboardFrame & {
          image_url?: string | null
          clip_url?: string | null
        })[]
        video_id: string | null
        video_url: string | null
        video_duration_ms: number | null
        voiced_video_url: string | null
        segment?: SegmentTarget | null
        versions?: StoryboardVersion[]
        current_version?: number
      }
      if (data === null) return
      // Replay each persisted frame back into the in-memory shape — image_url
      // and clip_url ride along so already-rendered media isn't re-generated.
      const frames: Frame[] = (data.frames ?? []).map((f) => {
        const base = makeFrame(f)
        return {
          ...base,
          image_url: f.image_url ?? null,
          status: f.image_url ? 'ready' : base.status,
          clip_url: f.clip_url ?? null,
          clip_status: f.clip_url ? 'ready' : base.clip_status,
        }
      })
      set({
        storyboardId: data.storyboard_id,
        aspect: data.aspect,
        cast: castSlotsFromList(data.cast ?? []),
        frames,
        narrative: data.narrative ?? null,
        cinematicBrief: data.cinematic_brief ?? null,
        voiceover: data.voiceover ?? null,
        titleCard: data.title_card ?? null,
        endCard: data.end_card ?? null,
        videoUrl: data.video_url,
        videoDurationMs: data.video_duration_ms,
        videoId: data.video_id,
        voicedVideoUrl: data.voiced_video_url,
        voiceoverStatus: data.voiced_video_url ? 'ready' : 'idle',
        voiceoverError: null,
        segment: data.segment ?? null,
        // Pre-select the picker so a re-suggest re-targets the same
        // segment unless the user explicitly clears it.
        selectedSegmentId: data.segment?.id ?? null,
        versions: data.versions ?? [],
        currentVersion: data.current_version ?? 1,
        // If we hydrated frames or a render we shouldn't sit in 'idle' —
        // pick the most-advanced status the persisted state reflects.
        status: data.video_url
          ? 'rendered'
          : frames.length > 0
            ? 'editing'
            : 'idle',
        error: null,
      })
    } catch {
      // Hydration is best-effort. Network blips shouldn't block the UI;
      // the user can still hit "Suggest from campaign" manually.
    }
  },

  requestCritique: async () => {
    const { storyboardId, frames, videoUrl } = get()
    if (!storyboardId || !videoUrl) return
    set({
      improvementStatus: 'critiquing',
      improvementError: null,
      pendingCritique: null,
    })
    try {
      // Pack only what the critic actually consumes — long URLs are kept
      // (it walks them for thumbnails) but cast_refs / effects pass
      // through verbatim so any frame-level mutations the model proposes
      // can target the exact field names.
      const body = {
        storyboard_id: storyboardId,
        video_url: videoUrl,
        frames: frames.map((f) => ({
          id: f.id,
          kind: f.kind,
          prompt: f.prompt,
          motion: f.motion,
          caption: f.caption,
          duration_ms: f.duration_ms,
          focal_zone: f.focal_zone,
          cast_refs: f.cast_refs,
          image_url: f.image_url,
          clip_url: f.clip_url,
          template: f.template,
          template_params: f.template_params,
          effects: f.effects,
        })),
      }
      const r = await fetch('/api/video/critique', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!r.ok) throw new Error(`critique ${r.status}`)
      const data = (await r.json()) as CritiquePlan
      set({
        pendingCritique: data,
        improvementStatus: 'review',
        improvementError: data.error || null,
      })
    } catch (err) {
      set({
        improvementStatus: 'failed',
        improvementError:
          err instanceof Error ? err.message : 'critique failed',
      })
    }
  },

  dismissCritique: () =>
    set({ pendingCritique: null, improvementStatus: 'idle', improvementError: null }),

  applyImprovements: async (approvedMutationIds) => {
    const { storyboardId, pendingCritique } = get()
    if (!storyboardId || !pendingCritique) return
    if (approvedMutationIds.length === 0) {
      // Treat zero-selection as a dismiss — nothing to do.
      set({ pendingCritique: null, improvementStatus: 'idle' })
      return
    }
    set({ improvementStatus: 'applying', improvementError: null })
    try {
      const r = await fetch('/api/video/improve', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          storyboard_id: storyboardId,
          approved_mutation_ids: approvedMutationIds,
          full_plan: pendingCritique,
        }),
      })
      if (!r.ok) {
        const detail = await r.text().catch(() => '')
        throw new Error(detail || `improve ${r.status}`)
      }
      const data = (await r.json()) as {
        storyboard_id: string
        version_number: number
        video_url: string
        duration_ms: number
        refired_frame_ids: string[]
        applied_mutation_ids: string[]
      }
      // The version index will arrive via SSE (video.version_rendered)
      // OR the next loadLatestStoryboard call. Update locally so the UI
      // reflects v(n+1) immediately.
      set((s) => ({
        videoUrl: data.video_url,
        videoDurationMs: data.duration_ms,
        // Reset voiced state — a new silent render invalidates the
        // previously-muxed voiceover (mirrors /render's policy).
        voicedVideoUrl: null,
        voiceoverStatus: 'idle',
        voiceoverError: null,
        currentVersion: data.version_number,
        // Append a placeholder entry; the loadLatestStoryboard call (or
        // SSE) will replace this with the canonical record.
        versions: (() => {
          const exists = s.versions.some(
            (v) => v.version_number === data.version_number,
          )
          if (exists) return s.versions
          const newEntry: StoryboardVersion = {
            version_number: data.version_number,
            video_url: data.video_url,
            summary: pendingCritique.summary,
            mutation_count: data.applied_mutation_ids.length,
            created_at: new Date().toISOString(),
          }
          return [...s.versions, newEntry].sort(
            (a, b) => a.version_number - b.version_number,
          )
        })(),
        pendingCritique: null,
        improvementStatus: 'idle',
        improvementError: null,
      }))
    } catch (err) {
      set({
        improvementStatus: 'failed',
        improvementError:
          err instanceof Error ? err.message : 'improve failed',
      })
    }
  },

  loadVersion: async (versionNumber) => {
    const { storyboardId } = get()
    if (!storyboardId) return
    try {
      const r = await fetch(
        `/api/video/storyboard/${storyboardId}/version/${versionNumber}`,
      )
      if (!r.ok) return
      const data = (await r.json()) as {
        storyboard_id: string
        version_number: number
        video_url: string | null
        frames: (StoryboardFrame & {
          image_url?: string | null
          clip_url?: string | null
        })[]
        aspect: VideoAspect | null
        title_card: StoryboardTitleCard | null
        end_card: StoryboardEndCard | null
      }
      const replayed: Frame[] = (data.frames ?? []).map((f) => {
        const base = makeFrame(f)
        return {
          ...base,
          image_url: f.image_url ?? null,
          status: f.image_url ? 'ready' : base.status,
          clip_url: f.clip_url ?? null,
          clip_status: f.clip_url ? 'ready' : base.clip_status,
        }
      })
      set((s) => ({
        frames: replayed,
        aspect: data.aspect ?? s.aspect,
        titleCard: data.title_card ?? s.titleCard,
        endCard: data.end_card ?? s.endCard,
        videoUrl: data.video_url ?? s.videoUrl,
        currentVersion: data.version_number,
        // Clear voiced state — the loaded version's silent mp4 is the
        // active artifact; voiceover applies to the live render.
        voicedVideoUrl: null,
        voiceoverStatus: 'idle',
        voiceoverError: null,
      }))
    } catch {
      /* version load is best-effort */
    }
  },

  reset: () => set(initial),
}))

// Re-export so consumers in components can keep importing CastBinding/CastKind
// without reaching into events/bus directly. (Pure type re-exports.)
export type { CastBinding, CastKind, CastMember, FocalZone }

// ─── bus listeners ──────────────────────────────────────────────────────────
// These mirror the optimistic local state updates so SSE remains the source
// of truth when the backend pushes events independently (e.g. when a frame
// is regenerated by another tab or the agent autonomously).

bus.on('video.storyboard_suggested', (p) => {
  useStoryboardStore.setState((s) => ({
    storyboardId: p.storyboard_id,
    aspect: p.aspect,
    cast: castSlotsFromList(p.cast ?? []),
    frames: (p.frames ?? []).map((f) => makeFrame(f)),
    narrative: p.narrative ?? null,
    cinematicBrief: p.cinematic_brief ?? null,
    voiceover: p.voiceover ?? null,
    voiceoverStatus: 'idle',
    voiceoverError: null,
    voicedVideoUrl: null,
    segment: p.segment ?? null,
    selectedSegmentId: p.segment?.id ?? null,
    titleCard: p.title_card ?? null,
    endCard: p.end_card ?? null,
    status: s.status === 'rendering' ? s.status : 'editing',
    videoUrl: null,
    videoDurationMs: null,
    videoId: null,
    error: null,
  }))
})

bus.on('video.frame_generated', (p) => {
  useStoryboardStore.setState((s) => ({
    frames: s.frames.map((f) =>
      p.frame_id !== null && f.id === p.frame_id
        ? {
            ...f,
            image_url: p.image_url,
            status: 'ready',
            error: null,
            stale: false,
          }
        : f,
    ),
  }))
})

bus.on('video.ingredient_generated', (p) => {
  useStoryboardStore.setState((s) => {
    const slot = s.cast[p.cast_id]
    if (!slot) return s
    const nextCast = {
      ...s.cast,
      [p.cast_id]: {
        ...slot,
        canonical_url: p.canonical_url,
        status: 'ready' as const,
        error: null,
      },
    }
    return { cast: nextCast }
  })
})

bus.on('video.ingredient_regenerated', (p) => {
  useStoryboardStore.setState((s) => {
    const slot = s.cast[p.cast_id]
    if (!slot) return s
    const nextCast = {
      ...s.cast,
      [p.cast_id]: {
        ...slot,
        canonical_url: p.canonical_url,
        status: 'ready' as const,
        error: null,
      },
    }
    const nextFrames = s.frames.map((f) =>
      f.cast_refs.includes(p.cast_id) ? { ...f, stale: true } : f,
    )
    return { cast: nextCast, frames: nextFrames }
  })
})

bus.on('video.cast_bible_locked', () => {
  useStoryboardStore.setState((s) =>
    s.status === 'generating_ingredients' ? { status: 'editing' } : {},
  )
})

bus.on('video.render_started', () => {
  useStoryboardStore.setState({
    status: 'rendering',
    error: null,
    videoUrl: null,
  })
})

bus.on('video.rendered', (p) => {
  useStoryboardStore.setState((s) => ({
    status: 'rendered',
    videoUrl: p.video_url,
    videoDurationMs: p.duration_ms,
    videoId: p.video_id ?? s.videoId,
    error: null,
  }))
})

bus.on('video.voiceover_generating', () => {
  useStoryboardStore.setState({
    voiceoverStatus: 'generating',
    voiceoverError: null,
  })
})

bus.on('video.voiceover_generated', (p) => {
  useStoryboardStore.setState({
    voiceoverStatus: 'ready',
    voiceoverError: null,
    voicedVideoUrl: p.video_url,
  })
})

bus.on('video.voiceover_failed', (p) => {
  useStoryboardStore.setState({
    voiceoverStatus: 'failed',
    voiceoverError: p.error || 'voiceover failed',
  })
})

bus.on('video.render_failed', (p) => {
  useStoryboardStore.setState({
    status: 'failed',
    error: p.error || 'render failed',
  })
})

bus.on('video.scene_generating', (p) => {
  useStoryboardStore.setState((s) => ({
    frames: s.frames.map((f) =>
      f.id === p.frame_id
        ? { ...f, clip_status: 'generating', clip_error: null, clip_retry: null }
        : f,
    ),
  }))
})

bus.on('video.scene_generated', (p) => {
  useStoryboardStore.setState((s) => ({
    frames: s.frames.map((f) =>
      f.id === p.frame_id
        ? {
            ...f,
            clip_url: p.clip_url,
            clip_status: 'ready',
            clip_error: null,
            clip_retry: null,
            stale: false,
          }
        : f,
    ),
  }))
})

bus.on('video.scene_retrying', (p) => {
  useStoryboardStore.setState((s) => ({
    frames: s.frames.map((f) =>
      f.id === p.frame_id
        ? {
            ...f,
            clip_retry: {
              phase: p.phase,
              attempt: p.attempt,
              max_attempts: p.max_attempts,
              delay_s: p.delay_s,
              reason: p.reason,
            },
          }
        : f,
    ),
  }))
})

// ── Improvement loop ───────────────────────────────────────────────────────
// SSE-only updates. The local applyImprovements optimistically advances the
// store, but version_rendered remains the canonical source — it's what
// fires when another tab or the autonomous agent runs the improver.

bus.on('video.critiquing', () => {
  useStoryboardStore.setState((s) =>
    s.improvementStatus === 'critiquing'
      ? s
      : { improvementStatus: 'critiquing', improvementError: null },
  )
})

bus.on('video.critiqued', (p) => {
  useStoryboardStore.setState((s) =>
    p.error
      ? { improvementStatus: 'failed', improvementError: p.error }
      : // Promote critiquing → review only when we don't already hold a
        // pendingCritique (the local fetch path already set it).
        s.pendingCritique
        ? s
        : { improvementStatus: s.improvementStatus === 'critiquing' ? 'critiquing' : s.improvementStatus },
  )
})

bus.on('video.improving_started', () => {
  useStoryboardStore.setState({
    improvementStatus: 'applying',
    improvementError: null,
  })
})

bus.on('video.version_rendered', (p) => {
  useStoryboardStore.setState((s) => {
    const newEntry: StoryboardVersion = {
      version_number: p.version_number,
      video_url: p.video_url,
      summary: s.pendingCritique?.summary ?? null,
      mutation_count: p.applied_mutation_ids.length,
      created_at: new Date().toISOString(),
    }
    const exists = s.versions.some(
      (v) => v.version_number === p.version_number,
    )
    return {
      videoUrl: p.video_url,
      videoDurationMs: p.duration_ms,
      currentVersion: p.version_number,
      versions: exists
        ? s.versions
        : [...s.versions, newEntry].sort(
            (a, b) => a.version_number - b.version_number,
          ),
      improvementStatus: 'idle',
      improvementError: null,
      pendingCritique: null,
      voicedVideoUrl: null,
      voiceoverStatus: 'idle',
      voiceoverError: null,
    }
  })
})

bus.on('video.improvement_failed', (p) => {
  useStoryboardStore.setState({
    improvementStatus: 'failed',
    improvementError: `${p.phase}: ${p.error}`,
  })
})
