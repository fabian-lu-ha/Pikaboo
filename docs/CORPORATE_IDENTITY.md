# Corporate Identity — Reading a Brand's Design System Off the Web

> *Status*: research + planning doc. Pairs with `DEEP_PALETTE.md` (color) — this doc covers everything else that constitutes a corporate identity.
> *Authors*: research-agent-A (web research), research-agent-B (codebase + schema). Ran as two background agents per the user's directive.
> *Audience*: hackathon team — what to extract, what schema to land in `Brand.identity`, and the smallest credible cut for Sun Apr 26.

The user's directive in plain language: *"create a corporate identity (design), research how to do so better in the web with 2 background agents."* Today the agent already extracts a logo, palette, voice, and a Gemini-vision style narrative. That's a *vibe*, not an identity. To render content that actually *looks like the brand* — landing-page sections, social posts, generated imagery — the agent needs the same artefact a senior designer would build on day-one of a brand engagement: a **design system snapshot** with concrete numbers (type sizes, spacing units, radii, shadows, motion durations) and concrete categorical labels (icon style, imagery direction, button vocabulary). This document is the spec for that snapshot.

The product principle: **the brand's homepage is its de-facto style guide, and a headless browser plus a 30-line `evaluate()` call can read more of it in under 2 seconds than a designer can in two hours.**

---

## 1. What a corporate identity / design system actually contains

The canonical breakdown — drawn from the public design systems we expect customers to mentally compare against. This is the inventory we measure ourselves against, not a wish-list.

### The token layer (atomic values)

| Category | Concrete sub-values | Reference systems |
|---|---|---|
| **Color** | Primary, secondary, accent, semantic (success/warn/danger/info), surfaces, text, borders. | Material 3 has 25+ semantic color roles; IBM Carbon splits "Layer", "Field", "Background", "Border" tokens. *(covered in `DEEP_PALETTE.md`)* |
| **Typography** | Font-family stacks (display / body / mono / serif). Scale (h1..h6 + body + small + caption + button + label) — each carries size, weight, line-height, letter-spacing. Often a **modular scale ratio** (1.125, 1.25, 1.333, 1.5, 1.618 = golden). | Carbon has *productive* + *expressive* sets that share a scale but differ in line-height density. Vercel Geist exposes 24+ named tokens (`text-heading-72` … `text-copy-13-mono`) — each pre-bakes size + leading + tracking + weight. Material 3 has *display / headline / title / body / label* × *large / medium / small*. |
| **Spacing** | A base unit (almost always 4 or 8 px) and a scale of multipliers. | Atlassian: `space.025` (2px) … `space.1000` (80px), 8px base with 4/2px half-steps. Material 3: 4dp grid. Tailwind: 4px base, exposed as `0.5`, `1`, `1.5`, `2` … `96`. |
| **Radii** | Small / medium / large / pill. Often linked to component size class. | Geist uses near-zero rounding (sharp corners). Polaris ships `radius-100` … `radius-500` + `radius-full`. Material 3 has shape tokens by component (`shape.corner.extra-small`, `extra-large`). |
| **Elevation / shadow** | A vocabulary of 3–6 shadows for surface depth (resting, raised, hover, modal, popover). | Material 3 has elevation 0–5; Carbon has `box-shadow-sm/md/lg/xl`. |
| **Borders** | Width tokens (1px / 2px), style (solid / dashed), color (often a specific neutral). | Atlassian "color.border", "color.border.bold". |
| **Motion** | Named **durations** (short / medium / long, often 100/200/300/500ms) + named **easings** (standard, emphasized, decelerate, accelerate as cubic-bezier curves) + spring presets. | Material 3 motion tokens: `motion.duration.short1=50ms` … `extra-long4=1000ms`; `motion.easing.emphasized = cubic-bezier(0.2, 0.0, 0.0, 1.0)`. |
| **Opacity** | Disabled (38–50%), hover overlay (8–12%), pressed overlay (12–16%). | Material 3 state-layer tokens. |
| **Iconography** | Stroke-width, fill style (filled / outlined / duotone / mixed), grid (16/20/24px), corner style (rounded vs square). | Lucide: 24×24 grid, 1.5px stroke, rounded caps. Phosphor: 24×24, 2px stroke, six weights. Heroicons: 1.5px stroke. |
| **Imagery direction** | Photography (lifestyle / editorial / product-on-white / journalistic) vs illustration (flat / iso / hand-drawn / 3D-render / gradient-meshy) vs hybrid. Treatment (high-contrast, duotone, soft-pastel, grainy). | Apple HIG: *photographic + symbolic* (SF Symbols). Stripe: *isometric illustration*. Linear: *3D rendered surfaces*. |
| **Layout / grid** | Container max-width, gutter, breakpoints, columns. | Bootstrap: 1140px container, 4 breakpoints. Geist: 1200px. Tailwind: 640/768/1024/1280/1536 breakpoints. |

### The component layer (composed values)

The token layer alone is not enough — design systems also fix the **component vocabulary** that's distinctive about the brand:

- **Buttons**: filled / outlined / ghost / link; pill vs rounded vs sharp; small/medium/large; with/without leading icon.
- **Inputs**: bordered box / underline-only / pill / floating-label.
- **Cards**: flat / outlined / shadow-raised; with/without media; with/without hover lift.
- **Navigation**: top-bar (sticky / transparent-on-hero), side-rail, bottom-tab.
- **Modals / sheets**: centred dialog vs bottom-sheet vs side-drawer.
- **Empty states / loading states**: skeletons vs spinners vs gradients vs typographic placeholders.

### The pattern + voice layer (already partially covered)

- **Voice / tone** — already extracted as `voice_profile` (tone, recurring phrases, do's, don'ts, voice excerpt).
- **Copy guidelines** — capitalization (sentence vs title case in headings, button labels), pluralization, oxford comma, em-dash habit. Partially in `voice_profile`, can be sharpened.
- **Logo system** — primary, favicon, apple-touch-icon. Already captured.

---

## 2. What we can actually extract from a rendered website

We render the brand's homepage with Playwright (Chromium, lifespan-managed, animation-killed via injected CSS) and have direct access to: the live DOM, `getComputedStyle()` of every node, `<style>` and `<link rel="stylesheet">` content, `document.fonts`, the network log, and N viewport screenshots. That's a stronger signal source than any static-CSS scraper. The state-of-the-art today (Dembrandt, design-extract by designlang, Project Wallace, Superposition, Brand.dev, Brandfetch) is built on exactly this foundation. Each axis below names the concrete things we go after.

