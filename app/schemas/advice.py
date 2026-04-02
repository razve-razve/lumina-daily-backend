from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class CategoryCard(BaseModel):
    score: int          # 1–10
    text: str


class DailyAdviceResponse(BaseModel):
    date: date
    generated_at: datetime
    mode: str
    theme: str
    moon_phase: str
    transit_tags: list[str]

    love: CategoryCard
    work: CategoryCard
    energy: CategoryCard
    communication: CategoryCard
    mood: CategoryCard
    watch_for: str      # risk text — no score


class SettingsModeRequest(BaseModel):
    mode: str


class SettingsNotificationsRequest(BaseModel):
    fcm_token: Optional[str] = None
    notification_time: Optional[str] = None  # "HH:MM"
    enabled: bool = True
