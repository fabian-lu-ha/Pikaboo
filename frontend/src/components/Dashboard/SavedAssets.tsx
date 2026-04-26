import { useEffect, useMemo, useState } from 'react'
import { motion } from 'motion/react'
import { useAssetLibraryStore } from '../../stores/assetLibraryStore'
import {
  CAST_KIND_EMOJI,
  CAST_KIND_LABEL,
  SUBKIND_GLYPH,
  type AssetItem,
  type AssetSubkind,
} from '../../lib/assets'

// "Source" filter — collapses cast_kind + subkind into a single human-
// friendly bucket so the user thinks in terms of "show me brand photos"
// rather than "show me images with cast_kind=null and subkind=upload".
type SourceFilter =
  | 'all'
  | 'brand'        // logos, screenshots, product photos, manual uploads
  | 'character'    // cast bible: characters
  | 'setting'      // cast bible: settings
  | 'prop'         // cast bible: props
  | 'product'      // cast bible: products (excluding brand-asset binding)
  | 'frame'        // generated keyframes
  | 'scene'        // Veo-rendered clips per frame
  | 'render'       // final muxed videos
type KindFilter = 'all' | 'image' | 'video'

const SOURCE_LABELS: Record<SourceFilter, { label: string; glyph: string }> = {
  all: { label: 'All', glyph: '◇' },
  brand: { label: 'Brand', glyph: '🏷️' },
  character: { label: 'Characters', glyph: CAST_KIND_EMOJI.character },
  setting: { label: 'Settings', glyph: CAST_KIND_EMOJI.setting },
  prop: { label: 'Props', glyph: CAST_KIND_EMOJI.prop },
  product: { label: 'Products', glyph: CAST_KIND_EMOJI.product },
  frame: { label: 'Frames', glyph: SUBKIND_GLYPH.frame },
  scene: { label: 'Scenes', glyph: SUBKIND_GLYPH.scene },
  render: { label: 'Final renders', glyph: SUBKIND_GLYPH.render },
}

function bucketOf(a: AssetItem): SourceFilter {
  // Brand bucket = anything that came from onboarding/manual upload, where
  // we don't have a cast role. Generated cast-bible images carry a
  // cast_kind so they get their own bucket.
  if (a.subkind === 'upload') {
    return a.cast_kind ?? 'brand'
  }
  if (a.subkind === 'ingredient') {
    return (a.cast_kind ?? 'brand') as SourceFilter
  }
  if (a.subkind === 'frame') return 'frame'
  if (a.subkind === 'scene') return 'scene'
  if (a.subkind === 'render') return 'render'
  return 'brand'
}

