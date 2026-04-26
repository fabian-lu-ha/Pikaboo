"""Extract a small product catalog from a competitor's marketing site.

Strategy: load the competitor's homepage with the existing Playwright
browser, then ask Gemini to extract up to 6 visible products with name,
price (best-effort), description, and url. Caches result on
``Competitor.pattern_library['products']`` via the caller — this module
is pure extraction.

Fail-soft: returns ``[]`` on any error. The caller MUST treat absent
competitor products as "no comparison line"; nothing should hard-fail
because a competitor site has anti-scraping measures or a non-standard
layout.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.enrichment import browser as pw_browser
from app.services.llm.client import chat_json

log = logging.getLogger(__name__)


PRODUCT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "products": {
            "type": "array",
            "minItems": 0,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "price_text": {"type": "string"},
                    "description": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["name", "price_text", "description", "url"],
            },
        }
    },
    "required": ["products"],
}


SYSTEM = (
    "You extract a small product catalog from a competitor's marketing "
    "page. Return up to 6 products that are clearly for sale (not navigation "
    "links, not blog posts). For each product give the visible name, the "
    "price as it appears on the page (e.g. '$79', '€129/mo', 'Free'), a "
    "one-sentence description, and the absolute URL if visible (relative "
    "URLs are fine — caller will resolve). If no products are obvious, "
    "return an empty array. Never invent products."
)


async def extract(competitor_url: str) -> list[dict[str, Any]]:
    if not competitor_url:
        return []
    try:
        browser = pw_browser.get_browser()
        page = await browser.new_page()
        try:
            await page.goto(
                competitor_url, timeout=15000, wait_until="domcontentloaded"
            )
            body_text = await page.evaluate(
                "() => document.body.innerText.slice(0, 6000)"
            )
        finally:
            await page.close()
    except Exception as e:  # noqa: BLE001
        log.warning(
            "competitor_products: page load failed for %s: %s",
            competitor_url,
            e,
        )
        return []

    try:
        result = await chat_json(
            messages=[
                {"role": "system", "content": SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"Competitor URL: {competitor_url}\n\nVisible page "
                        f"text (truncated to 6000 chars):\n{body_text}"
                    ),
                },
            ],
            schema=PRODUCT_SCHEMA,
        )
    except Exception:  # noqa: BLE001
        log.warning(
            "competitor_products: gemini extraction failed", exc_info=True
        )
        return []

    products = result.get("products", []) or []
    out: list[dict[str, Any]] = []
    for p in products[:6]:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "price_text": (p.get("price_text") or "").strip(),
                "description": (p.get("description") or "").strip(),
                "url": (p.get("url") or "").strip(),
            }
        )
    return out
