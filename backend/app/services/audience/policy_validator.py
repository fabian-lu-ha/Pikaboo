"""Freedom-to-Operate envelope enforcement for LLM-generated offers.

The brand defines an offer policy (``Brand.offer_policy``) with optional
per-segment overrides (``Segment.offer_policy_override``). The LLM is
*told* the envelope as a hard constraint via the system prompt, but
must be *checked* on the way out — the post-hoc clamp is the trust
boundary, not the prompt.

Pure functions only. No DB access. No event emission. Callers (services
and tests) are responsible for persistence and bus.emit.
"""
from __future__ import annotations

from typing import Any

# Defaults applied for any policy key the brand hasn't set yet. Conservative
# on purpose — better to deny a 30% discount than to leak one. Brands can
# widen these via the Settings panel.
DEFAULT_POLICY: dict[str, Any] = {
    "max_discount_pct": 20,
    "allowed_discount_types": [
        "percent",
        "fixed_amount",
        "free_shipping",
        "bogo",
    ],
    "allow_bundles": True,
    "max_bundle_size": 3,
    "allowed_addons": [
        "free_returns",
        "gift_wrap",
        "expedited_shipping",
    ],
    "expiration_max_days": 14,
    "max_total_redemptions": 1000,
    "forbid_urgency_language": False,
}

# Urgency phrases the validator scrubs when ``forbid_urgency_language`` is
# True. Lowercased substring match — keep the list short and obvious so the
# false-positive rate stays near zero.
_URGENCY_TOKENS: tuple[str, ...] = (
    "act now",
    "limited time",
    "hurry",
    "only today",
    "last chance",
    "ends soon",
    "expires today",
    "don't miss",
)


def effective_policy(
    brand_policy: dict | None,
    segment_override: dict | None = None,
) -> dict[str, Any]:
    """Merge order: defaults <- brand <- segment_override. Shallow merge —
    arrays are replaced, not concatenated, so an override saying
    ``allowed_discount_types: ["free_shipping"]`` actually narrows."""
    out: dict[str, Any] = dict(DEFAULT_POLICY)
    if brand_policy:
        out.update({k: v for k, v in brand_policy.items() if v is not None})
    if segment_override:
        out.update(
            {k: v for k, v in segment_override.items() if v is not None}
        )
    return out


def policy_to_prompt(policy: dict[str, Any]) -> str:
    """Render the envelope as a system-prompt constraint block. The LLM
    sees this verbatim. Phrasing chosen to be unambiguous: 'must not
    exceed' rather than 'try to stay under'."""
    parts = [
        "OFFER POLICY ENVELOPE — your output MUST satisfy every constraint:",
        f"- discount_pct must not exceed {policy['max_discount_pct']}",
        f"- discount_type must be one of: "
        f"{', '.join(policy['allowed_discount_types'])}",
        f"- bundles allowed: {policy['allow_bundles']}, "
        f"max products in a bundle: {policy['max_bundle_size']}",
        f"- allowed addons: "
        f"{', '.join(policy['allowed_addons']) or '(none)'}",
        f"- expiration: at most {policy['expiration_max_days']} days "
        f"from today",
    ]
    if policy.get("forbid_urgency_language"):
        parts.append(
            "- forbid urgency language (no 'act now', 'limited time', "
            "'hurry', etc.)"
        )
    return "\n".join(parts)


