"""Free local model RAM (Docker Model Runner, Ollama) when the user switches model, starts a new chat or asks to."""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.auth_helpers import require_user
from src.docker_model_runner import load_block_reason, looks_like_dmr
from src.llm_core import release_local_models
from src.ram_optimizer import free_ram, runner_urls as _runner_urls


class ReleaseRequest(BaseModel):
    # Model the user is moving to; it stays loaded. Empty unloads them all.
    model: str = ""


def setup_local_model_routes():
    router = APIRouter(prefix="/api/local-models", dependencies=[Depends(require_user)])

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
