from dataclasses import dataclass

from app.services.enrichment.browser import get_browser

VIEWPORT_WIDTH = 1440
VIEWPORT_HEIGHT = 900


@dataclass
class ScrapedSite:
    url: str
    final_url: str
    html: str
    screenshots: list[bytes]
    css_palette: dict | None = None


@dataclass
class ScrapedLite:
    url: str
    final_url: str
    html: str


_ANIMATION_KILL_CSS = """
*, *::before, *::after {
  animation-duration: 0.001ms !important;
  animation-delay: 0ms !important;
  animation-iteration-count: 1 !important;
  transition-duration: 0.001ms !important;
  transition-delay: 0ms !important;
  scroll-behavior: auto !important;
}
"""

_IMAGES_LOADED = """
() => {
  const imgs = Array.from(document.images);
  if (imgs.length === 0) return true;
  return imgs.every(img => img.complete && (img.naturalWidth > 0 || img.loading === 'lazy'));
}
"""

_CSS_PALETTE_JS = """
() => {
  const norm = (c) => {
    if (!c) return null;
    const s = String(c).trim().toLowerCase();
    if (s === 'transparent' || s === 'rgba(0, 0, 0, 0)' || s === 'rgba(0,0,0,0)') return null;
    return s;
  };
  const sample = (sel, props, max) => {
    const out = [];
    let i = 0;
    for (const el of document.querySelectorAll(sel)) {
      if (i++ >= max) break;
      const cs = getComputedStyle(el);
      const row = {};
      for (const p of props) row[p] = cs.getPropertyValue(p).trim();
      out.push(row);
    }
    return out;
  };
  const html = document.documentElement;
  const body = document.body;
  const bg = norm(getComputedStyle(body).backgroundColor) ||
             norm(getComputedStyle(html).backgroundColor);
  const fg = norm(getComputedStyle(body).color);

  const ctaSel = 'button, [role="button"], a[class*="button" i], a[class*="btn" i], a[class*="cta" i], [class*="primary" i], [class*="signup" i], [class*="get-started" i]';
  const ctaBgs = [];
  const ctaTexts = [];
  let n = 0;
  for (const el of document.querySelectorAll(ctaSel)) {
    if (n++ >= 60) break;
    const bgC = norm(getComputedStyle(el).backgroundColor);
    if (bgC) ctaBgs.push(bgC);
    const fgC = norm(getComputedStyle(el).color);
    if (fgC) ctaTexts.push(fgC);
  }

  const linkColors = [];
  let m = 0;
  for (const a of document.querySelectorAll('a:not([class*="logo" i])')) {
    if (m++ >= 30) break;
    const c = norm(getComputedStyle(a).color);
    if (c) linkColors.push(c);
  }

  const header = document.querySelector('header, nav');
  const headerBg = header ? norm(getComputedStyle(header).backgroundColor) : null;

  // ── Identity samples (typography, radii, shadows, buttons) ─────────────
  const typography = {
    body: sample('body', ['font-family', 'font-size', 'line-height', 'color'], 1)[0] || null,
    h1: sample('h1', ['font-family', 'font-size', 'font-weight', 'line-height', 'letter-spacing', 'color'], 5),
    h2: sample('h2', ['font-family', 'font-size', 'font-weight', 'line-height'], 5),
    h3: sample('h3', ['font-family', 'font-size', 'font-weight'], 5),
    p: sample('p', ['font-size', 'line-height'], 5),
    code: sample('code, pre', ['font-family', 'font-size'], 3),
  };

  const buttonSel = 'button[type="submit"], button[class*="primary" i], a[class*="cta" i], a[class*="primary" i], a[class*="signup" i], a[class*="get-started" i]';
  const buttons = sample(buttonSel,
    ['background-color', 'color', 'border-radius', 'padding', 'font-size', 'font-weight', 'border', 'box-shadow'],
    8
  );

  const radiusSamples = [];
  let r = 0;
  for (const el of document.querySelectorAll('button, input, [class*="card" i], [class*="rounded" i], [class*="btn" i], a[class*="button" i]')) {
    if (r++ >= 40) break;
    const v = getComputedStyle(el).borderRadius;
    if (v && v !== '0px') radiusSamples.push(v);
  }

  const shadowSamples = [];
  let s = 0;
  for (const el of document.querySelectorAll('[class*="card" i], [class*="shadow" i], section, header, nav, button[class*="primary" i]')) {
    if (s++ >= 40) break;
    const v = getComputedStyle(el).boxShadow;
    if (v && v !== 'none') shadowSamples.push(v);
  }

  // CSS custom properties on :root (when sites expose design tokens)
  const cssVars = {};
  let cssVarCount = 0;
  try {
    const rootStyle = getComputedStyle(html);
    for (let i = 0; i < rootStyle.length; i++) {
      const name = rootStyle[i];
      if (name.startsWith('--')) {
        cssVars[name] = rootStyle.getPropertyValue(name).trim();
        cssVarCount++;
        if (cssVarCount >= 100) break;
      }
    }
  } catch {}

  return {
    bg, fg, headerBg,
    cta_bgs: ctaBgs,
    cta_texts: ctaTexts,
    link_colors: linkColors,
    typography,
    buttons,
    radii: radiusSamples,
    shadows: shadowSamples,
    css_vars: cssVars,
  };
}
"""