### 2.1 Typography

**What's reachable:**
- `font-family` from `getComputedStyle(el)` for `h1, h2, h3, h4, h5, h6, p, blockquote, button, [class*="display" i], [class*="headline" i], [class*="lead" i], [class*="caption" i], code, pre, kbd, samp, [data-mono]`. Crucially we read what the browser **actually rendered**, not what's authored — DevTools' Computed panel exposes this and we can do the same via `parentNode.style.fontFamily` after a `font-display:swap` resolution.
- The actual loaded face: `document.fonts` exposes a `FontFaceSet` whose entries have `.family`, `.weight`, `.style`, `.status === 'loaded'`. We compare the first family name in the computed `font-family` stack against the loaded set to decide whether the brand uses a webfont vs a system stack.
- Detect **Google Fonts** by inspecting `<link href*="fonts.googleapis.com">` (a stable signature; the URL also encodes weights + subsets). Detect **Adobe Fonts/Typekit** by `<link href*="use.typekit.net">`. Detect **self-hosted custom fonts** by walking `document.fonts` for entries whose `family` doesn't appear in any `link[rel=stylesheet][href]` from a known CDN.
- **Type scale** — sample N elements per role, take the **mode** size and line-height. From `font-size` of `h1..h6 + body`, infer the **modular ratio** by checking whether the ratios `h1/h2`, `h2/h3`, `h3/h4` fit one of the well-known constants (1.125 minor-second, 1.2 minor-third, 1.25 major-third, 1.333 perfect-fourth, 1.5 perfect-fifth, 1.618 golden) within a ±5% tolerance. This is the trick `modularscale-sass` uses in reverse.
- **Tracking + leading** — `letter-spacing` and `line-height` per role. Both are returned by `getComputedStyle()` already resolved to px (or "normal", which we coerce to `1.2 * font-size`).

**Confidence:** very high for fonts and per-role sizes. High for ratio detection when the site uses a clean scale; medium when it doesn't (we still emit per-role values, just without a `ratio` field).

### 2.2 Spacing

**What's reachable:**
- `margin-top/right/bottom/left` and `padding-*` for every visible element. We sample ~500 elements (cap to keep evaluate() fast), bucket the values, and look for the **base unit** by checking GCD of frequent non-zero values across a divisibility ladder (`gcd(values) ∈ {2, 4, 6, 8}`). The Tailwind/Atlassian world is overwhelmingly 4px or 8px base — we bias towards those when the GCD is ambiguous.
- The **scale** is the top-K most-frequent multiples of the base. Atlassian's scale (4, 8, 12, 16, 24, 32, 40, 48, 64, 80) is a textbook example we can match against; we emit whatever the site actually uses.
- Gap: CSS `gap` (flex/grid) is an additional reliable spacing signal — sites that have adopted modern layout almost always use the same scale for `gap` as for padding.

**Confidence:** high for base unit; high for the scale's first 5–6 steps; medium for the larger steps (less data per bucket).

### 2.3 Border radius

**What's reachable:**
- `border-radius` of every element. We bin into 4 buckets: `0–2px` (sharp), `3–8px` (small), `9–18px` (medium), `19–48px` (large), and ≥`9999px / 50%` (pill / circle).
- We pick the **dominant radius per component class** by looking at samples of `button, [role="button"], [class*="btn" i]`, `input, textarea, select`, `[class*="card" i]`, `img, [class*="avatar" i]` separately — buttons and cards almost always share the same radius, but avatars are usually `50%` regardless.
- A "pill" classification triggers when the radius is ≥ height/2 (we read `getBoundingClientRect()`).

**Confidence:** very high.

### 2.4 Shadows / elevation

**What's reachable:**
- `box-shadow` per element, sampled across `[class*="card" i], [class*="modal" i], [role="dialog"], header, nav, [class*="dropdown" i], [class*="popover" i], [class*="tooltip" i]`.
- Parse each shadow string into structured `{offsetX, offsetY, blur, spread, color}` (regex against the standard CSS shadow grammar; multi-shadows comma-split). The W3C DTCG `$type:"shadow"` schema (2025.10 stable) is *exactly* this shape — we land in it directly.
- Cluster shadows by their (offset, blur, color-luminance) signature; the brand's "vocabulary" is typically 2–4 distinct shadows used repeatedly. Pull at most **5 named shadows** (`flat`, `card`, `raised`, `floating`, `modal`) — assign by total blur+offset magnitude.

**Confidence:** very high. Shadows are one of the cleanest signals on the page.

### 2.5 Iconography

**What's reachable:**
- `document.querySelectorAll('svg')` — for each, read `viewBox` (typically `0 0 24 24`), `stroke`, `stroke-width`, `fill`. Aggregate.
- **Style classification:**
  - If most SVGs have `stroke-width >= 1` and `fill="none"` → **outlined**.
  - If most have `fill` set and `stroke="none"` → **filled / solid**.
  - If we see both styles roughly equally → **mixed**.
  - If `<g>` children alternate fills with non-100% opacity → **duotone** (Phosphor signature).
- **Library guess** — heuristic combining stroke-width + grid + class names + presence of known signature paths:
  - 24×24 grid + 1.5px stroke + rounded caps + `lucide-*` class → **Lucide**.
  - 24×24 grid + 2px stroke or filled + `phosphor-*` class → **Phosphor**.
  - 24×24 grid + 1.5px stroke (slightly more conservative geometry) → **Heroicons** (fallback when no class).
  - 24×24 grid + 2px stroke + sparser icon set → **Feather**.
  - SVG `<symbol>` references in a `<use href="#sprite-...">` pattern → **custom in-house sprite**.
- We also count icons (a "rich icon vocabulary" is itself a brand signal: Linear has dense icons; Apple-style brands lean on emoji + SF Symbols and have very few inline SVGs).

**Confidence:** high for style; medium for library (most reliable when the brand uses an unmangled CDN class name; many brands strip those).

### 2.6 Imagery direction

