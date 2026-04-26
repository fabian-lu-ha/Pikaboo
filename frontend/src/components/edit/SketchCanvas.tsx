import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from 'react'

export type SketchCanvasHandle = {
  /** PNG dataURL of the sketch (white background, drawn strokes). */
  getSketchDataUrl: () => string
  clear: () => void
  undo: () => void
  hasStrokes: () => boolean
}

type Props = {
  /** Canvas aspect — must match what we tell the model to generate. */
  aspect: '1:1' | '16:9' | '9:16'
  brushSize?: number
  color?: string
  className?: string
}

const ASPECT_DIMS: Record<Props['aspect'], { w: number; h: number }> = {
  '1:1': { w: 1024, h: 1024 },
  '16:9': { w: 1280, h: 720 },
  '9:16': { w: 720, h: 1280 },
}

/**
 * Excalidraw-lite — a single-layer drawing canvas with brush size, color,
 * eraser, undo, clear. White background so the sketch reads clearly when
 * sent to the image model.
 *
 * Strokes are committed to the canvas on pointerup; undo pops the last
 * snapshot. We keep a small snapshot stack rather than re-rendering vector
 * paths because the parent only needs a flat raster export.
 */
const SketchCanvas = forwardRef<SketchCanvasHandle, Props>(function SketchCanvas(
  { aspect, brushSize = 6, color = '#1a1a1a', className },
  ref
) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const drawingRef = useRef(false)
  const lastPosRef = useRef<{ x: number; y: number } | null>(null)
  const undoStackRef = useRef<ImageData[]>([])
  const hasStrokesRef = useRef(false)

  const dims = ASPECT_DIMS[aspect]

  const [tool, setTool] = useState<'brush' | 'eraser'>('brush')

  const getCtx = useCallback(() => {
    const c = canvasRef.current
    if (!c) return null
    return c.getContext('2d')
  }, [])

  const paintWhiteBg = useCallback(() => {
    const ctx = getCtx()
    const c = canvasRef.current
    if (!ctx || !c) return
    ctx.fillStyle = '#ffffff'
    ctx.fillRect(0, 0, c.width, c.height)
  }, [getCtx])

  // Paint the white background once on mount and any time aspect changes —
  // the canvas element itself gets new dimensions so its bitmap resets.
  useEffect(() => {
    paintWhiteBg()
    undoStackRef.current = []
    hasStrokesRef.current = false
    // We deliberately depend on `aspect` not just dims so that toggling
    // aspects mid-session resets the canvas — there's no good way to map
    // strokes across aspect ratios.
  }, [aspect, paintWhiteBg])

  const pushUndo = useCallback(() => {
    const ctx = getCtx()
    const c = canvasRef.current
    if (!ctx || !c) return
    try {
      const snap = ctx.getImageData(0, 0, c.width, c.height)
      undoStackRef.current.push(snap)
      if (undoStackRef.current.length > 30) {
        undoStackRef.current.shift()
      }
    } catch {
      // ignore
    }
  }, [getCtx])

  const toCanvasCoords = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const c = canvasRef.current
      if (!c) return null
      const rect = c.getBoundingClientRect()
      const x = ((e.clientX - rect.left) / rect.width) * c.width
      const y = ((e.clientY - rect.top) / rect.height) * c.height
      return { x, y }
    },
    []
  )

  const onPointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      e.preventDefault()
      ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
      pushUndo()
      const pos = toCanvasCoords(e)
      if (!pos) return
      drawingRef.current = true
      lastPosRef.current = pos

      // Draw a single dot for taps that don't move.
      const ctx = getCtx()
      const c = canvasRef.current
      if (!ctx || !c) return
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      const k = c.width / c.getBoundingClientRect().width
      const r = (brushSize / 2) * k
      if (tool === 'eraser') {
        ctx.fillStyle = '#ffffff'
      } else {
        ctx.fillStyle = color
      }
      ctx.beginPath()
      ctx.arc(pos.x, pos.y, r, 0, Math.PI * 2)
      ctx.fill()
      hasStrokesRef.current = true
    },
    [brushSize, color, getCtx, pushUndo, toCanvasCoords, tool]
  )

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!drawingRef.current) return
      const pos = toCanvasCoords(e)
      const ctx = getCtx()
      const c = canvasRef.current
      const last = lastPosRef.current
      if (!pos || !ctx || !c || !last) return

      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      const k = c.width / c.getBoundingClientRect().width
      ctx.lineWidth = brushSize * k
      ctx.strokeStyle = tool === 'eraser' ? '#ffffff' : color
      ctx.beginPath()
      ctx.moveTo(last.x, last.y)
      ctx.lineTo(pos.x, pos.y)
      ctx.stroke()
      lastPosRef.current = pos
      hasStrokesRef.current = true
    },
    [brushSize, color, getCtx, toCanvasCoords, tool]
  )

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      drawingRef.current = false
      lastPosRef.current = null
      ;(e.target as HTMLElement).releasePointerCapture?.(e.pointerId)
    },
    []
  )

  useImperativeHandle(
    ref,
    () => ({
      getSketchDataUrl: () => {
        const c = canvasRef.current
        if (!c) return ''
        return c.toDataURL('image/png')
      },
      clear: () => {
        paintWhiteBg()
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
        } else {
          paintWhiteBg()
          hasStrokesRef.current = false
        }
      },
      hasStrokes: () => hasStrokesRef.current,
    }),
    [getCtx, paintWhiteBg]
  )

  return (
    <div className={`flex flex-col gap-2 ${className ?? ''}`}>
      <div className="flex items-center gap-2 text-[11px] text-fg-mute">
        <button
          type="button"
          onClick={() => setTool('brush')}
          className={`rounded px-2 py-1 ${tool === 'brush' ? 'bg-fg text-bg-card' : 'bg-bg-soft hover:bg-bg-soft/80'}`}
        >
          brush
        </button>
        <button
          type="button"
          onClick={() => setTool('eraser')}
          className={`rounded px-2 py-1 ${tool === 'eraser' ? 'bg-fg text-bg-card' : 'bg-bg-soft hover:bg-bg-soft/80'}`}
        >
          eraser
        </button>
      </div>
      <div
        className="relative w-full overflow-hidden rounded-lg border border-line bg-white"
        style={{ aspectRatio: `${dims.w} / ${dims.h}` }}
      >
        <canvas
          ref={canvasRef}
          width={dims.w}
          height={dims.h}
          className="absolute inset-0 block h-full w-full cursor-crosshair touch-none"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        />
      </div>
    </div>
  )
})

export default SketchCanvas
