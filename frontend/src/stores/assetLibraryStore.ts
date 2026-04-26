import { create } from 'zustand'
import { bus } from '../events/bus'
import type { AssetItem } from '../lib/assets'

// Asset library — fetches /api/assets for a brand and stays live by
// subscribing to the same video.* events the backend listener writes from.
// Optimistic insert on each event so the Library page reflects new media
// immediately, even before a full refetch round-trip.

type State = {
  brandId: string | null
  items: AssetItem[]
  loading: boolean
  error: string | null
}

type Actions = {
  load: (brandId: string) => Promise<void>
  refresh: () => Promise<void>
  remove: (assetId: string) => Promise<void>
  // Trigger Gemini Vision on one asset and patch the resulting
  // description / tags / cast_kind into the in-memory list.
  describe: (assetId: string, force?: boolean) => Promise<void>
  // Bulk catch-up — describe every undescribed image asset for the
  // current brand. Long-running; the UI shows a progress badge.
  describeAll: () => Promise<void>
}

// Refetch debounce — multiple bus events in a single run (frame_generated,
// scene_generated, etc.) collapse into one network round-trip.
let _refreshTimer: ReturnType<typeof setTimeout> | null = null
function scheduleRefresh(): void {
  if (_refreshTimer) clearTimeout(_refreshTimer)
  _refreshTimer = setTimeout(() => {
    _refreshTimer = null
    const { brandId, refresh } = useAssetLibraryStore.getState()
    if (brandId) void refresh()
  }, 400)
}

export const useAssetLibraryStore = create<State & Actions>((set, get) => ({
  brandId: null,
  items: [],
  loading: false,
  error: null,
  async load(brandId: string) {
    set({ brandId, loading: true, error: null })
    try {
      const r = await fetch(
        `/api/assets?brand_id=${encodeURIComponent(brandId)}&limit=120`,
      )
      if (!r.ok) throw new Error(`status ${r.status}`)
      const data = (await r.json()) as { items: AssetItem[] }
      // Avoid clobbering a more-recent load if brandId changed mid-flight.
      if (get().brandId !== brandId) return
      set({ items: data.items, loading: false })
    } catch (e) {
      set({ error: (e as Error).message, loading: false })
    }
  },
  async refresh() {
    const id = get().brandId
    if (!id) return
    try {
      const r = await fetch(
        `/api/assets?brand_id=${encodeURIComponent(id)}&limit=120`,
      )
      if (!r.ok) return
      const data = (await r.json()) as { items: AssetItem[] }
      // Replace items but keep loading/error state — refresh is silent.
      if (get().brandId !== id) return
      set({ items: data.items, error: null })
    } catch {
      /* keep existing items on transient failure */
    }
  },
  async describe(assetId: string, force = false) {
    // Optimistically flip the row to 'pending' so the UI shows a shimmer.
    useAssetLibraryStore.setState((s) => ({
      items: s.items.map((a) =>
        a.id === assetId ? { ...a, description_status: 'pending' } : a,
      ),
    }))
    try {
      const r = await fetch(
        `/api/assets/${encodeURIComponent(assetId)}/describe?force=${force ? 'true' : 'false'}`,
        { method: 'POST' },
      )
      if (!r.ok) throw new Error(`status ${r.status}`)
      const data = (await r.json()) as {
        asset_id: string
        described: boolean
        description: string | null
        tags: string[]
        cast_kind: AssetItem['cast_kind']
      }
      useAssetLibraryStore.setState((s) => ({
        items: s.items.map((a) =>
          a.id === assetId
            ? {
                ...a,
                description: data.description,
                tags: data.tags ?? [],
                cast_kind: data.cast_kind ?? a.cast_kind,
                description_status: data.described ? 'ready' : 'failed',
              }
            : a,
        ),
      }))
    } catch {
      useAssetLibraryStore.setState((s) => ({
        items: s.items.map((a) =>
          a.id === assetId ? { ...a, description_status: 'failed' } : a,
        ),
      }))
    }
  },
  async describeAll() {
    const id = useAssetLibraryStore.getState().brandId
    if (!id) return
    try {
      const r = await fetch(
        `/api/assets/describe-all?brand_id=${encodeURIComponent(id)}`,
        { method: 'POST' },
      )
      if (r.ok) {
        // Refresh once the bulk pass returns so the UI picks up every
        // updated row at once instead of N progressive patches.
        await get().refresh()
      }
    } catch {
      /* swallow — partial describes are still useful */
    }
  },
  async remove(assetId: string) {
    const prev = get().items
    set({ items: prev.filter((a) => a.id !== assetId) })
    try {
      const r = await fetch(`/api/assets/${encodeURIComponent(assetId)}`, {
        method: 'DELETE',
      })
      if (!r.ok) throw new Error(`status ${r.status}`)
    } catch (e) {
      // Roll back on failure.
      set({ items: prev, error: (e as Error).message })
    }
  },
}))