**What's reachable:**
- HTML signal: `<img src>`, `<picture><source srcset>`, `background-image: url(...)` from computed style. Extract aspect ratios, file extensions (`.svg` → likely illustration; `.jpg/.webp` → likely photography), and host (CDN like `images.ctfassets.net` is a Contentful signal — neutral; `images.unsplash.com` strongly suggests *stock lifestyle photography*).
- **Vision signal**: feed our 4 viewport screenshots to Gemini with the prompt *"classify imagery direction: photographic_lifestyle / photographic_product / illustrated_flat / illustrated_iso / illustrated_handdrawn / 3d_render / gradient_mesh / mixed; describe treatment in 1 sentence."* Our existing `app/services/style/analyzer.py` already does multi-image vision — we extend its schema with two new fields (`imagery_direction` enum, `imagery_treatment` 1-liner) and that's it.

**Confidence:** high when CSS-only signals agree (e.g., 90% .svg → illustrated; 90% .jpg + Unsplash → photographic). Otherwise we let Gemini break the tie.

### 2.7 Components

**What's reachable:**
- **Buttons**: query `button, [role="button"], a[class*="btn" i], a[class*="button" i]`. For each, capture `{bg, color, border, border-radius, padding, font-weight}`. Cluster on these fingerprints; the largest cluster is the **primary** style, the next is **secondary**. Classify each cluster: filled (bg ≠ transparent), outlined (border-width > 0 + bg transparent), ghost (no border + transparent bg), link (no padding + underline). Pill if radius ≥ height/2.
- **Inputs**: query `input, textarea, select`. Classify by border style: bordered (border-width on all sides), underline (border-bottom only), pill (radius ≥ height/2).
- **Cards**: query `[class*="card" i], article, [data-card]`. Classify by `box-shadow`: shadow-raised (any shadow) vs flat-bordered (border-width > 0, no shadow) vs flat-clean (neither).

**Confidence:** medium-high. Some sites use bespoke class names that don't match common patterns — we degrade to extracting *whatever buttons we can find* by element tag alone.

### 2.8 Motion

**What's reachable:**
- `transition-duration`, `transition-timing-function`, `animation-duration`, `animation-timing-function` from `getComputedStyle()`. Sample on `button, a, [class*="card" i], [data-animate]`.
- *Caveat*: many sites set durations dynamically via JS (Framer Motion, GSAP). Our `_ANIMATION_KILL_CSS` injection neutralizes them on render. To capture motion intent we **read computed styles before** injecting that CSS — then re-inject before screenshots. (Currently we inject immediately; fix is a 4-line reorder.)
- **Easing names**: parse `cubic-bezier(...)` and snap to known curves (Material 3 emphasized = `cubic-bezier(0.2, 0.0, 0.0, 1.0)`, Apple-style "ease-out-quint" = `cubic-bezier(0.22, 1, 0.36, 1)`, `(0.16, 1, 0.3, 1)` is the popular "snappy" curve we use ourselves). Within ±0.05 tolerance.

**Confidence:** medium. Sites that animate via React state/Framer expose nothing in CSS; we get a useful signal only on CSS-driven brands. Document the limitation and fall back to a sane default (`240ms`, `cubic-bezier(0.16, 1, 0.3, 1)`).

### 2.9 Layout grid

**What's reachable:**
- `max-width` of `main, [role="main"], [class*="container" i], [class*="wrapper" i]`. The mode is the container width (typical: 1024 / 1200 / 1280 / 1440).
- Gutter: `padding-left/right` of the same container. Typical: 16 / 24 / 32 px.
- Breakpoints: parse `<style>` blocks and external stylesheets for `@media (min-width: ...)` queries; extract the unique breakpoints used. Modern Tailwind sites expose 640 / 768 / 1024 / 1280 / 1536 cleanly.

**Confidence:** high for max-width + gutter; high for breakpoints (the rule is right there in CSS).

### 2.10 Borders / dividers