export function SavedAssets({ brandId }: { brandId: string }) {
  const items = useAssetLibraryStore((s) => s.items)
  const loading = useAssetLibraryStore((s) => s.loading)
  const load = useAssetLibraryStore((s) => s.load)
  const refresh = useAssetLibraryStore((s) => s.refresh)
  const remove = useAssetLibraryStore((s) => s.remove)
  const describe = useAssetLibraryStore((s) => s.describe)
  const describeAll = useAssetLibraryStore((s) => s.describeAll)
  const [describingAll, setDescribingAll] = useState(false)
  const [source, setSource] = useState<SourceFilter>('all')
  const [kind, setKind] = useState<KindFilter>('all')
  const [query, setQuery] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    void load(brandId)
  }, [brandId, load])

  async function handleRefresh() {
    if (refreshing) return
    setRefreshing(true)
    try {
      await refresh()
    } finally {
      setRefreshing(false)
    }
  }

  // Count un-described image assets so the header can show a "describe N
  // images" badge — the user gets a clear call-to-action for the AI
  // describer instead of having to click into each card.
  const undescribedCount = useMemo(
    () =>
      items.filter(
        (a) =>
          a.kind === 'image' &&
          (a.description_status === 'idle' ||
            a.description_status === null ||
            a.description_status === 'failed'),
      ).length,
    [items],
  )

  async function handleDescribeAll() {
    if (describingAll || undescribedCount === 0) return
    setDescribingAll(true)
    try {
      await describeAll()
    } finally {
      setDescribingAll(false)
    }
  }

  const counts = useMemo(() => {
    const c: Record<SourceFilter, number> = {
      all: items.length,
      brand: 0,
      character: 0,
      setting: 0,
      prop: 0,
      product: 0,
      frame: 0,
      scene: 0,
      render: 0,
    }
    for (const a of items) {
      const b = bucketOf(a)
      if (b !== 'all') c[b] += 1
    }
    return c
  }, [items])

  const photoCount = items.filter((a) => a.kind === 'image').length
  const videoCount = items.filter((a) => a.kind === 'video').length

  const filtered = useMemo(() => {
    let out = items
    if (kind !== 'all') out = out.filter((a) => a.kind === kind)
    if (source !== 'all') out = out.filter((a) => bucketOf(a) === source)
    const q = query.trim().toLowerCase()
    if (q) {
      out = out.filter((a) => {
        const blob = `${a.label ?? ''} ${a.subkind} ${a.cast_kind ?? ''} ${a.prompt_preview ?? ''}`
        return blob.toLowerCase().includes(q)
      })
    }
    return out
  }, [items, source, kind, query])

  // Visible filter chips — only show buckets that actually have anything,
  // in a stable canonical order. Kind chips are always shown.
  const SOURCE_ORDER: SourceFilter[] = [
    'all',
    'brand',
    'character',
    'setting',
    'prop',
    'product',
    'frame',
    'scene',
    'render',
  ]
  const visibleSources = SOURCE_ORDER.filter(
    (k) => k === 'all' || counts[k] > 0,
  )

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.12 }}
      className="mt-8"
    >
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-[13px] font-semibold">Saved Assets</h2>
          <p className="mt-0.5 text-[11px] text-fg-mute">
            {photoCount} photo{photoCount === 1 ? '' : 's'} ·{' '}
            {videoCount} video{videoCount === 1 ? '' : 's'} · auto-saved
            from every campaign and storyboard.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search…"
            className="hairline w-44 rounded-full bg-bg-card px-3 py-1.5 text-[12px] outline-none placeholder:text-fg-dim focus:border-accent"
          />
          <div className="hairline inline-flex rounded-full bg-bg p-0.5 text-[11px]">
            {(['all', 'image', 'video'] as KindFilter[]).map((k) => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={`rounded-full px-2.5 py-1 font-medium capitalize transition ${
                  kind === k
                    ? 'bg-bg-card text-fg shadow-[0_1px_2px_rgba(20,20,40,0.06)]'
                    : 'text-fg-mute hover:text-fg'
                }`}
              >
                {k === 'all' ? 'All' : k === 'image' ? 'Photos' : 'Videos'}
              </button>
            ))}
          </div>
          {undescribedCount > 0 && (
            <button
              onClick={handleDescribeAll}
              disabled={describingAll}
              title={`Run AI describer on ${undescribedCount} un-described image${undescribedCount === 1 ? '' : 's'}`}
              className="hairline inline-flex items-center gap-1.5 rounded-full bg-accent-soft px-3 py-1 text-[11px] font-medium text-accent transition hover:bg-accent hover:text-white disabled:opacity-60"
            >
              <span>{describingAll ? '◐' : '✨'}</span>
              <span>
                {describingAll
                  ? 'describing…'
                  : `describe ${undescribedCount}`}
              </span>
            </button>
          )}
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            title="Refresh library"
            aria-label="Refresh library"
            className="hairline grid h-7 w-7 place-items-center rounded-full bg-bg-card text-[12px] text-fg-mute transition hover:text-accent disabled:opacity-50"
          >
            <span className={refreshing ? 'inline-block animate-spin' : ''}>
              ↻
            </span>
          </button>
        </div>
      </header>

      {/* Source chips — wrap below the kind toggle on smaller widths. */}
      <div className="mt-3 flex flex-wrap gap-1.5">
        {visibleSources.map((s) => {
          const active = source === s
          const meta = SOURCE_LABELS[s]
          const count = s === 'all' ? items.length : counts[s]
          return (
            <button
              key={s}
              onClick={() => setSource(s)}
              className={`hairline inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium transition ${
                active
                  ? 'bg-accent-soft text-accent'
                  : 'bg-bg-card text-fg-mute hover:text-fg'
              }`}
            >
              <span>{meta.glyph}</span>
              <span>{meta.label}</span>
              <span className="text-fg-dim">{count}</span>
            </button>
          )
        })}
      </div>

      {loading && items.length === 0 ? (
        <div className="panel mt-4 grid place-items-center px-5 py-12 text-[12px] text-fg-mute">
          loading library…
        </div>
      ) : filtered.length === 0 ? (
        <div className="panel mt-4 grid place-items-center px-5 py-12 text-center text-[12px] text-fg-mute">
          {items.length === 0
            ? 'No saved assets yet — generate a storyboard and the photos + clips will land here.'
            : `Nothing matches the current filter${query ? ` for “${query}”` : ''}.`}
        </div>
      ) : (
        <ul className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {filtered.map((a) => (
            <AssetTile
              key={a.id}
              asset={a}
              onDelete={() => void remove(a.id)}
              onDescribe={() => void describe(a.id)}
            />
          ))}
        </ul>
      )}
    </motion.section>
  )
}

