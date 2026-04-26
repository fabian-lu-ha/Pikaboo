"""Deep brand-surface scrape — every page that smells like brand voice.

The training corpus is only as good as the writing we feed it. The
default onboarding scrape grabs the homepage; that's <2 KB of clean
voice signal. This module goes wide: sitemap + RSS + a list of common
brand-page paths + any in-bound link from the homepage to other pages
on the same domain. Each discovered URL is fetched with httpx, parsed
with trafilatura (already a project dep — handles boilerplate
stripping, dechrome, language detection), and chunked into post-sized
segments that the corpus builder can reverse-brief.

Three discovery channels run in parallel:

* **sitemap.xml** — the structured one. We follow the index file if
  the brand has one, then take URLs from the leaf sitemaps.
* **RSS / Atom feeds** — discovered via `<link rel="alternate">` on
  the homepage and the conventional `/feed`, `/rss`, `/atom.xml`,
  `/blog/feed` paths. Each entry is its own (chunkable) brand-voice
  document.
* **Common paths** — the suspect list: about, blog, pricing, features,
  faq, press, news, careers, customers, case-studies, manifesto, etc.

Caps everywhere — we don't want to burn 10 minutes scraping a 5K-page
docs site, and we don't want to look like a denial of service to the
target. Conservative defaults: 60 URLs per brand, 5 concurrent
fetches, 8 s per fetch.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

log = logging.getLogger(__name__)


_USER_AGENT = (
    "BrandAutopilotBot/1.0 (+https://github.com/squidbq/brand-autopilot; "
    "training-corpus-builder)"
)
_FETCH_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.7",
}

# Common brand pages, ordered roughly by signal strength. Some brands
# put marketing on /about, others on /story or /our-story; we try all
# and discard 404s. Each path is also tried with the literal singular
# ("blog/1", "press/2024", etc.) only via sitemap-driven discovery —
# the static list here is the seed.
_COMMON_PATHS: tuple[str, ...] = (
    "/about", "/about-us", "/story", "/our-story", "/manifesto", "/values",
    "/team", "/people", "/leadership",
    "/blog", "/journal", "/news", "/press", "/newsroom",
    "/pricing", "/plans", "/features", "/product", "/products", "/solutions",
    "/customers", "/case-studies", "/case-study", "/stories", "/testimonials",
    "/faq", "/help", "/support", "/contact",
    "/careers", "/jobs",
    "/launch", "/changelog", "/whats-new",
    "/sustainability", "/community", "/impact",
)

# Conventional feed paths if the homepage doesn't advertise a feed.
_FEED_PATHS: tuple[str, ...] = (
    "/feed", "/feed/", "/rss", "/rss.xml", "/atom.xml",
    "/blog/feed", "/blog/rss", "/news/feed", "/journal/feed",
)

_MAX_URLS = 60
_MAX_CONCURRENT = 5
_FETCH_TIMEOUT = 8.0
_CHUNK_TARGET_CHARS = 700
_CHUNK_MIN_CHARS = 220
_CHUNK_MAX_CHARS = 1400


# Patterns that indicate a chunk is NOT brand-voice prose — CSS, HTML,
# code, navigation menus, etc. trafilatura with favor_precision still
# leaks these on heavy-design pages. We post-filter aggressively
# because the LoRA absorbs whatever we feed it; one CSS rule in the
# corpus produces drafts that try to write CSS.
_NOISE_PATTERNS = [
    re.compile(r"<\s*[a-z][^>]{0,40}>", re.I),                 # HTML tags
    re.compile(r"\{[^{}]*:\s*[^{}]+;[^{}]*\}"),                # CSS rules
    re.compile(r"@media\s+(?:only\s+)?screen|@keyframes\b"),    # CSS at-rules
    re.compile(r"-webkit-|-moz-|background-image:|font-family:"),  # CSS props
    re.compile(r"\bfunction\s+\w+\s*\(|=>\s*\{|class\s+\w+\s*\{"),  # JS/code
    re.compile(r"\bimport\s+[\w{}\s,]+\s+from\s+['\"]"),        # JS imports
    re.compile(r"https?://\S+\s+https?://\S+\s+https?://"),     # URL sprays (link lists)
]


def _looks_like_noise(text: str) -> bool:
    """Returns True for non-prose chunks: CSS, HTML, code, link sprays."""
    # Quick guards first.
    letters = sum(1 for c in text if c.isalpha())
    if letters < 100:
        return True
    # All-caps spam (NAVIGATION HEADERS).
    caps_runs = len(re.findall(r"\b[A-Z]{4,}\b", text))
    if caps_runs > 6:
        return True
    # Pattern matches.
    for pat in _NOISE_PATTERNS:
        if pat.search(text):
            return True
    # High-symbol-density text (price tables, code).
    symbols = sum(1 for c in text if c in "{}[]<>;:=()/\\|")
    if symbols > letters * 0.20:
        return True
    return False


@dataclass
class ScrapedPage:
    url: str
    kind: str  # homepage_link | sitemap | rss | common
    title: str | None
    text: str
    chunks: list[str]


@dataclass
class DeepScrapeResult:
    domain: str
    discovered_urls: int
    fetched_pages: int
    text_chunks: int
    by_kind: dict[str, int] = field(default_factory=dict)
    pages: list[ScrapedPage] = field(default_factory=list)

    def all_chunks(self) -> list[str]:
        out: list[str] = []
        for p in self.pages:
            out.extend(p.chunks)
        return out


# --- discovery --------------------------------------------------------------


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def _same_domain(url: str, origin: str) -> bool:
    try:
        u = urlparse(url)
        o = urlparse(origin)
        return (u.netloc.lower() or o.netloc.lower()) == o.netloc.lower()
    except Exception:
        return False


async def _fetch(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        r = await client.get(url, follow_redirects=True, timeout=_FETCH_TIMEOUT)
        if r.status_code >= 400:
            return None
        ctype = r.headers.get("content-type", "").lower()
        if not (
            ctype.startswith("text/")
            or "xml" in ctype
            or "html" in ctype
            or ctype == ""
        ):
            return None
        return r
    except Exception as e:
        log.debug("deep_scrape fetch %s failed: %s", url, e)
        return None


async def _discover_homepage_links(
    client: httpx.AsyncClient, origin: str
) -> tuple[list[str], list[str]]:
    """Returns (in-domain links, advertised-feed urls) from the homepage."""
    r = await _fetch(client, origin)
    if r is None:
        return [], []
    html = r.text
    # in-domain links from <a href>
    href_re = re.compile(r"""<a\s[^>]*href\s*=\s*['"]([^'"#]+)['"]""", re.I)
    raw_links = href_re.findall(html)[:400]
    in_domain: list[str] = []
    seen: set[str] = set()
    for link in raw_links:
        if link.startswith(("javascript:", "mailto:", "tel:")):
            continue
        absolute = urljoin(origin + "/", link)
        if not _same_domain(absolute, origin):
            continue
        # Drop fragment + trailing slash for de-dup
        absolute = absolute.split("#", 1)[0].rstrip("/")
        if absolute and absolute not in seen:
            seen.add(absolute)
            in_domain.append(absolute)

    # advertised feeds
    feed_re = re.compile(
        r"""<link[^>]+rel=['"]alternate['"][^>]+href=['"]([^'"]+)['"]""", re.I
    )
    feed_re_alt = re.compile(
        r"""<link[^>]+href=['"]([^'"]+)['"][^>]+rel=['"]alternate['"]""", re.I
    )
    feeds: list[str] = []
    for m in [*feed_re.findall(html), *feed_re_alt.findall(html)]:
        absolute = urljoin(origin + "/", m)
        if absolute not in feeds:
            feeds.append(absolute)
    return in_domain, feeds


async def _discover_sitemap_urls(
    client: httpx.AsyncClient, origin: str
) -> list[str]:
    """Walk sitemap.xml + sitemap_index.xml. Caps total URLs returned."""
    candidates = [
        f"{origin}/sitemap.xml",
        f"{origin}/sitemap_index.xml",
        f"{origin}/sitemap-index.xml",
    ]
    found: list[str] = []
    for sitemap_url in candidates:
        r = await _fetch(client, sitemap_url)
        if r is None:
            continue
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            continue
        # Strip XML namespace from tags so .find/.findall work without prefixes.
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        # sitemap index points to nested sitemaps
        nested = [el.text for el in root.iter("loc") if el.text]
        if root.tag == "sitemapindex":
            for nested_url in nested[:5]:  # cap nested fan-out
                rr = await _fetch(client, nested_url.strip())
                if rr is None:
                    continue
                try:
                    sub_root = ET.fromstring(rr.text)
                except ET.ParseError:
                    continue
                for el in sub_root.iter():
                    if "}" in el.tag:
                        el.tag = el.tag.split("}", 1)[1]
                for el in sub_root.iter("loc"):
                    if el.text:
                        found.append(el.text.strip())
                if len(found) >= _MAX_URLS:
                    break
        else:
            for el in root.iter("loc"):
                if el.text:
                    found.append(el.text.strip())
        if found:
            break  # first sitemap that worked
    return found[:_MAX_URLS]


async def _discover_feed_urls(
    client: httpx.AsyncClient, origin: str, advertised: list[str]
) -> list[str]:
    """Resolve every feed candidate; return entry URLs for whichever feeds answer."""
    candidates = list(advertised) + [
        urljoin(origin + "/", p) for p in _FEED_PATHS
    ]
    seen: set[str] = set()
    candidates = [c for c in candidates if not (c in seen or seen.add(c))]

    entry_urls: list[str] = []
    for feed_url in candidates[:8]:
        r = await _fetch(client, feed_url)
        if r is None:
            continue
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            continue
        for el in root.iter():
            if "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        # RSS: <item><link>; Atom: <entry><link href="...">
        for it in root.iter("item"):
            link = it.find("link")
            if link is not None and link.text:
                entry_urls.append(link.text.strip())
        for it in root.iter("entry"):
            link = it.find("link")
            if link is not None:
                href = link.attrib.get("href")
                if href:
                    entry_urls.append(href.strip())
        if entry_urls:
            break  # one good feed is enough
    return entry_urls


def _looks_like_brand_page(url: str) -> bool:
    """Filter out URLs that are unlikely to contain brand-voice text:
    images, PDFs, code/docs paths, search/category endpoints, login
    pages, design-heavy pages where CSS bleeds through trafilatura."""
    u = url.lower()
    bad_suffix = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
                  ".ico", ".pdf", ".zip", ".dmg", ".css", ".js", ".xml",
                  ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3")
    if any(u.endswith(s) for s in bad_suffix):
        return False
    bad_segments = (
        # auth / commerce
        "/login", "/signin", "/signup", "/cart", "/checkout",
        "/account", "/wp-admin", "/admin/", "/search",
        "/.well-known/", "/cdn-cgi/",
        # developer docs / API references — heavy with code samples
        # that would teach the LoRA to write code instead of marketing.
        "/developer", "/docs/", "/api/", "/reference/",
        "/specs/", "/spec/", "/sdk/", "/sdks/",
        # Navigation-heavy pages that trafilatura tends to leak.
        "/leadership", "/sitemap", "/legal/", "/privacy",
        "/terms", "/shop/buy", "/shop/cart",
        # Pages that are mostly tabular pricing/spec tables.
        "/compare", "/specs.html",
    )
    if any(seg in u for seg in bad_segments):
        return False
    return True


# --- chunking ---------------------------------------------------------------


def _chunk_text(text: str) -> list[str]:
    """Split a body of cleaned page text into post-sized chunks.

    We split on paragraph breaks first and accumulate paragraphs until
    we hit the target. Paragraphs longer than the max get sentence-
    split. Anything below the min is dropped (boilerplate, button
    labels, "© 2026 …" footers).
    """
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for p in paras:
        if len(p) > _CHUNK_MAX_CHARS:
            # split this paragraph on sentence boundaries
            sents = re.split(r"(?<=[.!?])\s+", p)
            for s in sents:
                if not s:
                    continue
                if len(buf) + len(s) + 1 > _CHUNK_TARGET_CHARS and buf:
                    chunks.append(buf.strip())
                    buf = s
                else:
                    buf = (buf + " " + s).strip()
            continue
        if len(buf) + len(p) + 2 > _CHUNK_TARGET_CHARS and buf:
            chunks.append(buf.strip())
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip()
    if buf:
        chunks.append(buf.strip())
    # Quality floor + noise filter. Noise filter is the critical
    # one — without it CSS/HTML chunks make it into the training
    # corpus and the LoRA learns to emit code in its captions.
    return [
        c for c in chunks
        if len(c) >= _CHUNK_MIN_CHARS and not _looks_like_noise(c)
    ]


# --- top-level entry --------------------------------------------------------


def _select_paths(
    in_domain_links: Iterable[str],
    origin: str,
    sitemap: list[str],
    feeds: list[str],
) -> dict[str, list[str]]:
    """Build the final URL set, keyed by source kind. Caps overall."""
    seen: set[str] = set()
    out: dict[str, list[str]] = {
        "common": [],
        "homepage_link": [],
        "sitemap": [],
        "rss": [],
    }

    def add(kind: str, url: str) -> None:
        url = url.split("#", 1)[0].rstrip("/")
        if not url or url in seen or not _looks_like_brand_page(url):
            return
        seen.add(url)
        out[kind].append(url)

    # 1. common paths first — these are the highest-signal targets
    for p in _COMMON_PATHS:
        add("common", urljoin(origin + "/", p))

    # 2. RSS entries
    for u in feeds:
        add("rss", u)

    # 3. sitemap entries — filter to ones likely to be content pages.
    #    We bias toward URLs that match brand-y path patterns.
    pref_re = re.compile(
        r"/(blog|news|press|story|stories|case|customer|about|launch|product|feature|manifesto|journal|update)",
        re.I,
    )
    sitemap_pref = [u for u in sitemap if pref_re.search(u)]
    sitemap_rest = [u for u in sitemap if not pref_re.search(u)]
    for u in sitemap_pref + sitemap_rest:
        add("sitemap", u)
        if sum(len(v) for v in out.values()) >= _MAX_URLS:
            break

    # 4. fall back to other in-domain links from the homepage
    for u in in_domain_links:
        add("homepage_link", u)
        if sum(len(v) for v in out.values()) >= _MAX_URLS:
            break

    # Cap each kind so a sitemap-heavy site doesn't crowd out RSS / common
    out["sitemap"] = out["sitemap"][:25]
    out["homepage_link"] = out["homepage_link"][:15]
    return out


async def _scrape_one(
    client: httpx.AsyncClient, url: str, kind: str, sem: asyncio.Semaphore
) -> ScrapedPage | None:
    async with sem:
        r = await _fetch(client, url)
    if r is None:
        return None
    html = r.text
    # trafilatura does the heavy lifting: dechroming, boilerplate strip,
    # title extraction, language detection, comment removal.
    extracted = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=False,
        include_formatting=False,
        # ``favor_precision`` drops borderline boilerplate that
        # ``favor_recall`` lets through. For brand-voice training we
        # need clean prose, not heavy-design landing pages with
        # leaked CSS.
        favor_precision=True,
        url=url,
    )
    if not extracted or len(extracted) < _CHUNK_MIN_CHARS:
        return None
    title_match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.I)
    title = title_match.group(1).strip() if title_match else None
    chunks = _chunk_text(extracted)
    if not chunks:
        return None
    return ScrapedPage(
        url=url, kind=kind, title=title, text=extracted, chunks=chunks
    )


