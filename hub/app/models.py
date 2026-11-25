import secrets
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def now():
    return datetime.now(timezone.utc)


def new_token():
    return secrets.token_urlsafe(16)


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    token: Mapped[str] = mapped_column(String(40), unique=True, default=new_token)

    name: Mapped[str] = mapped_column(String(200), default="")
    email: Mapped[str] = mapped_column(String(200), default="", index=True)
    phone: Mapped[str] = mapped_column(String(30), default="", index=True)
    location: Mapped[str] = mapped_column(String(120), default="")
    education: Mapped[str] = mapped_column(String(200), default="")
    skills: Mapped[str] = mapped_column(Text, default="")
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ctc_lpa: Mapped[float | None] = mapped_column(Float, nullable=True)

    source: Mapped[str] = mapped_column(String(40), default="upload")
    applied_role: Mapped[str] = mapped_column(String(40), default="", index=True)
    resume_path: Mapped[str] = mapped_column(String(400), default="")
    resume_text: Mapped[str] = mapped_column(Text, default="")

    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    typing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    typing_wpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    typing_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    chat_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    chat_detail: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    voice_auto_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    voice_detail: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    voice_human: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    voice_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    lineup: Mapped[dict | None] = mapped_column(JSON(none_as_null=True), nullable=True)
    matched_role: Mapped[str] = mapped_column(String(40), default="", index=True)
    second_role: Mapped[str] = mapped_column(String(40), default="")
    recommendation: Mapped[str] = mapped_column(String(20), default="pending")
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="screened", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
