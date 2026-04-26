"""Kanban integration — read-only signal source.

Reads the company's project-management board (Trello today; Jira/Linear/Notion
later) and emits classified signals on the event bus:

  - kanban.feature_shipped     a card hit Done / Shipped / Released
  - kanban.feature_in_flight   a card moved into Doing / WIP / Review
  - kanban.marketing_active    activity on a marketing-tagged card

Two-layer architecture:
  - providers/  dumb adapters per source (Trello, Jira, ...). They normalize
                source payloads into ``NormalizedCard`` and never classify.
  - signals.py  provider-agnostic classifier. The agent loop subscribes to
                its events and never imports a concrete provider.
"""