async def deep_scrape(brand_url: str) -> DeepScrapeResult:
    """Top-level: discover → fetch → chunk. ~10–30 s for a typical brand site."""
    origin = _origin(brand_url)
    if not origin or not origin.startswith("http"):
        return DeepScrapeResult(
            domain=brand_url, discovered_urls=0, fetched_pages=0, text_chunks=0
        )

    async with httpx.AsyncClient(headers=_FETCH_HEADERS, timeout=_FETCH_TIMEOUT) as client:
        # Phase 1: discovery (parallel).
        homepage_task = asyncio.create_task(_discover_homepage_links(client, origin))
        sitemap_task = asyncio.create_task(_discover_sitemap_urls(client, origin))
        in_domain, advertised_feeds = await homepage_task
        sitemap_urls = await sitemap_task
        feed_entry_urls = await _discover_feed_urls(client, origin, advertised_feeds)

        url_buckets = _select_paths(in_domain, origin, sitemap_urls, feed_entry_urls)
        targets: list[tuple[str, str]] = []
        for kind, urls in url_buckets.items():
            for u in urls:
                targets.append((u, kind))

        if not targets:
            return DeepScrapeResult(
                domain=origin, discovered_urls=0, fetched_pages=0, text_chunks=0
            )

        # Phase 2: fetch + parse (concurrency-capped).
        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        results = await asyncio.gather(
            *(_scrape_one(client, u, k, sem) for u, k in targets),
            return_exceptions=True,
        )

    pages: list[ScrapedPage] = []
    by_kind: dict[str, int] = {}
    for res in results:
        if isinstance(res, ScrapedPage):
            pages.append(res)
            by_kind[res.kind] = by_kind.get(res.kind, 0) + 1

    return DeepScrapeResult(
        domain=origin,
        discovered_urls=len(targets),
        fetched_pages=len(pages),
        text_chunks=sum(len(p.chunks) for p in pages),
        by_kind=by_kind,
        pages=pages,
    )


def serialize_result(r: DeepScrapeResult) -> dict:
    return {
        "domain": r.domain,
        "discovered_urls": r.discovered_urls,
        "fetched_pages": r.fetched_pages,
        "text_chunks": r.text_chunks,
        "by_kind": r.by_kind,
        "pages": [
            {"url": p.url, "kind": p.kind, "title": p.title, "chunks": len(p.chunks)}
            for p in r.pages
        ],
    }
