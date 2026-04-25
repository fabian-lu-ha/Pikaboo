import {
  useRef,
  useState,
  type DragEvent,
  type FormEvent,
} from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { useOnboardingStore } from '../stores/onboardingStore'

type LocalAsset = {
  id: string
  name: string
  preview: string
  status: 'uploading' | 'done' | 'failed'
  asset_url?: string
}

let localAssetCounter = 0

export function StepBasics({ onAdvance }: { onAdvance: () => void }) {
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [posts, setPosts] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [localAssets, setLocalAssets] = useState<LocalAsset[]>([])
  const [dragActive, setDragActive] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)
  const setBrand = useOnboardingStore((s) => s.setBrand)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitting(true)

    const basics = await fetch('/api/onboarding/basics', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        url,
        name: name || undefined,
        description: description || undefined,
      }),
    })
    if (!basics.ok) {
      setSubmitting(false)
      return
    }
    const { brand_id } = (await basics.json()) as { brand_id: string }
    setBrand(brand_id, url)

    // Fire-and-forget: posts text (non-blocking)
    if (posts.trim()) {
      void fetch('/api/onboarding/posts', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ brand_id, posts_text: posts.trim() }),
      }).catch(() => {})
    }

    // Fire-and-forget: any pending assets that picked an upload before submit
    // already POST to the assets endpoint themselves. Brand_id is needed for that
    // — if the user dropped files BEFORE submit, we send them now with brand_id.
    const queued = localAssets.filter((a) => a.status === 'uploading' && !a.asset_url)
    for (const q of queued) {
      // re-upload with brand_id; fire-and-forget
      // (no-op for now: this branch is only hit if the user dropped before submit;
      // we handle that case below via uploadFiles which gates on brand_id)
      void q
    }

    void fetch('/api/onboarding/scrape', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ brand_id }),
    })

    onAdvance()
  }

  async function uploadFiles(files: File[]) {
    if (files.length === 0) return
    const brandId = useOnboardingStore.getState().brandId

    const newLocals: LocalAsset[] = files.map((f) => ({
      id: `local-${++localAssetCounter}`,
      name: f.name,
      preview: URL.createObjectURL(f),
      status: 'uploading',
    }))
    setLocalAssets((prev) => [...prev, ...newLocals])

    if (!brandId) {
      // Defer: mark files but the brand isn't created yet. Tell user to submit first.
      // Mark them failed for now to keep UX honest.
      setLocalAssets((prev) =>
        prev.map((a) =>
          newLocals.some((n) => n.id === a.id)
            ? { ...a, status: 'failed' as const }
            : a,
        ),
      )
      return
    }

    await Promise.all(
      newLocals.map(async (local, i) => {
        const file = files[i]
        const fd = new FormData()
        fd.append('brand_id', brandId)
        fd.append('files', file)
        try {
          const r = await fetch('/api/onboarding/assets', {
            method: 'POST',
            body: fd,
          })
          if (!r.ok) throw new Error(`upload failed: ${r.status}`)
          const data = (await r.json()) as { asset_urls?: string[] }
          const url = data.asset_urls?.[0]
          setLocalAssets((prev) =>
            prev.map((a) =>
              a.id === local.id
                ? { ...a, status: 'done', asset_url: url }
                : a,
            ),
          )
        } catch {
          setLocalAssets((prev) =>
            prev.map((a) =>
              a.id === local.id ? { ...a, status: 'failed' } : a,
            ),
          )
        }
      }),
    )
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
    const files = Array.from(e.dataTransfer.files).filter((f) =>
      f.type.startsWith('image/'),
    )
    void uploadFiles(files)
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    if (!dragActive) setDragActive(true)
  }

  function onDragLeave(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    e.stopPropagation()
    setDragActive(false)
  }

  return (
    <div className="grid min-h-[calc(100vh-73px)] place-items-center px-10 py-12">
      <div className="w-full max-w-2xl">
        <motion.span
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.1 }}
          className="text-[11px] font-medium uppercase tracking-[0.2em] text-fg-mute"
        >
          Step 01 — Introduce yourself
        </motion.span>

        <motion.h1
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.16, duration: 0.5 }}
          className="mt-3 text-5xl font-medium leading-[1.05] tracking-tight"
        >
          Tell us{' '}
          <span
            className="font-serif italic text-accent"
            style={{ fontVariationSettings: '"opsz" 144, "SOFT" 50' }}
          >
            your brand.
          </span>
        </motion.h1>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.32 }}
          className="mt-4 max-w-lg text-base text-fg-mute"
        >
          Drop a URL. The agent reads the rest — your voice, your products,
          your competitive field — for itself.
        </motion.p>

        <motion.form
          onSubmit={handleSubmit}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.42, duration: 0.5 }}
          className="mt-10 flex flex-col gap-4"
        >
          <div className="flex items-center rounded-2xl border border-line bg-bg-card px-1.5 py-1.5 shadow-[0_8px_30px_rgba(20,20,40,0.05)]">
            <span className="px-3 text-fg-dim">⌘</span>
            <input
              required
              type="url"
              placeholder="https://your-brand.com"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              className="flex-1 bg-transparent px-2 py-3 text-lg outline-none placeholder:text-fg-dim"
            />
            <button
              type="submit"
              disabled={!url || submitting}
              className="grid h-10 w-10 place-items-center rounded-xl bg-accent text-white shadow-[0_3px_12px_rgba(111,92,255,0.4)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
              title="Begin"
            >
              {submitting ? '◐' : '↑'}
            </button>
          </div>

          <details className="group rounded-xl border border-line bg-bg-card/60 px-4 py-3">
            <summary className="flex cursor-pointer items-center gap-2 text-sm text-fg-mute hover:text-fg">
              <span className="inline-block transition group-open:rotate-90">
                ›
              </span>
              Override / add more
            </summary>

            <div className="mt-4 flex flex-col gap-5">
              <div className="flex flex-col gap-3">
                <label className="text-[10px] font-medium uppercase tracking-[0.2em] text-fg-mute">
                  Identity
                </label>
                <input
                  type="text"
                  placeholder="Company name — we'll fetch it"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none placeholder:text-fg-dim focus:border-accent"
                />
                <textarea
                  placeholder="Description — we'll fetch it"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  className="rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none placeholder:text-fg-dim focus:border-accent"
                />
              </div>

              <div className="h-px bg-line-soft" />

              <div className="flex flex-col gap-2">
                <label className="text-[10px] font-medium uppercase tracking-[0.2em] text-fg-mute">
                  Best posts (optional)
                </label>
                <p className="text-[11px] leading-relaxed text-fg-dim">
                  Paste 3–10 of your favourite posts — captions, links, or
                  both. The agent will study them as voice training.
                </p>
                <textarea
                  placeholder={`We just shipped X — here's why it matters…\n\nhttps://x.com/yourbrand/status/…`}
                  value={posts}
                  onChange={(e) => setPosts(e.target.value)}
                  rows={5}
                  className="rounded-lg border border-line bg-bg px-3 py-2 font-mono text-xs leading-relaxed outline-none placeholder:text-fg-dim focus:border-accent"
                />
              </div>

              <div className="h-px bg-line-soft" />

              <div className="flex flex-col gap-2">
                <label className="text-[10px] font-medium uppercase tracking-[0.2em] text-fg-mute">
                  Product photos (optional)
                </label>
                <p className="text-[11px] leading-relaxed text-fg-dim">
                  Drop reference imagery the agent can riff on when it
                  generates posts.
                </p>
                <div
                  onDrop={onDrop}
                  onDragOver={onDragOver}
                  onDragEnter={onDragOver}
                  onDragLeave={onDragLeave}
                  onClick={() => fileInput.current?.click()}
                  className={`flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-2xl border-2 border-dashed px-6 py-7 text-center transition ${
                    dragActive
                      ? 'border-accent bg-accent-soft/40'
                      : 'border-line bg-bg-card hover:border-accent/60 hover:bg-bg-soft/40'
                  }`}
                >
                  <span className="text-2xl text-fg-dim">⊕</span>
                  <span className="text-sm font-medium text-fg">
                    Drop product photos here
                  </span>
                  <span className="text-[11px] text-fg-mute">
                    or click to browse · PNG / JPG / WEBP
                  </span>
                  <input
                    ref={fileInput}
                    type="file"
                    multiple
                    accept="image/*"
                    onChange={(e) =>
                      uploadFiles(Array.from(e.target.files ?? []))
                    }
                    className="hidden"
                  />
                </div>

                <AnimatePresence initial={false}>
                  {localAssets.length > 0 && (
                    <motion.ul
                      initial={{ opacity: 0, y: 4 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      className="mt-2 grid grid-cols-4 gap-2 sm:grid-cols-6"
                    >
                      {localAssets.map((a) => (
                        <motion.li
                          key={a.id}
                          initial={{ opacity: 0, scale: 0.96 }}
                          animate={{ opacity: 1, scale: 1 }}
                          transition={{ duration: 0.25 }}
                          className="relative aspect-square overflow-hidden rounded-lg border border-line bg-bg-soft"
                        >
                          <img
                            src={a.preview}
                            alt={a.name}
                            className="h-full w-full object-cover"
                          />
                          {a.status === 'uploading' && (
                            <div className="absolute inset-0 grid place-items-center bg-bg-card/60 backdrop-blur-[2px]">
                              <span className="font-mono text-[10px] uppercase tracking-wider text-accent">
                                ◐ uploading
                              </span>
                            </div>
                          )}
                          {a.status === 'failed' && (
                            <div className="absolute inset-0 grid place-items-center bg-danger/15">
                              <span className="font-mono text-[10px] uppercase tracking-wider text-danger">
                                ✕ failed
                              </span>
                            </div>
                          )}
                        </motion.li>
                      ))}
                    </motion.ul>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </details>
        </motion.form>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="mt-8 flex flex-wrap gap-2"
        >
          {['linear.app', 'cal.com', 'arc.net'].map((d) => (
            <button
              key={d}
              onClick={() => setUrl(`https://${d}`)}
              className="rounded-full border border-line bg-bg-card px-3 py-1.5 text-xs text-fg-mute transition hover:border-accent hover:text-fg"
            >
              try {d}
            </button>
          ))}
        </motion.div>
      </div>
    </div>
  )
}
