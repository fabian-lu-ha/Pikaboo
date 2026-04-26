/**
 * Two small icon buttons that float in the top-right of any image render
 * surface. Hidden until the parent's `group` is hovered (Tailwind's
 * group-hover utilities), so they don't fight the main content for
 * attention.
 *
 * The parent must add `relative` and `group` classes itself — we don't
 * wrap, because the buttons need to sit above any caption/overlay the
 * parent already has.
 */
type Props = {
  onInpaint: () => void
  onSketch: () => void
  hideSketch?: boolean
  /** When false, the inpaint button is disabled with a tooltip explaining
   * why (typically because no keyframe has been generated yet). */
  inpaintEnabled?: boolean
}

export default function EditOverlayButtons({
  onInpaint,
  onSketch,
  hideSketch = false,
  inpaintEnabled = true,
}: Props) {
  return (
    <div className="pointer-events-none absolute right-2 top-2 flex gap-1.5 opacity-0 transition-opacity duration-150 group-hover:opacity-100 focus-within:opacity-100">
      <button
        type="button"
        disabled={!inpaintEnabled}
        onClick={(e) => {
          e.stopPropagation()
          if (inpaintEnabled) onInpaint()
        }}
        title={
          inpaintEnabled
            ? 'reimagine a region'
            : 'generate the keyframe first to paint a mask'
        }
        aria-label="reimagine a region"
        className="pointer-events-auto grid h-8 w-8 place-items-center rounded-full bg-bg-card/95 text-fg shadow-[0_2px_10px_rgba(20,20,40,0.18)] backdrop-blur-sm hover:bg-accent hover:text-bg-card disabled:cursor-not-allowed disabled:bg-bg-card/60 disabled:text-fg-dim disabled:hover:bg-bg-card/60 disabled:hover:text-fg-dim"
      >
        {/* paintbrush glyph */}
        <span aria-hidden className="text-sm leading-none">
          🖌
        </span>
      </button>
      {!hideSketch && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation()
            onSketch()
          }}
          title="generate from sketch"
          aria-label="generate from sketch"
          className="pointer-events-auto grid h-8 w-8 place-items-center rounded-full bg-bg-card/95 text-fg shadow-[0_2px_10px_rgba(20,20,40,0.18)] backdrop-blur-sm hover:bg-accent hover:text-bg-card"
        >
          {/* pencil glyph */}
          <span aria-hidden className="text-sm leading-none">
            ✏︎
          </span>
        </button>
      )}
    </div>
  )
}
