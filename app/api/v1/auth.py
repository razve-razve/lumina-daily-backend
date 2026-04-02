"""
Auth endpoints — user record creation after Supabase handles sign-in.
Supabase manages all actual authentication (Apple, email, etc.).
"""
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt_verifier import decode_supabase_token
from app.db.models import User
from app.db.repositories.user_repository import create_user, get_user_by_id
from app.dependencies import get_db

router = APIRouter()


async def _decode_token(authorization: str) -> dict:
    """Verify Supabase JWT (ES256 via JWKS) and return payload."""
    token = authorization.removeprefix("Bearer ")
    try:
        payload = await decode_supabase_token(token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Called once after the user signs in via Supabase for the first time.
    Creates the user row in our database.
    """
    payload = await _decode_token(authorization)
    user_id_str = payload["sub"]

    existing = await get_user_by_id(db, user_id_str)
    if existing:
        return {"user_id": str(existing.id), "created": False}

    user = User(
        id=uuid.UUID(user_id_str),
        email=payload.get("email"),
        language="en",
        subscription_status="free",
    )
    await create_user(db, user)
    return {"user_id": user_id_str, "created": True}


@router.get("/me")
async def me(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    payload = await _decode_token(authorization)
    user_id_str = payload["sub"]

    user = await get_user_by_id(db, user_id_str)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "user_id": str(user.id),
        "language": user.language,
        "subscription_status": user.subscription_status,
    }
