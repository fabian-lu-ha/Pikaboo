"""Agent loop — the heart of the product. Listens for chat.submitted on
the pyee bus and runs the full draft+image+lift pipeline."""

from app.services.agent.loop import register_listener, run_agent

__all__ = ["register_listener", "run_agent"]
