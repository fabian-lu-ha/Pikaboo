import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import {
  useStoryboardStore,
  type CastSlot,
  type CritiqueMutation,
  type CritiquePlan,
  type CritiqueWeakness,
  type Frame,
  type ImprovementStatus,
  type MutationCost,
  type StoryboardVersion,
} from '../stores/storyboardStore'
import type {
  AudienceSegment,
  CastKind,
  CinematicBrief,
  DesignTemplate,
  Effect,
  EffectKind,
  FocalZone,
  SegmentTarget,
  StoryboardEndCard,
  StoryboardNarrative,
  StoryboardTitleCard,
  VeoQuality,
  VideoAspect,
  VoiceName,
  VoiceoverSpec,
} from '../events/bus'
import type { VoiceoverStatus } from '../stores/storyboardStore'
import ImageEditModal from './edit/ImageEditModal'
import EditOverlayButtons from './edit/EditOverlayButtons'
import type { EditAspect } from '../lib/imageEdit'
// Emoji per cast kind. Source of truth lives in `lib/assets.ts` so the
// asset-library tiles, ingredient pickers, and CastCard placeholders all
// agree on which glyph stands in for which type.
import { CAST_KIND_EMOJI, type AssetItem } from '../lib/assets'
import { useAssetLibraryStore } from '../stores/assetLibraryStore'

const ASPECTS: VideoAspect[] = ['9:16', '16:9', '1:1']
const VIDEO_QUALITIES: VeoQuality[] = ['fast', 'quality']
const VOICE_NAMES: VoiceName[] = [
  'Aoede',
  'Charon',
  'Fenrir',
  'Kore',
  'Leda',
  'Orus',
  'Puck',
  'Schedar',
  'Vindemiatrix',
  'Zephyr',
]

function aspectCss(aspect: VideoAspect): string {
  switch (aspect) {
    case '9:16':
      return '9 / 16'
    case '16:9':
      return '16 / 9'
    case '1:1':
      return '1 / 1'
  }
}

function aspectGlyph(aspect: VideoAspect): string {
  switch (aspect) {
    case '9:16':
      return '▯'
    case '16:9':
      return '▭'
    case '1:1':
      return '◻'
  }
}

function castGlyph(kind: CastKind): string {
  return CAST_KIND_EMOJI[kind]
}

function castKindLabel(kind: CastKind): string {
  switch (kind) {
    case 'character':
      return 'Character'
    case 'setting':
      return 'Setting'
    case 'prop':
      return 'Prop'
    case 'product':
      return 'Product'
  }
}

