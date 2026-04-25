from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.db.session import Base


def _uuid() -> str:
    return str(uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Brand(Base):
    __tablename__ = "brands"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=True)
    description = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    screenshots = Column(JSON, default=list)
    theme_color = Column(String, nullable=True)
    palette = Column(JSON, default=list)
    palette_roles = Column(JSON, default=list)
    identity = Column(JSON, default=dict)
    voice_profile = Column(JSON, default=dict)
    handles = Column(JSON, default=dict)
    product_images = Column(JSON, default=list)
    pasted_posts = Column(Text, nullable=True)
    recent_posts = Column(JSON, default=list)
    style_profile = Column(JSON, default=dict)
    reference_brands = Column(JSON, default=list)
    assets = Column(JSON, default=list)
    profile = Column(JSON, default=dict)
    onboarded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    competitors = relationship(
        "Competitor", back_populates="brand", cascade="all, delete-orphan"
    )


class Competitor(Base):
    __tablename__ = "competitors"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String, nullable=False)
    url = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    pattern_library = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="competitors")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(String, ForeignKey("brands.id"), nullable=False)
    title = Column(String, nullable=False)
    bundle = Column(JSON, default=dict)
    predicted_lift = Column(Float, nullable=True)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand")
