from __future__ import annotations
"""Redis cache via Upstash — stores daily advice so repeat requests are instant."""
import json
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

_redis: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _advice_key(user_id: str, date: str, mode: str, language: str = "en") -> str:
    return f"advice:{user_id}:{date}:{mode}:{language}"


async def get_cached_advice(user_id: str, date: str, mode: str, language: str = "en") -> Optional[dict]:
    r = get_redis()
    raw = await r.get(_advice_key(user_id, date, mode, language))
    return json.loads(raw) if raw else None


async def cache_advice(user_id: str, date: str, mode: str, data: dict, language: str = "en", ttl_seconds: int = 86400) -> None:
    r = get_redis()
    await r.setex(_advice_key(user_id, date, mode, language), ttl_seconds, json.dumps(data))


async def delete_cached_advice(user_id: str, date: str, mode: str, language: str = "en") -> None:
    r = get_redis()
    await r.delete(_advice_key(user_id, date, mode, language))


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None
