import { type ReactNode, useEffect } from 'react'
import { motion, AnimatePresence } from 'motion/react'
import { useOnboardingStore, reconcileFromStatus } from '../stores/onboardingStore'
import { useResearchStore } from '../stores/researchStore'
import { InitialsAvatar } from '../components/InitialsAvatar'
import { IdentityCard } from './IdentityCard'
import { ResearchCard } from '../components/ResearchCard'
import type {
  CompetitorSuggestion,
  Post,
  PostPlatform,
  ReferenceBrand,
  StyleProfile,
  VoiceProfile,
} from '../events/bus'

type ScrapedSnapshot = NonNullable<
  ReturnType<typeof useOnboardingStore.getState>['scraped']
>
type ActivityEntry = ReturnType<
  typeof useOnboardingStore.getState
>['activity'][number]
type EnrichedCompetitor = CompetitorSuggestion & { logo_url?: string | null }

export function StepReading({ onAdvance }: { onAdvance: () => void }) {
  // On mount, hydrate store from DB in case SSE events fired before this
  // panel was visible (e.g. user lingered on step 02, or SSE reconnected).
  useEffect(() => {
    reconcileFromStatus().catch(() => {/* non-fatal */})
    // Same idea for research — pull persisted brand research so the card
    // is populated even if research.completed fired before mount.
    fetch('/api/research/me')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { brand_id: string | null; research: Record<string, unknown> } | null) => {
        if (!d?.research || Object.keys(d.research).length === 0) return
        useResearchStore.getState().hydrateBrand({
          fetched_at: (d.research.fetched_at as string) ?? '',
          sources: (d.research.sources as never) ?? [],
          answer: (d.research.answer as string | null) ?? null,
          error: (d.research.error as string | null) ?? null,
          brand_id: d.brand_id ?? undefined,
        })
      })
      .catch(() => {/* non-fatal */})
  }, [])

  const scraped = useOnboardingStore((s) => s.scraped)
  const voice = useOnboardingStore((s) => s.voice)
  const competitors = useOnboardingStore((s) => s.competitors)
  const activity = useOnboardingStore((s) => s.activity)
  const posts = useOnboardingStore((s) => s.posts)
  const postsReceived = useOnboardingStore((s) => s.posts_received)
  const identity = useOnboardingStore((s) => s.identity)
  const style = useOnboardingStore((s) => s.style)
  const references = useOnboardingStore((s) => s.references)

  const ready = !!scraped && !!voice && competitors.length > 0

  return (
    <div className="flex flex-col">
      <div className="grid grid-cols-12 gap-5 px-10 py-8">
        <aside className="col-span-12 flex flex-col gap-5 md:col-span-4">
          <Card>
            <CardLabel
              icon={ready ? '●' : '◐'}
              accent={!ready}
              label="activity"
            />
            <ActivityFeed activity={activity} ready={ready} />
          </Card>
          {scraped &&
            (scraped.palette_roles.length > 0 ||
              scraped.palette.length > 0) && (
              <Card>
                <CardLabel label="palette" />
                <PaletteList
                  entries={scraped.palette_roles}
                  flat={scraped.palette}
                  themeColor={scraped.theme_color}
                />
              </Card>
            )}
        </aside>

        <main className="col-span-12 flex flex-col gap-5 md:col-span-8">
          <Card>
            <CardLabel num="01" label="Identity" />
            {scraped ? <BrandHero scraped={scraped} /> : <SkeletonHero />}
          </Card>

          <Card tone="accent">
            <CardLabel num="02" label="Voice" tone="accent" />
            {voice ? <VoiceBlock voice={voice} /> : <SkeletonText />}
          </Card>

          {scraped && scraped.screenshots.length > 0 && (
            <Card>
              <CardLabel num="03" label="Pages we read" />
              <ScreenshotStack screenshots={scraped.screenshots} />
            </Card>
          )}
        </main>
      </div>

      <div className="px-10 pb-8">
        <Card>
          <CardLabel num="04" label="Competitive field" />
          {competitors.length === 0 ? (
            <p className="mt-4 text-sm text-fg-mute">scoping…</p>
          ) : (
            <CompetitorRow competitors={competitors} />
          )}
        </Card>
      </div>

      <div className="px-10 pb-8">
        <ResearchCard scope="brand" title="Live web research" max={10} />
      </div>

      <div className="px-10 pb-8">
        <Card>
          <CardLabel num="05" label="Recent posts" />
          {posts.length > 0 ? (
            <PostsRow posts={posts} />
          ) : postsReceived ? (
            <p className="mt-4 text-sm text-fg-mute">
              No public posts found across the connected handles. Add posts in
              Step 03 (Review) or paste a few of your best ones in Step 01.
            </p>
          ) : (
            <SkeletonPosts />
          )}
        </Card>
      </div>

      {identity && (
        <div className="px-10 pb-8">
          <Card>
            <CardLabel num="06" label="Identity — how it looks" />
            <IdentityCard identity={identity} paletteRoles={scraped?.palette_roles ?? []} />
          </Card>
        </div>
      )}

      {style && (
        <div className="px-10 pb-8">
          <Card tone="accent">
            <CardLabel num="07" label="Visual style" tone="accent" />
            <StyleHero style={style} />
          </Card>
        </div>
      )}

      {references.length > 0 && (
        <div className="px-10 pb-10">
          <Card>
            <CardLabel num="07" label="Reference brands" />
            <ReferenceRow references={references} />
          </Card>
        </div>
      )}

      <div className="sticky bottom-0 flex items-center justify-between border-t border-line bg-bg-card/85 px-10 py-4 backdrop-blur">
        <p className="text-xs text-fg-mute">
          {ready ? (
            <span className="flex items-center gap-2">
              <span className="text-success">●</span> reading complete
            </span>
          ) : (
            <span className="flex items-center gap-2">
              <span className="text-accent">◐</span> still reading…
            </span>
          )}
        </p>
        <button
          onClick={onAdvance}
          disabled={!ready}
          className="rounded-full bg-accent px-6 py-2.5 text-sm font-medium text-white shadow-[0_4px_14px_rgba(111,92,255,0.4)] transition hover:brightness-110 disabled:bg-accent-dim disabled:shadow-none"
        >
          Continue → Review
        </button>
      </div>
    </div>
  )
}

