"""Environment CRUD endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.environment import Environment
from app.models.run import RunPersona
from app.schemas.environment import (
    EnvironmentCreate,
    EnvironmentResponse,
    EnvironmentUpdate,
)

router = APIRouter()


async def _get_editable(env_id: uuid.UUID, db: AsyncSession) -> Environment:
    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(404, "Environment not found")
    if env.is_builtin:
        raise HTTPException(403, "Built-in environments cannot be changed")
    return env


@router.get("", response_model=list[EnvironmentResponse])
async def list_environments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Environment).order_by(Environment.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=EnvironmentResponse, status_code=201)
async def create_environment(
    data: EnvironmentCreate, db: AsyncSession = Depends(get_db)
):
    env = Environment(name=data.name, image=data.image, description=data.description)
    db.add(env)
    await db.commit()
    await db.refresh(env)
    return env


@router.get("/{env_id}", response_model=EnvironmentResponse)
async def get_environment(env_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    env = await db.get(Environment, env_id)
    if not env:
        raise HTTPException(404, "Environment not found")
    return env


@router.put("/{env_id}", response_model=EnvironmentResponse)
async def update_environment(
    env_id: uuid.UUID,
    data: EnvironmentUpdate,
    db: AsyncSession = Depends(get_db),
):
    env = await _get_editable(env_id, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is None and key in ("name", "image"):
            continue
        setattr(env, key, value)
    await db.commit()
    await db.refresh(env)
    return env


@router.delete("/{env_id}", status_code=204)
async def delete_environment(env_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    env = await _get_editable(env_id, db)
    used = await db.scalar(
        select(func.count())
        .select_from(RunPersona)
        .where(RunPersona.environment_id == env_id)
    )
    if used:
        raise HTTPException(
            409,
            f"Environment is used by {used} persona run(s); delete those runs first",
        )
    await db.delete(env)
    await db.commit()
