from __future__ import annotations
from fastapi import Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jwt_verifier import decode_supabase_token
from app.db.session import AsyncSessionLocal
from app.db.models import User


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def get_current_user(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        token = authorization.removeprefix("Bearer ")
        payload = await decode_supabase_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    from app.db.repositories.user_repository import get_user_by_id
    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found — call /auth/register first",
        )
    return user
