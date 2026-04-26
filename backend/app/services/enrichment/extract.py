import base64
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import extruct
import trafilatura
from Pylette import extract_colors
from selectolax.parser import HTMLParser

SOCIAL_DOMAINS: dict[str, str] = {
    "x.com": "x",
    "twitter.com": "x",
    "linkedin.com": "linkedin",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "instagram.com": "instagram",
    "tiktok.com": "tiktok",
    "facebook.com": "facebook",
    "github.com": "github",
}

_TRACKING = re.compile(
    r"(tracking|pixel|analytics|spacer|sprite|favicon|gtm|ga\.js)", re.I
)

_PARKING = re.compile(
    r"(wsimg\.com/parking|parking[\s-]?lander|sedoparking|afternic|"
    r"hugedomains|dan\.com/parking|domain\s+is\s+for\s+sale|"
    r"buy\s+this\s+domain|this\s+domain\s+(is|may\s+be)\s+for\s+sale|"
    r"parked\s+free,?\s+courtesy)",
    re.I,
)


def is_parking_page(html: str) -> bool:
    """Heuristic: did the URL resolve to a domain-parking placeholder?"""
    return bool(_PARKING.search(html or ""))


@dataclass
class BrandExtract:
    title: str | None = None
    description: str | None = None
    body_markdown: str | None = None
    logo_url: str | None = None
    palette: list[str] = field(default_factory=list)
    palette_roles: list[dict] = field(default_factory=list)
    theme_color: str | None = None
    handles: dict[str, str] = field(default_factory=dict)
    product_images: list[str] = field(default_factory=list)
    og_image: str | None = None
    identity: dict = field(default_factory=dict)