// Build a synthetic asset row from a bus event payload. Mirrors the shape
// the backend listener writes so the optimistic prepend matches a refetch.
function synthesize(
  brandId: string,
  partial: Partial<AssetItem> & Pick<AssetItem, 'kind' | 'subkind' | 'url'>,
): AssetItem {
  return {
    id: `tmp-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    brand_id: brandId,
    cast_kind: null,
    storyboard_id: null,
    label: null,
    prompt_preview: null,
    duration_ms: null,
    aspect: null,
    meta: {},
    description: null,
    tags: [],
    description_status: 'idle',
    created_at: new Date().toISOString(),
    ...partial,
  }
}

function prepend(item: AssetItem) {
  useAssetLibraryStore.setState((s) => {
    if (!s.brandId) return s
    // Skip if we already have this URL (race vs. fetch).
    if (s.items.some((a) => a.url === item.url)) return s
    return { items: [item, ...s.items].slice(0, 200) }
  })
}

// Each handler does two things:
//   1. Optimistic prepend — only when the store already has a brandId, so
//      the Library page (mounted with a load() call) updates instantly
//      while a run is in progress.
//   2. ``scheduleRefresh()`` — debounced GET /api/assets call that picks up
//      whatever the backend listener actually persisted, including any
//      events the optimistic path missed (e.g. brandId not yet known
//      because the user hadn't visited Library before kicking off the
//      run). Replaces synthetic rows with the canonical backend rows.

bus.on('video.ingredient_generated', (e) => {
  const brandId = useAssetLibraryStore.getState().brandId
  if (brandId && e.canonical_url) {
    prepend(
      synthesize(brandId, {
        kind: 'image',
        subkind: 'ingredient',
        url: e.canonical_url,
        cast_kind: e.kind ?? null,
        storyboard_id: e.storyboard_id ?? null,
        label: e.cast_id ?? null,
        meta: { from_brand_asset: !!e.from_brand_asset },
      }),
    )
  }
  scheduleRefresh()
})

bus.on('video.frame_generated', (e) => {
  const brandId = useAssetLibraryStore.getState().brandId
  if (brandId && e.image_url) {
    prepend(
      synthesize(brandId, {
        kind: 'image',
        subkind: 'frame',
        url: e.image_url,
        storyboard_id: e.storyboard_id ?? null,
        label: e.frame_id ?? null,
        prompt_preview: e.prompt_preview ?? null,
        aspect: e.aspect ?? null,
      }),
    )
  }
  scheduleRefresh()
})

bus.on('video.scene_generated', (e) => {
  const brandId = useAssetLibraryStore.getState().brandId
  if (brandId && e.clip_url) {
    prepend(
      synthesize(brandId, {
        kind: 'video',
        subkind: 'scene',
        url: e.clip_url,
        storyboard_id: e.storyboard_id ?? null,
        label: e.frame_id ?? null,
        duration_ms: e.duration_ms ?? null,
        aspect: e.aspect ?? null,
        meta: { quality: e.quality },
      }),
    )
  }
  scheduleRefresh()
})

bus.on('video.rendered', (e) => {
  const brandId = useAssetLibraryStore.getState().brandId
  if (brandId && e.video_url) {
    prepend(
      synthesize(brandId, {
        kind: 'video',
        subkind: 'render',
        url: e.video_url,
        duration_ms: e.duration_ms ?? null,
      }),
    )
  }
  scheduleRefresh()
})

// AI describer lifecycle. The describing/described events let us patch
// the matching row in-place so the user sees a shimmer flip to the
// real description without a refetch.
bus.on('asset.describing', (e) => {
  useAssetLibraryStore.setState((s) => ({
    items: s.items.map((a) =>
      a.id === e.asset_id ? { ...a, description_status: 'pending' } : a,
    ),
  }))
})

bus.on('asset.described', (e) => {
  useAssetLibraryStore.setState((s) => ({
    items: s.items.map((a) =>
      a.id === e.asset_id
        ? {
            ...a,
            description: e.description,
            tags: e.tags ?? [],
            cast_kind: e.cast_kind ?? a.cast_kind,
            description_status: 'ready',
          }
        : a,
    ),
  }))
})

bus.on('asset.describe_failed', (e) => {
  useAssetLibraryStore.setState((s) => ({
    items: s.items.map((a) =>
      a.id === e.asset_id ? { ...a, description_status: 'failed' } : a,
    ),
  }))
})
