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
    """Delete today's advice for a user (DB + Redis) so it regenerates fresh.

    Must clear BOTH stores: /today caches the full advice in Redis for 24h, so
    deleting only the DB row would still serve the stale cached copy.
    """
    _check_secret(x_admin_secret)
    import uuid
    from datetime import datetime, timezone
    from app.db.repositories.advice_repository import delete_all_today_advice
    from app.services.redis_service import delete_cached_advice
    from app.core.modes import MODES

    today = datetime.now(timezone.utc).date()
    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as db:
        await delete_all_today_advice(db, uid, today)

    # Purge the Redis cache across every mode × language for today.
    for mode in MODES.keys():
        for lang in ("en", "ru", "pt"):
            await delete_cached_advice(str(uid), today.isoformat(), mode, language=lang)

    return {"status": "cleared (db + redis)", "user_id": user_id, "date": str(today)}


@router.get("/score-preview/{user_id}")
async def score_preview(user_id: str, date: str | None = None, x_admin_secret: str = Header(...)):
    """Show a user's category scores computed at several hours of a date.

    Read-only (no writes). Demonstrates how much the day's scores drift by hour
    (the fast Moon), so you can see the noon-UTC anchor is a representative
    sample, not an anomalous low. `date` = YYYY-MM-DD (default: today UTC).
    """
    _check_secret(x_admin_secret)
    import uuid
    from datetime import datetime, timezone
    import swisseph as swe
    from app.core.ephemeris import (
        calculate_current_transits, calculate_transit_aspects_to_natal, julian_day_for_local_noon,
    )
    from app.core.scoring import score_categories
    from app.db.repositories.profile_repository import get_profile_by_user_id

    d = datetime.strptime(date, "%Y-%m-%d").date() if date else datetime.now(timezone.utc).date()
    async with AsyncSessionLocal() as db:
        profile = await get_profile_by_user_id(db, uuid.UUID(user_id))
    if not profile:
        return {"error": "no profile"}
    natal_planets = (profile.natal_chart_json or {}).get("planets", {})

    def scores_at(jd: float) -> dict:
        aspects = calculate_transit_aspects_to_natal(calculate_current_transits(jd), natal_planets)
        s = score_categories(aspects)
        s["day_avg"] = round((s["love"] + s["work"] + s["energy"] + s["communication"] + s["mood"]) / 5)
        return s

    rows = []
    for hour in (0, 3, 6, 9, 12, 15, 18, 21):
        s = scores_at(swe.julday(d.year, d.month, d.day, float(hour)))
        rows.append({"utc_hour": hour, **s})

    # The anchor actually used to score this day: the user's LOCAL noon.
    anchor = scores_at(julian_day_for_local_noon(d, profile.device_timezone))
    day_avgs = [r["day_avg"] for r in rows]
    return {
        "date": str(d),
        "device_timezone": profile.device_timezone or "UTC",
        "anchor_used": {"local_noon": True, **anchor},
        "day_avg_range_across_utc_hours": {"min": min(day_avgs), "max": max(day_avgs)},
        "note": "Scores drift by hour (Moon ~0.5°/h). 'anchor_used' = the user's local noon — the value the app now stores.",
        "hourly_utc": rows,
    }