function Card({
  tone,
  children,
}: {
  tone?: 'accent'
  children: ReactNode
}) {
  const cls =
    tone === 'accent'
      ? 'bg-accent-soft/40 border-accent-soft'
      : 'bg-bg-card border-line'
  return (
    <section
      className={`rounded-2xl border ${cls} p-6 shadow-[0_2px_12px_rgba(20,20,40,0.03)]`}
    >
      {children}
    </section>
  )
}

function CardLabel({
  num,
  label,
  icon,
  accent,
  tone,
}: {
  num?: string
  label: string
  icon?: string
  accent?: boolean
  tone?: 'accent'
}) {
  return (
    <div className="flex items-center gap-3 text-[11px] font-medium uppercase tracking-[0.2em] text-fg-mute">
      {num && (
        <span
          className={`tabular-nums ${tone === 'accent' ? 'text-accent' : 'text-fg-dim'}`}
        >
          {num}
        </span>
      )}
      {icon && (
        <span className={accent ? 'text-accent' : 'text-fg-mute'}>{icon}</span>
      )}
      <span>{label}</span>
    </div>
  )
}

function ActivityFeed({
  activity,
  ready,
}: {
  activity: ActivityEntry[]
  ready: boolean
}) {
  return (
    <ul className="mt-4 space-y-1.5 font-mono text-[11px] leading-relaxed">
      <AnimatePresence initial={false}>
        {activity.map((a) => (
          <motion.li
            key={a.id}
            initial={{ opacity: 0, y: -3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="flex gap-3"
          >
            <span className="tabular-nums text-fg-dim">{a.at}</span>
            <span
              className={
                a.kind === 'done'
                  ? 'text-fg'
                  : a.kind === 'fail'
                    ? 'text-danger'
                    : 'text-fg-mute'
              }
            >
              {a.label}
            </span>
          </motion.li>
        ))}
      </AnimatePresence>
      {!ready && (
        <li className="flex gap-3 text-fg-dim">
          <span className="tabular-nums">·</span>
          <span className="animate-pulse">_</span>
        </li>
      )}
    </ul>
  )
}

const ROLE_LABELS: Record<string, string> = {
  background: 'Background',
  primary: 'Primary',
  secondary: 'Secondary',
  text: 'Text',
  link: 'Link',
  surface: 'Surface',
  ornament: 'Ornament',
}

const ROLE_USAGE: Record<string, string> = {
  background: 'page canvas — most-used surface',
  primary: 'CTA button background',
  secondary: 'second-tier button background',
  text: 'body copy + headings',
  link: 'inline links + interactive text',
  surface: 'header / nav / cards',
  ornament: 'imagery accent (decorative)',
}

const ROLE_ORDER: Record<string, number> = {
  background: 0,
  primary: 1,
  secondary: 2,
  link: 3,
  text: 4,
  surface: 5,
  ornament: 6,
}

type PaletteEntryT = { hex: string; role: string }

function PaletteList({
  entries,
  flat,
  themeColor,
}: {
  entries: PaletteEntryT[]
  flat: string[]
  themeColor: string | null
}) {
  const list: PaletteEntryT[] =
    entries.length > 0
      ? [...entries].sort(
          (a, b) =>
            (ROLE_ORDER[a.role] ?? 99) - (ROLE_ORDER[b.role] ?? 99),
        )
      : flat.map((hex) => ({ hex, role: 'ornament' }))

  const themeMatches =
    themeColor &&
    list.some((e) => e.hex.toLowerCase() === themeColor.toLowerCase())

  return (
    <ul className="mt-4 flex flex-col gap-2">
      {list.map((e, i) => {
        const isThemePrimary =
          themeColor &&
          e.hex.toLowerCase() === themeColor.toLowerCase() &&
          themeMatches
        return (
          <li key={e.hex + i} className="flex items-center gap-3">
            <span
              className="h-9 w-9 shrink-0 rounded-md border border-line"
              style={{ background: e.hex }}
              title={`${e.hex} · ${ROLE_USAGE[e.role] ?? e.role}`}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-medium text-fg">
                  {ROLE_LABELS[e.role] ?? e.role}
                </span>
                {isThemePrimary && (
                  <span className="rounded-full bg-accent-soft px-1.5 py-px text-[9px] font-medium uppercase tracking-wider text-accent">
                    declared
                  </span>
                )}
              </div>
              <div className="font-mono text-[10px] uppercase tabular-nums tracking-wider text-fg-mute">
                {e.hex}
              </div>
              <div className="text-[10px] leading-tight text-fg-dim">
                {ROLE_USAGE[e.role] ?? ''}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function BrandHero({ scraped }: { scraped: ScrapedSnapshot }) {
  return (
    <div className="mt-5 flex items-start gap-5">
      {scraped.logo_url ? (
        <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl bg-[#f5f1e8] p-3">
          <img
            src={scraped.logo_url}
            alt=""
            className="max-h-full max-w-full object-contain"
          />
        </div>
      ) : (
        <InitialsAvatar name={scraped.title || 'Brand'} size="lg" />
      )}
      <div className="min-w-0 flex-1">
        <h2 className="text-3xl font-medium leading-tight tracking-tight">
          {scraped.title || 'Your brand'}
        </h2>
        {scraped.description && (
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-mute">
            {scraped.description}
          </p>
        )}
        {Object.keys(scraped.handles).length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(scraped.handles).map(([k, v]) => (
              <a
                key={k}
                href={v}
                target="_blank"
                rel="noreferrer"
                className="rounded-full border border-line bg-bg-soft px-3 py-1 text-[11px] text-fg-mute transition hover:border-accent hover:text-accent"
              >
                {k} ↗
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function VoiceBlock({ voice }: { voice: VoiceProfile }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="mt-4 grid grid-cols-12 gap-5"
    >
      <div className="col-span-12 lg:col-span-7">
        <div className="relative">
          <span
            aria-hidden
            className="pointer-events-none absolute -left-2 -top-6 select-none font-serif text-[88px] leading-none text-accent/30"
            style={{ fontVariationSettings: '"opsz" 144' }}
          >
            “
          </span>
          <blockquote
            className="relative font-serif text-2xl italic leading-[1.3] tracking-tight text-fg"
            style={{ fontVariationSettings: '"opsz" 144, "SOFT" 60' }}
          >
            {voice.voice_excerpt}
          </blockquote>
        </div>
        <p className="mt-5 text-sm leading-relaxed text-fg-mute">
          {voice.tone}
        </p>
      </div>

      <div className="col-span-12 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:col-span-5 lg:grid-cols-1">
        <div>
          <h4 className="text-[10px] font-medium uppercase tracking-[0.2em] text-fg-mute">
            Recurring phrases
          </h4>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {voice.recurring_phrases.map((p) => (
              <li
                key={p}
                className="rounded-full border border-accent-soft bg-bg-card px-2.5 py-1 text-[11px] text-fg-mute"
              >
                {p}
              </li>
            ))}
          </ul>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <h4 className="text-[10px] font-medium uppercase tracking-[0.2em] text-success">
              Do
            </h4>
            <ul className="mt-3 space-y-1.5 text-xs text-fg-mute">
              {voice.do.map((d) => (
                <li key={d} className="flex gap-2">
                  <span className="text-success">+</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4 className="text-[10px] font-medium uppercase tracking-[0.2em] text-danger">
              Don't
            </h4>
            <ul className="mt-3 space-y-1.5 text-xs text-fg-mute">
              {voice.dont.map((d) => (
                <li key={d} className="flex gap-2">
                  <span className="text-danger">−</span>
                  <span>{d}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </motion.div>
  )
}

function ScreenshotStack({ screenshots }: { screenshots: string[] }) {
  return (
    <ol className="mt-5 grid grid-cols-2 gap-3">
      {screenshots.map((src, i) => (
        <motion.li
          key={src + i}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.45,
            delay: i * 0.06,
            ease: [0.16, 1, 0.3, 1],
          }}
          className="relative overflow-hidden rounded-xl border border-line bg-bg-soft"
        >
          <span className="absolute right-2 top-2 z-10 rounded-md bg-bg-card/85 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-fg-mute backdrop-blur">
            {String(i + 1).padStart(2, '0')}
          </span>
          <img src={src} alt="" className="block w-full" />
        </motion.li>
      ))}
    </ol>
  )
}

function CompetitorRow({
  competitors,
}: {
  competitors: EnrichedCompetitor[]
}) {
  return (
    <ul className="mt-6 grid grid-cols-1 gap-x-6 gap-y-6 sm:grid-cols-2 lg:grid-cols-5">
      {competitors.map((c, i) => (
        <motion.li
          key={c.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: i * 0.05 }}
          className="flex gap-3"
        >
          {c.logo_url ? (
            <div
              className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-[#f5f1e8] p-1.5"
              style={{
                filter:
                  'drop-shadow(0 1px 1px rgba(20,20,40,0.06))',
              }}
            >
              <img
                src={c.logo_url}
                alt=""
                className="max-h-full max-w-full object-contain"
              />
            </div>
          ) : (
            <InitialsAvatar name={c.name} size="md" />
          )}
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-medium leading-tight">{c.name}</h3>
            {c.reason && (
              <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-fg-mute">
                {c.reason}
              </p>
            )}
          </div>
        </motion.li>
      ))}
    </ul>
  )
}

function PostsRow({ posts }: { posts: Post[] }) {
  return (
    <div className="-mx-6 mt-5 overflow-x-auto px-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      <ul className="flex snap-x snap-mandatory gap-4 pb-2">
        {posts.map((p, i) => (
          <PostCard key={(p.url ?? p.caption) + i} post={p} index={i} />
        ))}
      </ul>
    </div>
  )
}

function PostCard({ post, index }: { post: Post; index: number }) {
  const thumb = post.media_urls[0]
  const platformLabel = post.platform.toUpperCase()
  return (
    <motion.li
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.4,
        delay: index * 0.04,
        ease: [0.16, 1, 0.3, 1],
      }}
      className="flex w-[240px] shrink-0 snap-start flex-col overflow-hidden rounded-2xl border border-line bg-bg-card shadow-[0_2px_12px_rgba(20,20,40,0.03)]"
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-bg-soft">
        {thumb ? (
          <img
            src={thumb}
            alt=""
            className="h-full w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="grid h-full w-full place-items-center text-fg-dim">
            <span className="font-mono text-[10px] uppercase tracking-[0.2em]">
              no media
            </span>
          </div>
        )}
        <span
          className={`absolute left-3 top-3 rounded-md px-2 py-0.5 font-mono text-[10px] uppercase tracking-[0.2em] ${platformBadge(post.platform)}`}
        >
          {platformLabel}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-2 px-4 py-3">
        <p className="line-clamp-2 text-xs leading-relaxed text-fg">
          {post.caption || 'no caption'}
        </p>
        {post.video_analysis && (
          <div className="rounded-md border border-line bg-bg-soft/60 px-2 py-1.5 text-[10px] leading-relaxed text-fg-mute">
            <div className="mb-1 flex items-center gap-1.5 text-fg-dim">
              <span>▸</span>
              <span className="uppercase tracking-[0.16em]">
                video transcript
                {post.video_analysis.duration_seconds != null && (
                  <span> · {Math.round(post.video_analysis.duration_seconds)}s</span>
                )}
              </span>
            </div>
            <p className="line-clamp-3">
              {post.video_analysis.content_summary ||
                post.video_analysis.visual_summary ||
                post.video_analysis.transcript.slice(0, 160)}
            </p>
          </div>
        )}
        <div className="mt-auto flex items-center justify-between text-[10px] text-fg-dim">
          <span className="tabular-nums">
            {post.posted_at ? formatDate(post.posted_at) : '—'}
          </span>
          {post.url && (
            <a
              href={post.url}
              target="_blank"
              rel="noreferrer"
              className="hover:text-accent"
            >
              open ↗
            </a>
          )}
        </div>
      </div>
    </motion.li>
  )
}

function platformBadge(p: PostPlatform): string {
  switch (p) {
    case 'youtube':
      return 'bg-danger/10 text-danger'
    case 'instagram':
      return 'bg-warn/10 text-warn'
    case 'tiktok':
      return 'bg-fg/10 text-fg'
    case 'linkedin':
      return 'bg-accent-soft text-accent'
    case 'x':
      return 'bg-bg-soft text-fg'
    default:
      return 'bg-bg-soft text-fg-mute'
  }
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return iso.slice(0, 10)
    return d.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
    })
  } catch {
    return iso.slice(0, 10)
  }
}

function StyleHero({ style }: { style: StyleProfile }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="mt-4 grid grid-cols-12 gap-6"
    >
      <div className="col-span-12 lg:col-span-7">
        <p
          className="font-serif text-2xl italic leading-[1.3] tracking-tight text-fg"
          style={{ fontVariationSettings: '"opsz" 144, "SOFT" 60' }}
        >
          {style.mood}
        </p>
        {style.palette_character && (
          <p className="mt-4 text-sm leading-relaxed text-fg-mute">
            {style.palette_character}
          </p>
        )}
        {style.distinctive_marks.length > 0 && (
          <div className="mt-6">
            <h4 className="text-[10px] font-medium uppercase tracking-[0.2em] text-fg-mute">
              Distinctive marks
            </h4>
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {style.distinctive_marks.map((m) => (
                <li
                  key={m}
                  className="rounded-full border border-accent/40 bg-bg-card px-2.5 py-1 text-[11px] text-accent"
                >
                  {m}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <div className="col-span-12 flex flex-col gap-5 lg:col-span-5">
        <StyleField label="Composition" value={style.composition} />
        <StyleField label="Typography" value={style.typography_feel} />
        <StyleField
          label="Photo vs. illustrated"
          value={style.photographic_vs_illustrated}
        />
        {style.generation_guidance.length > 0 && (
          <div>
            <h4 className="text-[10px] font-medium uppercase tracking-[0.2em] text-success">
              Do
            </h4>
            <ul className="mt-3 space-y-1.5 text-xs text-fg-mute">
              {style.generation_guidance.map((g) => (
                <li key={g} className="flex gap-2">
                  <span className="text-success">+</span>
                  <span>{g}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </motion.div>
  )
}

function StyleField({ label, value }: { label: string; value: string }) {
  if (!value) return null
  return (
    <div>
      <h4 className="text-[10px] font-medium uppercase tracking-[0.2em] text-fg-mute">
        {label}
      </h4>
      <p className="mt-1.5 text-sm leading-relaxed text-fg">{value}</p>
    </div>
  )
}

function ReferenceRow({ references }: { references: ReferenceBrand[] }) {
  return (
    <ul className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {references.map((r, i) => (
        <motion.li
          key={r.id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: i * 0.05 }}
          className="flex flex-col gap-3 rounded-2xl border border-line bg-bg-card p-4"
        >
          <div className="flex items-center gap-3">
            {r.logo_url ? (
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#f5f1e8] p-1.5">
                <img
                  src={r.logo_url}
                  alt=""
                  className="max-h-full max-w-full object-contain"
                />
              </div>
            ) : (
              <InitialsAvatar name={r.name} size="md" />
            )}
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium leading-tight">
                {r.name}
              </div>
              <div className="mt-0.5 truncate font-mono text-[10px] uppercase tracking-wider text-fg-mute">
                {stripScheme(r.url)}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-1">
            {r.palette.slice(0, 6).map((c, j) => (
              <span
                key={c + j}
                className="h-5 w-5 rounded-md border border-line"
                style={{ background: c }}
              />
            ))}
          </div>
          {r.screenshot_urls?.[0] && (
            <div className="aspect-video w-full overflow-hidden rounded-lg border border-line bg-bg-soft">
              <img
                src={r.screenshot_urls[0]}
                alt=""
                className="h-full w-full object-cover"
                loading="lazy"
              />
            </div>
          )}
        </motion.li>
      ))}
    </ul>
  )
}

function SkeletonHero() {
  return (
    <div className="mt-5 flex items-start gap-5">
      <div className="h-20 w-20 shrink-0 animate-pulse rounded-2xl bg-bg-soft" />
      <div className="flex flex-1 flex-col gap-3 pt-1">
        <div className="h-7 w-3/4 animate-pulse rounded-md bg-bg-soft" />
        <div className="h-4 w-1/2 animate-pulse rounded-md bg-bg-soft" />
      </div>
    </div>
  )
}

function SkeletonText() {
  return (
    <div className="mt-5 space-y-3">
      <div className="h-7 w-4/5 animate-pulse rounded-md bg-bg-card" />
      <div className="h-7 w-3/5 animate-pulse rounded-md bg-bg-card" />
    </div>
  )
}

function SkeletonPosts() {
  return (
    <div className="-mx-6 mt-5 overflow-hidden px-6">
      <ul className="flex gap-4 pb-2">
        {[0, 1, 2, 3].map((i) => (
          <li
            key={i}
            className="w-[240px] shrink-0 overflow-hidden rounded-2xl border border-line bg-bg-card"
          >
            <div className="aspect-[4/3] w-full animate-pulse bg-bg-soft" />
            <div className="flex flex-col gap-2 px-4 py-3">
              <div className="h-3 w-4/5 animate-pulse rounded bg-bg-soft" />
              <div className="h-3 w-2/3 animate-pulse rounded bg-bg-soft" />
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}

function stripScheme(u: string): string {
  return u.replace(/^https?:\/\//, '').replace(/\/$/, '')
}
