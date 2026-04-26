import { useState } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { useAgentSessionStore } from '../stores/agentSessionStore'
import type {
  AgentDraft,
  LiftPrediction,
  PeecSnapshot,
  PeecTarget,
} from '../events/bus'
import { CHANNELS, CHANNEL_ORDER, aspectStyle, type ChannelMeta } from '../lib/channels'
import { Storyboard } from './Storyboard'
import { ResearchCard } from './ResearchCard'
import ImageEditModal from './edit/ImageEditModal'
import EditOverlayButtons from './edit/EditOverlayButtons'
import type { EditAspect } from '../lib/imageEdit'

export function AgentSession() {
  const session = useAgentSessionStore()
  if (!session.userRequest) return null

  // Group drafts by channel: a "channel draft" carries both text and (optional)
  // image. The image arrives as a separate event with channel = "{id}_image".
  const drafts = session.drafts
  const channelDrafts = collectChannels(drafts)

  const isBundled = session.status === 'bundled'
  const isFailed = session.status === 'failed'

  return (
    <motion.section
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="mx-auto mt-10 w-full max-w-3xl"
    >
      <UserPrompt text={session.userRequest} />

      <Activity
        steps={session.steps}
        running={session.status === 'running'}
        failed={isFailed}
        error={session.error}
      />

      <div className="mt-5 flex flex-col gap-4">
        {session.peec && (
          <PeecCard
            snapshot={session.peec}
            targets={session.peecTargets}
          />
        )}
        {!session.peec && session.peecUnavailable && (
          <PeecUnavailableCard reason={session.peecUnavailable} />
        )}
        <ResearchCard scope="campaign" />
        {channelDrafts.map((cd) => (
          <ChannelCard key={cd.meta.id} cd={cd} />
        ))}
        {channelDrafts.length === 0 && session.heroImage && (
          <HeroCard src={session.heroImage} />
        )}
        {session.lift && <LiftCard lift={session.lift} />}
      </div>

      {channelDrafts.length > 0 && <Storyboard />}

      <AnimatePresence>
        {isBundled && session.bundle && (
          <CampaignReady
            title={session.bundle.blog?.title || 'Campaign ready'}
            bundle={session.bundle}
          />
        )}
      </AnimatePresence>
    </motion.section>
  )
}

type CampaignBundleShape = {
  drafts?: Array<{
    channel: string
    label: string
    body: string
    image_url: string | null
  }>
  hero_image_url: string | null
  blog?: { title: string; body: string }
}

type ChannelDraft = {
  meta: ChannelMeta
  text: AgentDraft | undefined
  imageUrl: string | null
  // Did we receive an `_image` event for this channel yet, even an empty one?
  // Empty body + this flag = generation failed; no event yet = still pending.
  imageReceived: boolean
}

function collectChannels(drafts: AgentDraft[]): ChannelDraft[] {
  const textByChannel = new Map<string, AgentDraft>()
  const imageByChannel = new Map<string, string>()
  const imageReceived = new Set<string>()
  for (const d of drafts) {
    if (d.channel === 'hero_image') continue
    if (d.channel.endsWith('_image')) {
      const cid = d.channel.replace(/_image$/, '')
      imageReceived.add(cid)
      const url = d.body || d.preview
      if (url) imageByChannel.set(cid, url)
      continue
    }
    textByChannel.set(d.channel, d)
  }
  const present = new Set<string>([
    ...textByChannel.keys(),
    ...imageByChannel.keys(),
    ...imageReceived,
  ])
  // Render in canonical order; unknown channels (newsletter, tiktok…) sort last.
  const ordered = [
    ...CHANNEL_ORDER.filter((c) => present.has(c)),
    ...[...present].filter((c) => !CHANNEL_ORDER.includes(c)),
  ]
  return ordered.map((cid) => ({
    meta: CHANNELS[cid] ?? fallbackMeta(cid),
    text: textByChannel.get(cid),
    imageUrl: imageByChannel.get(cid) ?? null,
    imageReceived: imageReceived.has(cid),
  }))
}

function fallbackMeta(id: string): ChannelMeta {
  return {
    id,
    label: id.charAt(0).toUpperCase() + id.slice(1),
    glyph: '◇',
    tint: '#6b7280',
    aspect: '16:9',
    textKind: 'post',
    caption: '',
  }
}

function snapEditAspect(a: ChannelMeta['aspect']): EditAspect {
  // The model only accepts 1:1 / 16:9 / 9:16. Map display aspects to the
  // closest supported ratio so editing from a Twitter or 4:5 card still
  // produces sensible results.
  switch (a) {
    case '1:1':
      return '1:1'
    case '9:16':
      return '9:16'
    case '4:5':
      return '9:16'
    case '1.91:1':
      return '16:9'
    case '16:9':
    default:
      return '16:9'
  }
}

