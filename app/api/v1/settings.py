from datetime import time

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.modes import ALL_MODE_NAMES, FREE_MODES
from app.db.models import User
from app.db.repositories.profile_repository import get_profile_by_user_id, update_profile
from app.db.repositories.user_repository import get_user_by_id
from app.dependencies import get_current_user, get_db
from app.schemas.advice import SettingsModeRequest, SettingsNotificationsRequest

router = APIRouter()


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
        h, m = map(int, body.notification_time.split(":"))
        profile.notification_time = time(h, m)

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
