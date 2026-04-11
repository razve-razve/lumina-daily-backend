"""
Apple Push Notification service (token-based auth, HTTP/2).
Replaces Firebase Admin SDK — no Firebase project required.

Required env vars:
  APNS_AUTH_KEY   — full contents of the .p8 file (with newlines as \\n)
  APNS_KEY_ID     — 10-char key ID from Apple Developer portal
  APNS_TEAM_ID    — 10-char team ID from Apple Developer portal
  APNS_BUNDLE_ID  — app bundle ID, e.g. com.yourname.lumina-daily
  APNS_PRODUCTION — "true" for production, "false" for sandbox (default true)
"""
from __future__ import annotations

import logging
import time

import httpx
from jose import jwt as jose_jwt

from app.config import settings

logger = logging.getLogger(__name__)

_PROD_URL = "https://api.push.apple.com"
_DEV_URL  = "https://api.development.push.apple.com"

# Cache the signed JWT for 55 min (valid for 60 min)
_jwt_cache: tuple[str, float] | None = None


def _apns_base_url() -> str:
    return _PROD_URL if getattr(settings, "apns_production", "true") == "true" else _DEV_URL


def _make_jwt() -> str:
    global _jwt_cache
    now = time.time()
    if _jwt_cache and _jwt_cache[1] > now + 60:
        return _jwt_cache[0]

    key_pem: str = getattr(settings, "apns_auth_key", "")
    key_id:  str = getattr(settings, "apns_key_id",   "")
    team_id: str = getattr(settings, "apns_team_id",  "")

    if not key_pem or not key_id or not team_id:
        raise RuntimeError("APNs not configured — set APNS_AUTH_KEY, APNS_KEY_ID, APNS_TEAM_ID")

    # p8 files use \\n in env vars — normalize to real newlines
    key_pem = key_pem.replace("\\n", "\n")

    token = jose_jwt.encode(
        {"iss": team_id, "iat": int(now)},
        key_pem,
        algorithm="ES256",
        headers={"kid": key_id, "alg": "ES256"},
    )
    _jwt_cache = (token, now + 3300)  # 55 min
    return token


async def send_daily_notification(device_token: str, language: str) -> bool:
    """Send 'your guidance is ready' push notification via APNs. Returns True on success."""
    if not device_token:
        return False

    bundle_id: str = getattr(settings, "apns_bundle_id", "")
    if not bundle_id:
        logger.warning("APNS_BUNDLE_ID not set — skipping push")
        return False

    messages = {
        "en": ("Your daily guidance is ready ✨", "Open Lumina Daily to read your stars."),
        "ru": ("Ваш ежедневный прогноз готов ✨", "Откройте Lumina Daily, чтобы узнать, что говорят звёзды."),
    }
    title, body = messages.get(language, messages["en"])

    try:
        jwt_token = _make_jwt()
    except Exception as e:
        logger.warning(f"APNs JWT error: {e}")
        return False

    url = f"{_apns_base_url()}/3/device/{device_token}"
    headers = {
        "authorization": f"bearer {jwt_token}",
        "apns-topic": bundle_id,
        "apns-push-type": "alert",
        "apns-priority": "10",
    }
    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        }
    }

    try:
        async with httpx.AsyncClient(http2=True, timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code == 200:
            return True
        logger.warning(f"APNs rejected token {device_token[:16]}…: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.warning(f"APNs request failed: {e}")
        return False
