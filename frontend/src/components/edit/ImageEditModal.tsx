import { useEffect, useRef, useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import {
  editRegion,
  fromSketch,
  type EditAspect,
  type EditScope,
} from '../../lib/imageEdit'
import MaskCanvas, { type MaskCanvasHandle } from './MaskCanvas'
import SketchCanvas, { type SketchCanvasHandle } from './SketchCanvas'

type CommonProps = {
  open: boolean
  onClose: () => void
  onResult: (newImageUrl: string) => void
  aspect?: EditAspect
  scope?: EditScope
  scopeId?: string | null
}

export type InpaintModalProps = CommonProps & {
  mode: 'inpaint'
  /** The image the user wants to edit a region of. */
  sourceUrl: string
}

export type SketchModalProps = CommonProps & {
  mode: 'sketch'
  sourceUrl?: never
}

export type ImageEditModalProps = InpaintModalProps | SketchModalProps

/**
 * Single modal component that hosts either flow:
 *
 *   - `mode='inpaint'` shows MaskCanvas over `sourceUrl`. User paints the
 *     region they want changed, types what should go there, hits submit.
 *   - `mode='sketch'` shows SketchCanvas with brush/eraser and an aspect
 *     picker. User scribbles a layout, types what it represents, submits.
 *
 * On submit we POST to the matching endpoint, then call `onResult` with
 * the new URL so the caller can swap it into the relevant store / state.
 *
 * The modal owns its prompt input + brush size + aspect, delegates drawing
 * to the canvas refs, and handles submit/loading/error in one place.
 */
export default function ImageEditModal(props: ImageEditModalProps) {
  const { open, onClose, onResult, mode } = props
  const [prompt, setPrompt] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [brush, setBrush] = useState(mode === 'inpaint' ? 36 : 6)
  const [color, setColor] = useState('#1a1a1a')
  const [aspect, setAspect] = useState<EditAspect>(props.aspect ?? '16:9')

  const maskRef = useRef<MaskCanvasHandle | null>(null)
  const sketchRef = useRef<SketchCanvasHandle | null>(null)

  // Reset state every time the modal is freshly opened so a previous
  // session's prompt doesn't bleed into the next.
  useEffect(() => {
    if (open) {
      setPrompt('')
      setError(null)
      setSubmitting(false)
      // The canvas refs aren't mounted yet on the first effect tick;
      // clearing happens lazily on first interaction.
    }
  }, [open])

  // Close on Escape so power users don't have to reach for the X.
  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !submitting) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, submitting, onClose])

  async function handleSubmit() {
    if (submitting) return
    if (!prompt.trim()) {
      setError('describe what should appear in the highlighted area')
      return
    }

    setSubmitting(true)
    setError(null)
    try {
      if (props.mode === 'inpaint') {
        const mask = maskRef.current?.getMaskDataUrl()
        if (!mask) {
          setError('paint over the region you want to change first')
          setSubmitting(false)
          return
        }
        const r = await editRegion({
          source_url: props.sourceUrl,
          mask_data_url: mask,
          prompt: prompt.trim(),
          aspect,
          save_scope: props.scope,
          save_scope_id: props.scopeId,
        })
        onResult(r.image_url)
        onClose()
      } else {
        const sketch = sketchRef.current?.getSketchDataUrl() ?? ''
        if (!sketchRef.current?.hasStrokes()) {
          setError('sketch something first')
          setSubmitting(false)
          return
        }
        const r = await fromSketch({
          sketch_data_url: sketch,
          prompt: prompt.trim(),
          aspect,
          save_scope: props.scope,
          save_scope_id: props.scopeId,
        })
        onResult(r.image_url)
        onClose()
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'edit failed')
      setSubmitting(false)
    }
  }

  const title =
    mode === 'inpaint' ? 'reimagine a region' : 'sketch → image'
  const placeholder =
    mode === 'inpaint'
      ? "what should appear in the highlighted area? e.g. 'a ceramic mug with steam, same lighting'"
      : "what is this sketch of? e.g. 'a bottle of olive oil on a marble counter, soft window light'"

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          className="fixed inset-0 z-50 grid place-items-center bg-fg/40 p-4 backdrop-blur-sm"
          onMouseDown={(e) => {
            // Click-outside to close, but only if the click started on the
            // backdrop itself — drags out of the canvas shouldn't close.
            if (e.target === e.currentTarget && !submitting) onClose()
          }}
        >
          <motion.div
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_20px_60px_rgba(20,20,40,0.18)]"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <header className="flex items-center justify-between border-b border-line-soft px-5 py-3">
              <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
                {title}
              </div>
              <button
                type="button"
                onClick={onClose}
                disabled={submitting}
                className="rounded-md px-2 py-1 text-fg-dim hover:bg-bg-soft disabled:opacity-40"
                aria-label="close"
              >
                ✕
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-5 py-4">
              <div className="grid place-items-center">
                {props.mode === 'inpaint' ? (
                  <MaskCanvas
                    ref={maskRef}
                    imageUrl={props.sourceUrl}
                    brushSize={brush}
                  />
                ) : (
                  <SketchCanvas
                    ref={sketchRef}
                    aspect={aspect}
                    brushSize={brush}
                    color={color}
                    className="w-full max-w-2xl"
                  />
                )}
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-3 text-[11px] text-fg-mute">
                <label className="flex items-center gap-2">
                  <span>brush</span>
                  <input
                    type="range"
                    min={mode === 'inpaint' ? 8 : 2}
                    max={mode === 'inpaint' ? 120 : 32}
                    value={brush}
                    onChange={(e) => setBrush(Number(e.target.value))}
                    className="w-32"
                  />
                  <span className="tabular-nums text-fg-dim">{brush}px</span>
                </label>
                {mode === 'sketch' && (
                  <label className="flex items-center gap-2">
                    <span>color</span>
                    <input
                      type="color"
                      value={color}
                      onChange={(e) => setColor(e.target.value)}
                      className="h-6 w-8 cursor-pointer rounded border border-line"
                    />
                  </label>
                )}
                {mode === 'sketch' && (
                  <label className="flex items-center gap-2">
                    <span>aspect</span>
                    <select
                      value={aspect}
                      onChange={(e) => setAspect(e.target.value as EditAspect)}
                      className="rounded border border-line bg-bg-card px-2 py-1 text-fg"
                    >
                      <option value="16:9">16:9</option>
                      <option value="1:1">1:1</option>
                      <option value="9:16">9:16</option>
                    </select>
                  </label>
                )}
                <button
                  type="button"
                  onClick={() => {
                    if (props.mode === 'inpaint') maskRef.current?.undo()
                    else sketchRef.current?.undo()
                  }}
                  className="rounded bg-bg-soft px-2 py-1 hover:bg-bg-soft/80"
                >
                  undo
                </button>
                <button
                  type="button"
                  onClick={() => {
                    if (props.mode === 'inpaint') maskRef.current?.clear()
                    else sketchRef.current?.clear()
                  }}
                  className="rounded bg-bg-soft px-2 py-1 hover:bg-bg-soft/80"
                >
                  clear
                </button>
              </div>

              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={placeholder}
                rows={3}
                disabled={submitting}
                className="mt-4 block w-full resize-none rounded-lg border border-line bg-bg-card px-3 py-2 text-sm text-fg placeholder:text-fg-dim focus:border-accent focus:outline-none disabled:opacity-60"
              />

              {error && (
                <div className="mt-2 rounded bg-danger/10 px-3 py-2 text-xs text-danger">
                  {error}
                </div>
              )}
            </div>

            <footer className="flex items-center justify-between gap-3 border-t border-line-soft px-5 py-3">
              <div className="text-[11px] text-fg-dim">
                {mode === 'inpaint'
                  ? 'paint the area you want changed; the rest is preserved'
                  : 'rough shapes only — the model fills in the rest'}
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={submitting}
                  className="rounded-lg px-3 py-1.5 text-sm text-fg-mute hover:bg-bg-soft disabled:opacity-40"
                >
                  cancel
                </button>
                <button
                  type="button"
                  onClick={handleSubmit}
                  disabled={submitting}
                  className="rounded-lg bg-accent px-4 py-1.5 text-sm font-medium text-bg-card hover:bg-accent/90 disabled:opacity-60"
                >
                  {submitting ? 'generating…' : 'generate'}
                </button>
              </div>
            </footer>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
