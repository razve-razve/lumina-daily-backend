from __future__ import annotations
from datetime import date, time
from typing import Optional

from pydantic import BaseModel, Field


class ProfileCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=30)
    gender: str = Field(..., description="Female / Male / Non-binary / Prefer not to say")
    date_of_birth: date
    time_of_birth: time
    time_known: bool = True
    city_name: str
    latitude: float
    longitude: float
    timezone_id: str = Field(..., description="IANA timezone name e.g. America/New_York")
    utc_offset_at_birth: int = Field(..., description="UTC offset in seconds at birth moment")
    interpretation_mode: str = "Practical Daily"
    notification_time: Optional[time] = None


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=30)
    gender: Optional[str] = None
    notification_time: Optional[time] = None
    interpretation_mode: Optional[str] = None


class NatalChartResponse(BaseModel):
    natal_chart: dict
    sun_sign: str
    moon_sign: str
    rising_sign: str
    time_known: bool
    name: str


class ProfileResponse(BaseModel):
    name: str
    gender: str
    sun_sign: str
    moon_sign: str
    rising_sign: str
    time_known: bool
    city_name: str
    interpretation_mode: str
