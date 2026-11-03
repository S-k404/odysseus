"""Free local model RAM when the user switches model or starts a new chat."""

import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.database import ModelEndpoint, SessionLocal
from src.auth_helpers import require_user
from src.docker_model_runner import load_block_reason, looks_like_dmr, runner_root
from src.llm_core import release_local_models


class ReleaseRequest(BaseModel):
    # Model the user is moving to; it stays loaded. Empty unloads them all.
    model: str = ""


def _runner_urls() -> list:
    db = SessionLocal()
    try:
        urls = [ep.base_url for ep in db.query(ModelEndpoint).filter(ModelEndpoint.is_enabled == True).all()]  # noqa: E712
    finally:
        db.close()
    seen, out = set(), []
    for url in urls:
        root = runner_root(url or "")
        if root and looks_like_dmr(url) and root not in seen:
            seen.add(root)
            out.append(url)
    return out


def setup_local_model_routes():
    router = APIRouter(prefix="/api/local-models", dependencies=[Depends(require_user)])

    @router.post("/release")
    async def release(body: ReleaseRequest):
        keep = body.model.strip()
        urls = _runner_urls()
        # Picking a model that will be refused shouldn't cost the working one.
        for url in urls:
            if await asyncio.to_thread(load_block_reason, url, keep):
                return {"unloaded": [], "skipped": "blocked"}
        return await release_local_models(urls, keep=keep)

    return router
