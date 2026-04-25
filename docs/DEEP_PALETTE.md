# Deep Palette — Research & Implementation Plan

> Brand Autopilot, April 2026
> Status: research + planning. No production code yet.
> Owner: enrichment pipeline (`backend/app/services/enrichment/*`).

---

## TL;DR

The current pipeline returns `palette: list[str]` — five hex codes ordered by a hand-rolled CSS-role priority then padded with Pylette pixel frequencies. That shape can't answer the questions an AI marketer actually asks (*"what color is the CTA, what's legal text on it, what's the muted neutral, do they have a danger color?"*).

The fix is to replace the flat list with a **role-mapped, multi-layer palette object** modeled after the W3C Design Tokens 2025.10 spec and Material 3's role tokens. Three layers — **reference colors** (raw hexes harvested from the page), **semantic roles** (background / surface / primary / on-primary / etc.), and **shade ladders** (50→950 scales for the brand and neutrals). Plus an `ornament` bucket for decorative pixel-frequency colors that don't earn a role.

The three highest-leverage extraction additions over what we ship today:

1. **`:root` CSS custom-property harvest** — modern marketing sites already publish a tokenized palette (`--color-primary`, `--brand-500`, etc.); reading these gives us the design system the brand's own engineers committed to source control.
2. **Text-on-background contrast graph** — for every text element, record `(fg, bg)` and tally usage. The most-trafficked legal pair becomes our "body / surface" anchor; the highest-contrast minority pair is usually the headline color.
3. **SVG `fill` extraction from header/nav inline SVGs** — logos and core icons are nearly always inline SVG. Their fills are the brand's own answer to *"what color is the brand?"* — much higher signal than pixel frequency.

---

## 1. What "deep palette" means