def clamp(
    offer: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return ``(clamped_offer, clamp_log)``.

    ``offer`` is the raw LLM JSON for an offer. Expected keys:
    ``discount_pct: int``, ``discount_type: str``, ``product_ids: list``,
    ``addons: list[str]``, ``expiration_days: int``, ``copy: dict``.
    Any of these may be missing; the validator only acts on what's present.

    Each clamp event is one dict with keys ``field``, ``proposed``,
    ``clamped_to``, ``reason`` — emitted as-is in
    ``OFFER_POLICY_CLAMPED`` payloads and persisted in
    ``Offer.policy_clamps``.
    """
    out = dict(offer)
    log: list[dict[str, Any]] = []

    # Discount percent
    if "discount_pct" in out and out["discount_pct"] is not None:
        try:
            proposed = int(out["discount_pct"])
        except (TypeError, ValueError):
            proposed = 0
        cap = int(policy["max_discount_pct"])
        if proposed > cap:
            log.append(
                {
                    "field": "discount_pct",
                    "proposed": proposed,
                    "clamped_to": cap,
                    "reason": f"exceeds max_discount_pct={cap}",
                }
            )
            out["discount_pct"] = cap
        elif proposed < 0:
            log.append(
                {
                    "field": "discount_pct",
                    "proposed": proposed,
                    "clamped_to": 0,
                    "reason": "negative discount",
                }
            )
            out["discount_pct"] = 0

    # Discount type
    allowed_types = set(policy["allowed_discount_types"])
    if out.get("discount_type") and out["discount_type"] not in allowed_types:
        proposed = out["discount_type"]
        # Fall back to free_shipping if available; else first allowed type.
        fallback = (
            "free_shipping"
            if "free_shipping" in allowed_types
            else next(iter(allowed_types), "percent")
        )
        log.append(
            {
                "field": "discount_type",
                "proposed": proposed,
                "clamped_to": fallback,
                "reason": "not in allowed_discount_types",
            }
        )
        out["discount_type"] = fallback

    # Bundle cap
    if not policy.get("allow_bundles") and len(out.get("product_ids") or []) > 1:
        proposed = list(out["product_ids"])
        out["product_ids"] = proposed[:1]
        log.append(
            {
                "field": "product_ids",
                "proposed": proposed,
                "clamped_to": out["product_ids"],
                "reason": "bundles disallowed",
            }
        )
    elif (
        out.get("product_ids")
        and len(out["product_ids"]) > policy["max_bundle_size"]
    ):
        proposed = list(out["product_ids"])
        # Keep the first N — the LLM is instructed to put highest-priority
        # items first. Caller can re-rank by margin if it wants.
        cap = int(policy["max_bundle_size"])
        out["product_ids"] = proposed[:cap]
        log.append(
            {
                "field": "product_ids",
                "proposed": proposed,
                "clamped_to": out["product_ids"],
                "reason": f"exceeds max_bundle_size={cap}",
            }
        )

    # Addons
    allowed_addons = set(policy["allowed_addons"])
    if out.get("addons"):
        proposed = list(out["addons"])
        kept = [a for a in proposed if a in allowed_addons]
        if kept != proposed:
            log.append(
                {
                    "field": "addons",
                    "proposed": proposed,
                    "clamped_to": kept,
                    "reason": "filtered to allowed_addons",
                }
            )
            out["addons"] = kept

    # Expiration
    if out.get("expiration_days") is not None:
        try:
            proposed = int(out["expiration_days"])
        except (TypeError, ValueError):
            proposed = policy["expiration_max_days"]
        cap = int(policy["expiration_max_days"])
        if proposed > cap:
            log.append(
                {
                    "field": "expiration_days",
                    "proposed": proposed,
                    "clamped_to": cap,
                    "reason": f"exceeds expiration_max_days={cap}",
                }
            )
            out["expiration_days"] = cap
        elif proposed < 1:
            log.append(
                {
                    "field": "expiration_days",
                    "proposed": proposed,
                    "clamped_to": 1,
                    "reason": "non-positive expiration",
                }
            )
            out["expiration_days"] = 1

    # Urgency-language scrub
    if policy.get("forbid_urgency_language") and out.get("copy"):
        copy = dict(out["copy"])
        scrubs: list[tuple[str, str]] = []
        for k in ("subject", "body", "cta", "headline"):
            v = copy.get(k)
            if not isinstance(v, str):
                continue
            cleaned = v
            for token in _URGENCY_TOKENS:
                # Match case-insensitively but preserve surrounding text.
                lower = cleaned.lower()
                idx = lower.find(token)
                while idx != -1:
                    cleaned = cleaned[:idx] + cleaned[idx + len(token) :]
                    lower = cleaned.lower()
                    idx = lower.find(token)
            cleaned = " ".join(cleaned.split())  # collapse whitespace
            if cleaned != v:
                scrubs.append((k, v))
                copy[k] = cleaned
        if scrubs:
            log.append(
                {
                    "field": "copy.urgency",
                    "proposed": [k for k, _ in scrubs],
                    "clamped_to": "scrubbed",
                    "reason": "forbid_urgency_language",
                }
            )
            out["copy"] = copy

    return out, log
