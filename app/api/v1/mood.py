"""Mood journal — user's own 1-5 rating of how the day actually went.

Zero AI cost: plain rows in Postgres. Later powers the "prediction vs reality"
patterns screen once enough entries accumulate.
"""
from __future__ import annotations
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import MoodEntry, User
from app.dependencies import get_current_user, get_db

router = APIRouter()


class MoodUpsertRequest(BaseModel):
    date: date
    rating: int = Field(..., ge=1, le=5)


class MoodEntryResponse(BaseModel):
    date: str      # "YYYY-MM-DD"
    rating: int    # 1-5


@router.put("", response_model=MoodEntryResponse)
async def upsert_mood(
    body: MoodUpsertRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save (or update) the user's rating for a day. Future dates rejected."""
    if body.date > date.today():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot rate a future date.")

    result = await db.execute(
        select(MoodEntry).where(MoodEntry.user_id == current_user.id, MoodEntry.date == body.date)
    )
    entry = result.scalar_one_or_none()
    if entry:
        entry.rating = body.rating
    else:
        entry = MoodEntry(user_id=current_user.id, date=body.date, rating=body.rating)
        db.add(entry)
    await db.commit()
    return MoodEntryResponse(date=body.date.isoformat(), rating=body.rating)


@router.get("", response_model=list[MoodEntryResponse])
async def get_mood_range(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """All mood entries in [start, end]."""
    if end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be >= start")
    if (end - start).days > 400:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Range too large (max 400 days).")

    result = await db.execute(
        select(MoodEntry)
        .where(MoodEntry.user_id == current_user.id, MoodEntry.date >= start, MoodEntry.date <= end)
        .order_by(MoodEntry.date)
    )
    return [
        MoodEntryResponse(date=e.date.isoformat(), rating=e.rating)
        for e in result.scalars().all()
    ]