// Per-tile aspect ratio — videos hint at 16:9 unless aspect was recorded,
// generated frames respect their stored aspect, brand uploads + cast
// sheets default to 4:5 portrait so the grid stays even.
function aspectForTile(a: AssetItem): string {
  if (a.aspect === '9:16') return '9 / 16'
  if (a.aspect === '16:9') return '16 / 9'
  if (a.aspect === '1:1') return '1 / 1'
  if (a.kind === 'video') return '16 / 9'
  return '4 / 5'
}

function badgeFor(a: AssetItem): { glyph: string; label: string } {
  if (a.cast_kind) {
    return {
      glyph: CAST_KIND_EMOJI[a.cast_kind],
      label: CAST_KIND_LABEL[a.cast_kind],
    }
  }
  return {
    glyph: SUBKIND_GLYPH[a.subkind as AssetSubkind] ?? '◇',
    label: capitalize(a.subkind),
  }
}

function AssetTile({
  asset,
  onDelete,
  onDescribe,
}: {
  asset: AssetItem
  onDelete: () => void
  onDescribe: () => void
}) {
  const [loaded, setLoaded] = useState(false)
  const isVideo = asset.kind === 'video'
  const badge = badgeFor(asset)
  // Tooltip prefers AI description (richer) over the legacy prompt_preview.
  const tooltip =
    asset.description || asset.prompt_preview || asset.label || ''
  const describing = asset.description_status === 'pending'
  const described = asset.description_status === 'ready' && !!asset.description
  const describeFailed = asset.description_status === 'failed'
  // Only image assets get the AI describer; videos are skipped server-side.
  const showDescribeButton = asset.kind === 'image' && !described && !describing

  function copyUrl() {
    const abs = asset.url.startsWith('http')
      ? asset.url
      : `${window.location.origin}${asset.url}`
    navigator.clipboard?.writeText(abs).catch(() => {})
  }

  return (
    <li className="group relative flex flex-col overflow-hidden rounded-xl bg-bg-card hairline">
      <div
        className="relative w-full bg-bg-soft"
        style={{ aspectRatio: aspectForTile(asset) }}
        title={tooltip}
      >
        {/* Emoji placeholder always sits underneath; the real media
            crossfades over once it actually paints. */}
        <div
          aria-hidden
          className={`absolute inset-0 grid place-items-center text-3xl transition-opacity ${
            loaded ? 'opacity-0' : 'opacity-100'
          }`}
          style={{ background: '#eef0ff' }}
        >
          {badge.glyph}
        </div>
        {isVideo ? (
          <video
            src={asset.url}
            muted
            playsInline
            loop
            preload="metadata"
            onLoadedData={() => setLoaded(true)}
            onMouseEnter={(e) => void e.currentTarget.play().catch(() => {})}
            onMouseLeave={(e) => {
              e.currentTarget.pause()
              e.currentTarget.currentTime = 0
            }}
            className={`h-full w-full object-cover transition-opacity duration-300 ${
              loaded ? 'opacity-100' : 'opacity-0'
            }`}
          />
        ) : (
          <img
            src={asset.url}
            alt={badge.label}
            loading="lazy"
            onLoad={() => setLoaded(true)}
            className={`h-full w-full object-cover transition-opacity duration-300 ${
              loaded ? 'opacity-100' : 'opacity-0'
            }`}
          />
        )}

        {/* Top-left badge: emoji + role/source. */}
        <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-fg/80 px-2 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
          <span>{badge.glyph}</span>
          <span>{badge.label}</span>
        </span>

        {/* Top-right: video duration / kind dot. */}
        {isVideo && asset.duration_ms != null ? (
          <span className="absolute right-2 top-2 rounded-full bg-fg/80 px-1.5 py-0.5 text-[10px] font-medium text-white backdrop-blur-sm">
            {(asset.duration_ms / 1000).toFixed(1)}s
          </span>
        ) : (
          <span
            className="absolute right-2 top-2 grid h-4 w-4 place-items-center rounded-full bg-white/90 text-[9px] font-semibold text-fg backdrop-blur-sm"
            title={asset.kind}
          >
            {isVideo ? '▶' : '◌'}
          </span>
        )}

        {/* Hover overlay with controls. */}
        <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end gap-1 bg-gradient-to-t from-black/65 to-transparent p-2 opacity-0 transition group-hover:pointer-events-auto group-hover:opacity-100">
          <button
            onClick={copyUrl}
            className="rounded-md bg-white/90 px-2 py-0.5 text-[10px] font-medium text-fg hover:bg-white"
          >
            Copy URL
          </button>
          <a
            href={asset.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-md bg-white/90 px-2 py-0.5 text-[10px] font-medium text-fg hover:bg-white"
          >
            Open
          </a>
          <div className="flex-1" />
          <button
            onClick={onDelete}
            className="rounded-md bg-red-500/90 px-2 py-0.5 text-[10px] font-medium text-white hover:bg-red-500"
          >
            Delete
          </button>
        </div>
      </div>
      <div className="px-3 py-2">
        <div className="flex items-start justify-between gap-2">
          <div className="truncate text-[11.5px] font-medium leading-tight">
            {asset.label || capitalize(asset.subkind)}
          </div>
          {described && (
            <span
              className="shrink-0 rounded-full bg-accent-soft px-1.5 py-0.5 text-[9px] font-medium text-accent"
              title="AI-described — visible to the storyboard planner"
            >
              ✨ AI
            </span>
          )}
        </div>
        {describing ? (
          <div className="mt-1 line-clamp-2 text-[10.5px] italic text-fg-mute">
            describing with Gemini Vision…
          </div>
        ) : described ? (
          <div
            className="mt-1 line-clamp-2 text-[10.5px] leading-snug text-fg-mute"
            title={asset.description ?? ''}
          >
            {asset.description}
          </div>
        ) : describeFailed ? (
          <div className="mt-1 text-[10.5px] text-danger">
            describe failed —
            <button
              onClick={onDescribe}
              className="ml-1 underline-offset-2 hover:underline"
            >
              retry
            </button>
          </div>
        ) : showDescribeButton ? (
          <button
            onClick={onDescribe}
            className="mt-1 inline-flex items-center gap-1 rounded-full border border-dashed border-line px-2 py-0.5 text-[10px] text-fg-dim transition hover:border-accent hover:text-accent"
          >
            <span>✨</span>
            <span>describe with AI</span>
          </button>
        ) : null}
        {asset.tags && asset.tags.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {asset.tags.slice(0, 4).map((t) => (
              <span
                key={t}
                className="rounded-full bg-bg-soft px-1.5 py-0.5 text-[9.5px] text-fg-dim"
              >
                {t}
              </span>
            ))}
          </div>
        )}
        <div className="mt-1 flex items-center justify-between gap-2 text-[10.5px] text-fg-mute">
          <span className="truncate">{capitalize(asset.subkind)}</span>
          <span className="shrink-0 tabular-nums">
            {relativeAge(asset.created_at)}
          </span>
        </div>
      </div>
    </li>
  )
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s
}

function relativeAge(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const ms = Date.now() - t
  const sec = Math.floor(ms / 1000)
  if (sec < 60) return 'just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.floor(hr / 24)
  if (day < 7) return `${day}d ago`
  return new Date(iso).toLocaleDateString()
}
