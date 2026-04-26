"""Per-action GEO asset generators. Each module exports an async
``generate(brand, gap, recommendation) -> GeneratedAsset`` function.

The dispatch table lives in ``asset_generator.py`` — adding a new
playbook entry is one new module + one row in ``_register()``."""
