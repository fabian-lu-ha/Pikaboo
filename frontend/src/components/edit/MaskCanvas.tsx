import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'

/** Imperative handle exposed to the parent modal so submit/clear/undo
 * controls live next to the prompt input rather than inside the canvas. */
export type MaskCanvasHandle = {
  /** PNG dataURL of the mask layer alone (transparent where untouched). */
  getMaskDataUrl: () => string | null
  clear: () => void
  undo: () => void
  hasStrokes: () => boolean
}

type Props = {
  imageUrl: string
  brushSize?: number
  className?: string
}

/**
 * Mask drawing surface — renders the source image in the background and
 * overlays a semi-transparent magenta layer where the user paints. The
 * exported mask is the painted layer alone (no source pixels), so the
 * backend can use the alpha channel as the hit-map.
 *
 * Sizing strategy: the canvas's intrinsic pixel size matches the image's
 * natural size to keep mask edges sharp regardless of how the modal scales.
 * CSS scales the displayed surface; brush coordinates are mapped from CSS
 * px to canvas px on every pointer event.
 *
 * Brush preview: a circle outline follows the pointer at the configured
 * brush size — so the user sees the brush footprint BEFORE they click.
 */
const MaskCanvas = forwardRef<MaskCanvasHandle, Props>(function MaskCanvas(
  { imageUrl, brushSize = 36, className },
  ref
) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const drawingRef = useRef(false)
  // Snapshot stack for undo. Each push is the full canvas after a stroke
  // ends; we cap at 20 to keep memory bounded on big sources.
  const undoStackRef = useRef<ImageData[]>([])
  const hasStrokesRef = useRef(false)

  // Sized once the rendered <img> fires onLoad. Using the actual rendered
  // image (not an offscreen probe) avoids CORS oddities and silent hangs.
  const [naturalSize, setNaturalSize] = useState<{ w: number; h: number } | null>(
    null,
  )
  const [imgError, setImgError] = useState(false)
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null)

  const handleImgLoad = useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      const img = e.currentTarget
      const max = 2048
      let w = img.naturalWidth
      let h = img.naturalHeight
      if (!w || !h) {
        setImgError(true)
        return
      }
      const longest = Math.max(w, h)
      if (longest > max) {
        const k = max / longest
        w = Math.round(w * k)
        h = Math.round(h * k)
      }
      setNaturalSize({ w, h })
      setImgError(false)
    },
    [],
  )

  const getCtx = useCallback(() => {
    const c = canvasRef.current
    if (!c) return null
    return c.getContext('2d')
  }, [])

  const pushUndo = useCallback(() => {
    const ctx = getCtx()
    const c = canvasRef.current
    if (!ctx || !c) return
    try {
      const snap = ctx.getImageData(0, 0, c.width, c.height)
      undoStackRef.current.push(snap)
      if (undoStackRef.current.length > 20) {
        undoStackRef.current.shift()
      }
    } catch {
      // getImageData can throw on tainted canvases — silently skip undo.
    }
  }, [getCtx])

  const drawAt = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const c = canvasRef.current
      const ctx = getCtx()
      if (!c || !ctx) return
      const rect = c.getBoundingClientRect()
      // Map CSS pixel → canvas pixel. The canvas sits at native image
      // resolution so this scaling is non-trivial.
      const x = ((e.clientX - rect.left) / rect.width) * c.width
      const y = ((e.clientY - rect.top) / rect.height) * c.height
      // Brush radius is specified in CSS px — convert to canvas px so the
      // stroke feels the same regardless of zoom.
      const r = (brushSize / 2) * (c.width / rect.width)

      ctx.fillStyle = 'rgba(255, 0, 220, 0.55)'
      ctx.beginPath()
      ctx.arc(x, y, r, 0, Math.PI * 2)
      ctx.fill()
      hasStrokesRef.current = true
    },
    [brushSize, getCtx],
  )

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      e.preventDefault()
      ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
      pushUndo()
      drawingRef.current = true
      drawAt(e)
    },
    [drawAt, pushUndo],
  )

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      setHover({ x: e.clientX - rect.left, y: e.clientY - rect.top })
      if (!drawingRef.current) return
      drawAt(e)
    },
    [drawAt],
  )

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      drawingRef.current = false
      ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
    },
    [],
  )

  const onPointerLeave = useCallback(() => {
    setHover(null)
    drawingRef.current = false
  }, [])

  useImperativeHandle(
    ref,
    () => ({
      getMaskDataUrl: () => {
        const c = canvasRef.current
        if (!c) return null
        if (!hasStrokesRef.current) return null
        return c.toDataURL('image/png')
      },
      clear: () => {
        const ctx = getCtx()
        const c = canvasRef.current
        if (!ctx || !c) return
        ctx.clearRect(0, 0, c.width, c.height)
        undoStackRef.current = []
        hasStrokesRef.current = false
      },
      undo: () => {
        const ctx = getCtx()
        const c = canvasRef.current
        if (!ctx || !c) return
        const snap = undoStackRef.current.pop()
        if (snap) {
          ctx.putImageData(snap, 0, 0)
          // Strokes might still exist after popping — best effort: assume
          // there are strokes if any non-zero alpha pixel remains. Cheap
          // sample of corners + center is good enough for the gating UI.
          hasStrokesRef.current = sampleHasInk(ctx, c.width, c.height)
        } else {
          ctx.clearRect(0, 0, c.width, c.height)
          hasStrokesRef.current = false
        }
      },
      hasStrokes: () => hasStrokesRef.current,
    }),
    [getCtx],
  )

  return (
    <div
      ref={containerRef}
      className={`relative inline-block max-h-[60vh] max-w-full ${className ?? ''}`}
      style={
        naturalSize
          ? { aspectRatio: `${naturalSize.w} / ${naturalSize.h}` }
          : { minHeight: 320, minWidth: 320 }
      }
    >
      {/* The rendered image is always present so onLoad fires reliably.
          We don't set crossOrigin — a same-origin /api/storage URL doesn't
          need it, and adding it caused some browsers to silently hang the
          load (the previous bug that left the canvas unmounted). */}
      <img
        src={imageUrl}
        alt=""
        onLoad={handleImgLoad}
        onError={() => setImgError(true)}
        className="absolute inset-0 block h-full w-full select-none object-contain"
        draggable={false}
      />

      {imgError && (
        <div className="absolute inset-0 grid place-items-center bg-bg-soft/85 p-6 text-center text-xs text-danger">
          couldn't load image — refresh and try again
        </div>
      )}

      {!naturalSize && !imgError && (
        <div className="absolute inset-0 grid place-items-center bg-bg-soft/40 p-6 text-center text-xs text-fg-dim">
          loading image…
        </div>
      )}

      {naturalSize && (
        <canvas
          ref={canvasRef}
          width={naturalSize.w}
          height={naturalSize.h}
          className="absolute inset-0 block h-full w-full cursor-crosshair touch-none"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onPointerLeave={onPointerLeave}
        />
      )}

      {/* Visible brush preview — a circle outline that follows the pointer
          at the configured brush size. Pointer-events:none so it doesn't
          intercept the canvas's own pointer handling. */}
      {naturalSize && hover && (
        <div
          aria-hidden
          className="pointer-events-none absolute rounded-full border border-white/80 ring-1 ring-fg/40 mix-blend-difference"
          style={{
            left: hover.x - brushSize / 2,
            top: hover.y - brushSize / 2,
            width: brushSize,
            height: brushSize,
          }}
        />
      )}
    </div>
  )
})

function sampleHasInk(ctx: CanvasRenderingContext2D, w: number, h: number): boolean {
  // Cheap probe — read a small grid of pixels. Full getImageData on a 2K
  // canvas after every undo is wasteful and we just need a yes/no signal.
  const points: [number, number][] = []
  for (let yi = 0; yi < 5; yi++) {
    for (let xi = 0; xi < 5; xi++) {
      points.push([
        Math.floor((xi / 5) * w),
        Math.floor((yi / 5) * h),
      ])
    }
  }
  for (const [x, y] of points) {
    try {
      const d = ctx.getImageData(x, y, 1, 1).data
      if (d[3] > 0) return true
    } catch {
      return false
    }
  }
  return false
}

export default MaskCanvas
