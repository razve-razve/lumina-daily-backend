from __future__ import annotations
import uuid
from datetime import date
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyAdvice


async def get_advice(
    db: AsyncSession, user_id: uuid.UUID, target_date: date, mode: str,
    language: Optional[str] = None,
) -> Optional[DailyAdvice]:
    filters = [
        DailyAdvice.user_id == user_id,
        DailyAdvice.date == target_date,
        DailyAdvice.mode == mode,
    ]
    if language:
        filters.append(DailyAdvice.language == language)
    result = await db.execute(select(DailyAdvice).where(*filters))
    return result.scalar_one_or_none()


async def get_advice_range(
    db: AsyncSession, user_id: uuid.UUID, start: date, end: date,
) -> list[DailyAdvice]:
    """All stored advice rows for a user in [start, end] — any mode/language.
    Read-only: never triggers generation."""
    result = await db.execute(
        select(DailyAdvice)
        .where(
            DailyAdvice.user_id == user_id,
            DailyAdvice.date >= start,
            DailyAdvice.date <= end,
        )
        .order_by(DailyAdvice.date)
    )
    return list(result.scalars().all())


async def create_advice(db: AsyncSession, advice: DailyAdvice) -> DailyAdvice:
    try:
        db.add(advice)
        await db.commit()
        await db.refresh(advice)
        return advice
    except IntegrityError:
        await db.rollback()
        # Try same language first (concurrent request race)
        existing = await get_advice(db, advice.user_id, advice.date, advice.mode, language=advice.language)
        if existing:
            return existing
        # Language mismatch — old row exists in a different language (e.g. user switched language).
        # Delete the stale row and re-insert in the new language.
        stale = await get_advice(db, advice.user_id, advice.date, advice.mode)
        if stale:
            await db.delete(stale)
            await db.commit()
            db.add(advice)
            await db.commit()
            await db.refresh(advice)
            return advice
        raise


async def delete_advice(
    db: AsyncSession, user_id: uuid.UUID, target_date: date, mode: str
) -> None:
    result = await db.execute(
        select(DailyAdvice).where(
            DailyAdvice.user_id == user_id,
            DailyAdvice.date == target_date,
            DailyAdvice.mode == mode,
        )
    )
    advice = result.scalar_one_or_none()
    if advice:
        await db.delete(advice)
        await db.commit()


async def delete_all_today_advice(
    db: AsyncSession, user_id: uuid.UUID, target_date: date
) -> None:
    """Delete all advice rows for a user on a given date (all modes). Single commit."""
    await db.execute(
        delete(DailyAdvice).where(
            DailyAdvice.user_id == user_id,
            DailyAdvice.date == target_date,
        )
    )
    await db.commit()


async def get_recent_advice(
    db: AsyncSession,
    user_id: uuid.UUID,
    mode: str,
    limit: int = 7,
) -> list[DailyAdvice]:
    result = await db.execute(
        select(DailyAdvice)
        .where(DailyAdvice.user_id == user_id, DailyAdvice.mode == mode)
        .order_by(DailyAdvice.date.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