**What's reachable:**
- `border-color` + `border-width` of `hr, [class*="divider" i], [class*="separator" i], thead tr, tbody tr` and the most-frequent border-color across all elements (a brand's "neutral border" almost always shows up in the top-3 border colors used).
- Bonus: detect *whether the brand uses borders at all* — minimalist brands (Linear, Notion) often have none and rely on shadow + bg-elevation; corporate brands (Carbon-style) lean heavily on borders.

**Confidence:** high.

---

## 3. Output schema — `Brand.identity`

A new JSON column on `Brand`. Shape is W3C-DTCG-adjacent (the 2025.10 stable spec) but flattened where DTCG's nesting hurts ergonomics. We deliberately keep it **flat enough to render in a React component without a recursion helper** — DTCG-strict can be re-emitted later from this shape.

```jsonc
{
  "typography": {
    "fonts": {
      "body":    "Inter, system-ui, sans-serif",
      "display": "Söhne Halbfett, Inter, sans-serif",
      "mono":    "Geist Mono, ui-monospace, monospace",
      "serif":   null
    },
    "fonts_loaded": [
      { "family": "Inter",      "source": "google",     "weights": [400, 500, 600, 700] },
      { "family": "Geist Mono", "source": "self-hosted","weights": [400] }
    ],
    "scale": {
      "h1":     { "size_px": 60, "weight": 700, "leading": 1.05, "tracking_em": -0.02 },
      "h2":     { "size_px": 48, "weight": 700, "leading": 1.10, "tracking_em": -0.02 },
      "h3":     { "size_px": 32, "weight": 600, "leading": 1.20, "tracking_em": -0.01 },
      "h4":     { "size_px": 24, "weight": 600, "leading": 1.25, "tracking_em":  0.00 },
      "body":   { "size_px": 16, "weight": 400, "leading": 1.60, "tracking_em":  0.00 },
      "small":  { "size_px": 14, "weight": 400, "leading": 1.50, "tracking_em":  0.00 },
      "button": { "size_px": 14, "weight": 500, "leading": 1.00, "tracking_em":  0.01 }
    },
    "ratio": 1.25,
    "ratio_name": "major_third",
    "base_size_px": 16
  },

  "spacing": {
    "base_px": 8,
    "scale_px": [4, 8, 12, 16, 24, 32, 48, 64, 96],
    "dominant_gap_px": 24
  },

  "radii": {
    "small_px": 4,
    "medium_px": 12,
    "large_px": 24,
    "pill": "9999px",
    "dominant_px": 12,
    "by_component": { "button": 9999, "card": 12, "input": 8, "avatar": "50%" }
  },

  "shadows": [
    { "name": "card",     "css": "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)" },
    { "name": "raised",   "css": "0 4px 12px rgba(0,0,0,0.06)" },
    { "name": "floating", "css": "0 8px 24px rgba(0,0,0,0.08)" },
    { "name": "modal",    "css": "0 24px 48px rgba(0,0,0,0.16)" }
  ],

  "borders": {
    "default":  { "css": "1px solid #e8e6f0",  "width_px": 1, "color": "#e8e6f0" },
    "strong":   { "css": "1px solid #d2d2d7",  "width_px": 1, "color": "#d2d2d7" },
    "uses_borders": true
  },

  "icons": {
    "style":         "outlined",
    "stroke_width":  1.5,
    "grid_px":       24,
    "library_guess": "lucide",
    "library_confidence": 0.78,
    "count_inline":  47
  },

  "imagery": {
    "direction":   "photographic_minimal",
    "treatment":   "high contrast, generous negative space, no people",
    "subjects":    ["product on white", "typographic hero"],
    "stock_signal": false
  },

  "components": {
    "buttons": {
      "primary":   { "style": "filled",   "shape": "pill",     "size_px": [14, 28] },
      "secondary": { "style": "outlined", "shape": "rounded",  "size_px": [14, 28] }
    },
    "inputs":  { "default": { "style": "underline", "radius_px": 0 } },
    "cards":   { "default": { "style": "shadow",    "radius_px": 12, "shadow": "card" } }
  },

  "motion": {
    "duration_ms":     240,
    "easing_css":      "cubic-bezier(0.16, 1, 0.3, 1)",
    "easing_name":     "snappy_outquint",
    "durations_seen":  [150, 240, 350],
    "easings_seen":    ["cubic-bezier(0.16, 1, 0.3, 1)", "ease-out"]
  },

  "layout": {
    "container_max_px": 1200,
    "gutter_px":        24,
    "breakpoints_px":   [640, 768, 1024, 1280],
    "columns":          12
  },

  "voice": {
    "$ref": "voice_profile"
  },

  "extracted_at":      "2026-04-25T20:34:11Z",
  "source_url":        "https://example.com",
  "extraction_method": "playwright_dom_evaluate@1",
  "confidence":        { "typography": 0.94, "spacing": 0.88, "radii": 0.97,
                         "shadows": 0.91, "icons": 0.66, "imagery": 0.82,
                         "components": 0.74, "motion": 0.45, "layout": 0.89 }
}
```

**Why this shape:**

- **Flat per-role buckets** for typography mean a React component renders `identity.typography.scale.h1` directly — no `$value`/`$type` walking. This matches how Vercel Geist exposes its tokens (`text-heading-72` is a flat name) rather than how DTCG nests.
- **Confidence per axis** — when the agent is generating content it can decide whether to *use* the extracted token or fall back to a safer default. Dembrandt and design-extract both ship confidence scores; we mirror the convention.
- **`durations_seen`/`easings_seen` as arrays** keep raw-sample fidelity in case downstream code wants to do its own clustering.
- **`fonts_loaded`** explicitly distinguishes Google Fonts vs Adobe vs self-hosted vs system — this matters for license-aware reuse: we cannot embed Adobe Fonts in a generated PDF without a license we don't own; we can embed Google Fonts freely.
- **`$ref` to voice_profile** keeps voice as the single-source-of-truth in the existing column rather than duplicating it.

---

## 4. Extraction algorithm — concrete

Three concerns, three components:

### 4.1 The Playwright `evaluate()` — one big DOM walk

A single `page.evaluate()` returning a JSON blob of raw samples. The function never *makes decisions* — only collects. All clustering happens in Python. The body is roughly:

```js
() => {
  const sample = (sel, n) => {
    const els = Array.from(document.querySelectorAll(sel)).slice(0, n);
    return els.map(el => {
      const cs = getComputedStyle(el);
      const r  = el.getBoundingClientRect();
      return {
        tag: el.tagName.toLowerCase(),
        cls: el.className && typeof el.className === 'string'
              ? el.className.slice(0, 200) : '',
        font_family:    cs.fontFamily,
        font_size:      cs.fontSize,
        font_weight:    cs.fontWeight,
        line_height:    cs.lineHeight,
        letter_spacing: cs.letterSpacing,
        color:          cs.color,
        bg_color:       cs.backgroundColor,
        margin:         [cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft],
        padding:        [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft],
        gap:            cs.gap,
        border:         [cs.borderTopWidth, cs.borderColor, cs.borderStyle],
        border_radius:  cs.borderRadius,
        box_shadow:     cs.boxShadow,
        transition:     [cs.transitionDuration, cs.transitionTimingFunction],
        max_width:      cs.maxWidth,
        width:  r.width, height: r.height,
      };
    });
  };

  // Selectors per axis — each is short, focused, capped.
  const typography = sample('h1, h2, h3, h4, h5, h6, p, blockquote, code, pre', 200);
  const buttons    = sample('button, [role="button"], a[class*="btn" i], a[class*="button" i]', 60);
  const inputs     = sample('input, textarea, select', 30);
  const cards      = sample('[class*="card" i], article', 40);
  const containers = sample('main, [role="main"], [class*="container" i], [class*="wrapper" i]', 20);
  const everything = sample('*', 800);  // for spacing / radius / shadow distributions

  // SVG / icon inventory
  const svgs = Array.from(document.querySelectorAll('svg')).slice(0, 100).map(s => {
    const paths = s.querySelectorAll('path, line, circle, rect');
    const first = paths[0];
    return {
      viewBox:      s.getAttribute('viewBox'),
      stroke:       first ? getComputedStyle(first).stroke : null,
      stroke_width: first ? getComputedStyle(first).strokeWidth : null,
      fill:         first ? getComputedStyle(first).fill : null,
      cls:          s.className?.baseVal || s.getAttribute('class') || '',
    };
  });

  // Loaded webfonts (FontFaceSet API)
  const fonts_loaded = Array.from(document.fonts).map(f => ({
    family: f.family, weight: f.weight, style: f.style, status: f.status,
  }));

  // Webfont CDN signatures
  const fontLinks = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
    .map(l => l.href).filter(h =>
      h.includes('fonts.googleapis.com') ||
      h.includes('use.typekit.net') ||
      h.includes('fonts.bunny.net')
    );

  // Media queries — for breakpoints
  const breakpoints = new Set();
  for (const sheet of document.styleSheets) {
    try {
      for (const rule of sheet.cssRules || []) {
        if (rule instanceof CSSMediaRule) {
          const m = rule.conditionText.match(/min-width:\s*(\d+)px/);
          if (m) breakpoints.add(Number(m[1]));
        }
      }
    } catch {}  // cross-origin sheets throw
  }

  // <img> inventory + background-images
  const images = Array.from(document.images).slice(0, 60).map(i => ({
    src: i.currentSrc || i.src, w: i.naturalWidth, h: i.naturalHeight,
  }));

  return {
    typography, buttons, inputs, cards, containers, everything, svgs,
    fonts_loaded, font_links: fontLinks,
    breakpoints: Array.from(breakpoints).sort((a, b) => a - b),
    images,
  };
}
```

This runs **once**, returns ~400KB of JSON max, takes ~50–200ms inside a page that's already loaded. It happens *inside* `scrape()` so we don't re-render.

**Critical ordering fix**: read motion + transitions **before** injecting `_ANIMATION_KILL_CSS`. The current scraper injects animation-kill CSS at line 102 *before* any computed-style read, which zeroes out all `transition-duration` we'd want. We split the eval into two passes: pass-1 reads motion samples, then we inject animation-kill, then pass-2 takes screenshots and reads everything else.

### 4.2 The Python post-processor — `app/services/enrichment/identity.py` (new)

A pure-functional module: `analyze_identity(samples: dict) -> dict`. Stateless, no I/O, easy to unit-test offline against a recorded `samples.json`. The functions:

- `_typography(samples)` → fonts (parse first family from each stack, cross-ref with `fonts_loaded`); per-role mode size/weight/leading/tracking; ratio detection (try each canonical ratio, snap if within ±5% across at least two adjacent roles).
- `_spacing(samples)` → flatten margin + padding + gap values (px), strip zeros, take the GCD on the modal cluster, snap base to {2, 4, 6, 8}; emit the top 8 multiples by frequency.
- `_radii(samples)` → bin into sharp/small/medium/large/pill; pick dominant per component (button/input/card/avatar) and overall.
- `_shadows(samples)` → parse box-shadow strings (regex `/(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px(?:\s+(-?\d+(?:\.\d+)?)px)?\s+(rgba?\([^)]+\)|#[0-9a-f]+)/gi`), cluster, name 2–4 of them by their (offset+blur) magnitude.
- `_borders(samples)` → modal border-color from all-element samples; widths + presence flag.
- `_icons(samples.svgs)` → mode stroke-width, fill-vs-stroke majority, library guess via class names + signature + stroke.
- `_motion(samples)` → mode duration (filtering 0 / 0.001ms — our injected zero), mode easing, snap to known curves.
- `_layout(samples.containers, samples.breakpoints)` → max-width mode + breakpoints from `@media`.
- `_components(samples)` → button cluster classification (filled/outlined/ghost/link, pill/rounded/sharp); input style; card style.

Each function emits its piece of the schema *plus* a confidence float (signal: how much the modal value dominates the distribution; high entropy = low confidence). Top-level `confidence` is each axis's score, kept independent so downstream consumers can pick.

### 4.3 The Gemini-vision pass — extends `app/services/style/analyzer.py`

We **don't** add a new vision call — we extend the existing schema. Today `StyleProfile` returns `{palette_character, composition, mood, typography_feel, photographic_vs_illustrated, distinctive_marks, generation_guidance}`. We add three fields:

- `imagery_direction` (enum: `photographic_lifestyle | photographic_product | illustrated_flat | illustrated_iso | illustrated_handdrawn | 3d_render | gradient_mesh | mixed | none`)
- `imagery_treatment` (1-sentence description)
- `icon_style_visual` (enum: `outlined | filled | duotone | mixed | none`) — used to verify our CSS-side icon classification

And we **defer the vision call entirely** when CSS-only confidence is high (e.g., >0.85 from `_icons` heuristic and unambiguous img-extension stats). This keeps the latency budget tight: 4 of 5 brands skip the second vision call.

---

## 5. Concrete implementation plan — file by file

The smallest credible cut. Every file path is real, every change is small.

### Backend

**`backend/app/services/enrichment/scraper.py`** — extend the existing `scrape()`:
1. Add a **first pass** of motion-sensitive computed-style reads before the animation-kill CSS injection.
2. Add a `_DESIGN_SAMPLES_JS` constant (the eval body in §4.1) executed after the screenshots pass.
3. Add `design_samples: dict | None` to `ScrapedSite`.

**`backend/app/services/enrichment/identity.py`** — new file, ~250 lines, the post-processor in §4.2. Pure functions, no side-effects, fully type-annotated. Takes `design_samples` from `ScrapedSite` plus `style_profile.imagery_direction` (optional, vision-derived) and emits the `identity` dict from §3.

**`backend/app/services/style/analyzer.py`** — extend `STYLE_SCHEMA` with the three new vision fields; extend `_build_prompt` with one extra paragraph instructing Gemini to classify imagery direction and verify icon style.

**`backend/app/db/models.py`** — add `identity = Column(JSON, default=dict)` on `Brand`. SQLite migration is a one-liner: SQLAlchemy auto-creates new columns on next `create_all()` since this is a hackathon SQLite DB; for the Postgres path we add a single `ALTER TABLE` on app start (provider does it lazily).

**`backend/app/services/onboarding/orchestrator.py`** — in `_run_post_enrichment` (after `analyze_style`), call `identity.analyze_identity(design_samples, style_profile.imagery_direction)`, write to `Brand.identity`, emit `ONBOARDING_IDENTITY_EXTRACTED`. Keep this *non-blocking* on style failure — even if vision dies we still ship the CSS-only identity (it covers ~85% of the schema).

**`backend/app/events/types.py`** — add:
```python
ONBOARDING_IDENTITY_EXTRACTING = "onboarding.identity_extracting"
ONBOARDING_IDENTITY_EXTRACTED  = "onboarding.identity_extracted"
```

### Frontend

**`frontend/src/events/bus.ts`** — add the `Identity` type (mirror of §3) and event payloads `'onboarding.identity_extracting': { brand_id }` and `'onboarding.identity_extracted': { brand_id, identity }`.

**`frontend/src/stores/onboardingStore.ts`** — add `identity: Identity | null` to state; `bus.on('onboarding.identity_extracted', ...)` to set it and push activity.

**`frontend/src/onboarding/IdentityCard.tsx`** — new component, the visual specimen page (§6). Plugs into `StepReading` between the existing `Visual style` card and `Reference brands` card.

**`frontend/src/onboarding/StepReading.tsx`** — render the IdentityCard when `identity != null`.

### Cut order (priority on the hackathon clock)

1. **Hour 1**: `scraper.py` design-samples eval + `identity.py` for typography + spacing + radii + shadows. These are the four highest-confidence axes and visually dominate the IdentityCard.
2. **Hour 2**: `IdentityCard.tsx` rendering the four axes above. This is the demo moment.
3. **Hour 3**: icons + components + layout + motion. Each is small and self-contained.
4. **Hour 4 (optional)**: extend `analyzer.py` with imagery direction + icon-style verification. Skippable — degrades gracefully.

If we truly run out of time, the **smallest acceptable cut** is steps 1+2: a card that shows H1/body specimens in the brand's font, a column of spacing rectangles, four radius tiles, and four shadow specimens. This alone is a stronger demo than what we have today.

---

## 6. The IdentityCard — visual presentation in the wizard

This is *the wow moment* the user pays for emotionally: their brand identity rendered back to them, in their own typography, at their own spacing, on their own radii, with their own shadows. The whole point of the agent is *"it knows my brand"* — this is the most legible proof of that claim short of a generated post.

The card's six sub-sections, top to bottom:

### 6.1 Type specimens (largest visual mass)
A column with 4 specimens, each rendered in the captured font stack:
- An H1 ("`{Brand} sells {what}`" — pulled from the LLM's brand summary) at the captured size + weight + tracking.
- An H3 secondary line.
- Two paragraphs of body text (lorem from `voice_profile.voice_excerpt`, so it's *the brand's actual voice* in *the brand's actual font*).
- A mono code chip (`brand_autopilot init {brand}`) in the captured mono stack — only if `mono` is non-null.

Right-side rail: the type-scale table (h1..body, with the size/weight/leading/tracking values in mono — feels like a real spec sheet).

### 6.2 Spacing rhythm visualization
A horizontal bar of rectangles, each `4px / 8px / 12px / 16px / 24px / 32px / 48px` wide, with the px label below. Same height. Looks like a piano keyboard. Captioned "8-pt grid · base 8" in mono.

### 6.3 Radii samples
Four squares (or pills) side-by-side: small, medium, large, pill. Each labelled with its radius value. Background = the brand's `bg-soft` or a captured tile color. Border = the brand's `borders.default`.

### 6.4 Shadow specimens
Four cards on a neutral background, each with one of the captured shadows. Caption in mono shows the shadow CSS truncated. Pure typography + box-shadow demo — drop-dead easy to render.

### 6.5 Icon style note + sample
A row showing 3–6 icons in the detected style (we use Lucide regardless — but render them at the captured stroke-width). Caption: "outlined · 1.5px · likely Lucide".

### 6.6 Component examples (the "live preview" finale)
A button + an input + a card, all rendered with the captured tokens:
- Button: filled, pill, in `palette[0]` with `palette_text`, size 14/28, font-weight from `scale.button`.
- Input: underline-style if that's what we detected, or bordered box.
- Card: with the captured radius + shadow + a sample title in the brand's display font.

This is the "I can ship a landing page in this brand's style **right now**" demo. Even the most jaded judge does a double-take when the preview button looks indistinguishable from the brand's actual "Sign up" button.

### Visual taste
The IdentityCard is **monochromatic with a single accent** — the same restraint our existing onboarding cards use. The brand's tokens are displayed *in mono numerals* (tabular, JetBrains-style) so the spec values feel like data, not decoration. We don't theme the card itself with the brand's palette — that would muddy "this is the agent reading you" vs "this is your brand". The card is the *agent's voice*; the specimens *inside* the card are the *brand's voice*. That contrast is the point.

---

## 7. How the agent loop USES the corporate identity

The CI is not a trophy. It's a context block that flows into every generation call. Closing the loop:

### 7.1 Image generation
When the agent generates a hero image, the prompt now includes:
- *"Corner radius: 12px on cards, fully pill on buttons. Shadow vocabulary: subtle, 0–8px blur. Imagery direction: photographic_minimal, high contrast, generous negative space, no people. Color palette: …"*

Concretely: extend `style_profile.generation_guidance` (already a list of imperatives) with *structured token references*. The image-gen prompt synthesizer in the agent loop merges both.

### 7.2 Text → layout templates
When the agent renders a generated post or landing-page section, it:
- Picks a button style from `components.buttons.primary`.
- Uses `spacing.scale_px` for vertical rhythm (h1 → h2 = `scale[3] = 16px`; section padding = `scale[6] = 48px`).
- Uses `typography.scale.h1` for the headline.
- Uses `radii.dominant_px` on cards.

### 7.3 Voice + visual together = brand-faithful content
The existing `voice_profile` says *what to write*. The new `identity` says *what it should look like*. Together they constitute the brand-fit guarantee: *"every piece the agent ships in your name uses your voice and your design system."* This is the moat sentence for the deck.

### 7.4 Continuous learning hook
Every approve/reject on a generated piece becomes a signal that re-weights `confidence`. If a brand-team rejects three drafts that used radius=12 because "we actually use 16 for marketing", we bump the per-channel override. This connects directly to the *continuous-learning* pillar from the project memory — onboarding extracts a first-pass identity, edits sharpen it.

### 7.5 The deck moment
The CI is also a **shareable artefact**: an "export" button on the IdentityCard renders the schema as a one-page PDF (simple HTML→print). The customer can *show this to their actual designer* — instant trust. This is the kind of move that makes the agent feel like a co-founder rather than a content tool.

---

## 8. Pitfalls + honest caveats

These are the things the hackathon demo will *not* gracefully handle, and the user should know:

1. **Cross-origin stylesheets** throw on `sheet.cssRules` access. We catch silently — breakpoints from those sheets are lost. Most modern brands inline their critical CSS, so this is a partial loss not a fatal one.
2. **Tailwind utility classes don't expose semantic tokens** — `class="px-4 py-2 rounded-lg"` is just shorthand for hard-coded values. Our extractor sees the resolved px and works fine. We *cannot* recover the brand's *internal* token names (e.g., they call it `radius-md`). We re-name them ourselves; that's a feature, not a bug.
3. **Animation-driven brands** (Framer/GSAP/JS-spring) yield zero motion samples from CSS. We document `motion.confidence` as low and fall back to a sane default. A v2 lift could read computed transforms over time, but that's a 4-hour project.
4. **Brands with 3+ marketing surfaces** (saas.brand.com, app.brand.com, blog.brand.com) often have *different* identities per surface. We only read the homepage. Document the limitation; let the user paste extra URLs for v1.
5. **License-aware reuse is partial**. We can detect Adobe Fonts, but we can't *use* them in generated content without the customer's license. We surface this to the agent loop as a flag; the agent picks a free fallback (a Google Font with similar metrics) when generating.
6. **Headless browser is detectable.** A few brands cloak CSS for headless visitors. Dembrandt addresses this with stealth patches; we don't, but in practice the brands that matter for early-stage hackathon customers don't cloak.
7. **Our existing `_ANIMATION_KILL_CSS` ordering bug** zeroes out motion samples — the fix is in §4.1, but anyone reusing our scraper without that fix will get garbage motion data.

---

## 9. Comparison — what's *better* than what's out there

Why the agent-grade extractor we sketch above beats the existing tools for our use case:

| Tool | What it does | Why it's not enough for us |
|---|---|---|
| **Brandfetch / Logo.dev / Brand.dev** | Hosted API: returns logo, palette, fonts, sometimes a colors-only "styleguide". | Coarse-grained — colors + fonts only, no spacing/radii/shadows/components/motion. Black-box; no ability to feed the brand's *actual* radius into a generation prompt. Privacy: every brand we look up phones home to Brandfetch. |
| **Dembrandt (OSS)** | Playwright + DOM walk + DTCG output + multi-page confidence. | Closest to our spec. We could theoretically shell out to it as a subprocess for a hackathon. The reason we still build our own: we want the eval embedded in our existing scrape (one render, one set of screenshots) and the schema flat for direct React rendering. |
| **design-extract by designlang (OSS)** | 17-extractor pipeline, DTCG + Tailwind + shadcn output, multi-platform emitters. | Massively over-scoped for a hackathon (iOS Compose, Flutter, etc. emitters we don't need). Not Python. Same "embed it in our pipeline" friction. Worth re-reading their selectors for inspiration. |
| **Project Wallace** | Static-CSS analyzer: counts colors, font-sizes, line-heights, shadows, radii. | Static CSS only — misses everything resolved at render time (Tailwind's compiled output IS readable, but JIT-only sites and JS-injected styles aren't). |
| **Superposition** | Renders site, exports tokens to CSS/SCSS/JS/Figma. | Free desktop app, not an API. Output is for designers to consume in their own tools, not for an LLM agent to feed into prompts. |
| **Brand.dev's Font API** | Crawls a domain, lists detected fonts with weights. | Only fonts. Genuinely useful as a *secondary cross-check* on our `fonts_loaded` if we want to verify against a 3rd-party. |

The **one credible advantage we have** that none of these tools have: we already render the page anyway (for screenshots + voice extraction), so the marginal cost of design-token extraction is ~50ms of `evaluate()` time. That's the unfair advantage.

---

## 10. The two-background-agents pattern (the user asked for it)

The user explicitly asked for "2 background agents". This is the right pattern for this work and we apply it both in research *and* in implementation.

### Research (this document)
We ran the research as two parallel agents — agent-A on web (Brandfetch / DTCG / Dembrandt / design-extract / Wallace / Superposition / Material 3 / Carbon / Geist / icon library detection / motion tokens) and agent-B on the codebase (existing scraper, models, orchestrator, frontend bus + stores + StepReading). Each pass cost zero of the other's latency budget. The doc you're reading is the merge.

### Implementation (the agent itself)
The same pattern translates directly: at brand-load time, the orchestrator already runs voice distillation and competitor suggestion serialized (quota-bound on Gemini 3 Flash preview). Adding identity extraction does **not** break that — it's pure CSS + DOM, no LLM call, so it runs in **parallel** with the voice + competitor LLM calls. The vision-augmentation step (imagery_direction) piggybacks on the existing `analyze_style` call (same prompt, more fields) — no extra latency.

Net: identity extraction adds ~200ms (pure DOM) to the onboarding pipeline. The IdentityCard renders in `StepReading` at roughly the same moment as the visual style block.

---

## 11. Sources (recent — 2024–2026)

The research that fed this document, with the publish/visit dates:

- [Design Tokens Format Module 2025.10 — W3C DTCG (stable)](https://www.designtokens.org/tr/drafts/format/) — first stable spec, October 28 2025.
- [Design Tokens Specification reaches first stable version — W3C announcement](https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version/) — companion blog post.
- [Dembrandt — extract design tokens from any website (OSS, Playwright)](https://github.com/dembrandt/dembrandt) — closest existing OSS to our extraction scheme; 2025.
- [I built Dembrandt: extract any website's design system in seconds](https://dev.to/thevangelist/i-built-dembrandt-extract-any-websites-design-system-in-seconds-open-source-2n6d) — author's blog, 2025.
- [Manavarya/design-extract — OSS extractor with DTCG + multi-platform emitters](https://github.com/Manavarya09/design-extract) — 2025/2026.
- [Material Design 3 — Design Tokens overview](https://m3.material.io/foundations/design-tokens) — 2025; covers color, type, shape, spacing, motion, elevation token categories.
- [Material Design 3 — Easing and Duration tokens](https://m3.material.io/styles/motion/easing-and-duration/tokens-specs) — `motion.duration.short1..extra-long4`, `motion.easing.emphasized` cubic-bezier specs.
- [IBM Carbon Design System — Type sets (productive vs expressive)](https://carbondesignsystem.com/) — composite type tokens.
- [Atlassian Design System — Spacing tokens](https://atlassian.design/foundations/spacing) — `space.025` (2px) … `space.1000` (80px), 8px base.
- [Vercel Geist — Typography](https://vercel.com/geist/typography) — flat named tokens (`text-heading-72` … `text-copy-13-mono`).
- [Vercel Geist — Design system breakdown (SeedFlip blog, 2025)](https://seedflip.co/blog/vercel-design-system) — token inventory.
- [Brandfetch — Brand API & Logo API](https://brandfetch.com/developers) — competitive benchmark (logo + colors + fonts only).
- [Brand.dev — Logo + Font + Styleguide APIs](https://www.brand.dev/) — competitive benchmark; closest API competitor on font detection.
- [Brand.dev Font API documentation](https://www.brand.dev/data/font-api) — methodology for crawl-based font detection.
- [Logo.dev — Brand API + Logo API](https://www.logo.dev/) — Clearbit successor; logo + colors API.
- [Project Wallace — CSS Design Tokens Analyzer](https://www.projectwallace.com/design-tokens) — static-CSS token analyzer; categories list.
- [Superposition — extract design tokens from a rendered site](https://superposition.design/) — free desktop OSS extractor.
- [Style Dictionary (Amazon, OSS) — multi-platform token transformer](https://styledictionary.com/) — DTCG-compatible build system; the standard for cross-platform export.
- [AWS Open Source Blog — Style Dictionary and design consistency](https://aws.amazon.com/blogs/opensource/style-dictionary-trust-design-consistency/) — 2024/2025 retrospective.
- [Tokens Studio — Typography composite tokens](https://docs.tokens.studio/manage-tokens/token-types/typography) — 9-property composite typography schema.
- [Tokens Studio for Figma — community plugin](https://www.figma.com/community/plugin/843461159747178978/tokens-studio-for-figma) — reference implementation.
- [zeroheight — Design Systems Report 2025](https://othr.zeroheight.com/hubfs/zeroheight%20-%20Design%20System%20Report%202025%20-%20release%20version.pdf) — adoption statistics; 79% of teams have a design-system team in 2025.
- [Lucide Icons — 24×24 grid, 1.5px stroke, rounded caps](https://lucide.dev/) — signature for library detection.
- [Phosphor / Heroicons / Feather comparison (icon library survey, 2026)](https://hugeicons.com/blog/design/8-lucide-icons-alternatives-that-offer-better-icons) — stroke-width fingerprints.
- [Modular Scale — Every Layout (typography ratios)](https://every-layout.dev/rudiments/modular-scale/) — the canonical reference for ratio-based type scales.
- [HarmonyType — type scale tooling 2025](https://harmonytype.com/) — current-gen type scale generator.
- [FontDetect.js — detecting which font in a stack actually rendered](https://github.com/JenniferSimonds/FontDetect) — the technique we use for font cross-check.
- [Chrome DevTools — "What font is that?" (rendered font inspection)](https://developer.chrome.com/blog/devtools-answers-what-font-is-that) — DevTools' resolved-font feature, available via getComputedStyle programmatically.
- [Playwright — getComputedStyle inside `page.evaluate` (LambdaTest, 2025)](https://www.lambdatest.com/automation-testing-advisor/javascript/playwright-internal-getComputedStyle) — the pattern this doc uses.
- [Tailwind — base unit and spacing scale rationale](https://github.com/tailwindlabs/tailwindcss/discussions/11439) — why 4px base, 8px most popular.
- [The Evolution of Design System Tokens — 2025 Deep Dive (Design Systems Collective, 2025)](https://www.designsystemscollective.com/the-evolution-of-design-system-tokens-a-2025-deep-dive-into-next-generation-figma-structures-969be68adfbe) — broad industry overview.
- [Material 3 Expressive — new motion + shape tokens (2025)](https://supercharge.design/blog/material-3-expressive) — current direction of Material's token expansion.

---

## Appendix A — quick spec for `_DESIGN_SAMPLES_JS`

For the avoidance of ambiguity at implementation time, the eval-call returns this shape (truncated for brevity):

```jsonc
{
  "typography": [
    { "tag": "h1", "cls": "...", "font_family": "Inter, ...",
      "font_size": "60px", "font_weight": "700", "line_height": "63px",
      "letter_spacing": "-1.2px", "color": "rgb(20,20,30)",
      "margin": ["0px","0px","16px","0px"], "padding": ["0px","0px","0px","0px"],
      "border_radius": "0px", "box_shadow": "none", "width": 720, "height": 63 },
    /* ... 199 more ... */
  ],
  "buttons": [ /* 60 max */ ],
  "inputs":  [ /* 30 max */ ],
  "cards":   [ /* 40 max */ ],
  "containers": [ /* 20 max */ ],
  "everything": [ /* 800 max — for distribution stats */ ],
  "svgs":    [ { "viewBox": "0 0 24 24", "stroke": "currentColor", "stroke_width": "1.5", "fill": "none", "cls": "lucide lucide-arrow-right" }, /* ... */ ],
  "fonts_loaded": [ { "family": "Inter", "weight": "700", "style": "normal", "status": "loaded" }, /* ... */ ],
  "font_links": ["https://fonts.googleapis.com/css2?family=Inter:wght@400..700"],
  "breakpoints": [640, 768, 1024, 1280],
  "images": [ { "src": "https://.../hero.webp", "w": 1920, "h": 1080 }, /* ... */ ]
}
```

The post-processor in `identity.py` consumes this verbatim and emits the schema in §3.

## Appendix B — known canonical motion easings (for snap-to-name)

From Material 3, Apple HIG, and observed-in-the-wild:

| Name | cubic-bezier | Vibe |
|---|---|---|
| `linear` | `cubic-bezier(0, 0, 1, 1)` | cold |
| `standard` | `cubic-bezier(0.2, 0, 0, 1)` | M3 default |
| `emphasized` | `cubic-bezier(0.2, 0, 0, 1)` | M3 attention |
| `emphasized-decelerate` | `cubic-bezier(0.05, 0.7, 0.1, 1)` | enter |
| `emphasized-accelerate` | `cubic-bezier(0.3, 0, 0.8, 0.15)` | exit |
| `snappy_outquint` | `cubic-bezier(0.16, 1, 0.3, 1)` | the popular "Apple-feeling" curve |
| `outquart` | `cubic-bezier(0.25, 1, 0.5, 1)` | smooth, less overshoot |
| `linear-spring` | n/a (CSS spring; 2025 syntax) | future-proofing |

Snap to nearest by sum-of-absolute-difference on the 4 control points; tolerance 0.06.