export function Storyboard() {
  const status = useStoryboardStore((s) => s.status)
  const aspect = useStoryboardStore((s) => s.aspect)
  const frames = useStoryboardStore((s) => s.frames)
  const cast = useStoryboardStore((s) => s.cast)
  const storyboardId = useStoryboardStore((s) => s.storyboardId)
  const narrative = useStoryboardStore((s) => s.narrative)
  const cinematicBrief = useStoryboardStore((s) => s.cinematicBrief)
  const segment = useStoryboardStore((s) => s.segment)
  const availableSegments = useStoryboardStore((s) => s.availableSegments)
  const selectedSegmentId = useStoryboardStore((s) => s.selectedSegmentId)
  const loadSegments = useStoryboardStore((s) => s.loadSegments)
  const setSelectedSegment = useStoryboardStore((s) => s.setSelectedSegment)
  const videoUrl = useStoryboardStore((s) => s.videoUrl)
  const videoDurationMs = useStoryboardStore((s) => s.videoDurationMs)
  const videoId = useStoryboardStore((s) => s.videoId)
  const voiceover = useStoryboardStore((s) => s.voiceover)
  const voiceoverStatus = useStoryboardStore((s) => s.voiceoverStatus)
  const voiceoverError = useStoryboardStore((s) => s.voiceoverError)
  const voicedVideoUrl = useStoryboardStore((s) => s.voicedVideoUrl)
  const updateVoiceover = useStoryboardStore((s) => s.updateVoiceover)
  const generateVoiceover = useStoryboardStore((s) => s.generateVoiceover)
  const error = useStoryboardStore((s) => s.error)
  const setAspect = useStoryboardStore((s) => s.setAspect)
  const videoQuality = useStoryboardStore((s) => s.videoQuality)
  const setVideoQuality = useStoryboardStore((s) => s.setVideoQuality)
  const addFrame = useStoryboardStore((s) => s.addFrame)
  const removeFrame = useStoryboardStore((s) => s.removeFrame)
  const updateFrame = useStoryboardStore((s) => s.updateFrame)
  const suggestFromCampaign = useStoryboardStore((s) => s.suggestFromCampaign)
  const generateFrame = useStoryboardStore((s) => s.generateFrame)
  const generateAllFrames = useStoryboardStore((s) => s.generateAllFrames)
  const generateScene = useStoryboardStore((s) => s.generateScene)
  const generateAllScenes = useStoryboardStore((s) => s.generateAllScenes)
  const generateAllIngredients = useStoryboardStore(
    (s) => s.generateAllIngredients,
  )
  const regenerateIngredient = useStoryboardStore((s) => s.regenerateIngredient)
  const renderVideo = useStoryboardStore((s) => s.renderVideo)
  const loadLatestStoryboard = useStoryboardStore(
    (s) => s.loadLatestStoryboard,
  )
  const requestCritique = useStoryboardStore((s) => s.requestCritique)
  const dismissCritique = useStoryboardStore((s) => s.dismissCritique)
  const applyImprovements = useStoryboardStore((s) => s.applyImprovements)
  const loadVersion = useStoryboardStore((s) => s.loadVersion)
  const improvementStatus = useStoryboardStore((s) => s.improvementStatus)
  const improvementError = useStoryboardStore((s) => s.improvementError)
  const pendingCritique = useStoryboardStore((s) => s.pendingCritique)
  const versions = useStoryboardStore((s) => s.versions)
  const currentVersion = useStoryboardStore((s) => s.currentVersion)

  // On first mount, hydrate from the backend's persisted storyboard so a
  // page reload doesn't strand the user with empty frames while their
  // generated media (image_url / clip_url / rendered video / voiced video)
  // sits unreachable in storage. We only hydrate when nothing's loaded yet
  // — never overwrite an in-flight session.
  useEffect(() => {
    if (storyboardId === null && frames.length === 0) {
      void loadLatestStoryboard()
    }
    // Always refresh the segment picker on mount so the dropdown reflects
    // any segments saved since the last visit.
    void loadSegments()
    // Mount-only — guarded by the storyboardId/frames check above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const isSuggesting = status === 'suggesting'
  const isRendering = status === 'rendering'
  // Render is enabled as soon as every frame has at least one of clip_url or
  // image_url. The renderer prefers clip_url server-side.
  const allReady =
    frames.length > 0 && frames.every((f) => !!f.clip_url || !!f.image_url)

  const castList = Object.values(cast)
  const allCastReady =
    castList.length === 0
      ? true
      : castList.every((c) => c.status === 'ready' && !!c.canonical_url)
  const anyFrameGenerating = frames.some((f) => f.status === 'generating')
  const anyClipGenerating = frames.some((f) => f.clip_status === 'generating')
  const generateAllFramesEnabled =
    allCastReady &&
    !anyFrameGenerating &&
    frames.some((f) => f.prompt.trim().length > 0)
  // Two-phase pipeline: animation requires a keyframe per frame. The
  // ControlBar's "Animate keyframes" button is enabled only when at least
  // one frame has a still rendered (image_url) and nothing's already in
  // flight.
  const anyKeyframeReady = frames.some((f) => !!f.image_url)
  const generateAllScenesEnabled =
    !!storyboardId &&
    !anyClipGenerating &&
    anyKeyframeReady &&
    frames.some((f) => f.prompt.trim().length > 0)

  const titleCard = useStoryboardStore((s) => s.titleCard)
  const endCard = useStoryboardStore((s) => s.endCard)

  const showCastStrip = !!storyboardId && castList.length > 0
  const showNarrative = !!narrative && !!narrative.premise
  const showBrief =
    !!cinematicBrief &&
    (cinematicBrief.reference_films.length > 0 ||
      cinematicBrief.lensing.length > 0 ||
      cinematicBrief.lighting.length > 0 ||
      cinematicBrief.palette_grade.length > 0)
  const showBookends = !!titleCard?.text || !!endCard?.headline || !!endCard?.cta

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
      className="mt-8 overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
    >
      <header className="flex items-baseline justify-between border-b border-line-soft px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="grid h-5 min-w-5 place-items-center rounded-md bg-accent px-1.5 text-[11px] font-semibold text-white">
            🎬
          </span>
          <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Storyboard
          </span>
        </div>
        <span className="text-xs text-fg-dim">
          Generate a marketing video from your campaign
        </span>
      </header>

      {frames.length === 0 ? (
        <EmptyState
          isSuggesting={isSuggesting}
          onSuggest={suggestFromCampaign}
          error={status === 'failed' ? error : null}
        />
      ) : (
        <div className="flex flex-col gap-4 px-5 py-4">
          {segment && <TargetingBanner segment={segment} />}

          {showBookends && (
            <BookendsBanner titleCard={titleCard} endCard={endCard} />
          )}

          {showNarrative && narrative && (
            <NarrativeBanner narrative={narrative} />
          )}

          {showBrief && cinematicBrief && (
            <DirectorBriefBanner brief={cinematicBrief} />
          )}

          <SegmentPicker
            segments={availableSegments}
            selectedId={selectedSegmentId}
            onSelect={setSelectedSegment}
          />

          {showCastStrip && (
            <CastStrip
              cast={castList}
              allReady={allCastReady}
              onGenerateAll={generateAllIngredients}
              onRegenerate={regenerateIngredient}
            />
          )}

          <ControlBar
            aspect={aspect}
            onAspectChange={setAspect}
            videoQuality={videoQuality}
            onVideoQualityChange={setVideoQuality}
            onSuggest={suggestFromCampaign}
            isSuggesting={isSuggesting}
            onAddFrame={addFrame}
            onRender={renderVideo}
            renderEnabled={allReady && !isRendering}
            isRendering={isRendering}
            frameCount={frames.length}
            onGenerateAllFrames={generateAllFrames}
            generateAllFramesEnabled={generateAllFramesEnabled}
            onGenerateAllScenes={generateAllScenes}
            generateAllScenesEnabled={generateAllScenesEnabled}
            castReady={allCastReady}
            castCount={castList.length}
            onCritique={() => void requestCritique()}
            critiqueEnabled={!!videoUrl && improvementStatus !== 'critiquing' && improvementStatus !== 'applying'}
            critiqueLoading={improvementStatus === 'critiquing'}
          />

          {versions.length > 1 && (
            <VersionStrip
              versions={versions}
              currentVersion={currentVersion}
              onLoad={(n) => void loadVersion(n)}
            />
          )}

          {improvementStatus === 'applying' && (
            <ImprovingBanner />
          )}

          {improvementStatus === 'failed' && improvementError && (
            <div className="rounded-md border border-danger/30 bg-bg-card px-3 py-2 text-xs text-danger">
              Critic / improvement failed: {improvementError}
              <button
                type="button"
                onClick={dismissCritique}
                className="ml-3 rounded-full border border-line px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-fg-mute hover:border-accent hover:text-accent"
              >
                dismiss
              </button>
            </div>
          )}

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            <AnimatePresence initial={false}>
              {frames.map((frame, idx) => (
                <FrameWindow
                  key={frame.id}
                  frame={frame}
                  index={idx}
                  total={frames.length}
                  aspect={aspect}
                  cast={cast}
                  onUpdate={(patch) => updateFrame(frame.id, patch)}
                  onRemove={() => removeFrame(frame.id)}
                  onGenerate={() => generateFrame(frame.id)}
                  onGenerateClip={() => generateScene(frame.id)}
                />
              ))}
            </AnimatePresence>
          </div>

          {isRendering && <RenderingRibbon />}

          {status === 'failed' && error && (
            <ErrorBanner error={error} onRetry={renderVideo} />
          )}

          {videoUrl && (
            <VideoPreview
              url={voicedVideoUrl ?? videoUrl}
              silentUrl={voicedVideoUrl ? videoUrl : null}
              aspect={aspect}
              durationMs={videoDurationMs}
              voiced={!!voicedVideoUrl}
            />
          )}

          {videoUrl && videoId && (
            <VoiceoverPanel
              voiceover={voiceover}
              status={voiceoverStatus}
              error={voiceoverError}
              voicedReady={!!voicedVideoUrl}
              onUpdate={updateVoiceover}
              onGenerate={generateVoiceover}
            />
          )}
        </div>
      )}

      <CritiqueModal
        plan={pendingCritique}
        open={pendingCritique !== null && improvementStatus === 'review'}
        onDismiss={dismissCritique}
        onApply={(ids) => void applyImprovements(ids)}
        applying={improvementStatus === 'applying'}
      />
    </motion.section>
  )
}

function EmptyState({
  isSuggesting,
  onSuggest,
  error,
}: {
  isSuggesting: boolean
  onSuggest: () => void
  error: string | null
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 px-5 py-14 text-center">
      <div className="font-serif text-2xl tracking-tight text-fg">
        Turn this campaign into a video
      </div>
      <p className="max-w-md text-sm leading-relaxed text-fg-mute">
        Six keyframes auto-filled from your draft, generated with nano-banana-pro,
        then composed by Remotion into an MP4 you can ship anywhere.
      </p>
      <button
        type="button"
        onClick={onSuggest}
        disabled={isSuggesting}
        className="mt-2 rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-white shadow-[0_4px_14px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
      >
        {isSuggesting ? 'Suggesting…' : 'Suggest from campaign'}
      </button>
      {error && (
        <div className="mt-2 max-w-md rounded-md border border-danger/30 bg-bg-card px-3 py-2 text-xs text-danger">
          {error}
        </div>
      )}
    </div>
  )
}

function CastStrip({
  cast,
  allReady,
  onGenerateAll,
  onRegenerate,
}: {
  cast: CastSlot[]
  allReady: boolean
  onGenerateAll: () => void
  onRegenerate: (castId: string) => void
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const readyCount = cast.filter((c) => c.status === 'ready').length

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex flex-col gap-2 rounded-2xl border border-line bg-bg-card p-3"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Cast bible
          </span>
          <span className="text-[10px] tabular-nums text-fg-dim">
            {readyCount}/{cast.length} ready
          </span>
        </div>
        <button
          type="button"
          onClick={onGenerateAll}
          disabled={allReady}
          className="rounded-full bg-fg px-3 py-1 text-[11px] font-medium text-bg-card transition hover:brightness-125 disabled:bg-fg-dim"
          title={
            allReady
              ? 'All ingredients ready'
              : 'Generate canonical sheets for everyone'
          }
        >
          {allReady ? 'All ingredients ready' : 'Generate all ingredients'}
        </button>
      </div>

      <div className="flex flex-row gap-2 overflow-x-auto pb-1">
        {cast.map((member) => (
          <CastCard
            key={member.id}
            member={member}
            open={openId === member.id}
            onToggle={() =>
              setOpenId((prev) => (prev === member.id ? null : member.id))
            }
            onRegenerate={() => onRegenerate(member.id)}
          />
        ))}
      </div>
    </motion.div>
  )
}

function CastCard({
  member,
  open,
  onToggle,
  onRegenerate,
}: {
  member: CastSlot
  open: boolean
  onToggle: () => void
  onRegenerate: () => void
}) {
  const isGenerating = member.status === 'generating'
  const isReady = member.status === 'ready'
  const isFailed = member.status === 'failed'
  const [imgLoaded, setImgLoaded] = useState(false)
  // Reset the load state whenever the URL changes (regenerate / import)
  // so the placeholder shows again until the new image actually paints.
  const currentUrl = member.canonical_url
  return (
    <div className="flex w-44 shrink-0 flex-col">
      <button
        type="button"
        onClick={onToggle}
        className={`group relative flex flex-col gap-1.5 rounded-xl border bg-bg-card p-2 text-left transition ${
          open
            ? 'border-accent shadow-[0_2px_10px_rgba(111,92,255,0.18)]'
            : 'border-line hover:border-accent/60'
        }`}
      >
        <div className="relative h-16 w-16 overflow-hidden rounded-lg bg-bg-soft">
          {/* Emoji placeholder always present underneath; the real image
              fades in over it once it actually paints, so there's no jarring
              broken-img flash when canonical_url is set but still loading. */}
          <div className="absolute inset-0 grid place-items-center text-2xl">
            {castGlyph(member.kind)}
          </div>
          {currentUrl && (
            <img
              key={currentUrl}
              src={currentUrl}
              alt={member.role}
              onLoad={() => setImgLoaded(true)}
              onError={() => setImgLoaded(false)}
              className={`absolute inset-0 h-full w-full object-cover transition-opacity duration-300 ${
                imgLoaded ? 'opacity-100' : 'opacity-0'
              }`}
            />
          )}
          {isGenerating && (
            <motion.div
              initial={{ opacity: 0.4 }}
              animate={{ opacity: [0.4, 0.85, 0.4] }}
              transition={{ duration: 1.2, repeat: Infinity }}
              className="pointer-events-none absolute inset-0 bg-accent/40"
            />
          )}
          <span
            className={`absolute right-1 top-1 grid h-3.5 w-3.5 place-items-center rounded-full text-[8px] ${
              isReady
                ? 'bg-success text-white'
                : isFailed
                  ? 'bg-danger text-white'
                  : isGenerating
                    ? 'bg-accent text-white'
                    : 'bg-fg-dim text-bg-card'
            }`}
            title={member.status}
          >
            {isReady ? '●' : isFailed ? '✕' : isGenerating ? '◐' : '○'}
          </span>
        </div>
        <div className="flex flex-col">
          <span
            className="truncate text-xs font-medium text-fg"
            title={member.role}
          >
            <span className="mr-1">{castGlyph(member.kind)}</span>
            {member.role}
          </span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
            {member.binding.type === 'brand_asset' ? 'brand' : 'synthesized'}
          </span>
        </div>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 flex flex-col gap-2 rounded-xl border border-line-soft bg-bg-soft/50 p-2">
              <div className="text-[10px] uppercase tracking-[0.18em] text-fg-mute">
                {castKindLabel(member.kind)} ·{' '}
                {member.binding.type === 'brand_asset'
                  ? 'brand asset'
                  : 'synthesized'}
              </div>
              <div className="text-[11px] leading-relaxed text-fg-mute">
                {member.description}
              </div>
              {member.error && (
                <div className="text-[10px] text-danger">{member.error}</div>
              )}
              <div className="flex flex-wrap gap-1.5">
                <button
                  type="button"
                  onClick={onRegenerate}
                  disabled={isGenerating}
                  className="rounded-full border border-line bg-bg-card px-3 py-1 text-[11px] text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
                >
                  {isGenerating ? 'Generating…' : 'Regenerate'}
                </button>
                <ImportFromLibraryButton
                  castId={member.id}
                  castKind={member.kind}
                />
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

// Picker that lets the user reuse a previously-generated ingredient or
// any saved image asset for this cast slot. Pulls assets that match the
// member's kind first; falls back to all images so a "Character" slot can
// still grab an unrelated image if the user wants.
function ImportFromLibraryButton({
  castId,
  castKind,
}: {
  castId: string
  castKind: CastKind
}) {
  const [open, setOpen] = useState(false)
  const items = useAssetLibraryStore((s) => s.items)
  const loading = useAssetLibraryStore((s) => s.loading)
  const importIngredient = useStoryboardStore((s) => s.importIngredient)

  // Order assets by usefulness for THIS cast slot:
  //   1. cast_kind matches AND has an AI description (best signal)
  //   2. cast_kind matches but no description yet
  //   3. other cast_kind, described
  //   4. other cast_kind, no description
  // The describer tags character/setting/prop/product on every image so
  // sort-by-match-first gets us the right photo for the slot the user
  // is staring at, with the AI description making intent legible.
  const allImages = items.filter((a) => a.kind === 'image')
  const tier = (a: AssetItem): number => {
    const matches = a.cast_kind === castKind
    const described = !!a.description
    if (matches && described) return 0
    if (matches) return 1
    if (described) return 2
    return 3
  }
  const ordered: AssetItem[] = [...allImages]
    .sort((a, b) => tier(a) - tier(b))
    .slice(0, 30)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-full border border-line bg-bg-card px-3 py-1 text-[11px] text-fg-mute transition hover:border-accent hover:text-accent"
      >
        ↓ Import from library
      </button>
      <AnimatePresence>
        {open && (
          <>
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.18 }}
              className="fixed inset-0 z-50 bg-black/40 backdrop-blur-[2px]"
              onClick={() => setOpen(false)}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 6 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 6 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="fixed left-1/2 top-1/2 z-50 max-h-[70vh] w-[min(92vw,640px)] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-line bg-bg-card shadow-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <header className="flex items-center justify-between border-b border-line px-5 py-3">
                <div>
                  <div className="text-[13px] font-semibold">
                    Import {castKindLabel(castKind).toLowerCase()} from
                    library
                  </div>
                  <div className="mt-0.5 text-[11px] text-fg-mute">
                    Reuse a saved photo from a past storyboard.
                  </div>
                </div>
                <button
                  onClick={() => setOpen(false)}
                  className="grid h-7 w-7 place-items-center rounded-md text-fg-mute hover:bg-bg-soft hover:text-fg"
                  aria-label="Close"
                >
                  ✕
                </button>
              </header>
              <div className="max-h-[58vh] overflow-y-auto p-4 [scrollbar-width:thin]">
                {loading && ordered.length === 0 ? (
                  <div className="grid place-items-center py-12 text-[12px] text-fg-mute">
                    loading library…
                  </div>
                ) : ordered.length === 0 ? (
                  <div className="grid place-items-center px-6 py-12 text-center text-[12px] text-fg-mute">
                    Nothing saved yet — generate at least one ingredient and
                    it'll appear here for reuse.
                  </div>
                ) : (
                  <ul className="grid grid-cols-3 gap-3 sm:grid-cols-4">
                    {ordered.map((a) => {
                      const matches = a.cast_kind === castKind
                      const desc = a.description ?? ''
                      return (
                        <li
                          key={a.id}
                          className="flex flex-col gap-1.5"
                          title={desc || a.label || a.subkind}
                        >
                          <button
                            type="button"
                            onClick={() => {
                              importIngredient(castId, a.url)
                              setOpen(false)
                            }}
                            className="group relative aspect-[4/5] w-full overflow-hidden rounded-xl border border-line bg-bg-soft transition hover:border-accent"
                          >
                            <img
                              src={a.url}
                              alt={a.label || a.subkind}
                              loading="lazy"
                              className="h-full w-full object-cover"
                            />
                            <span className="absolute left-1.5 top-1.5 inline-flex items-center gap-1 rounded-full bg-fg/80 px-1.5 py-0.5 text-[9px] font-medium text-white backdrop-blur-sm">
                              {a.cast_kind
                                ? CAST_KIND_EMOJI[a.cast_kind]
                                : '✨'}
                              {matches ? ' match' : ''}
                            </span>
                            {desc && (
                              <span
                                className="absolute right-1.5 top-1.5 rounded-full bg-accent-soft px-1.5 py-0.5 text-[8.5px] font-semibold text-accent backdrop-blur-sm"
                                title="AI-described"
                              >
                                ✨
                              </span>
                            )}
                          </button>
                          {desc ? (
                            <p className="line-clamp-2 px-0.5 text-[9.5px] leading-snug text-fg-mute">
                              {desc}
                            </p>
                          ) : (
                            <p className="px-0.5 text-[9.5px] italic text-fg-dim">
                              {a.label || a.subkind}
                            </p>
                          )}
                        </li>
                      )
                    })}
                  </ul>
                )}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  )
}

function ControlBar({
  aspect,
  onAspectChange,
  videoQuality,
  onVideoQualityChange,
  onSuggest,
  isSuggesting,
  onAddFrame,
  onRender,
  renderEnabled,
  isRendering,
  frameCount,
  onGenerateAllFrames,
  generateAllFramesEnabled,
  onGenerateAllScenes,
  generateAllScenesEnabled,
  castReady,
  castCount,
  onCritique,
  critiqueEnabled,
  critiqueLoading,
}: {
  aspect: VideoAspect
  onAspectChange: (a: VideoAspect) => void
  videoQuality: VeoQuality
  onVideoQualityChange: (q: VeoQuality) => void
  onSuggest: () => void
  isSuggesting: boolean
  onAddFrame: () => void
  onRender: () => void
  renderEnabled: boolean
  isRendering: boolean
  frameCount: number
  onGenerateAllFrames: () => void
  generateAllFramesEnabled: boolean
  onGenerateAllScenes: () => void
  generateAllScenesEnabled: boolean
  castReady: boolean
  castCount: number
  onCritique: () => void
  critiqueEnabled: boolean
  critiqueLoading: boolean
}) {
  const generateAllTitle = !castReady
    ? 'Generate cast ingredients first'
    : !generateAllFramesEnabled
      ? 'Add prompts and wait for any in-flight keyframes'
      : 'Render every keyframe in parallel (~5s each — cheap preview)'

  const generateAllScenesTitle = !generateAllScenesEnabled
    ? 'Render at least one keyframe first — Veo animates the keyframe'
    : 'Animate every keyframe with Veo in parallel (~30-90s each)'

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onSuggest}
          disabled={isSuggesting}
          className="rounded-full border border-line bg-bg-card px-4 py-1.5 text-xs font-medium text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
          title="Replace frames with fresh suggestions"
        >
          {isSuggesting ? 'Suggesting…' : 'Suggest from campaign'}
        </button>

        <div className="flex items-center gap-1 rounded-full border border-line bg-bg-card p-0.5">
          {ASPECTS.map((a) => {
            const active = aspect === a
            return (
              <button
                key={a}
                type="button"
                onClick={() => onAspectChange(a)}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition ${
                  active
                    ? 'bg-accent text-white shadow-[0_2px_8px_rgba(111,92,255,0.3)]'
                    : 'text-fg-mute hover:text-fg'
                }`}
                aria-pressed={active}
              >
                <span className="text-[10px]">{aspectGlyph(a)}</span>
                <span className="tabular-nums">{a}</span>
              </button>
            )
          })}
        </div>

        <div
          className="flex items-center gap-1 rounded-full border border-line bg-bg-card p-0.5"
          title="Veo render tier — Fast renders ~30-45s/clip; Quality is the hero render at ~60-90s/clip"
        >
          {VIDEO_QUALITIES.map((q) => {
            const active = videoQuality === q
            return (
              <button
                key={q}
                type="button"
                onClick={() => onVideoQualityChange(q)}
                className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-medium transition ${
                  active
                    ? 'bg-accent text-white shadow-[0_2px_8px_rgba(111,92,255,0.3)]'
                    : 'text-fg-mute hover:text-fg'
                }`}
                aria-pressed={active}
              >
                <span className="text-[10px]">{q === 'fast' ? '⚡' : '✦'}</span>
                <span className="capitalize">{q}</span>
              </button>
            )
          })}
        </div>

        <button
          type="button"
          onClick={onAddFrame}
          className="rounded-full border border-dashed border-line bg-bg-card px-3 py-1.5 text-xs text-fg-mute transition hover:border-accent hover:text-accent"
          title="Add an empty frame"
        >
          + Add frame
        </button>

        <span className="ml-1 text-[11px] uppercase tracking-[0.18em] text-fg-dim">
          {frameCount} {frameCount === 1 ? 'frame' : 'frames'}
        </span>
        {castCount > 0 && !castReady && (
          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
            cast not ready
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onGenerateAllFrames}
          disabled={!generateAllFramesEnabled}
          className="rounded-full border border-line bg-bg-card px-4 py-1.5 text-xs font-medium text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
          title={generateAllTitle}
        >
          1 · Render keyframes
        </button>
        <button
          type="button"
          onClick={onGenerateAllScenes}
          disabled={!generateAllScenesEnabled}
          className="rounded-full border border-line bg-bg-card px-4 py-1.5 text-xs font-medium text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
          title={generateAllScenesTitle}
        >
          2 · Animate with Veo
        </button>
        <button
          type="button"
          onClick={onRender}
          disabled={!renderEnabled}
          className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
          title={
            renderEnabled
              ? 'Render video with Remotion'
              : 'Generate every frame first'
          }
        >
          {isRendering ? 'Rendering…' : 'Render video →'}
        </button>
        <button
          type="button"
          onClick={onCritique}
          disabled={!critiqueEnabled}
          className="rounded-full border border-line bg-bg-card px-4 py-1.5 text-xs font-medium text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
          title={
            critiqueEnabled
              ? 'Ask the AI critic to review v1 and propose improvements'
              : 'Render the video first — the critic reviews the rendered mp4'
          }
        >
          {critiqueLoading ? 'Critiquing…' : '⚖ Critique'}
        </button>
      </div>
    </div>
  )
}

