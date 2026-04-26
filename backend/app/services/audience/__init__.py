"""Audience service — segmentation + personalized email drafts.

Reads from the persisted Customer / CustomerEvent / Product tables (populated
by ``services.crm.sync``) and runs LLM steps to produce segments and email
drafts. PII never leaves the box unmediated — see ``services.pii``.

Importing this package registers the shop-event auto-personalize listener
AND the campaign-trigger dispatcher (cart_abandoned / subscription_lapsed
auto-plan a draft Campaign).
"""
from app.services.audience import shop_triggers as _shop_triggers
from app.services.audience import triggers as _triggers

_shop_triggers.register()
_triggers.register()

