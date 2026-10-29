from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.models.journey import Journey, JourneyPhase
from app.schemas.journey import (
    JourneyCreate,
    JourneyPhaseCreate,
    JourneyPhaseResponse,
    JourneyPhaseUpdate,
    JourneyResponse,
    JourneyUpdate,
)

router = APIRouter()


# ── Journey CRUD ──────────────────────────────────────────────────────


@router.get("", response_model=list[JourneyResponse])
async def list_journeys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Journey)
        .options(selectinload(Journey.phases))
        .order_by(Journey.created_at.desc())
    )
    return result.scalars().all()


@router.post("", response_model=JourneyResponse, status_code=201)
async def create_journey(data: JourneyCreate, db: AsyncSession = Depends(get_db)):
    journey = Journey(name=data.name, description=data.description)
    db.add(journey)
    await db.commit()
    result = await db.execute(
        select(Journey)
        .options(selectinload(Journey.phases))
        .where(Journey.id == journey.id)
    )
    return result.scalar_one()


@router.get("/{journey_id}", response_model=JourneyResponse)
async def get_journey(journey_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Journey)
        .options(selectinload(Journey.phases))
        .where(Journey.id == journey_id)
    )
    journey = result.scalar_one_or_none()
    if not journey:
        raise HTTPException(404, "Journey not found")
    return journey


@router.put("/{journey_id}", response_model=JourneyResponse)
async def update_journey(
    journey_id: uuid.UUID,
    data: JourneyUpdate,
    db: AsyncSession = Depends(get_db),
):
    journey = await db.get(Journey, journey_id)
    if not journey:
        raise HTTPException(404, "Journey not found")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(journey, key, value)
    await db.commit()
    result = await db.execute(
        select(Journey)
        .options(selectinload(Journey.phases))
        .where(Journey.id == journey_id)
    )
    return result.scalar_one()


@router.delete("/{journey_id}", status_code=204)
async def delete_journey(journey_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    journey = await db.get(Journey, journey_id)
    if not journey:
        raise HTTPException(404, "Journey not found")
    await db.delete(journey)
    await db.commit()


# ── Phase CRUD (nested under journey) ────────────────────────────────


@router.post(
    "/{journey_id}/phases",
    response_model=JourneyPhaseResponse,
    status_code=201,
)
async def create_phase(
    journey_id: uuid.UUID,
    data: JourneyPhaseCreate,
    db: AsyncSession = Depends(get_db),
):
    journey = await db.get(Journey, journey_id)
    if not journey:
        raise HTTPException(404, "Journey not found")

    # Auto-set order to max+1
    result = await db.execute(
        select(func.coalesce(func.max(JourneyPhase.order), 0)).where(
            JourneyPhase.journey_id == journey_id
        )
    )
    next_order = result.scalar() + 1

    phase = JourneyPhase(
        journey_id=journey_id,
        order=next_order,
        name=data.name,
        instructions=data.instructions,
    )
    db.add(phase)
    await db.commit()
    await db.refresh(phase)
    return phase


@router.put(
    "/{journey_id}/phases/{phase_id}",
    response_model=JourneyPhaseResponse,
)
async def update_phase(
    journey_id: uuid.UUID,
    phase_id: uuid.UUID,
    data: JourneyPhaseUpdate,
    db: AsyncSession = Depends(get_db),
):
    phase = await db.get(JourneyPhase, phase_id)
    if not phase or phase.journey_id != journey_id:
        raise HTTPException(404, "Phase not found")
    update_data = data.model_dump(exclude_unset=True)

    # Handle reordering
    new_order = update_data.pop("order", None)
    for key, value in update_data.items():
        setattr(phase, key, value)

    if new_order is not None and new_order != phase.order:
        old_order = phase.order
        # Shift other phases
        if new_order < old_order:
            result = await db.execute(
                select(JourneyPhase).where(
                    JourneyPhase.journey_id == journey_id,
                    JourneyPhase.order >= new_order,
                    JourneyPhase.order < old_order,
                )
            )
            for p in result.scalars().all():
                p.order += 1
        else:
            result = await db.execute(
                select(JourneyPhase).where(
                    JourneyPhase.journey_id == journey_id,
                    JourneyPhase.order > old_order,
                    JourneyPhase.order <= new_order,
                )
            )
            for p in result.scalars().all():
                p.order -= 1
        phase.order = new_order

    await db.commit()
    await db.refresh(phase)
    return phase


@router.delete("/{journey_id}/phases/{phase_id}", status_code=204)
async def delete_phase(
    journey_id: uuid.UUID,
    phase_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    phase = await db.get(JourneyPhase, phase_id)
    if not phase or phase.journey_id != journey_id:
        raise HTTPException(404, "Phase not found")
    deleted_order = phase.order
    await db.delete(phase)

    # Re-number remaining phases
    result = await db.execute(
        select(JourneyPhase).where(
            JourneyPhase.journey_id == journey_id,
            JourneyPhase.order > deleted_order,
        )
    )
    for p in result.scalars().all():
        p.order -= 1

    await db.commit()