function FrameWindow({
  frame,
  index,
  total,
  aspect,
  cast,
  onUpdate,
  onRemove,
  onGenerate,
  onGenerateClip,
}: {
  frame: Frame
  index: number
  total: number
  aspect: VideoAspect
  cast: Record<string, CastSlot>
  onUpdate: (patch: Partial<Omit<Frame, 'id'>>) => void
  onRemove: () => void
  onGenerate: () => void
  onGenerateClip: () => void
}) {
  // Pure-graphic Remotion beats need a different editor — no Veo flow, no
  // keyframe pipeline, just template params. Route them to a dedicated card.
  if (frame.kind === 'design_sequence') {
    return (
      <DesignFrameWindow
        frame={frame}
        index={index}
        total={total}
        onUpdate={onUpdate}
        onRemove={onRemove}
      />
    )
  }
  const canGenerate = frame.prompt.trim().length > 0 && frame.status !== 'generating'
  // Two-phase pipeline: animation requires a keyframe (frame.image_url) so
  // Veo runs in image-to-video mode with the still as its first frame.
  const hasKeyframe = !!frame.image_url
  const canGenerateClip =
    frame.prompt.trim().length > 0 &&
    frame.clip_status !== 'generating' &&
    hasKeyframe
  const generateLabel =
    frame.status === 'generating'
      ? 'Rendering keyframe…'
      : frame.stale
        ? 'Regenerate keyframe'
        : frame.status === 'ready'
          ? 'Regenerate keyframe'
          : 'Generate keyframe'
  const clipLabel =
    frame.clip_status === 'generating'
      ? 'Animating…'
      : frame.clip_status === 'ready'
        ? 'Re-animate'
        : 'Animate keyframe'
  const clipTitle = !hasKeyframe
    ? 'Generate the keyframe first — Veo animates it into a clip'
    : 'Send the keyframe + motion direction to Veo'

  const referencedCast = frame.cast_refs
    .map((id) => cast[id])
    .filter((c): c is CastSlot => !!c)

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.18 } }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={`flex flex-col overflow-hidden rounded-xl border bg-bg-card transition-colors ${
        frame.stale ? 'border-warn/60' : 'border-line'
      }`}
    >
      <MediaPreview frame={frame} aspect={aspect} />

      <div className="flex flex-col gap-2 px-3 py-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Prompt
          </span>
          <textarea
            rows={3}
            value={frame.prompt}
            onChange={(e) => onUpdate({ prompt: e.target.value })}
            placeholder="A cinematic shot of…"
            className="resize-none rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs leading-relaxed text-fg outline-none transition focus:border-accent"
          />
        </label>

        <CastRefsRow members={referencedCast} />

        <EffectsRow effects={frame.effects} />

        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Caption
          </span>
          <input
            value={frame.caption}
            maxLength={120}
            onChange={(e) => onUpdate({ caption: e.target.value })}
            placeholder="On-screen text…"
            className="rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs text-fg outline-none transition focus:border-accent"
          />
          <span className="text-right text-[10px] tabular-nums text-fg-dim">
            {frame.caption.length}/120
          </span>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Motion (Veo direction)
          </span>
          <input
            value={frame.motion}
            onChange={(e) => onUpdate({ motion: e.target.value })}
            placeholder="Slow push-in, subject turns head…"
            className="rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs text-fg outline-none transition focus:border-accent"
          />
        </label>

        <label className="flex items-center gap-2">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Duration
          </span>
          <input
            type="range"
            min={1500}
            max={4000}
            step={100}
            value={frame.duration_ms}
            onChange={(e) => onUpdate({ duration_ms: Number(e.target.value) })}
            className="flex-1 accent-accent"
          />
          <span className="w-14 text-right text-[10px] tabular-nums text-fg-mute">
            {(frame.duration_ms / 1000).toFixed(1)}s
          </span>
        </label>
      </div>

      <footer className="flex flex-col gap-2 border-t border-line-soft px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onGenerate}
              disabled={!canGenerate}
              className="rounded-full bg-fg px-3 py-1 text-[11px] font-medium text-bg-card transition hover:brightness-125 disabled:bg-fg-dim"
            >
              {generateLabel}
            </button>
            <FrameStatusDot frame={frame} />
          </div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] tabular-nums text-fg-dim">
              {String(index + 1).padStart(2, '0')} /{' '}
              {String(total).padStart(2, '0')}
            </span>
            <button
              type="button"
              onClick={onRemove}
              title="Remove frame"
              className="grid h-6 w-6 place-items-center rounded-full text-fg-dim transition hover:bg-bg-soft hover:text-danger"
            >
              ✕
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onGenerateClip}
            disabled={!canGenerateClip}
            className="rounded-full border border-accent/50 bg-bg-card px-3 py-1 text-[11px] font-medium text-accent transition hover:bg-accent hover:text-white disabled:border-line disabled:bg-bg-card disabled:text-fg-dim"
            title={clipTitle}
          >
            {clipLabel}
          </button>
          <ClipStatusDot frame={frame} />
        </div>
      </footer>
    </motion.article>
  )
}

// ─── design_sequence editor ─────────────────────────────────────────────────
// design_sequence frames are pure-graphic Remotion templates — no Veo, no
// keyframe pipeline. They get their own editor card so the user reads them
// as "graphic beat" instead of "shot still rendering". Visually distinct via
// accent-deep accents instead of the live-action accent.

function templateLabel(t: DesignTemplate): string {
  switch (t) {
    case 'gradient_kinetic':
      return 'Gradient Hero'
    case 'spec_card':
      return 'Spec Card'
    case 'ui_zoom':
      return 'UI Zoom'
    case 'code_window':
      return 'Code Window'
    case 'logo_reveal':
      return 'Logo Reveal'
    case 'comparison_split':
      return 'Comparison Split'
    case 'text_scroll':
      return 'Text Scroll'
    case 'headline_punch':
      return 'Headline Punch'
    case 'word_kinetic':
      return 'Word Kinetic'
    case 'canvas_kinetic':
      return 'Canvas Kinetic'
  }
}

function DesignFrameWindow({
  frame,
  index,
  total,
  onUpdate,
  onRemove,
}: {
  frame: Frame
  index: number
  total: number
  onUpdate: (patch: Partial<Omit<Frame, 'id'>>) => void
  onRemove: () => void
}) {
  const template = frame.template
  const params = (frame.template_params ?? {}) as Record<string, unknown>

  // Param patch helper — preserves any unknown keys the planner attached.
  const patchParams = (patch: Record<string, unknown>) => {
    onUpdate({ template_params: { ...params, ...patch } })
  }

  // TODO(future): wire to a backend per-frame regen endpoint when one
  // exists. For canvas_kinetic specifically, regen should re-fire
  // nano-banana with fresh canvas_prompt — a /regenerate-canvas endpoint
  // is the next step. For now this just re-spreads template_params to
  // nudge a re-render and clears any stored canvas_url so the next /render
  // re-generates the bg from the (possibly edited) canvas_prompt.
  const onRegenerateTemplate = () => {
    if (template === 'canvas_kinetic') {
      const next = { ...params }
      delete next.canvas_url
      onUpdate({ template_params: next })
      return
    }
    onUpdate({ template_params: { ...params } })
  }

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 10, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, scale: 0.97, transition: { duration: 0.18 } }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="flex flex-col overflow-hidden rounded-xl border border-accent-deep/40 bg-bg-card"
    >
      <DesignPreviewTile template={template} params={params} />

      <div className="flex flex-col gap-2 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-accent-deep/40 bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] text-accent-deep">
            <span className="text-[8px]">◆</span>
            {template ? templateLabel(template) : 'Design'}
          </span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
            graphic beat · no Veo
          </span>
        </div>

        {template === 'gradient_kinetic' && (
          <GradientKineticEditor params={params} onPatch={patchParams} />
        )}
        {template === 'spec_card' && (
          <SpecCardEditor params={params} onPatch={patchParams} />
        )}
        {template === 'ui_zoom' && (
          <UiZoomEditor params={params} onPatch={patchParams} />
        )}
        {template === 'code_window' && (
          <CodeWindowEditor params={params} onPatch={patchParams} />
        )}
        {template === 'logo_reveal' && (
          <LogoRevealEditor params={params} onPatch={patchParams} />
        )}
        {template === 'comparison_split' && (
          <ComparisonSplitEditor params={params} onPatch={patchParams} />
        )}
        {template === 'canvas_kinetic' && (
          <CanvasKineticEditor params={params} onPatch={patchParams} />
        )}
        {!template && (
          <div className="rounded-md border border-dashed border-line bg-bg-soft/40 px-2.5 py-2 text-[11px] text-fg-mute">
            No template assigned yet. The planner usually picks one — this
            frame may have been created manually.
          </div>
        )}

        <label className="mt-1 flex items-center gap-2">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Duration
          </span>
          <input
            type="range"
            min={1500}
            max={4000}
            step={100}
            value={frame.duration_ms}
            onChange={(e) => onUpdate({ duration_ms: Number(e.target.value) })}
            className="flex-1 accent-accent-deep"
          />
          <span className="w-14 text-right text-[10px] tabular-nums text-fg-mute">
            {(frame.duration_ms / 1000).toFixed(1)}s
          </span>
        </label>
      </div>

      <footer className="flex items-center justify-between gap-2 border-t border-line-soft px-3 py-2">
        <button
          type="button"
          onClick={onRegenerateTemplate}
          className="rounded-full border border-accent-deep/40 bg-bg-card px-3 py-1 text-[11px] font-medium text-accent-deep transition hover:bg-accent-deep hover:text-white"
          title="Re-apply current params (per-frame regen endpoint TBD)"
        >
          Regenerate template
        </button>
        <div className="flex items-center gap-2">
          <span className="font-mono text-[10px] tabular-nums text-fg-dim">
            {String(index + 1).padStart(2, '0')} /{' '}
            {String(total).padStart(2, '0')}
          </span>
          <button
            type="button"
            onClick={onRemove}
            title="Remove frame"
            className="grid h-6 w-6 place-items-center rounded-full text-fg-dim transition hover:bg-bg-soft hover:text-danger"
          >
            ✕
          </button>
        </div>
      </footer>
    </motion.article>
  )
}

// ─── design preview tiles (dumb visual approximations) ──────────────────────
// These are NOT Remotion renders. They're tiny static cards so the user can
// tell at a glance which template they have. Match the dashboard's spare
// aesthetic — 16:9 to match the editor's existing media slot.

function DesignPreviewTile({
  template,
  params,
}: {
  template: DesignTemplate | null
  params: Record<string, unknown>
}) {
  if (!template) {
    return (
      <div className="grid aspect-video w-full place-items-center border-b border-dashed border-line bg-bg-soft/50 text-fg-dim">
        <div className="text-2xl">◆</div>
      </div>
    )
  }
  switch (template) {
    case 'gradient_kinetic':
      return <GradientKineticPreview params={params} />
    case 'spec_card':
      return <SpecCardPreview params={params} />
    case 'ui_zoom':
      return <UiZoomPreview params={params} />
    case 'code_window':
      return <CodeWindowPreview params={params} />
    case 'logo_reveal':
      return <LogoRevealPreview params={params} />
    case 'comparison_split':
      return <ComparisonSplitPreview params={params} />
    case 'canvas_kinetic':
      return <CanvasKineticPreview params={params} />
    case 'text_scroll':
    case 'headline_punch':
    case 'word_kinetic':
      // Task-6 kinetic templates render via the Remotion bundle; no
      // dedicated dashboard preview yet — show a generic graphic placeholder
      // so the editor card still has a visual.
      return (
        <div className="grid aspect-video w-full place-items-center border-b border-line-soft bg-bg-soft/50 text-fg-dim">
          <div className="font-serif text-2xl">{templateLabel(template)}</div>
        </div>
      )
  }
}

