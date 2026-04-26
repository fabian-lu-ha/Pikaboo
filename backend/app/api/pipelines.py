"""Pipeline editor API.

Endpoints (all under /api/pipelines):
  GET    /                         list pipelines for a brand
  POST   /                         create a pipeline
  GET    /{pipeline_id}            full pipeline (nodes + edges + recent runs)
  PUT    /{pipeline_id}            replace nodes/edges/name (debounced save)
  DELETE /{pipeline_id}            drop the pipeline + its runs
  POST   /{pipeline_id}/run        trigger a background execution
  POST   /{pipeline_id}/webhook    fire a run from an external webhook
  GET    /{pipeline_id}/runs       last N runs (status + finished_at)
  GET    /runs/{run_id}            single run (logs + node_states + result)
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import SessionLocal, get_db
from app.events.bus import bus
from app.events.types import Events
from app.services.llm.client import chat_json
from app.services.pipeline.executor import execute as execute_pipeline

log = logging.getLogger(__name__)

router = APIRouter(prefix="/pipelines")


# ---------- shapes ----------


class NodeIn(BaseModel):
    id: str
    kind: str
    name: str | None = None
    label: str | None = None
    glyph: str | None = None
    tint: str | None = None
    x: float | None = None
    y: float | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class EdgeIn(BaseModel):
    id: str
    from_: str = Field(alias="from")
    to: str

    model_config = {"populate_by_name": True}


class PipelineIn(BaseModel):
    brand_id: str
    name: str = "Untitled Pipeline"
    nodes: list[NodeIn] = Field(default_factory=list)
    edges: list[EdgeIn] = Field(default_factory=list)


class PipelinePut(BaseModel):
    name: str | None = None
    nodes: list[NodeIn] | None = None
    edges: list[EdgeIn] | None = None


def _serialize_pipeline(p: models.Pipeline) -> dict:
    return {
        "id": p.id,
        "brand_id": p.brand_id,
        "name": p.name,
        "nodes": p.nodes or [],
        "edges": p.edges or [],
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _serialize_run(r: models.PipelineRun) -> dict:
    return {
        "id": r.id,
        "pipeline_id": r.pipeline_id,
        "status": r.status,
        "started_at": r.started_at.isoformat() if r.started_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        "node_states": r.node_states or {},
        "logs": r.logs or [],
        "result": r.result or {},
        "error": r.error,
    }


# ---------- CRUD ----------


@router.get("/")
def list_pipelines(
    brand_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    rows = (
        db.query(models.Pipeline)
        .filter(models.Pipeline.brand_id == brand_id)
        .order_by(models.Pipeline.updated_at.desc().nullslast())
        .all()
    )
    return {"pipelines": [_serialize_pipeline(p) for p in rows]}


@router.post("/")
def create_pipeline(
    body: PipelineIn,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")
    p = models.Pipeline(
        brand_id=body.brand_id,
        name=body.name,
        nodes=[n.model_dump() for n in body.nodes],
        edges=[e.model_dump(by_alias=True) for e in body.edges],
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    bus.emit(
        Events.PIPELINE_SAVED,
        {
            "pipeline_id": p.id,
            "brand_id": p.brand_id,
            "name": p.name,
            "node_count": len(p.nodes or []),
            "edge_count": len(p.edges or []),
            "kind": "created",
        },
    )
    return _serialize_pipeline(p)


@router.get("/{pipeline_id}")
def get_pipeline(
    pipeline_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    p = db.get(models.Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    runs = (
        db.query(models.PipelineRun)
        .filter(models.PipelineRun.pipeline_id == pipeline_id)
        .order_by(models.PipelineRun.started_at.desc())
        .limit(10)
        .all()
    )
    return {
        **_serialize_pipeline(p),
        "recent_runs": [_serialize_run(r) for r in runs],
    }


@router.put("/{pipeline_id}")
def update_pipeline(
    pipeline_id: str,
    body: PipelinePut,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    p = db.get(models.Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    if body.name is not None:
        p.name = body.name
    if body.nodes is not None:
        p.nodes = [n.model_dump() for n in body.nodes]
    if body.edges is not None:
        p.edges = [e.model_dump(by_alias=True) for e in body.edges]
    db.add(p)
    db.commit()
    db.refresh(p)
    bus.emit(
        Events.PIPELINE_SAVED,
        {
            "pipeline_id": p.id,
            "brand_id": p.brand_id,
            "name": p.name,
            "node_count": len(p.nodes or []),
            "edge_count": len(p.edges or []),
            "kind": "updated",
        },
    )
    return _serialize_pipeline(p)


@router.delete("/{pipeline_id}")
def delete_pipeline(
    pipeline_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    p = db.get(models.Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    brand_id = p.brand_id
    db.delete(p)
    db.commit()
    bus.emit(
        Events.PIPELINE_DELETED,
        {"pipeline_id": pipeline_id, "brand_id": brand_id},
    )
    return {"ok": True}


# ---------- runs ----------


async def _run_in_background(
    pipeline_id: str, trigger_payload: dict | None = None
) -> None:
    """Execute the pipeline on its own DB session.

    Runs as an asyncio task — we don't want the HTTP request to block on a
    full pipeline run, and the executor emits SSE events as it walks the
    graph so the client gets live progress.
    """
    db = SessionLocal()
    try:
        await execute_pipeline(db, pipeline_id, trigger_payload=trigger_payload)
    except Exception:  # noqa: BLE001
        log.exception("pipeline %s background run failed", pipeline_id)
    finally:
        db.close()


class RunIn(BaseModel):
    """Optional trigger payload from a manual ▶ Run click. Lets the user
    pass arbitrary inputs into the pipeline (e.g. a kanban card preview)
    without going through a real bus event."""

    payload: dict[str, Any] | None = None


@router.post("/{pipeline_id}/run")
async def run_pipeline(
    pipeline_id: str,
    db: Annotated[Session, Depends(get_db)],
    body: RunIn | None = None,
) -> dict:
    p = db.get(models.Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    if not (p.nodes or []):
        raise HTTPException(status_code=400, detail="pipeline has no nodes")
    asyncio.create_task(
        _run_in_background(
            pipeline_id, trigger_payload=(body.payload if body else None)
        )
    )
    return {"ok": True, "pipeline_id": pipeline_id}


def _find_webhook_node(pipeline: models.Pipeline) -> dict | None:
    for n in pipeline.nodes or []:
        if (
            n.get("kind") == "trigger"
            and (n.get("config") or {}).get("variant") == "webhook"
        ):
            return n
    return None


@router.post("/{pipeline_id}/webhook")
async def webhook_trigger(
    pipeline_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_pipeline_token: Annotated[str | None, Header(alias="X-Pipeline-Token")] = None,
) -> dict:
    """Fire a pipeline run from an external webhook.

    Authentication: the trigger node carries a ``token`` in its config.
    Callers send it as either ``X-Pipeline-Token`` or
    ``Authorization: Bearer <token>``. If the trigger has no token set,
    the webhook is open (intended for local-dev only — UI warns).
    """
    p = db.get(models.Pipeline, pipeline_id)
    if p is None:
        raise HTTPException(status_code=404, detail="pipeline not found")
    node = _find_webhook_node(p)
    if node is None:
        raise HTTPException(
            status_code=400, detail="pipeline has no webhook trigger node"
        )
    expected = (node.get("config") or {}).get("token")
    if expected:
        provided = x_pipeline_token
        if not provided and authorization and authorization.lower().startswith("bearer "):
            provided = authorization.split(" ", 1)[1].strip()
        if provided != expected:
            raise HTTPException(status_code=401, detail="invalid token")

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        items = [body] if body else []
    payload = {
        "trigger": "webhook",
        "items": items,
        "raw": body,
    }
    asyncio.create_task(
        _run_in_background(pipeline_id, trigger_payload=payload)
    )
    return {"ok": True, "pipeline_id": pipeline_id, "item_count": len(items)}


@router.get("/{pipeline_id}/runs")
def list_runs(
    pipeline_id: str,
    db: Annotated[Session, Depends(get_db)],
    limit: int = 20,
) -> dict:
    rows = (
        db.query(models.PipelineRun)
        .filter(models.PipelineRun.pipeline_id == pipeline_id)
        .order_by(models.PipelineRun.started_at.desc())
        .limit(limit)
        .all()
    )
    return {"runs": [_serialize_run(r) for r in rows]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    r = db.get(models.PipelineRun, run_id)
    if r is None:
        raise HTTPException(status_code=404, detail="run not found")
    return _serialize_run(r)


# ---------- copilot ----------
# The "Recipe Copilot" chat in the dashboard is grounded in two things:
#   1) what we actually know about the brand (connections, competitor count,
#      voice tone) — fed into the system prompt so the LLM doesn't invent
#      sources that aren't wired up.
#   2) the existing executor's node kinds (source/filter/model/destination) —
#      the model is told the only valid scaffold shape so anything it returns
#      can be POST'd straight into /api/pipelines/.


class CopilotMessage(BaseModel):
    role: str  # "user" | "agent"
    text: str


class CopilotIn(BaseModel):
    brand_id: str
    prompt: str
    history: list[CopilotMessage] = Field(default_factory=list)


_COPILOT_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {
            "type": "string",
            "description": (
                "Concise, conversational reply (1-3 sentences). When suggesting "
                "a pipeline, describe the flow in plain language — don't dump "
                "JSON into the chat."
            ),
        },
        "suggested_pipeline": {
            "type": "object",
            "description": (
                "Optional. Set ONLY when the user asked for something concrete "
                "enough to scaffold. Otherwise omit."
            ),
            "properties": {
                "name": {"type": "string"},
                "summary": {"type": "string"},
                "nodes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "kind": {
                                "type": "string",
                                "enum": [
                                    "source",
                                    "filter",
                                    "model",
                                    "destination",
                                ],
                            },
                            "name": {"type": "string"},
                            "config": {"type": "object"},
                        },
                        "required": ["id", "kind", "name"],
                    },
                },
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "from": {"type": "string"},
                            "to": {"type": "string"},
                        },
                        "required": ["id", "from", "to"],
                    },
                },
            },
            "required": ["name", "nodes", "edges"],
        },
    },
    "required": ["reply"],
}


_TINTS = {
    "source": "sky",
    "filter": "amber",
    "model": "violet",
    "destination": "emerald",
}
_GLYPHS = {
    "source": "◈",
    "filter": "▽",
    "model": "✦",
    "destination": "◇",
}
_LABELS = {
    "source": "SOURCE",
    "filter": "FILTER",
    "model": "AI MODEL",
    "destination": "DESTINATION",
}


def _layout_pipeline(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Lay out the LLM-generated nodes left→right so the canvas isn't a pile.

    Topo-rank each node (longest path from a source). Nodes at the same rank
    stack vertically. Coordinates are world-space (matching FlowNode.x / .y).
    """
    incoming: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    for e in edges:
        if e.get("to") in incoming and e.get("from") in incoming:
            incoming[e["to"]].add(e["from"])

    rank: dict[str, int] = {}
    # Kahn-style longest-path via memoized recursion. Cycles → rank 0 fallback.
    def _rank(nid: str, seen: set[str]) -> int:
        if nid in rank:
            return rank[nid]
        if nid in seen:
            return 0
        if not incoming[nid]:
            rank[nid] = 0
            return 0
        seen = seen | {nid}
        r = 1 + max(_rank(p, seen) for p in incoming[nid])
        rank[nid] = r
        return r

    for n in nodes:
        _rank(n["id"], set())

    by_rank: dict[int, list[dict]] = defaultdict(list)
    for n in nodes:
        by_rank[rank.get(n["id"], 0)].append(n)

    out: list[dict] = []
    for r, group in by_rank.items():
        for i, n in enumerate(group):
            kind = (n.get("kind") or "source").lower()
            out.append(
                {
                    "id": n["id"],
                    "kind": kind,
                    "name": n.get("name") or "Untitled",
                    "label": _LABELS.get(kind, kind.upper()),
                    "glyph": _GLYPHS.get(kind, "●"),
                    "tint": _TINTS.get(kind, "sky"),
                    "config": n.get("config") or {},
                    "x": 140 + r * 320,
                    "y": 180 + i * 160,
                }
            )
    return out


