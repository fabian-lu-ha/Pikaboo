// Brand asset library shared types — mirrors backend/app/api/assets.py.
//
// Subkinds reflect which pipeline stage produced the media:
//   - ingredient: cast-bible images (character/setting/prop/product sheets)
//   - frame:      single-frame keyframes from the video frame_gen step
//   - scene:      Veo-rendered video clips, one per storyboard frame
//   - render:     final mux'd video (output of /api/video/render)
//   - upload:     manually uploaded media (future)

export type AssetKind = 'image' | 'video'

export type AssetSubkind =
  | 'ingredient'
  | 'frame'
  | 'scene'
  | 'render'
  | 'upload'

export type CastKind = 'character' | 'setting' | 'prop' | 'product'

// AI-described status — populated by the Gemini Vision describer that
// runs after every asset is recorded. Front-end uses this to flip the
// asset card from a shimmer to the real description without polling.
export type AssetDescribeStatus =
  | 'idle'      // not yet picked up by the describer
  | 'pending'   // describer holds it, Gemini call in flight
  | 'ready'     // description authored
  | 'failed'    // describer gave up (bytes unloadable / model error)

export type AssetItem = {
  id: string
  brand_id: string
  kind: AssetKind
  subkind: AssetSubkind
  url: string
  storyboard_id: string | null
  cast_kind: CastKind | null
  label: string | null
  prompt_preview: string | null
  duration_ms: number | null
  aspect: string | null
  meta: Record<string, unknown>
  // AI-authored visual description + entity tags. Both null until the
  // describer has run (see /api/assets/{id}/describe).
  description: string | null
  tags: string[]
  description_status: AssetDescribeStatus | null
  created_at: string
}

export type AssetListResponse = {
  items: AssetItem[]
  total: number
}

// Emoji per cast kind — used in CastCard, ingredient pickers, and
// asset-library tiles so the same character/setting/prop/product
// hint shows everywhere.
export const CAST_KIND_EMOJI: Record<CastKind, string> = {
  character: '🧑',
  setting: '🏞️',
  prop: '📦',
  product: '🛍️',
}

export const CAST_KIND_LABEL: Record<CastKind, string> = {
  character: 'Character',
  setting: 'Setting',
  prop: 'Prop',
  product: 'Product',
}

// Subkind glyph for asset-library tiles when no cast_kind is available
// (frames, renders, manual uploads).
export const SUBKIND_GLYPH: Record<AssetSubkind, string> = {
  ingredient: '✨',
  frame: '🖼',
  scene: '🎬',
  render: '🎞',
  upload: '⬆',
}
