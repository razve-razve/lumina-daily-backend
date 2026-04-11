import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from app.config import settings
from app.core.batch_job import run_daily_batch
from app.db.models import Profile, User
from app.db.session import AsyncSessionLocal
from app.services.apns_service import send_daily_notification

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_secret(secret: str):
    if not settings.admin_secret or secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/run-batch")
async def trigger_batch(x_admin_secret: str = Header(...)):
    """Manually trigger the daily batch job. Protected by admin secret."""
    _check_secret(x_admin_secret)
    asyncio.create_task(run_daily_batch())
    return {"status": "batch job started"}


@router.post("/test-push")
async def test_push(x_admin_secret: str = Header(...)):
    """Send a test push notification to all profiles that have a device token."""
    _check_secret(x_admin_secret)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Profile).where(Profile.fcm_token.isnot(None)))
        profiles = list(result.scalars().all())

    if not profiles:
        return {"status": "no device tokens found in database — token was never synced"}

    results = []
    for p in profiles:
        try:
            success = await send_daily_notification(p.fcm_token, "en")
            results.append({"profile_id": str(p.id), "token_prefix": p.fcm_token[:16], "sent": success})
        except Exception as e:
            results.append({"profile_id": str(p.id), "token_prefix": p.fcm_token[:16], "sent": False, "error": str(e)})

    return {"status": "done", "results": results}


@router.get("/debug")
async def debug(x_admin_secret: str = Header(...)):
    """Show database state and APNs config for diagnosing notification issues."""
    _check_secret(x_admin_secret)

    async with AsyncSessionLocal() as db:
        users_result = await db.execute(select(User))
        users = list(users_result.scalars().all())

        profiles_result = await db.execute(select(Profile))
        profiles = list(profiles_result.scalars().all())

    return {
        "users": [{"id": str(u.id), "email": u.email} for u in users],
        "profiles": [
            {
                "id": str(p.id),
                "user_id": str(p.user_id),
                "name": p.name,
                "fcm_token": p.fcm_token[:20] + "..." if p.fcm_token else None,
            }
            for p in profiles
        ],
        "apns_config": {
            "key_id": settings.apns_key_id or "NOT SET",
            "team_id": settings.apns_team_id or "NOT SET",
            "bundle_id": settings.apns_bundle_id or "NOT SET",
            "production": settings.apns_production,
            "key_set": bool(settings.apns_auth_key),
        },
    }