function ChannelCard({ cd }: { cd: ChannelDraft }) {
  const { meta, text, imageUrl, imageReceived } = cd
  const body = text?.body || text?.preview || ''
  const title = text?.title && meta.id === 'blog' ? text.title : ''
  // Image received event but no URL → generation failed.
  const imageFailed = imageReceived && !imageUrl
  // Local override survives in this component instance even though the
  // store-derived imageUrl might re-arrive on later events. The override
  // wins so a user-initiated edit isn't clobbered by a stale event.
  const [editedUrl, setEditedUrl] = useState<string | null>(null)
  const [editMode, setEditMode] = useState<'inpaint' | 'sketch' | null>(null)
  const displayUrl = editedUrl ?? imageUrl
  const editAspect = snapEditAspect(meta.aspect)
  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
      style={{ borderLeftColor: meta.tint, borderLeftWidth: 3 }}
    >
      <header className="flex items-baseline justify-between border-b border-line-soft px-5 py-3">
        <div className="flex items-center gap-2">
          <span
            className="grid h-5 min-w-5 place-items-center rounded-md px-1.5 text-[10px] font-semibold tracking-tight text-white"
            style={{ background: meta.tint }}
          >
            {meta.glyph}
          </span>
          <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            {meta.label}
          </span>
          {meta.caption && (
            <span className="text-[11px] text-fg-dim">· {meta.caption}</span>
          )}
        </div>
        <span className="text-xs text-fg-dim">in your voice</span>
      </header>

      <div className="grid gap-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {displayUrl ? (
          <div
            className="group relative overflow-hidden border-b border-line-soft md:border-b-0 md:border-r"
            style={{ aspectRatio: aspectStyle(meta.aspect) }}
          >
            <img
              src={displayUrl}
              alt=""
              loading="eager"
              decoding="async"
              fetchPriority="high"
              className="block h-full w-full object-cover"
            />
            <EditOverlayButtons
              onInpaint={() => setEditMode('inpaint')}
              onSketch={() => setEditMode('sketch')}
            />
            {editMode === 'inpaint' && (
              <ImageEditModal
                mode="inpaint"
                open
                sourceUrl={displayUrl}
                aspect={editAspect}
                scope="channel"
                scopeId={meta.id}
                onClose={() => setEditMode(null)}
                onResult={(u) => setEditedUrl(u)}
              />
            )}
            {editMode === 'sketch' && (
              <ImageEditModal
                mode="sketch"
                open
                aspect={editAspect}
                scope="channel"
                scopeId={meta.id}
                onClose={() => setEditMode(null)}
                onResult={(u) => setEditedUrl(u)}
              />
            )}
          </div>
        ) : imageFailed ? (
          <div
            className="grid place-items-center border-b border-line-soft bg-bg-soft/40 px-4 text-center text-[11px] text-fg-mute md:border-b-0 md:border-r"
            style={{ aspectRatio: aspectStyle(meta.aspect) }}
          >
            <div>
              <div className="font-medium text-fg">Image unavailable</div>
              <div className="mt-1 text-fg-dim">
                Generation failed — check server logs (likely missing
                GEMINI_API_KEY or quota).
              </div>
            </div>
          </div>
        ) : text ? (
          <div
            className="grid place-items-center border-b border-line-soft bg-bg-soft/40 text-[11px] text-fg-dim md:border-b-0 md:border-r"
            style={{ aspectRatio: aspectStyle(meta.aspect) }}
          >
            <span className="animate-pulse">generating image…</span>
          </div>
        ) : null}
        <div className="px-5 py-4">
          {title && (
            <h3 className="mb-3 font-serif text-2xl leading-tight tracking-tight">
              {title}
            </h3>
          )}
          {body ? (
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-fg">
              {body}
            </p>
          ) : (
            <p className="animate-pulse text-[11px] text-fg-dim">
              drafting {meta.textKind}…
            </p>
          )}
        </div>
      </div>
    </motion.article>
  )
}

function UserPrompt({ text }: { text: string }) {
  return (
    <div className="rounded-2xl border border-line bg-bg-card px-5 py-4 shadow-[0_2px_10px_rgba(20,20,40,0.03)]">
      <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        You
      </div>
      <p className="mt-1.5 text-base leading-snug">{text}</p>
    </div>
  )
}

