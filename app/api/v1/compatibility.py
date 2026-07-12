"""Compatibility (synastry) — add a person, get compatibility with them.

Computed ONCE per pair (natal charts never change), stored forever.
Free tier: overall percent + summary. Pro: sphere scores + full texts.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.advice_generator import generate_compatibility_texts
from app.core.ephemeris import birth_to_julian_day, calculate_natal_chart
from app.core.synastry import compute_synastry
from app.db.models import CompatibilityPartner, User
from app.db.repositories.profile_repository import get_profile_by_user_id
from app.dependencies import get_current_user, get_db

router = APIRouter()

MAX_PARTNERS = 20


class PartnerCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    date_of_birth: date
    time_of_birth: Optional[time] = None       # None → noon, rising unknown
    city_name: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    utc_offset_seconds: Optional[int] = None   # from /timezone/resolve when city picked


class PartnerListItem(BaseModel):
    id: str
    name: str
    partner_sun_sign: str
    partner_moon_sign: str
    overall: int


class PartnerDetailResponse(BaseModel):
    id: str
    name: str
    date_of_birth: str
    partner_sun_sign: str
    partner_moon_sign: str
    overall: int
    summary: str
    # Pro-only fields — None for free users
    sphere_scores: Optional[dict] = None
    texts: Optional[dict] = None


def _is_pro(user: User) -> bool:
    return user.subscription_status in ("pro", "active")


def _texts_by_language(p: CompatibilityPartner) -> dict:
    """Normalize stored texts to {language: {summary, romance, ...}}.
    Rows created before multi-language support stored a flat dict."""
    stored = p.texts or {}
    if "summary" in stored:  # legacy flat format
        return {p.language or "en": stored}
    return stored


async def _texts_for_language(
    p: CompatibilityPartner, lang: str, db: AsyncSession, user_profile,
) -> dict:
    """Texts in the requested language — generate once and persist if missing."""
    by_lang = _texts_by_language(p)
    if lang in by_lang:
        return by_lang[lang]

    user_planets = (user_profile.natal_chart_json or {}).get("planets", {})
    aspect_list = ", ".join(
        f"{p.name}'s {a['partner_planet']} {a['aspect']} {user_profile.name}'s {a['user_planet']} "
        f"(orb {a['orb']:.1f}°)"
        for a in (p.aspects or [])
    ) or "no close inter-chart aspects"

    texts = await generate_compatibility_texts(
        user_name=user_profile.name,
        partner_name=p.name,
        language=lang,
        user_sun=user_planets.get("Sun", {}).get("sign", "unknown"),
        user_moon=user_planets.get("Moon", {}).get("sign", "unknown"),
        partner_sun=p.partner_sun_sign,
        partner_moon=p.partner_moon_sign,
        aspect_list=aspect_list,
        sphere_scores=p.sphere_scores or {},
        overall=p.overall,
    )
    by_lang[lang] = texts
    p.texts = dict(by_lang)   # reassign so SQLAlchemy sees the JSONB change
    db.add(p)
    await db.commit()
    return texts


def _to_detail(p: CompatibilityPartner, pro: bool, texts: dict) -> PartnerDetailResponse:
    return PartnerDetailResponse(
        id=str(p.id),
        name=p.name,
        date_of_birth=p.date_of_birth.isoformat(),
        partner_sun_sign=p.partner_sun_sign,
        partner_moon_sign=p.partner_moon_sign,
        overall=p.overall,
        summary=texts.get("summary", ""),
        sphere_scores=p.sphere_scores if pro else None,
        texts=texts if pro else None,
    )


@router.post("", response_model=PartnerDetailResponse)
async def add_partner(
    body: PartnerCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user.id
    lang = current_user.language or "en"

    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    count_result = await db.execute(
        select(CompatibilityPartner).where(CompatibilityPartner.user_id == user_id)
    )
    if len(list(count_result.scalars().all())) >= MAX_PARTNERS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Partner limit reached.")

    # Partner natal chart. No time → noon (rising unknown but Sun/Moon fine).
    # No city → 0,0 coords; houses are meaningless then, but synastry uses only planets.
    t = body.time_of_birth or time(12, 0)
    offset = body.utc_offset_seconds or 0
    lat = body.latitude if body.latitude is not None else 0.0
    lon = body.longitude if body.longitude is not None else 0.0

    def compute() -> tuple[dict, dict]:
        jd = birth_to_julian_day(
            body.date_of_birth.year, body.date_of_birth.month, body.date_of_birth.day,
            t.hour, t.minute, 0, offset,
        )
        partner_chart = calculate_natal_chart(jd, lat, lon)
        user_planets = (profile.natal_chart_json or {}).get("planets", {})
        return partner_chart, compute_synastry(user_planets, partner_chart["planets"])

    loop = asyncio.get_event_loop()
    partner_chart, syn = await loop.run_in_executor(None, compute)

    user_planets = (profile.natal_chart_json or {}).get("planets", {})
    aspect_list = ", ".join(
        f"{body.name}'s {a['partner_planet']} {a['aspect']} {profile.name}'s {a['user_planet']} "
        f"(orb {a['orb']:.1f}°)"
        for a in syn["aspects"]
    ) or "no close inter-chart aspects"

    texts = await generate_compatibility_texts(
        user_name=profile.name,
        partner_name=body.name,
        language=lang,
        user_sun=user_planets.get("Sun", {}).get("sign", "unknown"),
        user_moon=user_planets.get("Moon", {}).get("sign", "unknown"),
        partner_sun=partner_chart["planets"]["Sun"]["sign"],
        partner_moon=partner_chart["planets"]["Moon"]["sign"],
        aspect_list=aspect_list,
        sphere_scores=syn["sphere_scores"],
        overall=syn["overall"],
    )

    partner = CompatibilityPartner(
        user_id=user_id,
        name=body.name,
        date_of_birth=body.date_of_birth,
        time_of_birth=body.time_of_birth,
        time_known=body.time_of_birth is not None,
        city_name=body.city_name,
        latitude=body.latitude,
        longitude=body.longitude,
        partner_sun_sign=partner_chart["planets"]["Sun"]["sign"],
        partner_moon_sign=partner_chart["planets"]["Moon"]["sign"],
        overall=syn["overall"],
        sphere_scores=syn["sphere_scores"],
        texts={lang: texts},   # keyed by language — more generated on demand
        aspects=syn["aspects"],
        language=lang,
    )
    db.add(partner)
    await db.commit()
    await db.refresh(partner)

    return _to_detail(partner, _is_pro(current_user), texts)


@router.get("", response_model=list[PartnerListItem])
async def list_partners(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompatibilityPartner)
        .where(CompatibilityPartner.user_id == current_user.id)
        .order_by(CompatibilityPartner.created_at.desc())
    )
    return [
        PartnerListItem(
            id=str(p.id), name=p.name,
            partner_sun_sign=p.partner_sun_sign, partner_moon_sign=p.partner_moon_sign,
            overall=p.overall,
        )
        for p in result.scalars().all()
    ]


@router.get("/{partner_id}", response_model=PartnerDetailResponse)
async def get_partner(
    partner_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompatibilityPartner).where(
            CompatibilityPartner.id == partner_id,
            CompatibilityPartner.user_id == current_user.id,
        )
    )
    partner = result.scalar_one_or_none()
    if not partner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")

    # Serve texts in the user's CURRENT app language — generate once if missing
    lang = current_user.language or "en"
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")
    texts = await _texts_for_language(partner, lang, db, profile)
    return _to_detail(partner, _is_pro(current_user), texts)


@router.delete("/{partner_id}")
async def delete_partner(
    partner_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CompatibilityPartner).where(
            CompatibilityPartner.id == partner_id,
            CompatibilityPartner.user_id == current_user.id,
        )
    )
    partner = result.scalar_one_or_none()
    if not partner:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")
    await db.delete(partner)
    await db.commit()
    return {"status": "deleted"}