def _abs(base: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(base, href.strip())


def _meta_basics(
    metadata: dict, dom: HTMLParser
) -> tuple[str | None, str | None, str | None, str | None]:
    title: str | None = None
    desc: str | None = None
    og_image: str | None = None
    theme_color: str | None = None

    og_blob = metadata.get("opengraph") or []
    if og_blob:
        og = og_blob[0] if isinstance(og_blob[0], dict) else {}
        properties = og.get("properties", []) if isinstance(og, dict) else []
        if isinstance(properties, list):
            for prop in properties:
                if not isinstance(prop, list) or len(prop) != 2:
                    continue
                k, v = prop
                if k == "og:title" and not title:
                    title = v
                elif k == "og:description" and not desc:
                    desc = v
                elif k == "og:image" and not og_image:
                    og_image = v
        title = title or og.get("og:title") or og.get("title") if isinstance(og, dict) else title
        desc = desc or og.get("og:description") or og.get("description") if isinstance(og, dict) else desc
        og_image = og_image or og.get("og:image") if isinstance(og, dict) else og_image

    if not title:
        node = dom.css_first("title")
        if node:
            title = node.text(strip=True)

    if not desc:
        node = dom.css_first('meta[name="description"]')
        if node:
            desc = node.attributes.get("content")

    node = dom.css_first('meta[name="theme-color"]')
    if node:
        theme_color = node.attributes.get("content")

    return title, desc, og_image, theme_color


# Strings that mark an image as an award/certification badge rather than a
# brand logo. Samsung.de showed Stiftung Warentest seals in the header and
# our broad `header img` fallback grabbed those instead of the logo.
_BADGE_TOKENS = (
    "warentest",
    "stiftung",
    "award",
    "rated",
    "certified",
    "certification",
    "winner",
    "best",
    "siegel",  # German "seal"
    "pruefsiegel",
    "approved",
    "guarantee",
    "rating",
    "trustpilot",
)


def _img_src(node) -> str | None:
    if node is None:
        return None
    return node.attributes.get("src") or node.attributes.get("data-src")


def _is_badge(href: str | None, node) -> bool:
    """Heuristic: detect award/certification badges that masquerade as logos."""
    if not href:
        return False
    haystack = href.lower()
    if node is not None:
        haystack += " " + (node.attributes.get("alt") or "").lower()
        haystack += " " + (node.attributes.get("class") or "").lower()
        haystack += " " + (node.attributes.get("id") or "").lower()
        haystack += " " + (node.attributes.get("title") or "").lower()
    return any(tok in haystack for tok in _BADGE_TOKENS)


def _logo(
    metadata: dict, dom: HTMLParser, base: str, og_image: str | None
) -> str | None:
    # 1. JSON-LD Organization.logo (rare but authoritative)
    for entry in metadata.get("json-ld", []) or []:
        if not isinstance(entry, dict):
            continue
        types_val = entry.get("@type")
        types = types_val if isinstance(types_val, list) else [types_val] if types_val else []
        if any(str(x).lower() == "organization" for x in types):
            logo = entry.get("logo")
            href = (
                logo.get("url") if isinstance(logo, dict)
                else logo if isinstance(logo, str)
                else None
            )
            if href:
                return _abs(base, href)

    # 2. <img> in header/nav with explicit "logo" markers (alt/class/id/aria)
    for sel in (
        'header img[alt*="logo" i]',
        'header img[class*="logo" i]',
        'header img[id*="logo" i]',
        'nav img[alt*="logo" i]',
        'nav img[class*="logo" i]',
        'a[class*="logo" i] img',
        'a[aria-label*="logo" i] img',
    ):
        href = _img_src(dom.css_first(sel))
        if href and not _is_badge(href, dom.css_first(sel)):
            return _abs(base, href)

    # 3. apple-touch-icon — almost always the brand mark (it's the home-screen
    #    icon). Promoted ahead of broad header/nav fallbacks because those
    #    catch award badges (Stiftung Warentest, "Rated #1", etc.).
    apple = dom.css_first('link[rel="apple-touch-icon"]')
    if apple:
        href = apple.attributes.get("href")
        if href:
            return _abs(base, href)

    # 4. broad header/nav fallbacks — last resort, but with badge filter
    for sel in (
        'a[href="/"] img',
        'header a:first-of-type img',
        'header img',
        'nav img',
    ):
        node = dom.css_first(sel)
        href = _img_src(node)
        if href and not _is_badge(href, node):
            return _abs(base, href)

    # 5. inline <svg> in header/nav — modern sites render the logo as inline SVG
    for sel in (
        'header svg[class*="logo" i]',
        'header svg[aria-label*="logo" i]',
        'a[href="/"] svg',
        'header a:first-of-type svg',
        'header svg',
        'nav svg',
    ):
        node = dom.css_first(sel)
        if not node:
            continue
        svg_html = node.html or ""
        if "<svg" not in svg_html:
            continue
        if not any(tag in svg_html for tag in ("<path", "<g", "<polygon", "<rect", "<circle")):
            continue
        if "xmlns=" not in svg_html:
            svg_html = svg_html.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
        encoded = base64.b64encode(svg_html.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    # 6. largest <link rel="icon">
    best_size = 0
    best_href: str | None = None
    for node in dom.css('link[rel~="icon"]'):
        sizes = (node.attributes.get("sizes") or "0x0").split(" ")[0]
        try:
            w = int(sizes.split("x")[0])
        except ValueError:
            w = 0
        if w >= best_size:
            best_size = w
            best_href = node.attributes.get("href")
    if best_href:
        return _abs(base, best_href)

    # 7. og:image as last resort
    return _abs(base, og_image)


def _palette(screenshot_png: bytes, n: int = 5) -> list[str]:
    palette = extract_colors(
        image=screenshot_png, palette_size=n, sort_mode="frequency"
    )
    out: list[str] = []
    for color in palette.colors:
        rgb = color.rgb
        if hasattr(rgb, "tolist"):
            rgb = rgb.tolist()
        rgb_t = tuple(int(c) for c in tuple(rgb)[:3])
        out.append("#{:02x}{:02x}{:02x}".format(*rgb_t))
    return out


_RGB_RE = re.compile(
    r"rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})(?:\s*,\s*([\d.]+))?\s*\)"
)


def _css_to_hex(css: str | None) -> str | None:
    if not css:
        return None
    m = _RGB_RE.match(css.strip())
    if not m:
        return None
    r, g, b = (int(m.group(i)) for i in range(1, 4))
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    if a < 0.01:
        return None
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
    )


def _palette_from_css(
    css_palette: dict | None,
) -> list[dict]:
    """Build a brand-usage-weighted palette of role-tagged entries.
    Each entry: {"hex": "#rrggbb", "role": "background|primary|text|link|surface"}.
    Ordered for display: background → primary → text → link → surface (header bg).
    """
    if not css_palette:
        return []

    from collections import Counter

    out: list[dict] = []
    seen: set[str] = set()

    def _add(hex_value: str | None, role: str) -> None:
        if not hex_value or hex_value in seen:
            return
        out.append({"hex": hex_value, "role": role})
        seen.add(hex_value)

    _add(_css_to_hex(css_palette.get("bg")), "background")

    cta_counts: Counter[str] = Counter()
    for c in css_palette.get("cta_bgs") or []:
        h = _css_to_hex(c)
        if h:
            cta_counts[h] += 1
    for i, (h, _) in enumerate(cta_counts.most_common(2)):
        _add(h, "primary" if i == 0 else "secondary")

    _add(_css_to_hex(css_palette.get("fg")), "text")

    link_counts: Counter[str] = Counter()
    for c in css_palette.get("link_colors") or []:
        h = _css_to_hex(c)
        if h:
            link_counts[h] += 1
    for h, _ in link_counts.most_common(2):
        if len(out) < 6:
            _add(h, "link")

    _add(_css_to_hex(css_palette.get("headerBg")), "surface")
    return out[:6]


def _merge_palettes(
    css_pal: list[dict], pixel_pal: list[str]
) -> list[dict]:
    """CSS roles win priority; pixel results fill remaining slots as 'ornament'."""
    out: list[dict] = list(css_pal)
    seen = {entry["hex"] for entry in out}
    for c in pixel_pal:
        if c in seen:
            continue
        if len(out) >= 6:
            break
        out.append({"hex": c, "role": "ornament"})
        seen.add(c)
    return out


def _flatten_palette(rich: list[dict]) -> list[str]:
    """Backwards-compat flat list of hex strings, in role order."""
    return [entry["hex"] for entry in rich]


# ── Identity extraction ──────────────────────────────────────────────────

_PX_RE = re.compile(r"(-?[0-9]+(?:\.[0-9]+)?)px")
_EM_RE = re.compile(r"(-?[0-9]+(?:\.[0-9]+)?)em")


def _parse_px(v: str | None) -> float | None:
    if not v or v == "none":
        return None
    m = _PX_RE.search(v)
    return float(m.group(1)) if m else None


def _parse_em(v: str | None) -> float | None:
    if not v:
        return None
    m = _EM_RE.search(v)
    return float(m.group(1)) if m else None


def _parse_number(v: str | None) -> float | None:
    """font-weight / line-height are sometimes 'normal' or 'bold'."""
    if not v or v == "normal":
        return None
    if v == "bold":
        return 700.0
    try:
        return float(v)
    except ValueError:
        return _parse_px(v)


def _font_first(stack: str | None) -> str | None:
    if not stack:
        return None
    parts = [p.strip().strip('"').strip("'") for p in stack.split(",")]
    return parts[0] if parts else None


def _mode(values: list) -> object:
    from collections import Counter

    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return None
    return Counter(cleaned).most_common(1)[0][0]


def _build_identity(css_palette: dict | None) -> dict:
    """Build a structured Identity dict from CSS computed-style samples."""
    if not css_palette:
        return {}

    typography_samples = css_palette.get("typography") or {}
    buttons_samples = css_palette.get("buttons") or []
    radii_samples = css_palette.get("radii") or []
    shadow_samples = css_palette.get("shadows") or []
    css_vars = css_palette.get("css_vars") or {}

    body = typography_samples.get("body") or {}
    h1_samples = typography_samples.get("h1") or []
    h2_samples = typography_samples.get("h2") or []
    p_samples = typography_samples.get("p") or []
    code_samples = typography_samples.get("code") or []

    body_size = _parse_px(body.get("font-size")) or 16.0
    body_family = body.get("font-family")

    h1 = h1_samples[0] if h1_samples else {}
    h1_size = _parse_px(h1.get("font-size"))
    h1_weight = _parse_number(h1.get("font-weight"))
    h1_lh_raw = h1.get("line-height")
    h1_lh = _parse_number(h1_lh_raw)
    if h1_lh and h1_size and h1_lh > 5:
        h1_lh = h1_lh / h1_size
    h1_ls = _parse_em(h1.get("letter-spacing"))
    if h1_ls is None and h1.get("letter-spacing"):
        ls_px = _parse_px(h1.get("letter-spacing"))
        if ls_px is not None and h1_size:
            h1_ls = ls_px / h1_size

    h2 = h2_samples[0] if h2_samples else {}
    h2_size = _parse_px(h2.get("font-size"))

    p_first = p_samples[0] if p_samples else {}
    p_size = _parse_px(p_first.get("font-size")) or body_size
    p_lh_raw = p_first.get("line-height")
    p_lh = _parse_number(p_lh_raw)
    if p_lh and p_lh > 5 and p_size:
        p_lh = p_lh / p_size

    code = code_samples[0] if code_samples else {}

    typography = {
        "body_font": body_family,
        "body_font_first": _font_first(body_family),
        "headline_font": h1.get("font-family") or body_family,
        "headline_font_first": _font_first(
            h1.get("font-family") or body_family
        ),
        "mono_font": code.get("font-family"),
        "mono_font_first": _font_first(code.get("font-family")),
        "body_size_px": body_size,
        "h1_size_px": h1_size,
        "h1_weight": h1_weight,
        "h1_line_height": round(h1_lh, 3) if h1_lh else None,
        "h1_letter_spacing_em": round(h1_ls, 3) if h1_ls else 0,
        "h2_size_px": h2_size,
        "p_line_height": round(p_lh, 3) if p_lh else None,
    }

    radii_px = []
    for r in radii_samples:
        v = _parse_px(r)
        if v is not None:
            radii_px.append(v)
    radii_px_unique = sorted(set(radii_px))
    has_pill = any(v >= 999 for v in radii_px_unique)
    real = [v for v in radii_px_unique if v < 999]
    dominant = _mode([v for v in radii_px if v < 999])
    radii = {
        "samples_px": radii_px_unique,
        "dominant_px": dominant,
        "small_px": real[0] if real else None,
        "medium_px": real[len(real) // 2] if real else None,
        "large_px": real[-1] if real else None,
        "has_pill": has_pill,
    }

    from collections import Counter

    shadow_freq = Counter(s for s in shadow_samples if s and s != "none")
    shadows = [s for s, _ in shadow_freq.most_common(3)]

    primary_button = None
    for b in buttons_samples:
        bg_b = (b.get("background-color") or "").strip().lower()
        if bg_b and bg_b not in ("rgba(0, 0, 0, 0)", "rgba(0,0,0,0)", "transparent"):
            primary_button = {
                "bg": b.get("background-color"),
                "fg": b.get("color"),
                "radius_px": _parse_px(b.get("border-radius")),
                "padding": b.get("padding"),
                "font_size_px": _parse_px(b.get("font-size")),
                "font_weight": _parse_number(b.get("font-weight")),
                "border": (b.get("border") or "").strip()
                if b.get("border") and b.get("border") != "none"
                else None,
                "shadow": b.get("box-shadow")
                if b.get("box-shadow") and b.get("box-shadow") != "none"
                else None,
            }
            break

    color_vars = sum(1 for k in css_vars if "color" in k.lower())
    space_vars = sum(
        1 for k in css_vars if "space" in k.lower() or "spacing" in k.lower()
    )

    return {
        "typography": typography,
        "radii": radii,
        "shadows": shadows,
        "buttons": {"primary": primary_button} if primary_button else {},
        "tokens": {
            "css_vars_total": len(css_vars),
            "color_vars": color_vars,
            "space_vars": space_vars,
            "exposes_design_system": len(css_vars) >= 5,
        },
    }


def _socials_from_dom(dom: HTMLParser) -> dict[str, str]:
    found: dict[str, str] = {}
    for a in dom.css("a[href]"):
        href = a.attributes.get("href") or ""
        try:
            host = urlparse(href).netloc.lower()
        except Exception:
            continue
        host = host.removeprefix("www.")
        for domain, platform in SOCIAL_DOMAINS.items():
            if host == domain or host.endswith("." + domain):
                found.setdefault(platform, href)
                break
    return found


def _socials_from_jsonld(metadata: dict) -> list[str]:
    out: list[str] = []
    for entry in metadata.get("json-ld", []) or []:
        if not isinstance(entry, dict):
            continue
        same_as = entry.get("sameAs")
        if isinstance(same_as, list):
            out.extend(s for s in same_as if isinstance(s, str))
        elif isinstance(same_as, str):
            out.append(same_as)
    return out


def _merge_socials(dom_s: dict[str, str], jsonld_urls: list[str]) -> dict[str, str]:
    merged = dict(dom_s)
    for url in jsonld_urls:
        try:
            host = urlparse(url).netloc.lower().removeprefix("www.")
        except Exception:
            continue
        for domain, platform in SOCIAL_DOMAINS.items():
            if host == domain or host.endswith("." + domain):
                merged.setdefault(platform, url)
                break
    return merged


def _hero_images(
    dom: HTMLParser, base: str, og_image: str | None
) -> list[str]:
    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for img in dom.css(
        "main img, section img, article img, header img, body > img"
    ):
        src = img.attributes.get("src") or img.attributes.get("data-src")
        if not src or src.startswith("data:"):
            continue
        if _TRACKING.search(src):
            continue
        try:
            w = int(img.attributes.get("width") or 0)
            h = int(img.attributes.get("height") or 0)
        except ValueError:
            w = h = 0
        score = w * h if (w and h) else 1
        abs_src = _abs(base, src)
        if not abs_src or abs_src in seen:
            continue
        seen.add(abs_src)
        candidates.append((score, abs_src))

    candidates.sort(key=lambda t: -t[0])
    out = [src for _, src in candidates[:8]]

    if og_image:
        og_abs = _abs(base, og_image)
        if og_abs and og_abs not in seen:
            out.insert(0, og_abs)

    return out[:8]


def extract(
    html: str,
    screenshots: list[bytes],
    final_url: str,
    css_palette: dict | None = None,
) -> BrandExtract:
    metadata = extruct.extract(
        html,
        base_url=final_url,
        syntaxes=["json-ld", "opengraph", "microdata"],
    )
    dom = HTMLParser(html)

    title, desc, og_image, theme_color = _meta_basics(metadata, dom)

    body_md = trafilatura.extract(
        html,
        url=final_url,
        output_format="markdown",
        favor_precision=True,
        with_metadata=False,
        include_comments=False,
        include_tables=False,
    )

    css_pal = _palette_from_css(css_palette)
    pixel_pal = _palette(screenshots[0]) if screenshots else []
    palette_roles = _merge_palettes(css_pal, pixel_pal)
    palette = _flatten_palette(palette_roles)
    identity = _build_identity(css_palette)

    return BrandExtract(
        title=title,
        description=desc,
        body_markdown=body_md,
        logo_url=_logo(metadata, dom, final_url, og_image),
        palette=palette,
        palette_roles=palette_roles,
        theme_color=theme_color,
        handles=_merge_socials(
            _socials_from_dom(dom), _socials_from_jsonld(metadata)
        ),
        product_images=_hero_images(dom, final_url, og_image),
        og_image=og_image,
        identity=identity,
    )


def extract_logo(html: str, final_url: str) -> str | None:
    """Logo-only extraction for competitor enrichment."""
    metadata = extruct.extract(
        html, base_url=final_url, syntaxes=["json-ld", "opengraph"]
    )
    dom = HTMLParser(html)
    _, _, og_image, _ = _meta_basics(metadata, dom)
    return _logo(metadata, dom, final_url, og_image)