function GradientKineticPreview({ params }: { params: Record<string, unknown> }) {
  const headline = (params.headline as string) || 'Headline'
  const subtitle = (params.subtitle as string) || ''
  return (
    <div
      className="relative aspect-video w-full overflow-hidden border-b border-line-soft"
      style={{
        background:
          'linear-gradient(135deg, var(--color-accent) 0%, var(--color-accent-deep) 60%, #1a1735 100%)',
      }}
    >
      <div className="absolute inset-0 flex flex-col justify-end gap-1 p-4 text-white">
        <div className="font-serif text-base leading-tight">{headline}</div>
        {subtitle && (
          <div className="text-[11px] uppercase tracking-[0.18em] text-white/75">
            {subtitle}
          </div>
        )}
      </div>
    </div>
  )
}

function SpecCardPreview({ params }: { params: Record<string, unknown> }) {
  const value = (params.value as string) || 'M7'
  const label = (params.label as string) || ''
  const unit = (params.unit as string) || ''
  const theme = (params.theme as string) === 'dark' ? 'dark' : 'light'
  const isDark = theme === 'dark'
  return (
    <div
      className={`relative grid aspect-video w-full place-items-center overflow-hidden border-b border-line-soft ${
        isDark ? 'bg-fg text-bg-card' : 'bg-bg-soft text-fg'
      }`}
    >
      <div className="flex flex-col items-center gap-1">
        <div className="font-serif text-5xl font-semibold tracking-tight">
          {value}
          {unit && (
            <span className="ml-1 text-2xl font-medium opacity-70">{unit}</span>
          )}
        </div>
        {label && (
          <div className="text-[10px] uppercase tracking-[0.22em] opacity-60">
            {label}
          </div>
        )}
        <div
          className={`mt-1 h-px w-12 ${isDark ? 'bg-accent-dim' : 'bg-accent-deep'}`}
        />
      </div>
    </div>
  )
}

function UiZoomPreview({ params }: { params: Record<string, unknown> }) {
  const label = (params.label as string) || 'UI detail'
  const focus =
    typeof params.focus_zone === 'string' ? (params.focus_zone as FocalZone) : 'mc'
  return (
    <div className="relative aspect-video w-full overflow-hidden border-b border-line-soft bg-bg-soft">
      {/* Stand-in screenshot rectangle */}
      <div className="absolute inset-3 rounded-md border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.05)]">
        <div className="grid grid-cols-3 grid-rows-3 h-full">
          {(['tl','tc','tr','ml','mc','mr','bl','bc','br'] as FocalZone[]).map((z) => (
            <div
              key={z}
              className={`m-0.5 rounded-sm ${z === focus ? 'border border-accent-deep bg-accent-soft' : 'bg-bg-soft/60'}`}
            />
          ))}
        </div>
      </div>
      <div className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-full bg-fg/85 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.18em] text-bg-card">
        zoom · {focus}
      </div>
      {label && (
        <div className="absolute right-2 bottom-2 max-w-[60%] truncate rounded-md bg-fg/85 px-1.5 py-0.5 text-[9px] uppercase tracking-[0.18em] text-bg-card">
          {label}
        </div>
      )}
    </div>
  )
}

function CodeWindowPreview({ params }: { params: Record<string, unknown> }) {
  const lines = Array.isArray(params.lines)
    ? (params.lines as unknown[]).map((l) => String(l))
    : []
  const language = (params.language as string) || 'tsx'
  const theme = (params.theme as string) === 'light' ? 'light' : 'dark'
  const isDark = theme === 'dark'
  const visible = lines.slice(0, 4)
  return (
    <div className="relative aspect-video w-full overflow-hidden border-b border-line-soft bg-bg-soft">
      <div
        className={`mx-auto mt-3 w-[88%] overflow-hidden rounded-md border ${
          isDark ? 'border-fg/20 bg-fg' : 'border-line bg-bg-card'
        }`}
      >
        <div
          className={`flex items-center gap-1.5 border-b px-2 py-1 ${
            isDark ? 'border-white/10' : 'border-line-soft'
          }`}
        >
          <span className="h-1.5 w-1.5 rounded-full bg-danger" />
          <span className="h-1.5 w-1.5 rounded-full bg-warn" />
          <span className="h-1.5 w-1.5 rounded-full bg-success" />
          <span
            className={`ml-1.5 font-mono text-[8px] tracking-tight ${
              isDark ? 'text-white/60' : 'text-fg-dim'
            }`}
          >
            main.{language}
          </span>
        </div>
        <pre
          className={`m-0 p-2 font-mono text-[9px] leading-tight ${
            isDark ? 'text-bg-card' : 'text-fg'
          }`}
        >
          {visible.length === 0 ? (
            <span className="opacity-60">// no lines</span>
          ) : (
            visible.map((l, i) => (
              <div key={i} className="truncate">
                <span
                  className={`mr-1.5 inline-block w-3 text-right ${
                    isDark ? 'text-white/30' : 'text-fg-dim'
                  }`}
                >
                  {i + 1}
                </span>
                {l || ' '}
              </div>
            ))
          )}
        </pre>
      </div>
    </div>
  )
}

function LogoRevealPreview({ params }: { params: Record<string, unknown> }) {
  const wordmark = (params.wordmark as string) || (params.brand_name as string) || 'BRAND'
  const tagline = (params.tagline as string) || ''
  const theme = (params.theme as string) === 'light' ? 'light' : 'dark'
  const isDark = theme === 'dark'
  return (
    <div
      className={`relative grid aspect-video w-full place-items-center overflow-hidden border-b border-line-soft ${
        isDark ? 'bg-fg text-bg-card' : 'bg-bg-soft text-fg'
      }`}
    >
      <div className="flex flex-col items-center gap-1">
        <div className="font-serif text-2xl font-semibold tracking-tight">
          {wordmark}
        </div>
        {tagline && (
          <div className="text-[10px] uppercase tracking-[0.24em] opacity-65">
            {tagline}
          </div>
        )}
      </div>
    </div>
  )
}

function ComparisonSplitPreview({ params }: { params: Record<string, unknown> }) {
  const before = (params.before as { label?: string } | undefined)?.label || 'Before'
  const after = (params.after as { label?: string } | undefined)?.label || 'After'
  const orientation = (params.orientation as string) === 'h' ? 'h' : 'v'
  if (orientation === 'h') {
    return (
      <div className="relative grid aspect-video w-full grid-rows-2 overflow-hidden border-b border-line-soft">
        <div className="grid place-items-center bg-bg-soft text-fg-mute">
          <div className="text-[10px] uppercase tracking-[0.22em]">{before}</div>
        </div>
        <div className="grid place-items-center bg-fg text-bg-card">
          <div className="text-[10px] uppercase tracking-[0.22em]">{after}</div>
        </div>
        <div className="pointer-events-none absolute left-0 right-0 top-1/2 h-px bg-accent-deep" />
      </div>
    )
  }
  return (
    <div className="relative grid aspect-video w-full grid-cols-2 overflow-hidden border-b border-line-soft">
      <div className="grid place-items-center bg-bg-soft text-fg-mute">
        <div className="text-[10px] uppercase tracking-[0.22em]">{before}</div>
      </div>
      <div className="grid place-items-center bg-fg text-bg-card">
        <div className="text-[10px] uppercase tracking-[0.22em]">{after}</div>
      </div>
      <div className="pointer-events-none absolute bottom-0 left-1/2 top-0 w-px bg-accent-deep" />
    </div>
  )
}

// ─── per-template editors ───────────────────────────────────────────────────
// Plain text inputs/textareas styled like the live-action editor. A small
// segmented control for theme. A 9-cell radio grid for focal_zone. Grouped
// fields for nested shapes (comparison_split.before/after).

function DesignField({
  label,
  children,
}: {
  label: string
  children: React.ReactNode
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        {label}
      </span>
      {children}
    </label>
  )
}

const DESIGN_INPUT_CLASS =
  'rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs text-fg outline-none transition focus:border-accent-deep'
const DESIGN_TEXTAREA_CLASS =
  'resize-none rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs leading-relaxed text-fg outline-none transition focus:border-accent-deep'

function ThemeToggle({
  value,
  onChange,
}: {
  value: 'light' | 'dark'
  onChange: (v: 'light' | 'dark') => void
}) {
  return (
    <div className="inline-flex items-center gap-1 rounded-full border border-line bg-bg-card p-0.5">
      {(['light', 'dark'] as const).map((t) => {
        const active = value === t
        return (
          <button
            key={t}
            type="button"
            onClick={() => onChange(t)}
            className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] transition ${
              active
                ? 'bg-accent-deep text-white'
                : 'text-fg-mute hover:text-fg'
            }`}
            aria-pressed={active}
          >
            {t}
          </button>
        )
      })}
    </div>
  )
}

const FOCAL_ZONES: FocalZone[] = [
  'tl', 'tc', 'tr',
  'ml', 'mc', 'mr',
  'bl', 'bc', 'br',
]

function FocalZoneGrid({
  value,
  onChange,
}: {
  value: FocalZone
  onChange: (z: FocalZone) => void
}) {
  return (
    <div className="inline-grid grid-cols-3 gap-0.5 rounded-md border border-line bg-bg-card p-1">
      {FOCAL_ZONES.map((z) => {
        const active = z === value
        return (
          <button
            key={z}
            type="button"
            onClick={() => onChange(z)}
            aria-label={`focal zone ${z}`}
            aria-pressed={active}
            title={z}
            className={`h-4 w-4 rounded-sm transition ${
              active
                ? 'bg-accent-deep'
                : 'bg-bg-soft hover:bg-accent-dim/40'
            }`}
          />
        )
      })}
    </div>
  )
}

function GradientKineticEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  return (
    <>
      <DesignField label="Headline">
        <input
          value={(params.headline as string) ?? ''}
          onChange={(e) => onPatch({ headline: e.target.value })}
          placeholder="Bold gradient hook"
          className={DESIGN_INPUT_CLASS}
        />
      </DesignField>
      <DesignField label="Subtitle">
        <input
          value={(params.subtitle as string) ?? ''}
          onChange={(e) => onPatch({ subtitle: e.target.value })}
          placeholder="Optional supporting line"
          className={DESIGN_INPUT_CLASS}
        />
      </DesignField>
    </>
  )
}

function SpecCardEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  const theme = (params.theme as string) === 'dark' ? 'dark' : 'light'
  return (
    <>
      <DesignField label="Value">
        <input
          value={(params.value as string) ?? ''}
          onChange={(e) => onPatch({ value: e.target.value })}
          placeholder="M7"
          className={DESIGN_INPUT_CLASS}
        />
      </DesignField>
      <div className="grid grid-cols-2 gap-2">
        <DesignField label="Label">
          <input
            value={(params.label as string) ?? ''}
            onChange={(e) => onPatch({ label: e.target.value })}
            placeholder="Cores"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
        <DesignField label="Unit">
          <input
            value={(params.unit as string) ?? ''}
            onChange={(e) => onPatch({ unit: e.target.value })}
            placeholder="GB"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
      </div>
      <DesignField label="Theme">
        <ThemeToggle
          value={theme}
          onChange={(v) => onPatch({ theme: v })}
        />
      </DesignField>
    </>
  )
}

function UiZoomEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  const focus =
    typeof params.focus_zone === 'string'
      ? (params.focus_zone as FocalZone)
      : 'mc'
  return (
    <>
      <DesignField label="Image URL">
        <input
          value={(params.image_url as string) ?? ''}
          onChange={(e) => onPatch({ image_url: e.target.value })}
          placeholder="https://…"
          className={DESIGN_INPUT_CLASS}
        />
      </DesignField>
      <DesignField label="Label">
        <input
          value={(params.label as string) ?? ''}
          onChange={(e) => onPatch({ label: e.target.value })}
          placeholder="Optional callout"
          className={DESIGN_INPUT_CLASS}
        />
      </DesignField>
      <DesignField label="Focus zone">
        <FocalZoneGrid
          value={focus}
          onChange={(z) => onPatch({ focus_zone: z })}
        />
      </DesignField>
    </>
  )
}

function CodeWindowEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  const lines = Array.isArray(params.lines)
    ? (params.lines as unknown[]).map((l) => String(l))
    : []
  const text = lines.join('\n')
  const theme = (params.theme as string) === 'light' ? 'light' : 'dark'
  return (
    <>
      <DesignField label="Code">
        <textarea
          rows={4}
          value={text}
          onChange={(e) =>
            onPatch({
              // Keep empty trailing line meaningful so cursor newlines don't
              // disappear under the user. Split-on-\n preserves those.
              lines: e.target.value.split('\n'),
            })
          }
          placeholder={'const ship = () => true\nship()'}
          className={`${DESIGN_TEXTAREA_CLASS} font-mono`}
          spellCheck={false}
        />
      </DesignField>
      <div className="grid grid-cols-2 gap-2">
        <DesignField label="Language">
          <input
            value={(params.language as string) ?? ''}
            onChange={(e) => onPatch({ language: e.target.value })}
            placeholder="tsx"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
        <DesignField label="Theme">
          <ThemeToggle
            value={theme}
            onChange={(v) => onPatch({ theme: v })}
          />
        </DesignField>
      </div>
    </>
  )
}

function LogoRevealEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  const theme = (params.theme as string) === 'light' ? 'light' : 'dark'
  return (
    <>
      <div className="grid grid-cols-2 gap-2">
        <DesignField label="Wordmark">
          <input
            value={(params.wordmark as string) ?? ''}
            onChange={(e) => onPatch({ wordmark: e.target.value })}
            placeholder="BRAND"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
        <DesignField label="Brand name">
          <input
            value={(params.brand_name as string) ?? ''}
            onChange={(e) => onPatch({ brand_name: e.target.value })}
            placeholder="Brand Inc."
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
      </div>
      <DesignField label="Tagline">
        <input
          value={(params.tagline as string) ?? ''}
          onChange={(e) => onPatch({ tagline: e.target.value })}
          placeholder="Optional tagline"
          className={DESIGN_INPUT_CLASS}
        />
      </DesignField>
      <DesignField label="Theme">
        <ThemeToggle
          value={theme}
          onChange={(v) => onPatch({ theme: v })}
        />
      </DesignField>
    </>
  )
}

function ComparisonSplitEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  const before = (params.before as Record<string, unknown> | undefined) ?? {}
  const after = (params.after as Record<string, unknown> | undefined) ?? {}
  const orientation = (params.orientation as string) === 'h' ? 'h' : 'v'

  const patchBefore = (patch: Record<string, unknown>) =>
    onPatch({ before: { ...before, ...patch } })
  const patchAfter = (patch: Record<string, unknown>) =>
    onPatch({ after: { ...after, ...patch } })

  return (
    <>
      <div className="grid grid-cols-2 gap-2">
        <DesignField label="Before label">
          <input
            value={(before.label as string) ?? ''}
            onChange={(e) => patchBefore({ label: e.target.value })}
            placeholder="Before"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
        <DesignField label="After label">
          <input
            value={(after.label as string) ?? ''}
            onChange={(e) => patchAfter({ label: e.target.value })}
            placeholder="After"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <DesignField label="Before image URL">
          <input
            value={(before.image_url as string) ?? ''}
            onChange={(e) => patchBefore({ image_url: e.target.value })}
            placeholder="https://…"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
        <DesignField label="After image URL">
          <input
            value={(after.image_url as string) ?? ''}
            onChange={(e) => patchAfter({ image_url: e.target.value })}
            placeholder="https://…"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
      </div>
      <DesignField label="Orientation">
        <div className="inline-flex items-center gap-1 rounded-full border border-line bg-bg-card p-0.5">
          {(['v', 'h'] as const).map((o) => {
            const active = orientation === o
            return (
              <button
                key={o}
                type="button"
                onClick={() => onPatch({ orientation: o })}
                className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] transition ${
                  active
                    ? 'bg-accent-deep text-white'
                    : 'text-fg-mute hover:text-fg'
                }`}
                aria-pressed={active}
              >
                {o === 'v' ? 'vertical' : 'horizontal'}
              </button>
            )
          })}
        </div>
      </DesignField>
    </>
  )
}