@router.get("/token-health")
async def token_health(x_admin_secret: str = Header(...)):
    """Validate EVERY device token without disturbing users.

    Sends a SILENT background push (content-available, no alert/sound) to each
    profile's token and reports Apple's per-token status. 200 = token live,
    410 = Unregistered (app deleted / token rotated — should be cleared),
    400 BadDeviceToken = wrong environment. Nothing is shown on any device.
    """
    _check_secret(x_admin_secret)

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Profile).where(Profile.fcm_token.isnot(None)))
        profiles = list(result.scalars().all())
        users = {u.id: u for u in (await db.execute(select(User))).scalars().all()}

    if not profiles:
        return {"status": "no device tokens in database"}

    import httpx
    from app.services.apns_service import _apns_base_url, _make_jwt
    from app.config import settings as cfg

    live, dead = 0, 0
    results = []
    for p in profiles:
        email = users[p.user_id].email if p.user_id in users else None
        try:
            jwt_token = _make_jwt()
            url = f"{_apns_base_url()}/3/device/{p.fcm_token}"
            headers = {
                "authorization": f"bearer {jwt_token}",
                "apns-topic": cfg.apns_bundle_id,
                "apns-push-type": "background",   # silent — not shown to the user
                "apns-priority": "5",             # required for background pushes
            }
            payload = {"aps": {"content-available": 1}}
            async with httpx.AsyncClient(http2=True, timeout=10) as client:
                resp = await client.post(url, json=payload, headers=headers)
            ok = resp.status_code == 200
            live += 1 if ok else 0
            dead += 0 if ok else 1
            results.append({
                "name": p.name,
                "email": email,
                "status": resp.status_code,
                "reason": "live" if ok else (resp.text or "unknown"),
            })
        except Exception as e:
            dead += 1
            results.append({"name": p.name, "email": email, "status": "error", "reason": str(e)})

    return {
        "summary": {"total": len(profiles), "live": live, "dead": dead},
        "apns_url": _apns_base_url(),
        "results": results,
    }


@router.get("/notif-status/{user_id}")
async def notif_status(user_id: str, x_admin_secret: str = Header(...)):
    """Diagnose why a single user is / isn't getting daily pushes.

    Reports every condition the hourly notification job checks: timezone,
    desired hour, current local hour, catch-up window, whether advice exists
    for the user's local today, and whether the dedup lock is currently set.
    """
    _check_secret(x_admin_secret)
    import uuid
    from app.core.batch_job import (
        _user_local_hour, _user_local_date, _DEFAULT_LOCAL_HOUR,
    )
    from app.db.repositories.profile_repository import get_profile_by_user_id
    from app.db.repositories.advice_repository import get_advice
    from app.services.redis_service import redis_get

    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        profile = await get_profile_by_user_id(db, uid)
        if not profile:
            return {"error": "no profile for that user_id"}

        tz_id = profile.device_timezone
        local_hour = _user_local_hour(tz_id)
        local_date = _user_local_date(tz_id)
        desired = profile.notification_time.hour if profile.notification_time else _DEFAULT_LOCAL_HOUR
        catchup = 6
        in_window = desired <= local_hour <= desired + catchup

        language = (user.language if user else None) or "en"
        advice = await get_advice(db, uid, local_date, profile.interpretation_mode, language=language)

        lock_key = f"notif_sent:{uid}:{local_date.isoformat()}"
        lock = await redis_get(lock_key)

    return {
        "name": profile.name,
        "has_token": bool(profile.fcm_token),
        "device_timezone": tz_id or "NOT SET (defaults to UTC)",
        "desired_hour_local": desired,
        "current_local_hour": local_hour,
        "local_date": str(local_date),
        "in_send_window": in_window,
        "window": f"{desired}:00 .. {desired + catchup}:00 local",
        "interpretation_mode": profile.interpretation_mode,
        "language": language,
        "advice_exists_for_local_today": advice is not None,
        "dedup_lock_set": lock is not None,
        "dedup_lock_key": lock_key,
        "verdict": (
            "LOCK STUCK: lock is set but blocks resend — clear it to unblock"
            if (lock is not None and advice is None) else
            "NO ADVICE for local today — job skips push (and burns the lock)"
            if advice is None else
            "OK: would send inside window if lock not already set"
        ),
    }


@router.delete("/notif-lock/{user_id}")
async def clear_notif_lock(user_id: str, x_admin_secret: str = Header(...)):
    """Clear today's dedup lock so the next hourly run can (re)send the push."""
    _check_secret(x_admin_secret)
    import uuid
    from app.core.batch_job import _user_local_date
    from app.db.repositories.profile_repository import get_profile_by_user_id
    from app.services.redis_service import redis_delete

    uid = uuid.UUID(user_id)
    async with AsyncSessionLocal() as db:
        profile = await get_profile_by_user_id(db, uid)
        tz_id = profile.device_timezone if profile else None
    local_date = _user_local_date(tz_id)
    lock_key = f"notif_sent:{uid}:{local_date.isoformat()}"
    await redis_delete(lock_key)
    return {"status": "cleared", "lock_key": lock_key}


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
