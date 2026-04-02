import uuid
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DailyAdvice


async def get_advice(
    db: AsyncSession, user_id: uuid.UUID, target_date: date, mode: str
) -> Optional[DailyAdvice]:
    result = await db.execute(
        select(DailyAdvice).where(
            DailyAdvice.user_id == user_id,
            DailyAdvice.date == target_date,
            DailyAdvice.mode == mode,
        )
    )
    return result.scalar_one_or_none()


async def create_advice(db: AsyncSession, advice: DailyAdvice) -> DailyAdvice:
    db.add(advice)
    await db.commit()
    await db.refresh(advice)
    return advice


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