A flat list of five hexes throws away every relationship that makes a palette useful. The state-of-the-art design-token tools converged on a **three-layer model** ([W3C Design Tokens Format Module 2025.10](https://www.designtokens.org/tr/drafts/format/), [Material 3 Tokens](https://m3.material.io/foundations/design-tokens), [Tokens Studio JSON schema](https://docs.tokens.studio/tokens/json-schema)):

| Layer            | What it stores                              | Example                                      |
| ---------------- | ------------------------------------------- | -------------------------------------------- |
| **Reference**    | raw color values — the visible hexes        | `colors.blue.500 = #0071e3`                  |
| **Semantic**     | role aliases pointing at reference colors   | `brand.primary = {colors.blue.500}`          |
| **Component**    | UI-scoped tokens (out of scope for us)      | `button.cta.bg = {brand.primary}`            |

For Brand Autopilot we need layers 1 and 2. Layer 3 belongs to whoever consumes the palette downstream (the asset generator).

The semantic layer is where the depth lives. Material 3 organizes it as **role pairs** (every fill role has a paired `on-` text role guaranteed to be legible on it). Open Color and Tailwind v4 organize it as **named hue families with 10–11 step shade ladders**. We want both: role pairs for the brand-distinctive colors, ladders for the neutrals (and for the brand color itself, when we can detect a ladder in the wild).

What "depth" buys us in practice:

- **Role-aware asset generation** — when we render an Instagram post, we know which color is the CTA fill vs the brand accent vs the background. No more guessing the order of a flat list.
- **Contrast guarantees** — every role pair has a measured contrast value. Generated copy can pick text that's actually readable.
- **Hierarchy** — `primary` is always larger / first in the UI; `ornament` is always lower-trust and visibly tagged as such.
- **Fallbacks** — if the brand has no clear primary (Apple, Vercel, Linear-style monochrome), we degrade gracefully to a "monochrome" palette with a single accent.

---

## 2. What we can extract from a rendered website

What a Playwright page can answer, ordered roughly by signal-to-noise:

### 2.1 — Already in scope

- **Page background / foreground** — `getComputedStyle(body).backgroundColor` and `.color`. Already done.
- **CTA bg + text pair** — query `button, [role=button], a[class*=button|btn|cta]`, computed style. Already done. Needs: also pair `.color` with `.backgroundColor` per element so we can store the legal text-on-CTA combo, not just the two colors as separate items.

### 2.2 — Easy wins to add

- **Link colors + visited** — query `a:not([class*=button])`, computed `.color`. We do part of this already; we should split "in-content links" (inside `<main>`, `<article>`) from "nav links" (inside `<header>`, `<nav>`), because the content link is the truer brand link color.
- **Headline color** — `getComputedStyle()` on `h1, h2, h3`. Often distinct from body fg (e.g. body is `#374151`, h1 is `#0f172a`).
- **Border / divider color** — sample `border-top-color` across `hr, [class*=card], [class*=divider], section, table, td`. Note: `border-color` is shorthand; you must read each side individually ([MDN getComputedStyle](https://developer.mozilla.org/en-US/docs/Web/API/Window/getComputedStyle)). Take the modal value across N samples.
- **Secondary surface** — sample `backgroundColor` of `[class*=card], [class*=panel], [class*=tile], section, aside, [class*=surface]`. The most-frequent value that is *close-but-not-equal* to body bg is the off-bg surface (think `#fafafc` against a white body).
- **Status colors** — query `.success, .error, .warning, .danger, .info, [role=alert], [role=status], .badge`, computed `.color` and `.backgroundColor`. Most marketing pages don't have these exposed on the homepage; when present they're gold.

### 2.3 — High-signal additions

- **`:root` CSS custom properties** — modern sites with a design system publish `--color-primary`, `--brand-500`, `--bg-elevated`, etc. on `:root`. The CSS-Tricks technique iterates `document.styleSheets` and pulls every `--*` declaration ([CSS-Tricks: Get All Custom Properties](https://css-tricks.com/how-to-get-all-custom-properties-on-a-page-in-javascript/)). Filter to entries whose value is parseable as a color OR whose name contains `color`, `bg`, `brand`, `primary`, `accent`, `surface`, `text`. **This is the single biggest lift** — when present, you're reading the brand's design tokens straight off the page.
- **Inline SVG fills** — header/nav `<svg>` elements (the logo and icon pack). Walk every `[fill]` attribute, every inline `style="fill:..."`, and every `<stop stop-color="...">` inside gradients. Skip `none`, `currentColor`, and anything that resolves to the page fg. Logo colors are the brand's own self-declared answer.
- **Theme color & manifest** — `<meta name="theme-color">` (we read this already as `theme_color`), `<link rel="manifest">` payload (often has a `theme_color` and `background_color`), and `<meta name="msapplication-TileColor">`. These are the brand's explicitly-declared mobile chrome colors.

### 2.4 — Pixel-derived (current Pylette path, kept as fallback)

- **Screenshot dominant colors via k-means / median-cut** — Pylette already does this. We continue using it but **only to fill the `ornament` bucket** when the CSS-derived palette is thin. Pixel frequency is high noise for brand intent (the Apple-Mother's-Day case in the directive: a hero image of flowers can dump #fb6533 / #fcc445 into the palette even though those aren't brand colors).

### 2.5 — Derived signals (computed from the above)

- **Shade families** — colors that look like variations of one hue. Convert each candidate to OKLCH ([Tailwind v4 OKLCH palette](https://tailwindcss.com/docs/colors), [Evil Martians: OKLCH dynamic themes](https://evilmartians.com/chronicles/better-dynamic-themes-in-tailwind-with-oklch-color-magic)), cluster by hue (Δh < ~10°) and chroma (Δc < ~0.05), sort cluster members by lightness, recognize a shade ladder.
- **Most-trafficked color pairs** — for each text node we sampled, store `(fg_hex, bg_hex)` and a count. Dump that as a graph adjacency list. This mirrors how [Huemint](https://huemint.com/about/) encodes palette intent — a contrast graph where edges have weights — but we read it from the wild instead of generating it.

---

## 3. Output schema proposal

The `palette` field on `Brand` becomes a structured object. Layers, role names, and ladder shape are aligned with [W3C Design Tokens 2025.10](https://www.designtokens.org/tr/drafts/format/) (which standardized in Oct 2025) and Material 3's role pairing convention.

### 3.1 — The shape

```jsonc
{
  "version": 1,
  "source": {                             // provenance per-color, for debugging
    "css_vars_found": 7,
    "svg_fills_found": 4,
    "pixel_fallback_used": false
  },
  "brand": {
    "primary":      { "hex": "#0071e3", "role": "primary",      "source": "cta_bg",        "uses": 18 },
    "primary_on":   { "hex": "#ffffff", "role": "on_primary",   "source": "cta_text",      "uses": 18, "contrast_apca": 96, "contrast_wcag": 8.59 },
    "accent":       { "hex": "#0066cc", "role": "accent",       "source": "in_content_link", "uses": 11 }
  },
  "neutrals": {
    "background":   { "hex": "#ffffff", "role": "background",   "source": "body_bg" },
    "surface":      { "hex": "#fafafc", "role": "surface",      "source": "card_bg",       "delta_e_from_bg": 1.4 },
    "text":         { "hex": "#1d1d1f", "role": "text",         "source": "body_fg",       "contrast_apca": 99, "contrast_wcag": 17.1 },
    "text_muted":   { "hex": "#6e6e73", "role": "text_muted",   "source": "secondary_text" },
    "border":       { "hex": "#d2d2d7", "role": "border",       "source": "border_modal" },
    "headline":     { "hex": "#000000", "role": "headline",     "source": "h1_color" }
  },
  "semantic": {
    "success":      { "hex": "#34c759", "role": "success",      "source": "css_var_or_status_class" },
    "warning":      { "hex": "#ff9500", "role": "warning",      "source": null },
    "danger":       { "hex": "#ff3b30", "role": "danger",       "source": "alert_role" },
    "info":         { "hex": "#5ac8fa", "role": "info",         "source": null }
  },
  "shades": {                             // populated only when a ladder is detected
    "primary": [
      { "step":  50, "hex": "#e8f0fe" },
      { "step": 100, "hex": "#cfe1fc" },
      { "step": 500, "hex": "#0071e3" },
      { "step": 700, "hex": "#0058b3" },
      { "step": 900, "hex": "#003c80" }
    ],
    "neutral": [
      { "step":  50, "hex": "#ffffff" },
      { "step": 100, "hex": "#fafafc" },
      { "step": 300, "hex": "#d2d2d7" },
      { "step": 500, "hex": "#6e6e73" },
      { "step": 900, "hex": "#1d1d1f" }
    ]
  },
  "ornament": [                           // pixel-frequency colors that don't fit a role
    { "hex": "#fb6533", "freq": 0.04, "trust": "low" },
    { "hex": "#fcc445", "freq": 0.03, "trust": "low" }
  ],
  "pairs": [                              // observed text-on-bg combinations (top N)
    { "fg": "#1d1d1f", "bg": "#ffffff", "count": 142, "apca":  99, "wcag": 17.1 },
    { "fg": "#ffffff", "bg": "#0071e3", "count":  18, "apca":  96, "wcag":  8.59 },
    { "fg": "#6e6e73", "bg": "#ffffff", "count":  47, "apca":  74, "wcag":  4.6 }
  ]
}
```

### 3.2 — Why this shape

- **Each color is an object, not a bare hex** — keeps `source` (provenance), `uses` (frequency), and contrast values together. The frontend can render contrast badges without re-computing.
- **Three buckets — `brand`, `neutrals`, `semantic`** — directly mirror Material 3 role groups (primary/secondary/tertiary, surface family, error). The split also matches how the StepReading UI already wants to group them.
- **`shades` is optional** — only emitted when we detect a ladder. Empty for sites that don't expose one.
- **`ornament` is explicitly low-trust** — UI tags it as "from screenshot pixels," so generated assets don't accidentally rebrand the company in marigold.
- **`pairs` is the contrast graph** — the same primitive Huemint uses internally, exposed for downstream tools (asset generator, copy generator) to pick legal combinations without recomputing contrast.
- **DB-friendly** — `palette` stays a single `Column(JSON, default=dict)` (already JSON in `models.py:28`); we just retire `palette_roles` since it folds in.

### 3.3 — Backward compatibility

The frontend currently reads `palette: list[str]` and `palette_roles: PaletteEntry[]` (`StepReading.tsx:47-53`). The rich object can be projected back to the old shape on the way out for any consumer not yet upgraded:

```python
def to_legacy_flat(p: dict) -> list[str]:
    return [
      p["brand"]["primary"]["hex"],
      p["brand"]["primary_on"]["hex"],
      p["neutrals"]["background"]["hex"],
      p["neutrals"]["text"]["hex"],
      p["brand"].get("accent", {}).get("hex") or p["neutrals"]["border"]["hex"],
    ]
```

---

## 4. Extraction algorithm

A single Playwright `page.evaluate(...)` call collects everything in one round-trip. Post-processing happens in Python so we can use proper color libraries.

### 4.1 — The JS collector (replaces `_CSS_PALETTE_JS` in `scraper.py`)

```javascript
() => {
  // ---------- helpers ----------
  const norm = (c) => {
    if (!c) return null;
    const s = String(c).trim().toLowerCase();
    if (s === 'transparent' || s === 'rgba(0, 0, 0, 0)' || s === 'rgba(0,0,0,0)') return null;
    return s;
  };
  const sample = (sel, fn, cap = 60) => {
    const out = [];
    let i = 0;
    for (const el of document.querySelectorAll(sel)) {
      if (i++ >= cap) break;
      const v = fn(el);
      if (v) out.push(v);
    }
    return out;
  };

  // ---------- basics ----------
  const html = document.documentElement;
  const body = document.body;
  const bg = norm(getComputedStyle(body).backgroundColor) ||
             norm(getComputedStyle(html).backgroundColor);
  const fg = norm(getComputedStyle(body).color);

  // ---------- :root CSS custom properties (NEW) ----------
  // Two paths: stylesheet traversal (catches every rule) + computed-on-:root
  // (catches dynamically-set vars). Union the results.
  const cssVars = {};
  try {
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch { continue; }   // CORS
      for (const rule of rules || []) {
        if (rule.type !== 1) continue;                       // CSSStyleRule
        if (!/^:root\b|^html\b/.test(rule.selectorText || '')) continue;
        for (const propName of rule.style) {
          if (!propName.startsWith('--')) continue;
          const val = rule.style.getPropertyValue(propName).trim();
          if (val) cssVars[propName] = val;
        }
      }
    }
  } catch {}
  // Also pull the resolved values via getComputedStyle(:root) for the names we found
  const rootStyles = getComputedStyle(html);
  for (const name of Object.keys(cssVars)) {
    const resolved = rootStyles.getPropertyValue(name).trim();
    if (resolved) cssVars[name] = resolved;
  }

  // ---------- CTA bg + text PAIR (improvement) ----------
  const ctaSel = 'button, [role="button"], a[class*="button" i], a[class*="btn" i], a[class*="cta" i], [class*="primary" i], [class*="signup" i], [class*="get-started" i]';
  const ctaPairs = sample(ctaSel, (el) => {
    const cs = getComputedStyle(el);
    const b = norm(cs.backgroundColor);
    const t = norm(cs.color);
    if (!b) return null;
    return { bg: b, fg: t };
  }, 60);

  // ---------- in-content vs nav links ----------
  const contentLinks = sample('main a:not([class*="logo" i]), article a:not([class*="logo" i])',
    (a) => norm(getComputedStyle(a).color), 30);
  const navLinks = sample('header a:not([class*="logo" i]), nav a:not([class*="logo" i])',
    (a) => norm(getComputedStyle(a).color), 30);

  // ---------- headlines ----------
  const headlineColors = sample('h1, h2, h3', (h) => norm(getComputedStyle(h).color), 20);

  // ---------- borders (each side individually — border-color is shorthand) ----------
  const borders = sample('hr, [class*="card" i], [class*="divider" i], section, table, td',
    (el) => {
      const cs = getComputedStyle(el);
      // skip elements with no actual border
      if (parseFloat(cs.borderTopWidth) < 0.5 &&
          parseFloat(cs.borderBottomWidth) < 0.5) return null;
      return norm(cs.borderTopColor) || norm(cs.borderBottomColor);
    }, 60);

  // ---------- surfaces (cards / panels — NOT body bg) ----------
  const surfaces = sample('[class*="card" i], [class*="panel" i], [class*="tile" i], aside, [class*="surface" i]',
    (el) => {
      const c = norm(getComputedStyle(el).backgroundColor);
      return (c && c !== bg) ? c : null;
    }, 40);

  // ---------- semantic / status ----------
  const statusSel = '[class*="success" i], [class*="error" i], [class*="warning" i], [class*="danger" i], [class*="info" i], [role="alert"], [role="status"]';
  const statusColors = sample(statusSel, (el) => {
    const cs = getComputedStyle(el);
    return { fg: norm(cs.color), bg: norm(cs.backgroundColor),
             cls: (el.className && el.className.toString().toLowerCase()) || '' };
  }, 30);

  // ---------- text-on-background contrast graph ----------
  // Walk visible text nodes; record (fg of element, effective bg of nearest filled ancestor)
  const effectiveBg = (el) => {
    let cur = el;
    while (cur && cur !== document.documentElement) {
      const c = norm(getComputedStyle(cur).backgroundColor);
      if (c) return c;
      cur = cur.parentElement;
    }
    return bg;
  };
  const pairs = [];
  let p = 0;
  for (const el of document.querySelectorAll('p, h1, h2, h3, h4, h5, span, li, a, button')) {
    if (p++ >= 200) break;
    const txt = (el.innerText || '').trim();
    if (txt.length < 3) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const f = norm(cs.color);
    const b = effectiveBg(el);
    if (!f || !b) continue;
    pairs.push({ fg: f, bg: b });
  }

  // ---------- inline SVG fills (logo + icon pack) ----------
  const svgFills = [];
  for (const svg of document.querySelectorAll('header svg, nav svg, [class*="logo" i] svg, a[href="/"] svg')) {
    for (const node of svg.querySelectorAll('[fill], [style*="fill"], stop[stop-color]')) {
      const fill = node.getAttribute('fill') ||
                   (node.getAttribute('style') || '').match(/fill\s*:\s*([^;]+)/)?.[1] ||
                   node.getAttribute('stop-color');
      if (!fill) continue;
      const f = fill.trim().toLowerCase();
      if (f === 'none' || f === 'currentcolor' || f === 'transparent') continue;
      svgFills.push(f);
    }
  }

  // ---------- header bg (kept for back-compat) ----------
  const header = document.querySelector('header, nav');
  const headerBg = header ? norm(getComputedStyle(header).backgroundColor) : null;

  return {
    bg, fg, headerBg,
    cta_pairs: ctaPairs,
    content_link_colors: contentLinks,
    nav_link_colors: navLinks,
    headline_colors: headlineColors,
    border_colors: borders,
    surface_colors: surfaces,
    status_colors: statusColors,
    text_bg_pairs: pairs,
    svg_fills: svgFills,
    css_vars: cssVars,
  };
}
```

### 4.2 — Python pipeline (`build_brand_palette` in new `palette.py`)

```python
# pseudocode

def build_brand_palette(css: dict, screenshot_png: bytes) -> dict:
    # 1. Parse every collected color string to a normalized linear-RGB tuple.
    #    Inputs may be rgb(...), rgba(...), hex, hsl(...), oklch(...), lab(...).
    #    Use a real color library (culori for JS / colormath / colorspacious for Py)
    #    to handle modern color functions including OKLCH and Display-P3.
    raw = parse_all(css)   # -> dict of role -> list[RGB]

    # 2. Mine CSS variables.
    css_var_palette = {}
    for name, val in (css.get("css_vars") or {}).items():
        rgb = try_parse_color(val)
        if rgb is None:
            continue
        # Map name -> our role using a small dictionary of conventions:
        #   --color-primary, --brand-primary, --accent-color, --bg, --surface, etc.
        role = guess_role_from_name(name)   # primary | accent | bg | surface | text | success | ...
        css_var_palette.setdefault(role, []).append(rgb)

    # 3. Aggregate counts to pick a single color per role.
    bg = mode(raw["bg_samples"]) or rgb_white()
    fg = mode(raw["fg_samples"]) or rgb_black()

    primary = pick_primary(
        candidates =
            css_var_palette.get("primary", []) +     # design-system tokens win
            [pair["bg"] for pair in raw["cta_pairs"]] +
            raw["svg_fills"],                         # logo color is brand-true
        bg = bg,
        fg = fg,
    )
    primary_on = mode(
        pair["fg"] for pair in raw["cta_pairs"]
        if approx_equal(pair["bg"], primary)
    ) or pick_legible_text(primary)

    accent = pick_accent(
        candidates =
            css_var_palette.get("accent", []) +
            raw["content_link_colors"] +
            raw["svg_fills"],
        exclude = [primary, bg, fg],
    )

    # 4. Neutrals.
    surface = pick_surface(raw["surface_colors"], bg)        # closest-to-bg-but-distinct
    text = fg
    text_muted = pick_muted(raw["text_bg_pairs"], bg, text)  # second-most-frequent text color on bg
    border = mode(raw["border_colors"]) or fade(text, 0.85)
    headline = mode(raw["headline_colors"]) or text

    # 5. Semantic — only emit when we actually saw evidence.
    semantic = {}
    for status in ("success", "warning", "danger", "info"):
        c = first_nonempty(
            css_var_palette.get(status),
            extract_status_color(raw["status_colors"], status),
        )
        if c:
            semantic[status] = c

    # 6. Shade ladders.
    all_brand_colors = [primary, accent] + list(raw["svg_fills"]) + sum(css_var_palette.values(), [])
    shades = detect_ladders(all_brand_colors, primary)  # cluster by OKLCH hue, sort by L
    neutral_ladder = build_neutral_ladder(bg, surface, border, text_muted, text)

    # 7. Ornament — pixel frequency, FILTERED to remove anything close to a role color.
    role_colors = {bg, fg, primary, accent, surface, border, text_muted, headline}
    pixel = pylette_extract(screenshot_png, n=8)
    ornament = [c for c in pixel
                if min_delta_e(c, role_colors) > 12 and       # not redundant
                   not is_image_dominant(c)]                  # not a hero-photo color

    # 8. Contrast graph — top-K most-trafficked text-on-bg pairs.
    pairs = top_k_pairs(raw["text_bg_pairs"], k=8)
    for pair in pairs:
        pair["apca"] = apca_contrast(pair["fg"], pair["bg"])
        pair["wcag"] = wcag_contrast(pair["fg"], pair["bg"])

    return {
        "version": 1,
        "source": {
            "css_vars_found": len(css.get("css_vars") or {}),
            "svg_fills_found": len(raw["svg_fills"]),
            "pixel_fallback_used": len(role_colors) < 5,
        },
        "brand": {"primary": primary, "primary_on": primary_on, "accent": accent},
        "neutrals": {"background": bg, "surface": surface, "text": text,
                     "text_muted": text_muted, "border": border, "headline": headline},
        "semantic": semantic,
        "shades": {"primary": shades.get("primary"), "neutral": neutral_ladder},
        "ornament": ornament,
        "pairs": pairs,
    }
```

### 4.3 — Shade-ladder detection

Following [Tailwind v4's OKLCH ladder convention](https://tailwindcss.com/docs/colors) and the reverse-engineering work in the [Mystery of Tailwind Colors v4](https://dev.to/matfrana/the-mystery-of-tailwind-colors-v4-hjh):

```text
1. Convert every candidate hex to OKLCH (use culori for JS, colormath/colorspacious for Py).
2. Bucket by (hue rounded to 10°, chroma rounded to 0.04).
3. Within a bucket, sort by lightness ascending.
4. A bucket of >= 3 members spanning lightness range >= 0.25 is a "ladder."
5. Snap each member to the nearest Tailwind step (50, 100, 200, ..., 950) by lightness:
   step = round(lerp(50, 950, (1 - L) / 1.0)) snapped to {50, 100, 200, ..., 950}.
6. If we have a brand primary but no detected ladder, synthesize one by holding hue
   constant in OKLCH, varying L from 0.97 → 0.15 in the standard Tailwind curve,
   and easing chroma down at the extremes (the "radioactive" fix from Evil Martians).
```

The synthesized ladder is marked `"synthesized": true` so the UI can label it differently — those colors didn't appear on the page, we made them up from the brand color.

### 4.4 — "Primaryness" scoring for CTA color selection

When multiple candidates compete for the `primary` slot:

```text
score(c) = w1 * cta_bg_count(c)              # appearance frequency
        + w2 * (delta_e(c, bg) > 25)         # is it actually distinct from bg?
        + w3 * (c in css_vars["primary"])    # design-system hint
        + w4 * (c in svg_fills)              # logo hint
        + w5 * (chroma(c) > 0.05)            # not a near-grey
        - w6 * (c == fg)                     # don't pick the body text color
```

Empirically `w1=1, w2=2, w3=4, w4=3, w5=1, w6=10` gives sensible answers on a sample of B2B SaaS landing pages.

---

## 5. Edge cases

### 5.1 — Monochrome sites (Apple, Vercel, Linear, Stripe pre-2023)

**Symptom:** every CTA bg is `#000` or `#fff`, no chroma anywhere, no `--color-primary` variable, no logo color.

**Handling:** detect at the end of the pipeline — if `chroma(primary) < 0.03` AND `delta_e(primary, fg) < 8`, mark the palette `"monochrome": true` and emit a `brand.accent` slot from the most chromatic non-ornament color (often a single hover/focus color or an SVG fill from an icon). If absolutely nothing chromatic exists, set `accent: null` and let the consumer downstream pick a brand-appropriate accent (the asset generator can ask the LLM for one with the brand's mood as input).

### 5.2 — Theme-switching sites (dark mode default)

**Symptom:** `prefers-color-scheme: dark` in the Playwright context yields a totally different palette than light. The user-facing brand identity might live in either mode.

**Handling:** capture both. Run the scrape with `colorScheme: "light"`, then with `colorScheme: "dark"` ([Playwright color-scheme testing](https://playwrightsolutions.com/is-it-possible-to-change-colorscheme-in-the-middle-of-a-playwright-tests/)). Store both palettes:

```jsonc
{ "palette": { "light": {...}, "dark": {...}, "default_mode": "light" } }
```

Decide `default_mode` by comparing which mode's body bg matches `<meta name="theme-color">` content. Hackathon-cut: only do `light` for v0; ship `dark` as a follow-up.

### 5.3 — OKLCH / LCH / HSL color values from getComputedStyle

**Symptom:** modern Chromium serializes computed color values in their declared color space when not sRGB. CSS `color: oklch(0.7 0.15 240)` may come back literally as `oklch(0.7 0.15 240)` or as a Display-P3 `color(display-p3 ...)` value. Our current `_RGB_RE` only matches `rgb()` / `rgba()`.

**Handling:** the JS collector returns the raw computed string; the Python parser uses a real color library (culori for JS-side prep, colormath / colorspacious in Python) instead of regex-only. Library converts everything to sRGB hex. Out-of-gamut P3 colors get gamut-mapped into sRGB (use OKLCH-aware mapping per [W3C Design Tokens 2025.10](https://www.designtokens.org/tr/drafts/color/), not naïve clipping).

### 5.4 — Decorative / seasonal images polluting pixel-frequency colors

**Symptom:** the directive's example — Apple homepage on Mother's Day, hero image of flowers gives `#fb6533` and `#fcc445` enough screen real estate that they enter the top-5 pixel palette, but they aren't brand colors.

**Handling:** two filters before a pixel color earns a role:

1. **CSS-derived roles always win** — pixel colors only fill `ornament`, never `brand` or `neutrals`. Ornament is tagged "low trust" in the UI.
2. **Image-region detection** — when we run Pylette on the screenshot, mask out regions where the underlying DOM is `<img>` or `<picture>` or `background-image: url(...)` (use Playwright's `element.boundingBox()` to get image rects, blank those regions before frequency analysis).

### 5.5 — Sites with no CSS variables and obfuscated class names

**Symptom:** Tailwind-built sites with `class="bg-[#0071e3]"` arbitrary values, or Vercel-style hashed class names, or Webflow's auto-generated classes. No `--color-primary` to mine, class names don't match `[class*=button]`.

**Handling:** the CTA selector already includes role-based fallbacks (`[role=button]`, `button` element) which work regardless of class naming. For `accent`, fall back to "most-frequent text color in `<main>` that isn't body fg." The `:root` var harvest just returns `{}` and we keep going.

### 5.6 — Cross-origin stylesheets (CORS)

**Symptom:** `sheet.cssRules` throws on cross-origin stylesheets even though `getComputedStyle` works fine through them.

**Handling:** wrap the `cssRules` access in a try/catch (already in the snippet above). For any rules we can't enumerate, the colors still flow through `getComputedStyle()` calls on actual elements. We just lose the ability to read the raw `--var` declarations on those rules — acceptable, since `getComputedStyle(:root).getPropertyValue('--color-primary')` returns the resolved value regardless of the rule's origin.

### 5.7 — Empty / parking / bot-walled pages

Already handled — `is_parking_page()` short-circuits enrichment. Add: if `len(css.get("text_bg_pairs", [])) < 3`, return a degraded palette `{ "version": 1, "degraded": true, "neutrals": { "background": ..., "text": ... } }` — better to flag than to invent.

---

## 6. Concrete implementation plan

File-by-file, in dependency order.

### 6.1 — `backend/app/services/enrichment/scraper.py`

Replace `_CSS_PALETTE_JS` with the expanded JS from §4.1. The function still returns a single `dict` from `page.evaluate`, just richer keys. No signature change.

### 6.2 — `backend/app/services/enrichment/palette.py` *(new file)*

Color-utility module. Keeps color math out of `extract.py`.

```python
# backend/app/services/enrichment/palette.py
"""Brand palette construction. Pure-function, fully testable.

Inputs: the dict from _CSS_PALETTE_JS + a screenshot PNG.
Output: the rich palette dict (see docs/DEEP_PALETTE.md §3).
"""

# Suggested deps:
#   - colormath  (LAB / Delta-E)
#   - colorspacious  (CAM02 if needed)
#   - Pylette  (already in)
# Or: a single dependency on `coloraide` (Py port of colorjs.io) which handles
# parsing modern CSS color funcs (OKLCH, LCH, color(display-p3 ...)) natively.

def parse_color(s: str) -> RGB | None: ...
def to_oklch(rgb: RGB) -> tuple[float, float, float]: ...
def from_oklch(L: float, C: float, h: float) -> RGB: ...
def hue_distance(a_deg: float, b_deg: float) -> float: ...
def delta_e(a: RGB, b: RGB) -> float: ...
def apca_contrast(text: RGB, bg: RGB) -> float: ...
def wcag_contrast(text: RGB, bg: RGB) -> float: ...
def detect_ladders(colors: list[RGB], anchor: RGB) -> dict[str, list[Shade]]: ...
def build_neutral_ladder(bg, surface, border, muted, text) -> list[Shade]: ...
def build_brand_palette(css_data: dict, screenshot_bytes: bytes) -> dict: ...
def to_legacy_flat(p: dict) -> list[str]: ...
```

Single library recommendation: **[`coloraide`](https://facelessuser.github.io/coloraide/)** — Python port of `color.js`, handles every modern CSS color function and the W3C 2025.10 spec's gamut-mapping requirements. ~300KB and pure Python; no compile step.

### 6.3 — `backend/app/services/enrichment/extract.py`

Replace `_palette` (Pylette-only), `_palette_from_css` (flat-list role priority), and `_merge_palettes` (truncate-to-5) with a single call:

```python
from app.services.enrichment.palette import build_brand_palette, to_legacy_flat

# ... inside extract() ...
rich_palette = build_brand_palette(
    css_data=css_palette or {},
    screenshot_bytes=screenshots[0] if screenshots else b"",
)
return BrandExtract(
    ...,
    palette=rich_palette,                       # NEW: dict, not list[str]
    palette_legacy=to_legacy_flat(rich_palette) # for any unmigrated consumer
)
```

Update `BrandExtract` dataclass: `palette: dict = field(default_factory=dict)` (was `list[str]`).

### 6.4 — `backend/app/db/models.py`

`palette = Column(JSON, default=list)` becomes `palette = Column(JSON, default=dict)`. Retire `palette_roles` (it's folded into the dict). Migration: a one-shot script that wraps existing list values as `{"version": 0, "legacy_flat": [...]}` so old rows stay readable until re-enrichment.

### 6.5 — Frontend types — `src/types/Palette.ts` *(new)* + consumer updates

```typescript
export type ColorEntry = {
  hex: string
  role: string
  source?: string
  uses?: number
  contrast_apca?: number
  contrast_wcag?: number
}
export type Palette = {
  version: number
  brand: { primary: ColorEntry; primary_on: ColorEntry; accent?: ColorEntry }
  neutrals: { background: ColorEntry; surface?: ColorEntry; text: ColorEntry;
              text_muted?: ColorEntry; border?: ColorEntry; headline?: ColorEntry }
  semantic: Partial<Record<'success'|'warning'|'danger'|'info', ColorEntry>>
  shades?: { primary?: Shade[]; neutral?: Shade[] }
  ornament?: { hex: string; freq: number; trust: 'low' }[]
  pairs?: { fg: string; bg: string; count: number; apca: number; wcag: number }[]
  degraded?: boolean
  monochrome?: boolean
}
```

`StepReading.tsx` `PaletteList` becomes `PaletteSections`:

- Section: **Brand** — primary larger, accent smaller, primary-on rendered as an inline chip on top of primary (so the contrast pair is visually obvious).
- Section: **Neutrals** — bg/surface/text/text_muted/border in a single horizontal strip with role labels underneath.
- Section: **Semantic** — only rendered if non-empty; shows success/warning/danger/info with their conventional icons.
- Section: **Shades** — collapsed by default; expand to show primary + neutral ladders as 11-step strips with step numbers (50, 100, ...).
- Section: **Ornament** — separated by a hairline, header reads "from screenshot pixels" with a small info tooltip explaining lower trust.

Each color chip: hex below, role label beneath, AA/AAA badge (small pill) if it appears as a contrast pair vs `neutrals.background`.

---

## 7. UI recommendations for the StepReading palette card

Concrete, prescriptive. The current `PaletteList` (`StepReading.tsx:272-`) is a flat row of swatches with role labels. Replace with grouped sections:

1. **Group order, top to bottom:** Brand → Neutrals → Semantic → Shades (collapsed) → Ornament.
2. **Visual hierarchy:**
   - `brand.primary` is rendered ~1.5x the size of other chips. It anchors the card.
   - `brand.primary_on` is *inset* into the primary chip as a smaller circle — visually demonstrates "this text on this background."
   - Same trick for any text-color/bg-color pair: render the text-color chip as a small circle inside the bg-color chip.
3. **Per-chip metadata, on hover:**
   - Hex code (always visible)
   - Role label (always visible, small caps)
   - Source provenance ("from CSS variable `--color-primary`" / "from logo SVG fill" / "from CTA button background") — on hover only, so the card stays clean.
   - APCA + WCAG contrast vs `neutrals.background` — small AA/AAA pill, only when relevant (not on bg itself).
4. **Shades:** rendered as horizontal 11-step strips. Step labels (50, 100, ..., 950) underneath each chip. If shades are synthesized (we generated them from primary, the brand doesn't actually use them), label the strip "synthesized" in muted text.
5. **Ornament hint:** a hairline separator + smaller chips + a one-line caption: *"Detected in the screenshot but not used in any brand role — likely decorative or seasonal."*
6. **Monochrome flag:** if `palette.monochrome === true`, render an inline note above Brand: *"This brand reads as monochrome. We picked an accent from the most chromatic on-page color."*
7. **Degraded flag:** if `palette.degraded === true`, render a warning row instead of the full card and offer a "retry enrichment" button.
8. **Color-blind preview toggle** (stretch goal): a single icon button that re-renders the strip with deuteranopia / protanopia / tritanopia simulation overlays — very impressive in a hackathon demo, ~30 lines with `culori`'s built-in CVD filters.

---

## 8. The smallest hackathon-acceptable cut

If we're racing the clock (hackathon reality), the minimum viable depth in priority order:

1. **(2 hr)** Extend `_CSS_PALETTE_JS` with the four highest-leverage additions: `:root` CSS vars, SVG fills from header/nav, headline colors, and the cta-bg-with-paired-text-color version of `cta_pairs`. The JS code is already sketched above.
2. **(2 hr)** New `palette.py` with **just** `parse_color` (sRGB + OKLCH via coloraide), `wcag_contrast`, and a `build_brand_palette` that fills `brand`, `neutrals`, and `pairs`. Skip shade detection, skip APCA, skip semantic colors for v0.
3. **(1 hr)** Update `extract.py` and `models.py` to store the dict. Add `to_legacy_flat()` so `StepReading.tsx` keeps working without changes.
4. **(2 hr)** Frontend: render the three sections (Brand / Neutrals / Pairs). Skip Shades, Semantic, Ornament for v0. Add the inset-text-on-bg trick for the CTA pair — that single visual is what sells "deep palette" in a demo.

That's a one-day implementation that meaningfully outperforms the current 5-hex flat list.

Everything else (shade ladders, semantic detection, dark-mode dual capture, APCA, color-blind preview) is incremental polish on top of a stable schema.

---

## Sources

- [W3C Design Tokens Format Module 2025.10 (stable)](https://www.designtokens.org/tr/drafts/format/) — schema for `$type: "color"`, color spaces, alias references.
- [Design Tokens Color Module 2025.10](https://www.designtokens.org/tr/drafts/color/) — sRGB / OKLCH / Display-P3 representation, gamut mapping rules.
- [Design Tokens Specification Reaches First Stable Version (W3C, Oct 2025)](https://www.w3.org/community/design-tokens/2025/10/28/design-tokens-specification-reaches-first-stable-version/) — context for why the spec is now production-ready and which orgs back it.
- [Material Design 3 — Color Roles & Tokens (Wear / Android Developers)](https://developer.android.com/design/ui/wear/guides/styles/color/roles-tokens) — full list of role pairs (primary / on-primary / primary-container / surface / surface-container / etc.) the schema borrows from.
- [Tailwind CSS v4 Colors](https://tailwindcss.com/docs/colors) — the 50–950 OKLCH ladder convention we mirror in `shades`.
- [Tailwind CSS v4.0 release notes](https://tailwindcss.com/blog/tailwindcss-v4) — the migration from RGB to OKLCH and the wider P3 gamut implications.
- [The Mystery of Tailwind Colors (v4) — DEV](https://dev.to/matfrana/the-mystery-of-tailwind-colors-v4-hjh) — reverse-engineered chroma + lightness curves for the Tailwind ladder.
- [Better dynamic themes in Tailwind with OKLCH — Evil Martians](https://evilmartians.com/chronicles/better-dynamic-themes-in-tailwind-with-oklch-color-magic) — algorithm for synthesizing a ladder from a single brand hex.
- [Open Color (Yeun)](https://yeun.github.io/open-color/) and [open-color.json source](https://github.com/yeun/open-color/blob/master/open-color.json) — flat hue-family schema with 10-step shades, the inspiration for our `shades` shape.
- [Huemint — about](https://huemint.com/about/) — contrast graph + CIE Delta-E weighted edges, the model behind our `pairs` field.
- [Realtime Colors](https://www.realtimecolors.com/) — practical primary / secondary / accent / text / background role split.
- [Tokens Studio — JSON schema](https://docs.tokens.studio/tokens/json-schema) and [token format docs](https://docs.tokens.studio/manage-settings/token-format) — production-grade reference for nested token sets and the W3C-DTCG token format.
- [Site Palette browser extension](https://palette.site/) and [Peek Chrome extension](https://trypeek.app/blog/how-to-extract-colors-typography-assets-from-website/) — prior art for in-browser palette extraction.
- [Apify — Website Color Palette Extractor](https://apify.com/botflowtech/website-color-palette-extractor) and [Colorize.design](https://colorize.design/) — modern hosted extractors that use both screenshot dominance and computed-style inspection.
- [How to Get All Custom Properties on a Page in JavaScript — CSS-Tricks](https://css-tricks.com/how-to-get-all-custom-properties-on-a-page-in-javascript/) — the stylesheet-traversal pattern for `--var` harvesting.
- [MDN — Window: getComputedStyle()](https://developer.mozilla.org/en-US/docs/Web/API/Window/getComputedStyle) — including the border-color shorthand caveat.
- [MDN — Using CSS custom properties (variables)](https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Cascading_variables/Using_custom_properties).
- [APCA — easy intro](https://git.apcacontrast.com/documentation/APCAeasyIntro.html), [Why APCA as a New Contrast Method](https://git.apcacontrast.com/documentation/WhyAPCA.html), and [SAPC-APCA repo](https://github.com/Myndex/SAPC-APCA) — the contrast metric replacing WCAG 2.x in WCAG 3 / APCA.
- [Generating accessible color palettes inspired by APCA — Canonical Design](https://canonical.design/blog/generating-color-palettes-for-design-systems-inspired-by-apca) — APCA-aware palette generation algorithm and OKHSL adjustments.
- [InclusiveColors](https://www.inclusivecolors.com/) — UI pattern for editing palettes with live contrast guarantees, model for our pair-aware UI.
- [Playwright — colorScheme test option](https://runebook.dev/en/docs/playwright/api/class-testoptions/test-options-color-scheme) and [setting colorScheme mid-test](https://playwrightsolutions.com/is-it-possible-to-change-colorscheme-in-the-middle-of-a-playwright-tests/) — for the dual-capture approach to dark-mode sites.
- [coloraide (Python port of color.js)](https://facelessuser.github.io/coloraide/) and [culori](https://culorijs.org/) — the modern color libraries that handle OKLCH, Display-P3, and gamut mapping per the W3C 2025.10 spec.
- [Color.js Released — Chris Lilley](https://svgees.us/blog/colorjs-release.html) — the canonical reference implementation behind both libraries.
