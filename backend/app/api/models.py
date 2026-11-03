"""Which LLM models runs can use."""

from __future__ import annotations

from fastapi import APIRouter

from app.engine.runner import default_model, list_models

router = APIRouter()


@router.get("")
async def get_models() -> dict:
    """The server's default model and, when the provider can list them, the rest."""
    return {"default": default_model({}), "available": await list_models({})}