function Activity({
  steps,
  running,
  failed,
  error,
}: {
  steps: { id: string; label: string; at: string }[]
  running: boolean
  failed: boolean
  error: string | null
}) {
  return (
    <div className="mt-4 rounded-2xl border border-line bg-bg-card px-5 py-4 shadow-[0_2px_10px_rgba(20,20,40,0.03)]">
      <div className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
        <span className={running ? 'text-accent' : failed ? 'text-danger' : 'text-success'}>
          {running ? '◐' : failed ? '✕' : '●'}
        </span>
        <span>agent</span>
        {running && (
          <span className="text-fg-dim">· working in front of you</span>
        )}
        {failed && error && (
          <span className="text-danger">· {error.slice(0, 80)}</span>
        )}
      </div>
      <ul className="mt-3 max-h-56 space-y-1.5 overflow-y-auto overscroll-contain pr-1 font-mono text-[11px] leading-relaxed [scrollbar-width:thin]">
        <AnimatePresence initial={false}>
          {steps.map((s) => (
            <motion.li
              key={s.id}
              initial={{ opacity: 0, x: -4 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.25 }}
              className="flex gap-3"
            >
              <span className="tabular-nums text-fg-dim">{s.at}</span>
              <span className="text-fg-mute">{s.label}</span>
            </motion.li>
          ))}
        </AnimatePresence>
        {running && (
          <li className="flex gap-3 text-fg-dim">
            <span className="tabular-nums">·</span>
            <span className="animate-pulse">_</span>
          </li>
        )}
      </ul>
    </div>
  )
}

function HeroCard({ src }: { src: string }) {
  const [editedUrl, setEditedUrl] = useState<string | null>(null)
  const [editMode, setEditMode] = useState<'inpaint' | 'sketch' | null>(null)
  const displayUrl = editedUrl ?? src
  return (
    <motion.figure
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.5 }}
      className="overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
    >
      <header className="flex items-baseline justify-between border-b border-line-soft px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-accent" />
          <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Hero image
          </span>
        </div>
        <span className="text-xs text-fg-dim">conditioned on your palette + identity</span>
      </header>
      <div className="group relative">
        <img
          src={displayUrl}
          alt=""
          loading="eager"
          decoding="async"
          fetchPriority="high"
          className="block w-full"
        />
        <EditOverlayButtons
          onInpaint={() => setEditMode('inpaint')}
          onSketch={() => setEditMode('sketch')}
        />
      </div>
      {editMode === 'inpaint' && (
        <ImageEditModal
          mode="inpaint"
          open
          sourceUrl={displayUrl}
          aspect="16:9"
          scope="hero"
          scopeId={null}
          onClose={() => setEditMode(null)}
          onResult={(u) => setEditedUrl(u)}
        />
      )}
      {editMode === 'sketch' && (
        <ImageEditModal
          mode="sketch"
          open
          aspect="16:9"
          scope="hero"
          scopeId={null}
          onClose={() => setEditMode(null)}
          onResult={(u) => setEditedUrl(u)}
        />
      )}
    </motion.figure>
  )
}

function LiftCard({ lift }: { lift: LiftPrediction }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="rounded-2xl border border-line bg-accent-soft/40 px-5 py-4 shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
    >
      <div className="flex items-baseline gap-3">
        <div className="font-serif text-4xl tracking-tight text-accent">
          +{lift.lift_percent}%
        </div>
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
          predicted AI-search lift · {lift.confidence}
        </div>
      </div>
      {lift.factors.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-fg-mute">
          {lift.factors.map((f) => (
            <li key={f}>· {f}</li>
          ))}
        </ul>
      )}
      {lift.target_prompts.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {lift.target_prompts.map((p) => (
            <span
              key={p}
              className="rounded-full border border-accent/30 bg-bg-card px-2.5 py-1 text-[11px] text-fg-mute"
            >
              {p}
            </span>
          ))}
        </div>
      )}
      <div className="mt-3 text-[10px] uppercase tracking-[0.18em] text-fg-dim">
        {lift.research_basis}
      </div>
    </motion.div>
  )
}

