"""
JWT verification using Supabase's JWKS endpoint.
Supports the new ECC (ES256) keys Supabase uses by default,
with fallback to legacy HS256 shared secrets.
"""
import logging

import httpx
from jose import jwt
from jose.exceptions import JWTError

from app.config import settings

logger = logging.getLogger(__name__)

_jwks_cache: dict | None = None


async def _fetch_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is not None:
        return _jwks_cache
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        logger.info("JWKS fetched and cached from Supabase")
        return _jwks_cache


async def decode_supabase_token(token: str) -> dict:
    """
    Decode and verify a Supabase-issued JWT.
    Tries ES256 (current Supabase default) first, falls back to HS256 (legacy).
    Returns the decoded payload or raises JWTError.
    """
    # Try new ES256 keys via JWKS
    try:
        jwks = await _fetch_jwks()
        payload = jwt.decode(
            token,
            jwks,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
        )
        return payload
    except JWTError:
        pass

    # Fall back to legacy HS256 shared secret
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


def invalidate_jwks_cache() -> None:
    """Call this if keys are rotated and tokens start failing."""
    global _jwks_cache
    _jwks_cache = None
