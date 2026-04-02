import uuid
from datetime import date, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Login / account record — one per Supabase auth user."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    apple_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    subscription_status: Mapped[str] = mapped_column(String(32), nullable=False, default="free")


class Profile(Base):
    """Birth data, natal chart, and app preferences for a user."""
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Identity
    name: Mapped[str] = mapped_column(String(30), nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)  # Female/Male/Non-binary/Prefer not to say

    # Birth data
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    time_of_birth: Mapped[time] = mapped_column(Time, nullable=False)
    time_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Birth location
    city_name: Mapped[str] = mapped_column(String(256), nullable=False)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    timezone_id: Mapped[str] = mapped_column(String(64), nullable=False)   # IANA e.g. "America/New_York"
    utc_offset_at_birth: Mapped[int] = mapped_column(Integer, nullable=False)  # seconds

    # Computed natal chart (JSON, calculated once, never changes)
    natal_chart_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # App preferences
    interpretation_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="Practical Daily")
    notification_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    fcm_token: Mapped[str | None] = mapped_column(String(512), nullable=True)


class DailyAdvice(Base):
    """AI-generated daily guidance — one row per user per day per mode."""
    __tablename__ = "daily_advice"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    generated_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Overall theme
    theme: Mapped[str] = mapped_column(Text, nullable=False)       # one sentence
    moon_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    transit_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # e.g. ["Venus trine Moon", "Mercury℞"]

    # 6 categories — score (1–10) + text
    love_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    love_text: Mapped[str] = mapped_column(Text, nullable=False)

    work_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    work_text: Mapped[str] = mapped_column(Text, nullable=False)

    energy_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    energy_text: Mapped[str] = mapped_column(Text, nullable=False)

    communication_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    communication_text: Mapped[str] = mapped_column(Text, nullable=False)

    mood_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    mood_text: Mapped[str] = mapped_column(Text, nullable=False)

    risk_text: Mapped[str] = mapped_column(Text, nullable=False)   # Watch For — no score, just text

    __table_args__ = (
        UniqueConstraint("user_id", "date", "mode", name="uq_user_date_mode"),
    )