function PeecCard({
  snapshot,
  targets,
}: {
  snapshot: PeecSnapshot
  targets: PeecTarget[]
}) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_10px_rgba(20,20,40,0.03)]"
    >
      <header className="flex items-baseline justify-between border-b border-line-soft px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500" />
          <span className="text-[11px] font-medium uppercase tracking-[0.18em] text-fg-mute">
            Peec visibility · live
          </span>
        </div>
        <span className="text-xs text-fg-dim">
          {snapshot.fetched_at?.slice(11, 19)} · the data layer Profound + HubSpot pay enterprise prices for
        </span>
      </header>
      <div className="grid grid-cols-3 gap-4 px-5 py-4">
        <Stat
          value={
            snapshot.visibility != null
              ? `${snapshot.visibility.toFixed(1)}%`
              : '—'
          }
          label="overall visibility"
        />
        <Stat
          value={
            snapshot.share_of_voice != null
              ? `${snapshot.share_of_voice.toFixed(1)}%`
              : '—'
          }
          label="share of voice"
        />
        <Stat
          value={
            snapshot.sentiment != null
              ? snapshot.sentiment.toFixed(2)
              : '—'
          }
          label="sentiment (-1 → +1)"
        />
      </div>
      {targets.length > 0 && (
        <div className="border-t border-line-soft px-5 py-4">
          <div className="text-[10px] font-medium uppercase tracking-[0.22em] text-fg-mute">
            Target prompts (where competitors win, you can break in)
          </div>
          <ul className="mt-3 space-y-2">
            {targets.map((t) => (
              <li
                key={t.prompt}
                className="flex items-center justify-between gap-3 rounded-md bg-bg-soft/60 px-3 py-2"
              >
                <span className="truncate text-sm">{t.prompt}</span>
                {t.competitor_winning && (
                  <span className="shrink-0 rounded-full bg-bg-card px-2 py-0.5 text-[10px] uppercase tracking-wider text-fg-mute">
                    {t.competitor_winning} winning
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {snapshot.cited_domains.length > 0 && (
        <div className="border-t border-line-soft px-5 py-4">
          <div className="text-[10px] font-medium uppercase tracking-[0.22em] text-fg-mute">
            Sources LLMs cite for your prompts
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {snapshot.cited_domains.slice(0, 8).map((d) => (
              <span
                key={d.domain}
                className="rounded-full border border-line bg-bg-card px-2.5 py-1 text-[11px] text-fg-mute"
              >
                {d.domain}
              </span>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  )
}

function PeecUnavailableCard({ reason }: { reason: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-bg-card px-5 py-3 text-xs text-fg-mute">
      <span className="font-medium text-fg">Peec offline</span> · {reason} · agent is using a heuristic fallback for target prompts
    </div>
  )
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <div className="font-serif text-3xl tracking-tight">{value}</div>
      <div className="mt-1 text-[10px] uppercase tracking-[0.18em] text-fg-mute">
        {label}
      </div>
    </div>
  )
}

function CampaignReady({
  title,
  bundle,
}: {
  title: string
  bundle: CampaignBundleShape
}) {
  const [toast, setToast] = useState<string | null>(null)
  const [copiedButton, setCopiedButton] = useState<string | null>(null)

  function flash(msg: string) {
    setToast(msg)
    window.setTimeout(() => setToast(null), 1800)
  }

  async function copyAll() {
    const drafts = bundle.drafts ?? []
    const lines: string[] = [`📣 ${title}`, '']
    for (const d of drafts) {
      lines.push(`— ${d.label} —`)
      lines.push(d.body || '(empty)')
      if (d.image_url) lines.push(`(image: ${d.image_url})`)
      lines.push('')
    }
    try {
      await navigator.clipboard.writeText(lines.join('\n').trim())
      flash('copied to clipboard')
      setCopiedButton('copy')
      window.setTimeout(() => setCopiedButton(null), 1500)
    } catch {
      flash('clipboard blocked — select manually')
    }
  }

  function shipToSlack() {
    // V1 demo behaviour: copy a Slack-ready summary to clipboard so the user
    // can paste it into a channel. Wiring a real Slack webhook would require
    // workspace OAuth — out of scope for the hackathon demo.
    const drafts = bundle.drafts ?? []
    const lines = [
      `*Campaign ready — ${title}*`,
      ...drafts.map(
        (d) =>
          `*${d.label}:* ${d.body.slice(0, 240)}${d.body.length > 240 ? '…' : ''}`,
      ),
    ]
    navigator.clipboard
      .writeText(lines.join('\n'))
      .then(() => {
        flash('Slack-ready post copied')
        setCopiedButton('slack')
        window.setTimeout(() => setCopiedButton(null), 1500)
      })
      .catch(() => flash('clipboard blocked'))
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45 }}
      className="relative mt-5 flex items-center justify-between rounded-2xl border border-accent/30 bg-bg-card px-5 py-4"
    >
      <div>
        <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-accent">
          ✓ Campaign ready
        </div>
        <div className="mt-1 truncate text-base font-medium">{title}</div>
      </div>
      <div className="flex gap-2">
        <button
          onClick={copyAll}
          className="rounded-full border border-line bg-bg-card px-4 py-2 text-xs text-fg-mute hover:border-accent hover:text-accent"
        >
          {copiedButton === 'copy' ? '✓ Copied' : 'Copy all'}
        </button>
        <button
          onClick={shipToSlack}
          className="rounded-full bg-accent px-5 py-2 text-xs font-medium text-white shadow-[0_3px_10px_rgba(111,92,255,0.35)] hover:brightness-110"
        >
          {copiedButton === 'slack' ? '✓ Slack-ready copied' : 'Ship to Slack'}
        </button>
      </div>
      <AnimatePresence>
        {toast && (
          <motion.div
            key={toast}
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            className="pointer-events-none absolute -top-9 right-0 rounded-md bg-fg/90 px-2.5 py-1 text-[10px] uppercase tracking-[0.18em] text-bg"
          >
            {toast}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
