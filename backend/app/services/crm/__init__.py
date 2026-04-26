"""CRM integration — read-only customer + product source.

Reads the brand's customer database (mock today; HubSpot / Klaviyo / Shopify
later) and persists normalized rows. Mirrors the kanban service shape:

  - providers/  dumb adapters per source. Normalize to ``NormalizedCustomer`` /
                ``NormalizedEvent`` / ``NormalizedProduct``. No side effects.
  - sync.py     provider-agnostic upsert + bus emit.
"""
