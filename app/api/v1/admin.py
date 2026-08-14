import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException
from sqlalchemy import select

from app.config import settings
from app.core.batch_job import run_advice_job
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
    asyncio.create_task(run_advice_job())
    return {"status": "batch job started"}


@router.post("/test-push")
async def test_push(x_admin_secret: str = Header(...), user_id: str | None = None):
    """Send a test push notification.

    By default targets every profile with a device token. Pass ?user_id=<uuid>
    to send to ONLY that one user's device — used for diagnosing a single
    device without notifying real users.
    """
    _check_secret(x_admin_secret)

    async with AsyncSessionLocal() as db:
        query = select(Profile).where(Profile.fcm_token.isnot(None))
        if user_id:
            import uuid
            try:
                query = query.where(Profile.user_id == uuid.UUID(user_id))
            except ValueError:
                raise HTTPException(status_code=400, detail="user_id must be a valid UUID")
        result = await db.execute(query)
        profiles = list(result.scalars().all())

    if not profiles:
        return {"status": "no device tokens found in database — token was never synced"}

    import httpx
    from app.services.apns_service import _apns_base_url, _make_jwt
    from app.config import settings as cfg

    results = []
    for p in profiles:
        try:
            jwt_token = _make_jwt()
            url = f"{_apns_base_url()}/3/device/{p.fcm_token}"
            headers = {
                "authorization": f"bearer {jwt_token}",
                "apns-topic": cfg.apns_bundle_id,
                "apns-push-type": "alert",
                "apns-priority": "10",
            }
            payload = {"aps": {"alert": {"title": "Test", "body": "Lumina test notification"}, "sound": "default"}}
            async with httpx.AsyncClient(http2=True, timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
            results.append({
                "profile_id": str(p.id),
                "token_prefix": p.fcm_token[:16],
                "apns_status": resp.status_code,
                "apns_reason": resp.text or "OK",
            })
        except Exception as e:
            results.append({"profile_id": str(p.id), "token_prefix": p.fcm_token[:16], "error": str(e)})

    return {"status": "done", "apns_url": _apns_base_url(), "results": results}


@router.delete("/clear-advice/{user_id}")
async def clear_advice(user_id: str, x_admin_secret: str = Header(...)):
    """Delete all today's advice for a user so it regenerates fresh."""
    _check_secret(x_admin_secret)
    import uuid
    from datetime import datetime, timezone
    from app.db.repositories.advice_repository import delete_all_today_advice
    today = datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as db:
        await delete_all_today_advice(db, uuid.UUID(user_id), today)
    return {"status": "cleared", "user_id": user_id, "date": str(today)}


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
