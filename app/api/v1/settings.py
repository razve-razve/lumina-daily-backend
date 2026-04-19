from __future__ import annotations
from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modes import ALL_MODE_NAMES, FREE_MODES
from app.db.models import User
from app.db.repositories.advice_repository import delete_all_today_advice
from app.db.repositories.profile_repository import get_profile_by_user_id, update_profile
from app.db.repositories.user_repository import get_user_by_id
from app.dependencies import get_current_user, get_db
from app.schemas.advice import SettingsModeRequest, SettingsNotificationsRequest
from app.services.redis_service import delete_cached_advice

router = APIRouter()


class LanguageRequest(BaseModel):
    language: str   # "en" | "ru"


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
):
    return {
        "user_id": str(current_user.id),
        "language": current_user.language,
        "subscription_status": current_user.subscription_status,
    }


# NOTE: There is intentionally NO client-facing endpoint to set subscription_status.
# Subscription status is set exclusively by the RevenueCat webhook
# (POST /api/v1/webhooks/revenuecat), which is protected by a shared secret.
# A client-facing endpoint would let any authenticated user grant themselves Pro
# by sending a fake transaction_id.


@router.put("/language")
async def update_language(
    body: LanguageRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    supported = {"en", "ru"}
    if body.language not in supported:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported language. Choose from: {supported}",
        )
    # Extract before any commit — db.commit() expires ORM objects causing MissingGreenlet
    user_id = current_user.id

    user = await get_user_by_id(db, str(user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    old_language = user.language or "en"
    user.language = body.language
    db.add(user)
    await db.commit()

    # Invalidate ALL today's advice so everything regenerates in the new language.
    today = datetime.now(timezone.utc).date()
    for mode in ALL_MODE_NAMES:
        await delete_cached_advice(str(user_id), today.isoformat(), mode, language=old_language)
    await delete_all_today_advice(db, user_id, today)

    return {"language": body.language}


@router.put("/mode")
async def update_mode(
    body: SettingsModeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.mode not in ALL_MODE_NAMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid mode. Choose from: {ALL_MODE_NAMES}",
        )
    if body.mode not in FREE_MODES and current_user.subscription_status == "free":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This mode requires Lumina Plus. Upgrade to access all 6 modes.",
        )

    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    profile.interpretation_mode = body.mode
    await update_profile(db, profile)
    return {"mode": body.mode}


@router.put("/notifications")
async def update_notifications(
    body: SettingsNotificationsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if body.fcm_token is not None:
        profile.fcm_token = body.fcm_token if body.enabled else None

    if body.notification_time is not None:
        try:
            parts = body.notification_time.split(":")
            if len(parts) != 2:
                raise ValueError("Expected HH:MM")
            h, m = int(parts[0]), int(parts[1])
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError("Hour must be 0–23, minute must be 0–59")
            profile.notification_time = time(h, m)
        except (ValueError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid notification_time. Expected HH:MM (24-hour). {exc}",
            )

    if body.timezone is not None:
        profile.device_timezone = body.timezone

    await update_profile(db, profile)
    return {"notifications_updated": True}


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """GDPR delete — removes user + all data (cascades to profiles + daily_advice)."""
    user = await get_user_by_id(db, str(current_user.id))
    if user:
        await db.delete(user)
        await db.commit()
