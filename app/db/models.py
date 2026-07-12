import uuid
from datetime import date as date_type, time as time_type
from typing import Optional

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
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    """Login / account record — one per Supabase auth user."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    apple_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    subscription_status: Mapped[str] = mapped_column(String(32), nullable=False, default="free")


class Profile(Base):
    """Birth data, natal chart, and app preferences for a user."""
    __tablename__ = "profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    name: Mapped[str] = mapped_column(String(30), nullable=False)
    gender: Mapped[str] = mapped_column(String(32), nullable=False)

    date_of_birth: Mapped[date_type] = mapped_column(Date, nullable=False)
    time_of_birth: Mapped[time_type] = mapped_column(Time, nullable=False)
    time_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    city_name: Mapped[str] = mapped_column(String(256), nullable=False)
    latitude: Mapped[float] = mapped_column(Double, nullable=False)
    longitude: Mapped[float] = mapped_column(Double, nullable=False)
    timezone_id: Mapped[str] = mapped_column(String(64), nullable=False)
    utc_offset_at_birth: Mapped[int] = mapped_column(Integer, nullable=False)

    natal_chart_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    interpretation_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="Practical Daily")
    notification_time: Mapped[Optional[time_type]] = mapped_column(Time, nullable=True)
    device_timezone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fcm_token: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)


class DailyAdvice(Base):
    """AI-generated daily guidance — one row per user per day per mode."""
    __tablename__ = "daily_advice"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    generated_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    theme: Mapped[str] = mapped_column(Text, nullable=False)
    moon_phase: Mapped[str] = mapped_column(String(32), nullable=False)
    transit_tags: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

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
    risk_text: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "date", "mode", name="uq_user_date_mode"),
    )


class MoodEntry(Base):
    """User's own 1-5 rating of how their day actually went (mood journal)."""
    __tablename__ = "mood_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1-5
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_mood_user_date"),
    )


class CompatibilityPartner(Base):
    """A saved person + computed synastry result (computed once, never changes)."""
    __tablename__ = "compatibility_partners"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    name: Mapped[str] = mapped_column(String(64), nullable=False)
    date_of_birth: Mapped[date_type] = mapped_column(Date, nullable=False)
    time_of_birth: Mapped[Optional[time_type]] = mapped_column(Time, nullable=True)
    time_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    city_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Double, nullable=True)

    partner_sun_sign: Mapped[str] = mapped_column(String(16), nullable=False)
    partner_moon_sign: Mapped[str] = mapped_column(String(16), nullable=False)
    # Only when birth time AND place are known — rising is unreliable otherwise
    partner_rising_sign: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    overall: Mapped[int] = mapped_column(SmallInteger, nullable=False)          # 0-100
    sphere_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)          # {romance, friendship, communication, conflict}: 1-10
    texts: Mapped[dict] = mapped_column(JSONB, nullable=False)                  # {summary, romance, friendship, communication, conflict}
    aspects: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)  # top inter-chart aspects
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
