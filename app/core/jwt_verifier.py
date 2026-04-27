"""
JWT verification using Supabase's JWKS endpoint.
Supports the new ECC (ES256) keys Supabase uses by default,
with fallback to legacy HS256 shared secrets.
"""
import asyncio
import logging
from typing import Optional

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

logger = logging.getLogger(__name__)

_jwks_cache: Optional[dict] = None


async def _fetch_jwks() -> dict:
    """Fetch JWKS from Supabase, with 3 retries and in-memory caching."""
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache

    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    last_error: Optional[Exception] = None

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                _jwks_cache = resp.json()
                logger.info("JWKS fetched and cached from Supabase (attempt %d)", attempt + 1)
                return _jwks_cache
        except Exception as exc:
            last_error = exc
            logger.warning("JWKS fetch attempt %d failed: %s", attempt + 1, exc)
            if attempt < 2:
                await asyncio.sleep(1)

    raise last_error  # type: ignore[misc]


async def decode_supabase_token(token: str) -> dict:
    """
    Decode and verify a Supabase-issued JWT.
    Tries ES256 (current Supabase default) first, falls back to HS256 (legacy).
    On JWKS network failure falls straight through to HS256 — a cold-start
    network hiccup must not lock every user out.
    Returns the decoded payload or raises JWTError.
    """
    # Try ES256/RS256 via JWKS
    jwks_available = False
    try:
        jwks = await _fetch_jwks()
        jwks_available = True
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
        return payload
    except JWTError:
        if jwks_available:
            # JWKS was fetched fine but token truly failed ES256 verification.
            # Still try HS256 below before giving up.
            pass
    except Exception as exc:
        # JWKS network/parse error — log and fall through to HS256.
        # Never let a transient Supabase JWKS outage reject all tokens.
        logger.warning("JWKS fetch/decode failed (%s) — trying HS256 fallback", exc)

    # Fall back to HS256 shared secret
    if settings.supabase_jwt_secret:
        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
            return payload
        except JWTError:
            pass

    raise JWTError("Token verification failed with all available keys")


async def warm_jwks_cache() -> None:
    """Pre-fetch JWKS at startup so the first real request never waits for it."""
    try:
        await _fetch_jwks()
    except Exception as exc:
        logger.warning("JWKS pre-warm failed (will retry on first request): %s", exc)


def invalidate_jwks_cache() -> None:
    """Call this if keys are rotated and tokens start failing."""
    global _jwks_cache
    _jwks_cache = None