async def scrape(url: str, num_shots: int = 4) -> ScrapedSite:
    browser = get_browser()
    ctx = await browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        reduced_motion="reduce",
    )
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_load_state("load", timeout=10000)

        try:
            await page.wait_for_function(
                "document.body && document.body.innerText.trim().length > 200",
                timeout=8000,
            )
        except Exception:
            pass

        # Read CSS samples (palette + identity tokens) BEFORE the animation
        # kill — otherwise computed transition / animation values would be
        # zeroed out for any future motion extraction.
        try:
            css_palette = await page.evaluate(_CSS_PALETTE_JS)
        except Exception:
            css_palette = None

        try:
            await page.add_style_tag(content=_ANIMATION_KILL_CSS)
        except Exception:
            pass

        await page.evaluate(
            "window.scrollTo({ top: document.body.scrollHeight, behavior: 'instant' })"
        )
        await page.wait_for_timeout(900)

        try:
            await page.wait_for_function(_IMAGES_LOADED, timeout=6000)
        except Exception:
            pass

        scroll_height = await page.evaluate(
            "document.documentElement.scrollHeight"
        )
        if scroll_height <= VIEWPORT_HEIGHT or num_shots <= 1:
            positions = [0]
        else:
            usable = scroll_height - VIEWPORT_HEIGHT
            positions = [
                int(usable * i / (num_shots - 1)) for i in range(num_shots)
            ]

        screenshots: list[bytes] = []
        for pos in positions:
            await page.evaluate(
                f"window.scrollTo({{ top: {pos}, behavior: 'instant' }})"
            )
            await page.wait_for_timeout(1200)
            screenshots.append(await page.screenshot(type="png", full_page=False))

        await page.evaluate(
            "window.scrollTo({ top: 0, behavior: 'instant' })"
        )
        await page.wait_for_timeout(200)

        final_url = page.url
        html = await page.content()

        return ScrapedSite(
            url=url,
            final_url=final_url,
            html=html,
            screenshots=screenshots,
            css_palette=css_palette,
        )
    finally:
        await ctx.close()


async def scrape_lite(url: str) -> ScrapedLite:
    """Fast HTML-only scrape — used for competitor logo extraction."""
    browser = get_browser()
    ctx = await browser.new_context(
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
    )
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        try:
            await page.wait_for_function(
                "document.body && document.body.innerText.trim().length > 100",
                timeout=4000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(400)
        return ScrapedLite(url=url, final_url=page.url, html=await page.content())
    finally:
        await ctx.close()