@router.post("/copilot")
async def pipeline_copilot(
    body: CopilotIn,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    brand = db.get(models.Brand, body.brand_id)
    if brand is None:
        raise HTTPException(status_code=404, detail="brand not found")

    kanban_providers = list((brand.kanban_connections or {}).keys())
    crm_providers = list((brand.crm_connections or {}).keys())
    social_providers = list((brand.social_connections or {}).keys())
    customer_count = (
        db.query(models.Customer)
        .filter(models.Customer.brand_id == brand.id)
        .count()
    )
    pipeline_count = (
        db.query(models.Pipeline)
        .filter(models.Pipeline.brand_id == brand.id)
        .count()
    )

    voice = brand.voice_profile or {}
    tone = voice.get("tone") or "balanced"

    system = (
        f"You are the Recipe Copilot inside Brand Autopilot for the brand "
        f"\"{brand.name}\". You help the operator design data pipelines that "
        "the in-app executor can actually run.\n\n"
        "GROUND TRUTH:\n"
        f"- Connected kanban providers: {kanban_providers or 'none'}\n"
        f"- Connected CRM providers: {crm_providers or 'none'}\n"
        f"- Connected social providers: {social_providers or 'none'}\n"
        f"- Customers in DB: {customer_count}\n"
        f"- Existing pipelines: {pipeline_count}\n"
        f"- Brand voice tone: {tone}\n"
        f"- Tracked competitors: {len(brand.competitors)}\n\n"
        "PIPELINE GRAMMAR (the only thing the executor accepts):\n"
        "- Node kinds: 'source', 'filter', 'model', 'destination'.\n"
        "- 'source' configs: provider can be 'CRM Export · Klaviyo', "
        "'CRM Export · HubSpot', 'CRM Export · Mock', "
        "'Kanban · Trello', 'Kanban · Linear', 'Kanban · Notion', or any "
        "string mentioning kanban/crm/klaviyo/hubspot. The executor matches "
        "on substring.\n"
        "- 'filter' config: rule (free-text substring), strict (bool).\n"
        "- 'model' config: version, threshold (0-100), tags (string list).\n"
        "- 'destination' config: target, format ('JSON' | 'CSV').\n"
        "- Every pipeline must start with at least one source and end with a "
        "destination. Edges connect node ids and must form a DAG.\n\n"
        "STYLE:\n"
        "- Reply concisely. 1-3 sentences. No markdown, no emoji.\n"
        "- If the user asks something open-ended, ask a clarifying question "
        "instead of inventing a pipeline.\n"
        "- Only set suggested_pipeline when the user asked for something "
        "concrete (a recipe, a flow, a use case). When you do, the reply "
        "should describe what you scaffolded in plain language.\n"
        "- Never reference data sources that aren't connected as if they "
        "were live; flag them as 'needs setup' in the reply instead."
    )

    chat: list[dict[str, str]] = [{"role": "system", "content": system}]
    for m in body.history[-12:]:
        role = "assistant" if m.role == "agent" else "user"
        chat.append({"role": role, "content": m.text})
    chat.append({"role": "user", "content": body.prompt})

    try:
        result = await chat_json(chat, schema=_COPILOT_SCHEMA)
    except Exception as e:  # noqa: BLE001
        log.exception("copilot llm call failed: %s", e)
        return {
            "reply": (
                "I'm offline at the moment — the LLM call failed. "
                "Try again in a sec or rephrase what you need."
            ),
            "suggested_pipeline": None,
        }

    suggested = result.get("suggested_pipeline")
    if suggested:
        nodes_in = list(suggested.get("nodes") or [])
        edges_in = list(suggested.get("edges") or [])
        # Reject obviously broken scaffolds rather than letting the user
        # accept a pipeline that won't run.
        if nodes_in:
            laid_out = _layout_pipeline(nodes_in, edges_in)
            suggested = {
                "name": suggested.get("name") or "Untitled Pipeline",
                "summary": suggested.get("summary") or "",
                "nodes": laid_out,
                "edges": [
                    {
                        "id": e.get("id") or f"e-{i}",
                        "from": e["from"],
                        "to": e["to"],
                    }
                    for i, e in enumerate(edges_in)
                    if e.get("from") and e.get("to")
                ],
            }
        else:
            suggested = None

    return {
        "reply": result.get("reply") or "",
        "suggested_pipeline": suggested,
    }
