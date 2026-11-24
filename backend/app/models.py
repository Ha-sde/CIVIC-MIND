from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import relationship

from .database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    role = Column(String(16), nullable=False, index=True)  # citizen | official
    name = Column(String(120), nullable=False)
    contact = Column(String(160), unique=True, nullable=False, index=True)  # phone or email
    department = Column(String(120))  # officials only
    ward = Column(String(80))
    created_at = Column(DateTime, default=utcnow)


class Otp(Base):
    __tablename__ = "otps"
    id = Column(Integer, primary_key=True)
    contact = Column(String(160), index=True, nullable=False)
    code_hash = Column(String(64), nullable=False)
    payload = Column(JSON, default=dict)  # pending registration details
    attempts = Column(Integer, default=0)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)


class Cluster(Base):
    """One real-world issue. Many citizen complaints can map to a single cluster."""
    __tablename__ = "clusters"
    id = Column(Integer, primary_key=True)
    title = Column(String(200), nullable=False)
    category = Column(String(80), index=True, nullable=False)
    sub_category = Column(String(80))
    department = Column(String(120), index=True, nullable=False)
    lat = Column(Float, nullable=False, index=True)
    lon = Column(Float, nullable=False, index=True)
    address = Column(String(300), default="")
    severity = Column(Integer, default=2)
    confidence = Column(Float, default=0.5)
    vulnerability = Column(Boolean, default=False)
    ai_reason = Column(Text, default="")
    ai_engine = Column(String(40), default="local")
    corpus = Column(Text, default="")
    complaint_count = Column(Integer, default=1)
    stage = Column(String(20), default="received", index=True)
    progress = Column(Integer, default=0)
    target_date = Column(DateTime)
    priority_override = Column(Integer)
    recategorised = Column(Boolean, default=False)
    reopen_count = Column(Integer, default=0)
    confirmations = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow)
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)
    last_reopened_at = Column(DateTime)

    complaints = relationship("Complaint", back_populates="cluster", cascade="all, delete-orphan")
    events = relationship("TimelineEvent", back_populates="cluster", cascade="all, delete-orphan",
                          order_by="TimelineEvent.created_at, TimelineEvent.id")


class Complaint(Base):
    __tablename__ = "complaints"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), index=True, nullable=False)
    text = Column(Text, default="")
    address = Column(String(300), default="")
    lat = Column(Float, nullable=False)
    lon = Column(Float, nullable=False)
    media = Column(JSON, default=list)  # [{url, type, name}]
    severity = Column(Integer, default=2)
    confidence = Column(Float, default=0.5)
    created_at = Column(DateTime, default=utcnow, index=True)

    cluster = relationship("Cluster", back_populates="complaints")
    user = relationship("User")


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    id = Column(Integer, primary_key=True)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), index=True, nullable=False)
    stage = Column(String(20), nullable=False)  # received|merged|acknowledged|in_progress|completed|reopened|note
    actor_id = Column(Integer)
    actor_name = Column(String(120), default="System")
    note = Column(Text, default="")
    progress = Column(Integer)
    photo_url = Column(String(300))
    created_at = Column(DateTime, default=utcnow)

    cluster = relationship("Cluster", back_populates="events")


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    cluster_id = Column(Integer)
    message = Column(String(300), nullable=False)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)


class ResolutionVote(Base):
    __tablename__ = "resolution_votes"
    __table_args__ = (UniqueConstraint("user_id", "cluster_id", "round", name="uq_vote"),)
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    cluster_id = Column(Integer, ForeignKey("clusters.id"), nullable=False)
    round = Column(Integer, default=0)  # reopen_count at vote time
    created_at = Column(DateTime, default=utcnow)


Index("ix_cluster_geo", Cluster.category, Cluster.lat, Cluster.lon)
