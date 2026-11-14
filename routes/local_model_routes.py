"""Free local model RAM (Docker Model Runner, Ollama) when the user switches model, starts a new chat or asks to."""

import asyncio
from dataclasses import asdict
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.auth_helpers import require_user
from src.docker_model_runner import load_block_reason, looks_like_dmr
from src.llm_core import release_local_models
from src import memory_guard
from src.model_context import is_local_endpoint
from src.model_router import Candidate, estimate_gb, route as route_model
from src.ram_optimizer import free_ram, runner_urls as _runner_urls


class ReleaseRequest(BaseModel):
    # Model the user is moving to; it stays loaded. Empty unloads them all.
    model: str = ""


class RouteCandidate(BaseModel):
    model: str
    endpoint_id: str = ""
    url: str = ""


class RouteRequest(BaseModel):
    message: str = ""
    current: str = ""            # the model the chat is on now
    previous_text: str = ""      # the text model to return to after a picture
    mode: str = "chat"
    has_image: bool = False
    plan_mode: bool = False
    approved_plan: bool = False
    last_image: bool = False     # the chat already has a generated picture on screen
    candidates: List[RouteCandidate] = []


def _fits_by_name(c: Candidate) -> bool:
    """Would this model fit in memory now? Local engines the load guard does not know are judged by an estimate from the
    model's name (and a model of unknown size, or one on a remote server, is let through)."""
    need = estimate_gb(c.model)
    if need is None or not is_local_endpoint(c.url):
        return True
    snap = memory_guard.snapshot()
    if not snap:
        return True
    return need <= float(snap["available_gb"]) - max(4.0, 0.10 * float(snap["total_gb"]))


def setup_local_model_routes():
    router = APIRouter(prefix="/api/local-models", dependencies=[Depends(require_user)])

    @router.post("/route")
    async def route(body: RouteRequest):
        """Which model fits this message? Returns {switch, model, endpoint_id, reason, intent}; never loads anything."""
        verdicts = {}

        def fits(c: Candidate) -> bool:  # the load guard (RAM, vLLM-Metal), asked once per model
            if c.model not in verdicts:
                ok = not load_block_reason(c.url, c.model)
                if ok and not looks_like_dmr(c.url):
                    ok = _fits_by_name(c)  # the guard only knows Docker Model Runner; judge other local engines by size
                verdicts[c.model] = ok
            return verdicts[c.model]

        decision = await asyncio.to_thread(
            route_model, body.message, body.current, [Candidate(**c.model_dump()) for c in body.candidates],
            has_image=body.has_image, plan_mode=body.plan_mode, approved_plan=body.approved_plan,
            mode=body.mode, previous_text=body.previous_text, last_image=body.last_image, fits=fits,
        )
        return asdict(decision)

    @router.post("/optimize")
    async def optimize(body: ReleaseRequest):
        """Free what Odysseus can (the "Optimise memory" button and menu bar item)."""
        return await free_ram(await asyncio.to_thread(_runner_urls), keep=body.model.strip())

    @router.post("/release")
    async def release(body: ReleaseRequest):
        keep = body.model.strip()
        urls = await asyncio.to_thread(_runner_urls)
        # Picking a model that will be refused shouldn't cost the working one.
        for url in urls:
            if looks_like_dmr(url) and await asyncio.to_thread(load_block_reason, url, keep):
                return {"unloaded": [], "skipped": "blocked"}
        return await release_local_models(urls, keep=keep)

    return router
