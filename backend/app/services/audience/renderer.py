"""HTML email renderer.

Builds a single-table inline-styled HTML email using the brand's palette
and logo. No template engine — just an f-string. The body text comes
from the LLM output (already plain). Linebreaks are converted to
``<p>`` tags.
"""
from __future__ import annotations

import html
from typing import Iterable

from app.db import models


_TEMPLATE = """<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f7f9;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
  <tr><td align="center" style="padding:24px 12px;">
    <table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;background:#ffffff;border-radius:14px;overflow:hidden;">
      <tr><td style="padding:24px 28px;background:{header_bg};color:{header_fg};">
        {logo_html}
      </td></tr>
      <tr><td style="padding:28px;color:#111;font-size:15px;line-height:1.55;">
        {body_html}
        {cta_html}
      </td></tr>
      <tr><td style="padding:18px 28px;background:#fafafa;color:#888;font-size:11px;">
        Sent by {brand_name}. You are receiving this because you are a customer.
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _paragraphs(body: str) -> str:
    """Split on blank lines into <p>; preserve single-newlines as <br>."""
    paras = [p.strip() for p in (body or "").split("\n\n") if p.strip()]
    if not paras:
        single = (body or "").strip()
        if not single:
            return ""
        paras = [single]
    out = []
    for p in paras:
        escaped = html.escape(p).replace("\n", "<br/>")
        out.append(f'<p style="margin:0 0 14px 0;">{escaped}</p>')
    return "".join(out)


def _logo_html(brand: models.Brand, header_fg: str) -> str:
    if brand.logo_url:
        return (
            f'<img src="{html.escape(brand.logo_url)}" '
            f'alt="{html.escape(brand.name or "")}" '
            f'height="28" style="display:block;height:28px;"/>'
        )
    return (
        f'<div style="font-weight:700;font-size:18px;color:{header_fg};">'
        f"{html.escape(brand.name or 'Brand')}</div>"
    )


def _cta_html(
    brand: models.Brand, products: Iterable[models.Product]
) -> str:
    products = list(products)[:1]
    if not products:
        return ""
    p = products[0]
    accent = brand.theme_color or "#111"
    label = f"Shop {p.name}"
    href = "#"  # real shop URL wiring is out of scope for v0
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'border="0" style="margin-top:8px;">'
        f'<tr><td style="background:{accent};border-radius:8px;">'
        f'<a href="{href}" style="display:inline-block;padding:11px 18px;'
        f'color:#fff;text-decoration:none;font-weight:600;font-size:14px;">'
        f"{html.escape(label)}</a>"
        f"</td></tr></table>"
    )


def _is_light_color(hex_color: str) -> bool:
    """Crude luminance check for picking a readable foreground over the
    brand accent. Defaults to dark-on-light if anything goes sideways."""
    s = (hex_color or "").lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    if len(s) != 6:
        return True
    try:
        r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        return True
    # ITU-R BT.601 luma; >150 is treated as light.
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150


def render(
    brand: models.Brand,
    body_text: str,
    recommended_products: Iterable[models.Product],
) -> str:
    accent = brand.theme_color or "#111"
    header_fg = "#111" if _is_light_color(accent) else "#fff"
    return _TEMPLATE.format(
        header_bg=accent,
        header_fg=header_fg,
        logo_html=_logo_html(brand, header_fg),
        body_html=_paragraphs(body_text),
        cta_html=_cta_html(brand, recommended_products),
        brand_name=html.escape(brand.name or "Your brand"),
    )
