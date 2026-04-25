import type { Identity, PaletteEntry } from '../events/bus'

export function IdentityCard({
  identity,
  paletteRoles,
}: {
  identity: Identity
  paletteRoles?: PaletteEntry[]
}) {
  const t = identity.typography
  const r = identity.radii
  const shadows = identity.shadows ?? []
  const button = identity.buttons?.primary
  const tokens = identity.tokens

  return (
    <div className="mt-6 flex flex-col gap-7">
      {paletteRoles && paletteRoles.length > 0 && (
        <PaletteRoleSwatches roles={paletteRoles} />
      )}
      {t && <TypographySpecimens typography={t} />}
      {r && r.samples_px.length > 0 && <RadiiSamples radii={r} />}
      {shadows.length > 0 && <ShadowSpecimens shadows={shadows} />}
      {button && button.bg && <ButtonPreview button={button} />}
      {tokens && tokens.css_vars_total > 0 && (
        <TokenSummary tokens={tokens} />
      )}
    </div>
  )
}

function PaletteRoleSwatches({ roles }: { roles: PaletteEntry[] }) {
  // Group entries by role so the user sees "this hex is the primary, that's
  // the surface, this is just decorative ornament", not just an array of hexes.
  const grouped = new Map<string, string[]>()
  for (const e of roles) {
    if (!grouped.has(e.role)) grouped.set(e.role, [])
    grouped.get(e.role)!.push(e.hex)
  }
  // Stable role order — most load-bearing first.
  const ROLE_ORDER = [
    'primary',
    'secondary',
    'accent',
    'bg',
    'surface',
    'text',
    'link',
    'ornament',
  ]
  const ordered = ROLE_ORDER.filter((r) => grouped.has(r))
  return (
    <section>
      <SubLabel>Palette · role-tagged</SubLabel>
      <ul className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {ordered.map((role) => (
          <li
            key={role}
            className="flex flex-col gap-1.5 rounded-xl border border-line bg-bg-soft/40 p-3"
          >
            <div className="flex items-center gap-1.5">
              {grouped.get(role)!.slice(0, 4).map((hex, i) => (
                <span
                  key={hex + i}
                  className="h-6 w-6 rounded-md border border-line shadow-[inset_0_0_0_1px_rgba(255,255,255,0.5)]"
                  style={{ background: hex }}
                  title={hex}
                />
              ))}
            </div>
            <div className="text-[10px] uppercase tracking-[0.18em] text-fg-mute">
              {role}
            </div>
            <div className="font-mono text-[10px] text-fg-dim">
              {grouped.get(role)![0]}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function TypographySpecimens({
  typography: t,
}: {
  typography: NonNullable<Identity['typography']>
}) {
  const headlineFont = t.headline_font || t.body_font || 'inherit'
  const bodyFont = t.body_font || 'inherit'
  const monoFont = t.mono_font || 'monospace'
  return (
    <section>
      <SubLabel>Typography</SubLabel>
      <div className="mt-3 rounded-xl border border-line bg-bg-soft/40 p-6">
        <div
          className="leading-none tracking-tight text-fg"
          style={{
            fontFamily: headlineFont,
            fontSize: clamp(t.h1_size_px ?? 48, 28, 84),
            fontWeight: t.h1_weight ?? 700,
            lineHeight: t.h1_line_height ?? 1.1,
            letterSpacing: `${t.h1_letter_spacing_em ?? 0}em`,
          }}
        >
          The quick brown fox.
        </div>
        <p
          className="mt-4 max-w-prose text-fg-mute"
          style={{
            fontFamily: bodyFont,
            fontSize: t.body_size_px ?? 16,
            lineHeight: t.p_line_height ?? 1.55,
          }}
        >
          The five boxing wizards jump quickly. Pack my box with five dozen
          liquor jugs — this is the brand's body voice in its own type stack.
        </p>
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[10px] uppercase tracking-[0.18em] text-fg-dim">
          <span>headline · {t.headline_font_first ?? '—'}</span>
          <span>body · {t.body_font_first ?? '—'}</span>
          {t.mono_font_first && <span>mono · {t.mono_font_first}</span>}
          {t.h1_size_px && (
            <span>
              h1 · {Math.round(t.h1_size_px)}px / {t.h1_weight ?? '—'}
            </span>
          )}
        </div>
      </div>
      {monoFont && t.mono_font_first && (
        <div
          className="mt-2 rounded-md bg-bg-soft/60 px-3 py-2 text-[12px] text-fg-mute"
          style={{ fontFamily: monoFont }}
        >
          /* mono · monospace voice for code + technical labels */
        </div>
      )}
    </section>
  )
}

function RadiiSamples({
  radii,
}: {
  radii: NonNullable<Identity['radii']>
}) {
  const tiles: { label: string; px: number | null }[] = [
    { label: 'Small', px: radii.small_px },
    { label: 'Medium', px: radii.medium_px },
    { label: 'Large', px: radii.large_px },
    {
      label: 'Pill',
      px: radii.has_pill ? 9999 : null,
    },
  ]
  return (
    <section>
      <SubLabel>
        Corners
        {radii.dominant_px != null && (
          <span className="ml-2 text-fg-dim">
            · dominant {Math.round(radii.dominant_px)}px
          </span>
        )}
      </SubLabel>
      <ul className="mt-3 grid grid-cols-4 gap-3">
        {tiles.map((t) => (
          <li key={t.label} className="flex flex-col items-center gap-2">
            <div
              className="h-16 w-16 border border-line bg-accent-soft"
              style={{ borderRadius: t.px == null ? 0 : `${t.px}px` }}
            />
            <div className="text-center text-[10px] uppercase tracking-[0.18em] text-fg-mute">
              {t.label}
              {t.px != null && t.px < 999 && (
                <span className="ml-1 text-fg-dim">{Math.round(t.px)}px</span>
              )}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ShadowSpecimens({ shadows }: { shadows: string[] }) {
  return (
    <section>
      <SubLabel>Elevation</SubLabel>
      <ul className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
        {shadows.slice(0, 3).map((s, i) => (
          <li
            key={i}
            className="flex h-20 items-center justify-center rounded-lg border border-line bg-bg-card"
            style={{ boxShadow: s }}
          >
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-fg-dim">
              shadow {i + 1}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ButtonPreview({
  button,
}: {
  button: NonNullable<NonNullable<Identity['buttons']>['primary']>
}) {
  return (
    <section>
      <SubLabel>Primary CTA — rendered with captured tokens</SubLabel>
      <div className="mt-3 flex items-center gap-4 rounded-xl border border-line bg-bg-soft/40 p-6">
        <button
          type="button"
          style={{
            background: button.bg ?? undefined,
            color: button.fg ?? undefined,
            borderRadius:
              button.radius_px != null ? `${button.radius_px}px` : undefined,
            padding: button.padding ?? undefined,
            fontSize:
              button.font_size_px != null ? `${button.font_size_px}px` : undefined,
            fontWeight: button.font_weight ?? undefined,
            border: button.border ?? 'none',
            boxShadow: button.shadow ?? undefined,
          }}
          className="cursor-default whitespace-nowrap"
        >
          Get started
        </button>
        <div className="font-mono text-[10px] leading-relaxed text-fg-dim">
          {button.bg && <div>bg · {button.bg}</div>}
          {button.radius_px != null && (
            <div>
              radius · {button.radius_px >= 999 ? 'pill' : `${button.radius_px}px`}
            </div>
          )}
          {button.padding && <div>padding · {button.padding}</div>}
          {button.font_size_px != null && (
            <div>
              type · {button.font_size_px}px / {button.font_weight ?? '—'}
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

function TokenSummary({
  tokens,
}: {
  tokens: NonNullable<Identity['tokens']>
}) {
  return (
    <section>
      <SubLabel>Design tokens</SubLabel>
      <div className="mt-3 flex flex-wrap gap-4 text-[11px] text-fg-mute">
        <span>
          <strong className="text-fg">{tokens.css_vars_total}</strong> CSS
          custom properties on :root
        </span>
        {tokens.color_vars > 0 && (
          <span>
            <strong className="text-fg">{tokens.color_vars}</strong> color vars
          </span>
        )}
        {tokens.space_vars > 0 && (
          <span>
            <strong className="text-fg">{tokens.space_vars}</strong> spacing vars
          </span>
        )}
        {tokens.exposes_design_system && (
          <span className="rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent">
            exposes design system
          </span>
        )}
      </div>
    </section>
  )
}

function SubLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[10px] font-medium uppercase tracking-[0.22em] text-fg-mute">
      {children}
    </div>
  )
}

function clamp(v: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, v))
}
