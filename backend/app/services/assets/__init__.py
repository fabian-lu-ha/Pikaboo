"""Brand asset library — persists every generated photo/video so the user
can reuse them later. Bus-driven: a listener subscribes to the relevant
``video.*`` events at app start and writes Asset rows opportunistically.

Direct callers can also use ``record_asset`` for non-bus paths.
"""
from app.services.assets.library import (  # noqa: F401  -- re-exports
    record_asset,
    start_listener,
)
