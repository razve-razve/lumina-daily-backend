"""
Auth endpoints — user record creation after Supabase handles sign-in.
Supabase manages all actual authentication (Apple, email, etc.).
"""
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import User
from app.db.repositories.user_repository import create_user, get_user_by_id
from app.dependencies import get_db

router = APIRouter()


def _decode_token(authorization: str) -> str:
    """Decode Supabase JWT and return user UUID string."""
    try:
        token = authorization.removeprefix("Bearer ")
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Called once after the user signs in via Supabase for the first time.
    Creates the user row in our database.
    """
    user_id_str = _decode_token(authorization)
    existing = await get_user_by_id(db, user_id_str)
    if existing:
        return {"user_id": str(existing.id), "created": False}

    # Extract optional fields from JWT claims
    token = authorization.removeprefix("Bearer ")
    payload = jwt.decode(
        token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
    )
    email    = payload.get("email")
    language = "en"   # will be updated during onboarding

    user = User(
        id=uuid.UUID(user_id_str),
        email=email,
        language=language,
        subscription_status="free",
    )
    await create_user(db, user)
    return {"user_id": user_id_str, "created": True}


@router.get("/me")
async def me(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
):
    user_id_str = _decode_token(authorization)
    user = await get_user_by_id(db, user_id_str)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "user_id": str(user.id),
        "language": user.language,
        "subscription_status": user.subscription_status,
    }
