"""LinkedIn public company-page post fetcher.

Best-effort and very pessimistic by 2026 standards: LinkedIn's "authwall"
intercepts almost all unauthenticated views of `/company/<slug>/posts/`,
sometimes after a few seconds of rendered content, sometimes immediately on
navigation. There is no public REST endpoint, no public RSS, and the
`embed/feed/update/<urn>` route only works once you already know the activity
URN. JSON-LD on the company overview page exposes the company description but
does not include posts.

Given that, the realistic outcome for an arbitrary company URL without an
auth cookie is `[]`. We still try, because a small fraction of company pages
do render their first few posts publicly (especially smaller / less-trafficked
pages, or pages hit from a fresh IP), and even partial DOM markers are
worth grabbing when they're there.

Strategy:
  1. Parse the slug from a `linkedin.com/company/<slug>/...` URL.
  2. Render `https://www.linkedin.com/company/<slug>/posts/` via the shared
     Playwright pool with a real-looking UA.
  3. If the response redirects into the authwall (`/uas/login`, `/login`,
     `/authwall`, `/checkpoint/`) or the rendered DOM is dominated by
     login-CTAs with no post containers, return `[]`.
  4. Otherwise walk every `div[data-urn*="urn:li:activity:"]` (or, on newer
     markup, `div.feed-shared-update-v2[data-urn*="activity"]`) and pull
     caption text, the activity URL, the post timestamp, media URLs, and a
     reaction count when the aria-labels are exposed.
  5. Cap at 5. Empty list on anything that goes wrong. Never raise.

Sources for the DOM markers:
  - christophe-garon/Linkedin-Post-Scraper README (selectors:
    `feed-shared-update-v2`, `feed-shared-update-v2__description-wrapper`,
    `update-components-image`, `update-components-video`, reaction
    `aria-label`).
  - Scrapfly "How to Scrape LinkedIn in 2026" — confirms authwall behavior
    and that post feeds are gated even when overview pages are not.
  - LinkedIn embed help center — confirms `linkedin.com/embed/feed/update/
    urn:li:activity:<id>` is the public-canonical URL for an activity.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.enrichment.browser import get_browser
from app.services.social import Post

log = logging.getLogger(__name__)

PLATFORM = "linkedin"
MAX_POSTS = 5
CAPTION_LIMIT = 500

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
_VIEWPORT = {"width": 1366, "height": 900}

# `urn:li:activity:7283749384732948732` — the canonical post identifier.
_ACTIVITY_URN_RE = re.compile(r"urn:li:activity:(\d+)")
# Numeric reaction counts come back like "1,234 reactions" or "1.2K reactions".
_NUMBER_TOKEN_RE = re.compile(r"([0-9][0-9,\.]*)\s*([KMB]?)", re.IGNORECASE)
# Authwall path markers on the response URL.
_AUTHWALL_PATHS = ("/uas/login", "/login", "/authwall", "/checkpoint/")


def _extract_slug(profile_url: str) -> str | None:
    """Pull the company slug from a LinkedIn URL.

    Accepts the variants we see in the wild:
      - https://www.linkedin.com/company/anthropic
      - https://linkedin.com/company/anthropic/
      - linkedin.com/company/anthropic/posts/
      - https://www.linkedin.com/company/anthropic/about/
      - bare slug ("anthropic")
    """
    if not profile_url:
        return None
    s = profile_url.strip()
    if not s:
        return None

    # Bare slug — no `/`, no `.`. Tolerate a leading `@` although LinkedIn
    # company URLs don't use it.
    if "/" not in s and "." not in s:
        return s.lstrip("@") or None

    if not s.startswith(("http://", "https://")):
        s = "https://" + s

    try:
        parsed = urlparse(s)
    except ValueError:
        return None

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None

    # Path forms: /company/<slug>/..., /school/<slug>/... (LinkedIn aliases
    # university pages this way), /showcase/<slug>/...
    for marker in ("company", "school", "showcase"):
        if marker in parts:
            i = parts.index(marker)
            if i + 1 < len(parts):
                return parts[i + 1] or None
            return None

    # No marker present — assume the first path segment is the slug.
    return parts[0] or None


def _truncate_caption(text: str | None) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= CAPTION_LIMIT:
        return text
    return text[: CAPTION_LIMIT - 1].rstrip() + "…"


def _parse_count(label: str | None) -> int | None:
    """`1,234 reactions` -> 1234; `1.2K reactions` -> 1200; `5 reactions` -> 5."""
    if not label:
        return None
    m = _NUMBER_TOKEN_RE.search(label)
    if not m:
        return None
    num_s, suffix = m.group(1), (m.group(2) or "").upper()
    try:
        num = float(num_s.replace(",", ""))
    except ValueError:
        return None
    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(suffix, 1)
    return int(num * mult)


def _activity_url(urn_or_id: str) -> str:
    m = _ACTIVITY_URN_RE.search(urn_or_id)
    activity_id = m.group(1) if m else urn_or_id
    # The /feed/update/urn:li:activity:<id>/ form is the canonical public
    # post URL and resolves both for logged-in and logged-out viewers.
    return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity_id}/"


def _looks_like_authwall(url: str | None, html: str) -> bool:
    """Heuristic: did the page resolve to a login wall?"""
    if url:
        lowered_url = url.lower()
        for marker in _AUTHWALL_PATHS:
            if marker in lowered_url:
                return True
    if not html:
        return True
    lowered = html.lower()
    if len(lowered) < 2_000:
        return True
    # Strong markers: authwall component, "join now" CTA without any post
    # containers, or the explicit /login form action.
    has_authwall = (
        "authwall" in lowered
        or "uas/login" in lowered
        or 'action="/login"' in lowered
        or 'action="/uas/login' in lowered
    )
    has_post_markers = (
        "feed-shared-update-v2" in lowered
        or "update-components-text" in lowered
        or "urn:li:activity:" in lowered
    )
    if has_authwall and not has_post_markers:
        return True
    return False


# JS evaluated in-page to harvest post nodes. Keeping this as one
# expression so a single eval round-trip handles all extraction.
_EXTRACT_JS = r"""
(() => {
    const out = [];
    const seen = new Set();

    // Primary: any container the rendered DOM tags with an activity URN.
    // We accept either feed-shared-update-v2 (the long-standing class) or
    // any element whose data-urn references an activity URN — newer A/B
    // variants sometimes drop the v2 class but keep the data-urn.
    const candidates = document.querySelectorAll(
        '[data-urn*="urn:li:activity:"], div.feed-shared-update-v2, .occludable-update'
    );

    for (const el of candidates) {
        const urn =
            el.getAttribute('data-urn') ||
            (el.querySelector('[data-urn*="urn:li:activity:"]') || {}).getAttribute?.('data-urn') ||
            '';
        const m = (urn || '').match(/urn:li:activity:(\d+)/);
        const activityId = m ? m[1] : null;
        if (!activityId || seen.has(activityId)) continue;

        // Caption text. Try the description wrapper first, fall back to the
        // newer `update-components-text` block, then any commentary span.
        let caption = '';
        const captionEl =
            el.querySelector('.feed-shared-update-v2__description-wrapper') ||
            el.querySelector('.update-components-text') ||
            el.querySelector('.feed-shared-text') ||
            el.querySelector('[data-test-id="main-feed-activity-card__commentary"]');
        if (captionEl) {
            caption = (captionEl.innerText || captionEl.textContent || '').trim();
        }

        // Media URLs — images and video posters.
        const mediaUrls = [];
        const imgs = el.querySelectorAll(
            '.update-components-image img, .ivm-image-view-model img, .feed-shared-image img'
        );
        for (const img of imgs) {
            const src = img.getAttribute('src') || img.getAttribute('data-delayed-url') || '';
            if (src && !src.startsWith('data:') && !mediaUrls.includes(src)) {
                mediaUrls.push(src);
            }
        }
        const videos = el.querySelectorAll('video');
        for (const v of videos) {
            const poster = v.getAttribute('poster') || '';
            if (poster && !mediaUrls.includes(poster)) mediaUrls.push(poster);
        }

        // Posted-at: the relative-time span LinkedIn renders carries the
        // human label ("3d", "2 weeks ago") but no machine timestamp without
        // auth, so we pass the raw label through as-is.
        let postedAt = null;
        const timeEl = el.querySelector(
            'time, .feed-shared-actor__sub-description, .update-components-actor__sub-description'
        );
        if (timeEl) {
            postedAt =
                timeEl.getAttribute('datetime') ||
                (timeEl.innerText || timeEl.textContent || '').trim() ||
                null;
            if (postedAt) postedAt = postedAt.split('\n')[0].trim().slice(0, 80) || null;
        }

        // Likes / reactions — LinkedIn exposes `aria-label="123 reactions"`
        // on the social-counts button when reactions are present.
        let likes = null;
        const reactionEl =
            el.querySelector('[aria-label*="reaction" i]') ||
            el.querySelector('.social-details-social-counts__reactions-count') ||
            el.querySelector('button[aria-label*="like" i]');
        if (reactionEl) {
            likes =
                reactionEl.getAttribute('aria-label') ||
                (reactionEl.innerText || reactionEl.textContent || '').trim() ||
                null;
        }

        seen.add(activityId);
        out.push({ activityId, caption, mediaUrls, postedAt, likes });
        if (out.length >= 12) break;  // Cap eval payload; caller takes top 5.
    }
    return out;
})()
"""


async def fetch(profile_url: str) -> list[Post]:
    slug = _extract_slug(profile_url)
    if not slug:
        log.warning("linkedin fetch: could not extract slug from %r", profile_url)
        return []

    try:
        browser = get_browser()
    except RuntimeError as e:
        log.warning("linkedin fetch: browser pool not available: %s", e)
        return []

    context = None
    try:
        context = await browser.new_context(
            viewport=_VIEWPORT,
            user_agent=_USER_AGENT,
            locale="en-US",
            extra_http_headers={
                "accept-language": "en-US,en;q=0.9",
            },
        )
        page = await context.new_page()

        target = f"https://www.linkedin.com/company/{slug}/posts/"
        try:
            response = await page.goto(target, wait_until="domcontentloaded", timeout=20_000)
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            log.warning("linkedin goto %s failed: %s", target, e)
            return []

        # Bail early if Playwright followed a redirect into the authwall.
        final_url = page.url or (response.url if response else None)
        if final_url:
            for marker in _AUTHWALL_PATHS:
                if marker in final_url.lower():
                    log.warning("linkedin fetch: authwall redirect for %s -> %s", slug, final_url)
                    return []

        # Let lazy-loaded post containers settle. networkidle is unreliable on
        # LinkedIn (always-on telemetry pings), so use a short bounded wait.
        try:
            await page.wait_for_load_state("networkidle", timeout=6_000)
        except PlaywrightTimeoutError:
            pass
        try:
            await page.wait_for_selector(
                '[data-urn*="urn:li:activity:"], .feed-shared-update-v2, .authwall',
                timeout=4_000,
            )
        except PlaywrightTimeoutError:
            pass

        try:
            html = await page.content()
        except (PlaywrightError, PlaywrightTimeoutError):
            html = ""

        if _looks_like_authwall(final_url, html):
            log.warning("linkedin fetch: authwall content for %s", slug)
            return []

        # Extract from the rendered DOM.
        try:
            raw_items = await page.evaluate(_EXTRACT_JS)
        except (PlaywrightError, PlaywrightTimeoutError) as e:
            log.warning("linkedin fetch: extract eval failed for %s: %s", slug, e)
            return []

        if not isinstance(raw_items, list) or not raw_items:
            log.warning("linkedin fetch: no public posts surfaced for %s", slug)
            return []

        posts: list[Post] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            activity_id = item.get("activityId")
            if not activity_id:
                continue
            caption = _truncate_caption(item.get("caption") or "")
            media_urls = [
                u for u in (item.get("mediaUrls") or []) if isinstance(u, str) and u
            ]
            posted_at = item.get("postedAt") or None
            likes = _parse_count(item.get("likes"))
            posts.append(
                Post(
                    platform=PLATFORM,
                    caption=caption,
                    media_urls=media_urls,
                    posted_at=posted_at,
                    url=_activity_url(str(activity_id)),
                    likes=likes,
                )
            )
            if len(posts) >= MAX_POSTS:
                break

        if not posts:
            log.warning("linkedin fetch: extractor matched nothing usable for %s", slug)
        return posts
    except Exception as e:  # final safety net — best-effort means never raise.
        log.warning("linkedin fetch failed for %s: %s", profile_url, e)
        return []
    finally:
        if context is not None:
            try:
                await context.close()
            except Exception:
                pass