function CanvasKineticEditor({
  params,
  onPatch,
}: {
  params: Record<string, unknown>
  onPatch: (patch: Record<string, unknown>) => void
}) {
  const motion = (params.motion as string) || 'punch'
  const motionOptions: Array<'punch' | 'scroll' | 'word_kinetic'> = [
    'punch',
    'scroll',
    'word_kinetic',
  ]
  return (
    <>
      <DesignField label="Canvas prompt">
        <textarea
          rows={3}
          value={(params.canvas_prompt as string) ?? ''}
          onChange={(e) => onPatch({ canvas_prompt: e.target.value })}
          placeholder="An exploded isometric view of a silicon chip floating in deep cobalt space, fractal circuit traces radiating outward, aurora glow"
          className={DESIGN_TEXTAREA_CLASS}
        />
      </DesignField>
      <div className="grid grid-cols-2 gap-2">
        <DesignField label="Headline">
          <input
            value={(params.headline as string) ?? ''}
            onChange={(e) => onPatch({ headline: e.target.value })}
            placeholder="3-5 words"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
        <DesignField label="Subtitle">
          <input
            value={(params.subtitle as string) ?? ''}
            onChange={(e) => onPatch({ subtitle: e.target.value })}
            placeholder="Optional"
            className={DESIGN_INPUT_CLASS}
          />
        </DesignField>
      </div>
      <DesignField label="Motion">
        <div className="inline-flex items-center gap-1 rounded-full border border-line bg-bg-card p-0.5">
          {motionOptions.map((m) => {
            const active = motion === m
            return (
              <button
                key={m}
                type="button"
                onClick={() => onPatch({ motion: m })}
                className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] transition ${
                  active
                    ? 'bg-accent-deep text-white'
                    : 'text-fg-mute hover:text-fg'
                }`}
                aria-pressed={active}
              >
                {m === 'word_kinetic' ? 'words' : m}
              </button>
            )
          })}
        </div>
      </DesignField>
    </>
  )
}

function CanvasKineticPreview({
  params,
}: {
  params: Record<string, unknown>
}) {
  const headline = (params.headline as string) || 'Headline'
  const canvasUrl = (params.canvas_url as string) || ''
  // Mini preview: when canvas exists, render the bg image with the headline
  // overlaid (drop shadow for legibility against any backdrop). When the
  // canvas hasn't been generated yet (the suggest-time state), fall back to
  // a brand-toned gradient so the editor still has a visible thumbnail.
  return (
    <div className="relative aspect-video w-full overflow-hidden border-b border-line-soft">
      {canvasUrl ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={canvasUrl}
          alt=""
          className="absolute inset-0 h-full w-full object-cover"
        />
      ) : (
        <div
          className="absolute inset-0"
          style={{
            background:
              'linear-gradient(135deg, var(--color-accent) 0%, var(--color-accent-deep) 60%, #1a1735 100%)',
          }}
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-black/55 via-black/15 to-transparent" />
      <div className="absolute inset-0 grid place-items-center px-3 text-center">
        <div
          className="font-serif text-base leading-tight text-white"
          style={{
            textShadow: '0 2px 10px rgba(0,0,0,0.65)',
            maxWidth: '90%',
          }}
        >
          {headline}
        </div>
      </div>
      <div className="absolute left-2 top-2 rounded-full border border-white/30 bg-black/35 px-2 py-0.5 text-[9px] font-semibold uppercase tracking-[0.18em] text-white/85 backdrop-blur-sm">
        canvas {canvasUrl ? '· ready' : '· pending'}
      </div>
    </div>
  )
}

function effectGlyph(kind: EffectKind): string {
  switch (kind) {
    case 'kinetic_text':
      return '✶'
    case 'lower_third':
      return '▭'
    case 'brand_stinger':
      return '⚡'
    case 'spotlight':
      return '◉'
    case 'kinetic_lines':
      return '〰'
    case 'data_pop':
      return '#'
  }
}

function effectLabel(kind: EffectKind): string {
  switch (kind) {
    case 'kinetic_text':
      return 'kinetic text'
    case 'lower_third':
      return 'lower-third'
    case 'brand_stinger':
      return 'stinger'
    case 'spotlight':
      return 'spotlight'
    case 'kinetic_lines':
      return 'lines'
    case 'data_pop':
      return 'data pop'
  }
}

function effectSummary(effect: Effect): string {
  const p = effect.params ?? {}
  switch (effect.kind) {
    case 'kinetic_text':
      return p.text ? `“${p.text}”` : effectLabel(effect.kind)
    case 'lower_third':
      return p.title ?? effectLabel(effect.kind)
    case 'brand_stinger':
      return p.text ? `flash · ${p.text}` : 'brand flash'
    case 'spotlight':
      return `spotlight · ${p.zone ?? 'mc'}`
    case 'kinetic_lines':
      return `lines · ${p.pattern ?? 'diagonal'}`
    case 'data_pop':
      return p.value ? `${p.value}` : effectLabel(effect.kind)
  }
}

function EffectsRow({ effects }: { effects: Effect[] | undefined }) {
  if (!effects || effects.length === 0) {
    return (
      <div className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
        — no effects
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[9px] font-medium uppercase tracking-[0.18em] text-fg-dim">
        FX
      </span>
      {effects.map((e) => (
        <span
          key={e.id}
          title={`${effectLabel(e.kind)} · rendered by Remotion`}
          className="inline-flex items-center gap-1 rounded-full border border-accent/30 bg-accent-soft/30 px-2 py-0.5 text-[10px] text-accent"
        >
          <span>{effectGlyph(e.kind)}</span>
          <span className="max-w-[10rem] truncate">{effectSummary(e)}</span>
        </span>
      ))}
    </div>
  )
}

function CastRefsRow({ members }: { members: CastSlot[] }) {
  if (members.length === 0) {
    return (
      <div className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
        — no cast
      </div>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {members.map((m) => (
        <span
          key={m.id}
          title={`${castKindLabel(m.kind)} · ${m.description}`}
          className="inline-flex items-center gap-1 rounded-full border border-line bg-bg-soft/60 px-2 py-0.5 text-[10px] text-fg-mute"
        >
          <span>{castGlyph(m.kind)}</span>
          <span className="max-w-[8rem] truncate">{m.role}</span>
        </span>
      ))}
    </div>
  )
}

function FrameStatusDot({ frame }: { frame: Frame }) {
  if (frame.status === 'generating') {
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-accent">
        ◐ working
      </span>
    )
  }
  if (frame.stale) {
    return (
      <span
        className="text-[10px] uppercase tracking-[0.18em] text-warn"
        title="ingredient changed since last generation"
      >
        ⚠ stale
      </span>
    )
  }
  if (frame.status === 'ready') {
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-success">
        ● still
      </span>
    )
  }
  if (frame.status === 'failed') {
    return (
      <span
        className="text-[10px] uppercase tracking-[0.18em] text-danger"
        title={frame.error ?? 'failed'}
      >
        ✕ failed
      </span>
    )
  }
  return (
    <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
      ○ idle
    </span>
  )
}

function ClipStatusDot({ frame }: { frame: Frame }) {
  if (frame.clip_status === 'generating') {
    if (frame.clip_retry) {
      const { phase, attempt, max_attempts, reason } = frame.clip_retry
      return (
        <span
          className="text-[10px] uppercase tracking-[0.18em] text-warn"
          title={`Veo ${phase} 5xx: ${reason}`}
        >
          ↻ retrying {attempt}/{max_attempts}
        </span>
      )
    }
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-accent">
        ◐ rendering clip
      </span>
    )
  }
  if (frame.clip_status === 'ready') {
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-success">
        ● clip
      </span>
    )
  }
  if (frame.clip_status === 'failed') {
    return (
      <span
        className="text-[10px] uppercase tracking-[0.18em] text-danger"
        title={frame.clip_error ?? 'failed'}
      >
        ✕ clip failed
      </span>
    )
  }
  return (
    <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
      ○ no clip
    </span>
  )
}

function BookendsBanner({
  titleCard,
  endCard,
}: {
  titleCard: StoryboardTitleCard | null
  endCard: StoryboardEndCard | null
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-line-soft bg-bg-card px-4 py-3"
    >
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Title + End card
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
          · rendered by Remotion
        </span>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
        {titleCard?.text && (
          <div className="rounded-lg border border-line/60 bg-bg-soft/40 px-3 py-2">
            <div className="text-[9px] font-medium uppercase tracking-[0.18em] text-fg-dim">
              ▶ Opens with
            </div>
            <div className="mt-1 font-serif text-sm leading-snug text-fg">
              {titleCard.text}
            </div>
          </div>
        )}
        {(endCard?.headline || endCard?.cta) && (
          <div className="rounded-lg border border-line/60 bg-bg-soft/40 px-3 py-2">
            <div className="text-[9px] font-medium uppercase tracking-[0.18em] text-fg-dim">
              ◼ Ends with
            </div>
            <div className="mt-1 font-serif text-sm leading-snug text-fg">
              {endCard?.headline}
            </div>
            {endCard?.cta && (
              <div className="mt-0.5 text-[10px] font-medium uppercase tracking-[0.22em] text-accent">
                → {endCard.cta}
              </div>
            )}
          </div>
        )}
      </div>
    </motion.div>
  )
}

function TargetingBanner({ segment }: { segment: SegmentTarget }) {
  // The "Targeted for: …" pill that explains why this storyboard looks
  // different from the brand's generic spot. Surfaces feature_focus +
  // segment size so the user can confirm the planner saw the right
  // signals at /suggest time.
  const feature = segment.feature_focus
  // Re-rank features by distinct customer count (then by event count)
  // so the chip strip below names the truly-dominant features first.
  const ranked = Object.keys(segment.feature_stats || {})
    .map((f) => ({
      feature: f,
      events: (segment.feature_stats || {})[f] ?? 0,
      contributors: (segment.contributor_counts || {})[f] ?? 0,
    }))
    .sort((a, b) => b.contributors - a.contributors || b.events - a.events)
    .slice(0, 5)
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-accent/40 bg-accent-soft/40 px-4 py-3"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">
          Targeted for
        </span>
        <span className="text-[12px] font-semibold text-fg">
          {segment.name || 'segment'}
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
          · {segment.size} customer{segment.size === 1 ? '' : 's'}
        </span>
        {feature && (
          <span
            className="ml-1 rounded-full bg-accent px-2 py-0.5 text-[10px] font-semibold text-white"
            title="Visual hero of this video — threaded through frames + voiceover"
          >
            ✨ {feature}
          </span>
        )}
      </div>
      {segment.description && (
        <p className="mt-1.5 line-clamp-2 text-[11.5px] leading-snug text-fg-mute">
          {segment.description}
        </p>
      )}
      {ranked.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {ranked.map((r) => (
            <span
              key={r.feature}
              className={`rounded-full px-2 py-0.5 text-[10px] ${
                r.feature === feature
                  ? 'bg-accent text-white'
                  : 'bg-bg-card text-fg-mute hairline'
              }`}
              title={`${r.contributors} customer(s), ${r.events} events`}
            >
              {r.feature}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  )
}

function SegmentPicker({
  segments,
  selectedId,
  onSelect,
}: {
  segments: AudienceSegment[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}) {
  // Inline picker that sits above ControlBar. Empty when no segments
  // exist (so we don't clutter the panel for users who haven't built
  // an audience yet). Shows feature_focus inline on each option so the
  // user picks intent, not just name.
  if (!segments || segments.length === 0) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-line-soft bg-bg-card px-3 py-2">
      <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Audience
      </span>
      <select
        value={selectedId ?? ''}
        onChange={(e) => onSelect(e.target.value || null)}
        className="rounded-md border border-line bg-bg-card px-2 py-1 text-[12px] text-fg outline-none transition focus:border-accent"
      >
        <option value="">— Generic (no targeting)</option>
        {segments.map((s) => {
          const tag = s.feature_focus
            ? ` · ✨ ${s.feature_focus}`
            : ''
          return (
            <option key={s.id} value={s.id}>
              {s.name} ({s.size}){tag}
            </option>
          )
        })}
      </select>
      <span className="text-[10.5px] text-fg-dim">
        {selectedId
          ? 'Next "Suggest" will tailor the spot to this segment'
          : 'Pick a segment to dynamically target the ad spot'}
      </span>
    </div>
  )
}

function DirectorBriefBanner({ brief }: { brief: CinematicBrief }) {
  const rows: { label: string; value: string }[] = [
    { label: 'Refs', value: brief.reference_films },
    { label: 'Lens', value: brief.lensing },
    { label: 'Light', value: brief.lighting },
    { label: 'Grade', value: brief.palette_grade },
    { label: 'Pace', value: brief.pacing },
  ].filter((r) => r.value.trim().length > 0)

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-line-soft bg-bg-card px-4 py-3"
    >
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Director's brief
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
          · threaded into every shot
        </span>
      </div>
      <div className="mt-2 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
        {rows.map((r) => (
          <div key={r.label} className="flex gap-2">
            <span className="shrink-0 pt-px text-[9px] font-semibold uppercase tracking-[0.18em] text-fg-dim">
              {r.label}
            </span>
            <span className="text-[11px] leading-relaxed text-fg-mute">
              {r.value}
            </span>
          </div>
        ))}
      </div>
    </motion.div>
  )
}

function NarrativeBanner({ narrative }: { narrative: StoryboardNarrative }) {
  const tone = narrative.tone?.trim()
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-line-soft bg-bg-soft/40 px-4 py-2.5"
    >
      <div className="flex items-center gap-2">
        <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          Narrative
        </span>
        {tone && (
          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
            · {tone}
          </span>
        )}
      </div>
      <p className="mt-1 text-[12px] italic leading-relaxed text-fg-mute">
        <span>{narrative.premise}</span>
        {narrative.arc && (
          <>
            <span className="mx-1.5 text-fg-dim">—</span>
            <span>{narrative.arc}</span>
          </>
        )}
      </p>
    </motion.div>
  )
}

function MediaPreview({
  frame,
  aspect,
}: {
  frame: Frame
  aspect: VideoAspect
}) {
  const aspectStyle = { aspectRatio: aspectCss(aspect) }
  const [editMode, setEditMode] = useState<'inpaint' | 'sketch' | null>(null)
  const storyboardId = useStoryboardStore((s) => s.storyboardId)
  const updateFrame = useStoryboardStore((s) => s.updateFrame)
  const editAspect: EditAspect = aspect
  const applyResult = (newUrl: string) => {
    // Replace the still in place. The Veo clip (if any) is left alone — the
    // user can re-render the scene from the new still afterwards.
    updateFrame(frame.id, {
      image_url: newUrl,
      status: 'ready',
      error: null,
      stale: true, // clip-derived state is stale; UI nudges a re-render
    })
  }

  // Clip-rendering shimmer ONLY when no clip_url is set. If a clip URL has
  // already arrived (the SSE event or local fetch resolved), show the video
  // even if clip_status is somehow still 'generating' — otherwise a stale
  // generating flag (from an out-of-order event or a re-render) hides a
  // perfectly good clip behind the shimmer. clip_url presence is the truth.
  if (frame.clip_status === 'generating' && !frame.clip_url) {
    const retryLabel = frame.clip_retry
      ? `retrying ${frame.clip_retry.attempt}/${frame.clip_retry.max_attempts} (${frame.clip_retry.phase})`
      : 'rendering clip…'
    return (
      <div
        className="relative w-full overflow-hidden bg-bg-soft"
        style={aspectStyle}
      >
        {frame.image_url && (
          <img
            src={frame.image_url}
            alt=""
            className="absolute inset-0 block h-full w-full object-cover opacity-30"
          />
        )}
        <motion.div
          initial={{ x: '-100%' }}
          animate={{ x: '100%' }}
          transition={{
            duration: 1.4,
            repeat: Infinity,
            ease: 'linear',
          }}
          className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-accent-soft/70 to-transparent"
        />
        <div
          className="absolute inset-0 grid place-items-center text-[10px] uppercase tracking-[0.22em] text-accent"
          title={frame.clip_retry?.reason ?? undefined}
        >
          {retryLabel}
        </div>
      </div>
    )
  }

  // Still generation shimmer.
  if (frame.status === 'generating') {
    return (
      <div
        className="relative w-full overflow-hidden bg-bg-soft"
        style={aspectStyle}
      >
        <motion.div
          initial={{ x: '-100%' }}
          animate={{ x: '100%' }}
          transition={{
            duration: 1.4,
            repeat: Infinity,
            ease: 'linear',
          }}
          className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-accent-soft/70 to-transparent"
        />
        <div className="absolute inset-0 grid place-items-center text-[10px] uppercase tracking-[0.22em] text-accent">
          generating…
        </div>
      </div>
    )
  }

  // Prefer Veo clip when set. Note: this branch runs even if clip_status is
  // still 'generating' (the local fetch resolves before SSE; or a stale
  // re-emission of GENERATING arrived after the URL). The presence of
  // clip_url is what matters for display — the in-flight badge below shows
  // any active retry/poll noise without hiding the working video.
  if (frame.clip_url) {
    const showInflightBadge = frame.clip_status === 'generating'
    return (
      <div
        className="relative w-full overflow-hidden bg-bg-soft"
        style={aspectStyle}
      >
        <video
          key={frame.clip_url}
          src={frame.clip_url}
          autoPlay
          loop
          muted
          playsInline
          controls={false}
          onError={(e) => {
            // Surface the failure instead of leaving the user staring at a
            // black box. Browsers swallow video load errors silently by
            // default; logging makes them debuggable from the JS console.
            console.warn('video load failed', frame.clip_url, e)
            updateFrame(frame.id, {
              clip_status: 'failed',
              clip_error: 'video element failed to load clip',
            })
          }}
          className="absolute inset-0 block h-full w-full object-cover"
        />
        {showInflightBadge && (
          <div className="pointer-events-none absolute left-2 top-2 rounded-full bg-accent/95 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-bg-card shadow-sm">
            {frame.clip_retry
              ? `retrying ${frame.clip_retry.attempt}/${frame.clip_retry.max_attempts}`
              : 'rendering clip'}
          </div>
        )}
        {frame.stale && !showInflightBadge && (
          <div className="pointer-events-none absolute left-2 top-2 rounded-full bg-warn/95 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-bg-card shadow-sm">
            stale — regenerate
          </div>
        )}
        {frame.caption && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-fg/85 via-fg/40 to-transparent p-3">
            <div className="line-clamp-2 text-xs leading-snug text-bg-card">
              {frame.caption}
            </div>
          </div>
        )}
      </div>
    )
  }

  // Fall back to still image.
  if (frame.image_url) {
    return (
      <div
        className="group relative w-full overflow-hidden bg-bg-soft"
        style={aspectStyle}
      >
        <motion.img
          key={frame.image_url}
          src={frame.image_url}
          alt={frame.caption || 'frame preview'}
          initial={{ opacity: 0, scale: 1.04 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="absolute inset-0 block h-full w-full object-cover"
        />
        {frame.stale && frame.clip_status !== 'failed' && (
          <div className="pointer-events-none absolute left-2 top-2 rounded-full bg-warn/95 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-bg-card shadow-sm">
            stale — regenerate
          </div>
        )}
        {frame.clip_status === 'failed' && (
          <div
            className="pointer-events-none absolute left-2 top-2 rounded-full bg-danger/95 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-bg-card shadow-sm"
            title={frame.clip_error ?? 'clip generation failed'}
          >
            ✕ clip failed — re-animate
          </div>
        )}
        <EditOverlayButtons
          onInpaint={() => setEditMode('inpaint')}
          onSketch={() => setEditMode('sketch')}
          inpaintEnabled={!!frame.image_url}
        />
        {frame.caption && (
          <div className="pointer-events-none absolute inset-x-0 bottom-0 bg-gradient-to-t from-fg/85 via-fg/40 to-transparent p-3">
            <div className="line-clamp-2 text-xs leading-snug text-bg-card">
              {frame.caption}
            </div>
          </div>
        )}
        {editMode === 'inpaint' && frame.image_url && (
          <ImageEditModal
            mode="inpaint"
            open
            sourceUrl={frame.image_url}
            aspect={editAspect}
            scope="frame"
            scopeId={storyboardId}
            onClose={() => setEditMode(null)}
            onResult={applyResult}
          />
        )}
        {editMode === 'sketch' && (
          <ImageEditModal
            mode="sketch"
            open
            aspect={editAspect}
            scope="frame"
            scopeId={storyboardId}
            onClose={() => setEditMode(null)}
            onResult={applyResult}
          />
        )}
      </div>
    )
  }

  if (frame.status === 'failed' || frame.clip_status === 'failed') {
    const message =
      frame.clip_error ?? frame.error ?? 'failed'
    return (
      <div
        className="relative grid w-full place-items-center border-b border-dashed border-danger/40 bg-bg-card"
        style={aspectStyle}
        title={message}
      >
        <div className="text-center">
          <div className="text-2xl text-danger">✕</div>
          <div className="mt-1 max-w-[80%] truncate px-3 text-[10px] uppercase tracking-[0.18em] text-danger">
            {message.slice(0, 60)}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      className="grid w-full place-items-center border-b border-dashed border-line bg-bg-soft/40"
      style={aspectStyle}
    >
      <div className="text-center text-fg-dim">
        <div className="text-3xl">✦</div>
        <div className="mt-1 text-[10px] uppercase tracking-[0.18em]">
          edit prompt → generate
        </div>
      </div>
    </div>
  )
}

function RenderingRibbon() {
  return (
    <div className="relative overflow-hidden rounded-xl border border-accent/30 bg-accent-soft/40 px-4 py-3">
      <motion.div
        initial={{ x: '-100%' }}
        animate={{ x: '100%' }}
        transition={{ duration: 1.6, repeat: Infinity, ease: 'linear' }}
        className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-transparent via-white/50 to-transparent"
      />
      <div className="relative flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
        <span className="animate-pulse">◐</span>
        Rendering with Remotion…
      </div>
    </div>
  )
}

function ErrorBanner({
  error,
  onRetry,
}: {
  error: string
  onRetry: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-danger/30 bg-bg-card px-4 py-3">
      <div className="flex items-center gap-2 text-xs text-danger">
        <span>✕</span>
        <span className="font-medium">Render failed:</span>
        <span className="text-fg-mute">{error}</span>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-full border border-danger/40 px-3 py-1 text-[11px] font-medium text-danger hover:bg-danger hover:text-white"
      >
        Retry
      </button>
    </div>
  )
}

function VoiceoverPanel({
  voiceover,
  status,
  error,
  voicedReady,
  onUpdate,
  onGenerate,
}: {
  voiceover: VoiceoverSpec | null
  status: VoiceoverStatus
  error: string | null
  voicedReady: boolean
  onUpdate: (patch: Partial<VoiceoverSpec>) => void
  onGenerate: () => void
}) {
  const isGenerating = status === 'generating'
  const script = voiceover?.script ?? ''
  const wordCount = script.trim().length === 0 ? 0 : script.trim().split(/\s+/).length
  const personaPlaceholder =
    'warm and confident, low register, patient pacing, slight smile in the voice'
  const buttonLabel = isGenerating
    ? 'Generating voiceover…'
    : voicedReady
      ? 'Re-generate voiceover'
      : 'Generate voiceover'
  const buttonTitle = !script.trim()
    ? 'Write a script first — Gemini TTS reads it onto the rendered clip'
    : 'Send to Gemini TTS, then mux onto the video with ffmpeg'
  const buttonDisabled = isGenerating || script.trim().length === 0

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-2xl border border-line bg-bg-card p-4"
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Voiceover
          </span>
          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
            · Gemini TTS, muxed onto the video
          </span>
        </div>
        <VoiceoverStatusDot status={status} voicedReady={voicedReady} />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-[1fr_220px]">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Script
          </span>
          <textarea
            rows={3}
            value={script}
            onChange={(e) => onUpdate({ script: e.target.value })}
            placeholder="The narration the voice will read…"
            className="resize-none rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs leading-relaxed text-fg outline-none transition focus:border-accent"
          />
          <span className="text-right text-[10px] tabular-nums text-fg-dim">
            {wordCount} {wordCount === 1 ? 'word' : 'words'} · target ~30-45 for
            ≤15s
          </span>
        </label>

        <div className="flex flex-col gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
              Voice
            </span>
            <select
              value={voiceover?.voice_name ?? 'Charon'}
              onChange={(e) =>
                onUpdate({ voice_name: e.target.value as VoiceName })
              }
              className="rounded-md border border-line bg-bg-card px-2 py-1.5 text-xs text-fg outline-none transition focus:border-accent"
            >
              {VOICE_NAMES.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
              Persona
            </span>
            <input
              value={voiceover?.voice_persona ?? ''}
              onChange={(e) => onUpdate({ voice_persona: e.target.value })}
              placeholder={personaPlaceholder}
              className="rounded-md border border-line bg-bg-card px-2.5 py-1.5 text-xs text-fg outline-none transition focus:border-accent"
            />
          </label>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between gap-3">
        <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
          {voicedReady
            ? 'voiced mp4 swapped into preview above'
            : 'silent video plays above until generated'}
        </span>
        <button
          type="button"
          onClick={onGenerate}
          disabled={buttonDisabled}
          title={buttonTitle}
          className="rounded-full bg-accent px-4 py-1.5 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          {buttonLabel}
        </button>
      </div>

      {status === 'failed' && error && (
        <div className="mt-2 rounded-md border border-danger/30 bg-bg-card px-3 py-2 text-[11px] text-danger">
          {error}
        </div>
      )}
    </motion.div>
  )
}

function VoiceoverStatusDot({
  status,
  voicedReady,
}: {
  status: VoiceoverStatus
  voicedReady: boolean
}) {
  if (status === 'generating') {
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-accent">
        ◐ rendering audio
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-danger">
        ✕ failed
      </span>
    )
  }
  if (voicedReady || status === 'ready') {
    return (
      <span className="text-[10px] uppercase tracking-[0.18em] text-success">
        ● voiced
      </span>
    )
  }
  return (
    <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
      ○ idle
    </span>
  )
}

function VideoPreview({
  url,
  silentUrl,
  aspect,
  durationMs,
  voiced,
}: {
  url: string
  silentUrl: string | null
  aspect: VideoAspect
  durationMs: number | null
  voiced: boolean
}) {
  const [toast, setToast] = useState<string | null>(null)
  function flash(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 1600)
  }

  async function copyUrl() {
    try {
      await navigator.clipboard.writeText(url)
      flash('url copied')
    } catch {
      flash('clipboard blocked')
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="relative flex flex-col gap-3 rounded-2xl border border-accent/30 bg-bg-card p-4"
    >
      <div className="flex items-baseline justify-between">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-success" />
          <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-success">
            {voiced ? 'Voiced video ready' : 'Video ready'}
          </span>
          {voiced && (
            <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
              · TTS narration muxed
            </span>
          )}
          {silentUrl && (
            <a
              href={silentUrl}
              target="_blank"
              rel="noreferrer"
              className="text-[10px] uppercase tracking-[0.18em] text-fg-dim underline-offset-2 hover:text-accent hover:underline"
            >
              silent original
            </a>
          )}
        </div>
        {durationMs && (
          <span className="text-xs tabular-nums text-fg-dim">
            {(durationMs / 1000).toFixed(1)}s
          </span>
        )}
      </div>

      <div
        className="mx-auto w-full max-w-md overflow-hidden rounded-xl bg-fg/95"
        style={{ aspectRatio: aspectCss(aspect) }}
      >
        <video
          controls
          src={url}
          className="block h-full w-full object-contain"
        />
      </div>

      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={copyUrl}
          className="rounded-full border border-line bg-bg-card px-4 py-1.5 text-xs text-fg-mute hover:border-accent hover:text-accent"
        >
          Copy URL
        </button>
        <a
          href={url}
          download
          className="rounded-full bg-accent px-4 py-1.5 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] hover:brightness-110"
        >
          Download MP4
        </a>
      </div>

      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="pointer-events-none absolute right-4 top-3 rounded-md bg-fg/90 px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-bg-card"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

// ── Improvement loop UI ────────────────────────────────────────────────────
// Critique modal: shows weaknesses (LEFT) + mutations as approve/reject
// checkboxes (RIGHT). Default-checked = high severity, half-checked for
// medium, none for low. Surfaces total estimated time at the bottom.

function VersionStrip({
  versions,
  currentVersion,
  onLoad,
}: {
  versions: StoryboardVersion[]
  currentVersion: number
  onLoad: (versionNumber: number) => void
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex items-center gap-2 rounded-2xl border border-line bg-bg-card px-3 py-2"
    >
      <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        Versions
      </span>
      <div className="flex flex-wrap gap-1.5">
        {versions.map((v) => {
          const active = v.version_number === currentVersion
          return (
            <button
              key={v.version_number}
              type="button"
              onClick={() => onLoad(v.version_number)}
              title={
                v.summary
                  ? `v${v.version_number} — ${v.summary.slice(0, 140)}`
                  : `Load v${v.version_number} into editor`
              }
              className={`rounded-full px-3 py-1 text-[11px] font-medium transition ${
                active
                  ? 'bg-accent text-white shadow-[0_2px_8px_rgba(111,92,255,0.3)]'
                  : 'border border-line text-fg-mute hover:border-accent hover:text-accent'
              }`}
            >
              v{v.version_number}
              {v.mutation_count > 0 && (
                <span className="ml-1 text-[10px] opacity-70">
                  ·{v.mutation_count}
                </span>
              )}
            </button>
          )
        })}
      </div>
    </motion.div>
  )
}

function ImprovingBanner() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="flex items-center justify-between gap-3 rounded-2xl border border-accent/30 bg-bg-card px-4 py-2.5"
    >
      <div className="flex items-center gap-2">
        <motion.span
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1.4, repeat: Infinity }}
          className="h-2 w-2 rounded-full bg-accent"
        />
        <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
          Generating next version…
        </span>
        <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
          re-firing approved scenes + re-rendering
        </span>
      </div>
    </motion.div>
  )
}

function severityBadgeClass(s: CritiqueWeakness['severity']): string {
  if (s === 'high') return 'bg-danger/15 text-danger border-danger/40'
  if (s === 'medium') return 'bg-amber-500/15 text-amber-600 border-amber-500/40'
  return 'bg-line text-fg-dim border-line'
}

function costBadgeLabel(cost: MutationCost, est: number): string {
  if (cost === 'free') return 'free'
  if (cost === 'render') return `${est}s render`
  return `${est}s veo`
}

function costBadgeClass(cost: MutationCost): string {
  if (cost === 'free') return 'bg-success/10 text-success border-success/30'
  if (cost === 'render') return 'bg-accent/10 text-accent border-accent/30'
  return 'bg-amber-500/10 text-amber-600 border-amber-500/30'
}

// Source chip for the dual-pass critic. "macro" = thumbnail pass (caption
// / composition / pacing). "effects" = full-video motion-graphics pass
// (kinetic_text / spotlight / lower_third / etc). Optional — pre-aggregator
// plans don't carry the tag, in which case we render no chip.
type CritiqueSourceTag = NonNullable<CritiqueWeakness['source']>
function sourceBadgeClass(source: CritiqueSourceTag): string {
  if (source === 'effects')
    return 'bg-purple-500/10 text-purple-600 border-purple-500/30'
  return 'bg-sky-500/10 text-sky-600 border-sky-500/30'
}

type CritiqueSourceFilter = 'all' | CritiqueSourceTag

function CritiqueModal({
  plan,
  open,
  onDismiss,
  onApply,
  applying,
}: {
  plan: CritiquePlan | null
  open: boolean
  onDismiss: () => void
  onApply: (approvedMutationIds: string[]) => void
  applying: boolean
}) {
  // Default selection rule (driven by severity of the weaknesses each
  // mutation addresses): all high-severity → checked (whether macro or
  // effects); medium-severity macro → every-other; low → unchecked.
  // Effects mutations are mostly free, so a footer "select all effects"
  // button makes one-click adoption easy without forcing them on by default.
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  // Source filter pill — All / Macro / Effects. Filters which mutations
  // the right-hand list renders; the underlying selection map is unchanged
  // so toggling the filter doesn't lose user picks.
  const [sourceFilter, setSourceFilter] = useState<CritiqueSourceFilter>('all')

  // When a new plan arrives, reset the selection + filter to defaults.
  useEffect(() => {
    if (!plan) {
      setSelected({})
      setSourceFilter('all')
      return
    }
    const sevByWeaknessId: Record<string, CritiqueWeakness['severity']> = {}
    for (const w of plan.weaknesses) {
      sevByWeaknessId[w.id] = w.severity
    }
    const next: Record<string, boolean> = {}
    let mediumIdx = 0
    for (const m of plan.mutations) {
      const severities = (m.weakness_ids || []).map(
        (wid) => sevByWeaknessId[wid] ?? 'medium',
      )
      const isHigh = severities.some((s) => s === 'high')
      const isMedium = !isHigh && severities.some((s) => s === 'medium')
      if (isHigh) {
        next[m.id] = true
      } else if (isMedium) {
        next[m.id] = mediumIdx % 2 === 0
        mediumIdx++
      } else {
        next[m.id] = false
      }
    }
    setSelected(next)
    setSourceFilter('all')
  }, [plan])

  if (!open || !plan) return null
  // Capture the non-null reference for closures (toggleAll). TS can't
  // narrow `plan` across nested function boundaries.
  const planRef: CritiquePlan = plan

  const approvedIds = Object.entries(selected)
    .filter(([, v]) => v)
    .map(([k]) => k)

  // Total estimated time. The /improve endpoint runs in two phases that
  // happen sequentially (scene refires → bridge gens → final render):
  //   Phase 1: scene refires fan out in parallel with a 1s stagger
  //            (frame.X.prompt/motion + frames.add live_action +
  //            frame.X.kind → live_action mutations).
  //   Phase 2: Veo motion bridges fan out in parallel with a 1s stagger
  //            (transition.X_Y.style → veo_bridge mutations).
  //   Phase 3: a single ~30s Remotion re-render.
  // Total = max(phase1) + max(phase2) + 30s.
  const selectedMutations = planRef.mutations.filter((m) => selected[m.id])
  const veoMutations = selectedMutations.filter((m) => m.cost === 'veo')
  // Split veo mutations into refires vs bridges so the parallel-stage
  // accounting is honest. Bridges are signaled by transition.*.style
  // targets where `to === 'veo_bridge'`.
  const isBridgeMutation = (m: CritiqueMutation): boolean => {
    const t = (m.target || '').trim()
    if (!t.startsWith('transition.') || !t.endsWith('.style')) return false
    return typeof m.to === 'string' && m.to === 'veo_bridge'
  }
  const refireMutations = veoMutations.filter((m) => !isBridgeMutation(m))
  const bridgeMutations = veoMutations.filter(isBridgeMutation)

  const refireSlowest = refireMutations.reduce(
    (max, m) => Math.max(max, m.estimated_seconds),
    0,
  )
  const bridgeSlowest = bridgeMutations.reduce(
    (max, m) => Math.max(max, m.estimated_seconds),
    0,
  )
  // 1s per submit beyond the first in each phase — same as the backend
  // _SCENE_REFIRE_STAGGER_S / _BRIDGE_GEN_STAGGER_S.
  const refireStagger = Math.max(0, refireMutations.length - 1)
  const bridgeStagger = Math.max(0, bridgeMutations.length - 1)
  // Re-render of Remotion always happens once at the end, ~30s.
  const finalRender = 30
  const totalSeconds =
    refireSlowest +
    refireStagger +
    bridgeSlowest +
    bridgeStagger +
    finalRender

  // Group weaknesses by severity for visual ordering.
  const sevOrder: Record<CritiqueWeakness['severity'], number> = {
    high: 0,
    medium: 1,
    low: 2,
  }
  const sortedWeaknesses = [...planRef.weaknesses].sort(
    (a, b) => sevOrder[a.severity] - sevOrder[b.severity],
  )

  function toggleAll(value: boolean) {
    const next: Record<string, boolean> = {}
    for (const m of planRef.mutations) next[m.id] = value
    setSelected(next)
  }

  // One-click adoption for the entire effects pass. Effects mutations are
  // cost="free" — no Veo refire — so a "yes to all" button is meaningfully
  // different from the macro pass and worth its own affordance.
  function selectAllEffects() {
    setSelected((prev) => {
      const next = { ...prev }
      for (const m of planRef.mutations) {
        if (m.source === 'effects') next[m.id] = true
      }
      return next
    })
  }

  // Apply the current source filter to the mutations list (left-hand
  // weaknesses keep their full visibility — the filter is a focus aid for
  // the action panel, not a hide).
  const filteredMutations = planRef.mutations.filter((m) => {
    if (sourceFilter === 'all') return true
    return m.source === sourceFilter
  })

  const macroMutationCount = planRef.mutations.filter(
    (m) => m.source === 'macro',
  ).length
  const effectsMutationCount = planRef.mutations.filter(
    (m) => m.source === 'effects',
  ).length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-fg/40 p-4 backdrop-blur-sm">
      <motion.div
        initial={{ opacity: 0, scale: 0.96, y: 8 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 8 }}
        transition={{ duration: 0.2 }}
        className="flex max-h-[88vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-line bg-bg shadow-[0_20px_60px_rgba(20,20,40,0.18)]"
      >
        <header className="flex items-start justify-between gap-3 border-b border-line-soft bg-bg-card px-6 py-4">
          <div className="flex flex-col gap-1.5">
            <div className="flex items-center gap-2">
              <span className="grid h-5 min-w-5 place-items-center rounded-md bg-accent px-1.5 text-[11px] font-semibold text-white">
                ⚖
              </span>
              <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                AI critique
              </span>
              {plan.error && (
                <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] text-amber-600">
                  degraded
                </span>
              )}
            </div>
            <p className="max-w-3xl text-sm leading-relaxed text-fg">
              {plan.summary || 'No summary returned.'}
            </p>
            {plan.error && (
              <span className="text-[10px] uppercase tracking-[0.18em] text-amber-600">
                {plan.error}
              </span>
            )}
          </div>
          <button
            type="button"
            onClick={onDismiss}
            disabled={applying}
            className="rounded-full border border-line bg-bg-card px-3 py-1 text-[11px] font-medium text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
          >
            ✕ close
          </button>
        </header>

        <div className="grid flex-1 grid-cols-1 gap-0 overflow-hidden md:grid-cols-2">
          {/* LEFT: weaknesses */}
          <section className="flex flex-col gap-2 overflow-y-auto border-line-soft px-6 py-4 md:border-r">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                Weaknesses
              </span>
              <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
                {plan.weaknesses.length} found
              </span>
            </div>
            {sortedWeaknesses.length === 0 ? (
              <div className="rounded-xl border border-line-soft bg-bg-card px-4 py-6 text-center text-[11px] text-fg-dim">
                The critic found nothing to improve.
              </div>
            ) : (
              <ul className="flex flex-col gap-2">
                {sortedWeaknesses.map((w) => (
                  <li
                    key={w.id}
                    className="flex flex-col gap-1.5 rounded-xl border border-line bg-bg-card p-3"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] ${severityBadgeClass(w.severity)}`}
                        >
                          {w.severity}
                        </span>
                        {w.source && (
                          <span
                            className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] ${sourceBadgeClass(w.source)}`}
                            title={
                              w.source === 'effects'
                                ? 'From the effects-layer pass — full-video review'
                                : 'From the macro pass — thumbnail review'
                            }
                          >
                            {w.source}
                          </span>
                        )}
                        <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
                          {w.category}
                        </span>
                        {w.frame_id && (
                          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
                            · {w.frame_id}
                          </span>
                        )}
                        {w.transition && (
                          <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
                            · {w.transition}
                          </span>
                        )}
                      </div>
                    </div>
                    <p className="text-[12px] leading-relaxed text-fg">
                      {w.issue}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* RIGHT: mutations as checkboxes */}
          <section className="flex flex-col gap-2 overflow-y-auto px-6 py-4">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                Proposed mutations
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => toggleAll(true)}
                  className="rounded-full border border-line bg-bg-card px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-fg-mute hover:border-accent hover:text-accent"
                >
                  all
                </button>
                <button
                  type="button"
                  onClick={() => toggleAll(false)}
                  className="rounded-full border border-line bg-bg-card px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-fg-mute hover:border-accent hover:text-accent"
                >
                  none
                </button>
              </div>
            </div>
            {/* Source filter pill — focus the action panel on macro vs effects.
                Counts roll up the unfiltered totals so the user can see what's
                hidden behind the current pill. */}
            {(macroMutationCount > 0 || effectsMutationCount > 0) && (
              <div className="flex items-center gap-1">
                {(['all', 'macro', 'effects'] as const).map((opt) => {
                  const count =
                    opt === 'all'
                      ? planRef.mutations.length
                      : opt === 'macro'
                        ? macroMutationCount
                        : effectsMutationCount
                  const active = sourceFilter === opt
                  return (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => setSourceFilter(opt)}
                      className={`rounded-full border px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] transition ${
                        active
                          ? 'border-accent bg-accent/10 text-accent'
                          : 'border-line bg-bg-card text-fg-mute hover:border-accent/40 hover:text-accent'
                      }`}
                    >
                      {opt} · {count}
                    </button>
                  )
                })}
              </div>
            )}
            {filteredMutations.length === 0 ? (
              <div className="rounded-xl border border-line-soft bg-bg-card px-4 py-6 text-center text-[11px] text-fg-dim">
                {plan.mutations.length === 0
                  ? 'No actionable mutations proposed.'
                  : `No ${sourceFilter} mutations.`}
              </div>
            ) : (
              <ul className="flex flex-col gap-2">
                {filteredMutations.map((m) => (
                  <MutationRow
                    key={m.id}
                    mutation={m}
                    checked={!!selected[m.id]}
                    onToggle={() =>
                      setSelected((prev) => ({
                        ...prev,
                        [m.id]: !prev[m.id],
                      }))
                    }
                  />
                ))}
              </ul>
            )}
          </section>
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-line-soft bg-bg-card px-6 py-3">
          <div className="flex flex-col gap-0.5">
            <span className="text-[10px] uppercase tracking-[0.18em] text-fg-mute">
              {approvedIds.length}{' '}
              {approvedIds.length === 1 ? 'mutation' : 'mutations'} selected
            </span>
            <span className="text-[10px] uppercase tracking-[0.18em] text-fg-dim">
              {approvedIds.length === 0
                ? 'Select at least one to apply'
                : `~${totalSeconds}s estimated`}
              {refireMutations.length > 0 && approvedIds.length > 0 && (
                <span>
                  {' '}
                  · {refireMutations.length} Veo refire
                  {refireMutations.length === 1 ? '' : 's'}
                </span>
              )}
              {bridgeMutations.length > 0 && approvedIds.length > 0 && (
                <span>
                  {' '}
                  · {bridgeMutations.length} Veo bridge
                  {bridgeMutations.length === 1 ? '' : 's'}
                </span>
              )}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {/* Effects-pass quick-adopt — every effects mutation is cost="free"
                (no Veo refire) so a single-click "yes to all of them" is a
                meaningfully different action than the macro pass. */}
            {effectsMutationCount > 0 && (
              <button
                type="button"
                onClick={selectAllEffects}
                disabled={applying}
                className="rounded-full border border-purple-500/40 bg-purple-500/10 px-3 py-1.5 text-[11px] font-medium text-purple-600 transition hover:bg-purple-500/15 disabled:opacity-60"
                title="Effects mutations are free (no Veo refire) — select them all"
              >
                ✓ all effects ({effectsMutationCount})
              </button>
            )}
            <button
              type="button"
              onClick={onDismiss}
              disabled={applying}
              className="rounded-full border border-line bg-bg-card px-4 py-1.5 text-xs text-fg-mute transition hover:border-accent hover:text-accent disabled:opacity-60"
            >
              cancel
            </button>
            <button
              type="button"
              onClick={() => onApply(approvedIds)}
              disabled={applying || approvedIds.length === 0}
              className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
            >
              {applying
                ? 'Applying…'
                : `Apply ${approvedIds.length} & generate v${nextVersionPlaceholder()}`}
            </button>
          </div>
        </footer>
      </motion.div>
    </div>
  )
}

// We don't have direct access to current_version inside the modal without
// piping it through; the parent always renders the modal once a render
// exists, so v(current+1) is the next version. The modal keeps it
// generic ("v…") when we don't have the count.
function nextVersionPlaceholder(): string {
  return '…'
}

// Structural-mutation label generator. Returns null for in-place edits
// so the existing `mutation.target` mono-string keeps showing. For
// structural ops we replace it with a human-readable headline ("Insert
// design_sequence at position 2", "Generate Veo bridge between f3 and
// f4", etc) — the exact mutation target string still ships in the
// expandable details panel below.
function structuralLabel(mutation: CritiqueMutation): {
  headline: string
  detail: string | null
} | null {
  const target = (mutation.target || '').trim()

  // frames.add — `to` is a full frame spec dict.
  if (target === 'frames.add') {
    const spec = isPlainObject(mutation.to) ? mutation.to : {}
    const kind =
      typeof spec.kind === 'string' ? spec.kind : 'live_action'
    const caption =
      typeof spec.caption === 'string' ? spec.caption.trim() : ''
    const prompt =
      typeof spec.prompt === 'string' ? spec.prompt.trim() : ''
    const template =
      typeof spec.template === 'string' ? spec.template.trim() : ''
    const indexHint = formatInsertLocation(mutation.from)
    const headline = `+ Insert ${kind} shot${indexHint}`
    const detail =
      caption ||
      (prompt && prompt.slice(0, 140)) ||
      (template && `template: ${template}`) ||
      null
    return { headline, detail }
  }

  // frames.remove — `from` references the frame being removed.
  if (target === 'frames.remove') {
    const ref = formatFrameRef(mutation.from)
    return {
      headline: `- Remove frame ${ref}`,
      detail: typeof mutation.from === 'object' && mutation.from
        ? null
        : null,
    }
  }

  // frames.reorder — `from` references the moving frame, `to` the dest.
  if (target === 'frames.reorder') {
    const fromRef = formatFrameRef(mutation.from)
    const toRef = formatFrameRef(mutation.to)
    return {
      headline: `↔ Move ${fromRef} → ${toRef}`,
      detail: null,
    }
  }

  // frame.X.kind swap.
  const parts = target.split('.')
  if (
    parts.length === 3 &&
    parts[0] === 'frame' &&
    parts[2] === 'kind'
  ) {
    const fid = parts[1]
    const oldKind = typeof mutation.from === 'string' ? mutation.from : '?'
    const newKind = typeof mutation.to === 'string' ? mutation.to : '?'
    return {
      headline: `↻ Swap ${fid}: ${oldKind} → ${newKind}`,
      detail: null,
    }
  }

  // transition.X_Y.style → veo_bridge.
  if (
    parts.length === 3 &&
    parts[0] === 'transition' &&
    parts[2] === 'style'
  ) {
    const pair = parts[1]
    const newStyle =
      typeof mutation.to === 'string' ? mutation.to : '?'
    if (newStyle === 'veo_bridge') {
      // Pair ID is "<from>_<to>" — split on first underscore for display.
      const underscoreIdx = pair.indexOf('_')
      const fromId = underscoreIdx > 0 ? pair.slice(0, underscoreIdx) : pair
      const toId = underscoreIdx > 0 ? pair.slice(underscoreIdx + 1) : ''
      return {
        headline: `▶ Generate Veo motion bridge between ${fromId} and ${toId}`,
        detail: null,
      }
    }
    // crossfade / match_cut still get the structural treatment so the
    // user sees a clean headline instead of just the target string.
    return {
      headline: `↹ Transition ${pair}: → ${newStyle}`,
      detail: null,
    }
  }

  return null
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

function formatInsertLocation(from: unknown): string {
  if (typeof from === 'number') return ` at position ${from}`
  if (isPlainObject(from)) {
    if (typeof from.after === 'string') return ` after ${from.after}`
    if (typeof from.before === 'string') return ` before ${from.before}`
    if (typeof from.id === 'string') return ` near ${from.id}`
  }
  return ' (appended)'
}

function formatFrameRef(ref: unknown): string {
  if (typeof ref === 'number') return `index ${ref}`
  if (typeof ref === 'string') return ref
  if (isPlainObject(ref)) {
    if (typeof ref.id === 'string') return ref.id
    if (typeof ref.after === 'string') return `after ${ref.after}`
    if (typeof ref.before === 'string') return `before ${ref.before}`
  }
  return '?'
}

function MutationRow({
  mutation,
  checked,
  onToggle,
}: {
  mutation: CritiqueMutation
  checked: boolean
  onToggle: () => void
}) {
  const structural = structuralLabel(mutation)
  return (
    <li
      className={`flex flex-col gap-2 rounded-xl border bg-bg-card p-3 transition ${
        checked
          ? 'border-accent shadow-[0_2px_10px_rgba(111,92,255,0.12)]'
          : 'border-line hover:border-accent/40'
      }`}
    >
      <label className="flex cursor-pointer items-start gap-2.5">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-0.5 h-4 w-4 cursor-pointer accent-[var(--accent)]"
        />
        <div className="flex flex-1 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {/* Structural mutations get a plain-language headline; in-place
                edits keep the mono target string they always had. */}
            {structural ? (
              <span className="text-[12px] font-semibold text-fg">
                {structural.headline}
              </span>
            ) : (
              <span className="font-mono text-[10.5px] text-fg">
                {mutation.target}
              </span>
            )}
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] ${costBadgeClass(mutation.cost)}`}
              title={
                mutation.cost === 'veo'
                  ? 'Re-fires Veo for this frame (~60-90s)'
                  : mutation.cost === 'render'
                    ? 'Remotion re-render only (~30s)'
                    : 'Pure prop edit — no model calls'
              }
            >
              {costBadgeLabel(mutation.cost, mutation.estimated_seconds)}
            </span>
            {mutation.source && (
              <span
                className={`rounded-full border px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.18em] ${sourceBadgeClass(mutation.source)}`}
                title={
                  mutation.source === 'effects'
                    ? 'From the effects-layer pass — full-video review'
                    : 'From the macro pass — thumbnail review'
                }
              >
                {mutation.source}
              </span>
            )}
            {/* For structural mutations, show the raw target as a small
                tooltip-y mono chip so power users can still copy the
                exact target into a debug panel. */}
            {structural && (
              <span
                className="rounded bg-bg-soft px-1.5 py-0.5 font-mono text-[9.5px] text-fg-dim"
                title={mutation.target}
              >
                {mutation.target}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-0.5 text-[11px] leading-relaxed text-fg">
            <span className="text-fg-dim">{mutation.reason}</span>
            {structural?.detail && (
              <span className="text-[11px] italic text-fg-mute">
                {structural.detail}
              </span>
            )}
            <div className="mt-0.5 flex flex-col gap-1 rounded-md bg-bg-soft px-2 py-1.5 font-mono text-[10.5px]">
              <div className="flex gap-2">
                <span className="text-fg-dim">from:</span>
                <span className="truncate text-fg-mute">
                  {prettyValue(mutation.from)}
                </span>
              </div>
              <div className="flex gap-2">
                <span className="text-fg-dim">to:&nbsp;&nbsp;</span>
                <span className="truncate text-accent">
                  {prettyValue(mutation.to)}
                </span>
              </div>
            </div>
          </div>
        </div>
      </label>
    </li>
  )
}

function prettyValue(v: unknown): string {
  if (v === null || v === undefined) return '∅'
  if (typeof v === 'string') return v.length > 140 ? v.slice(0, 140) + '…' : v
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  try {
    const s = JSON.stringify(v)
    return s.length > 140 ? s.slice(0, 140) + '…' : s
  } catch {
    return '<unserializable>'
  }
}

// Avoid unused-symbol warnings for type imports referenced only in
// JSX through their parent containers (TypeScript's emit ignores
// these at runtime but the linter sometimes flags them).
export type { ImprovementStatus }
