from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    kanban_connections = Column(JSON, default=dict)
    crm_connections = Column(JSON, default=dict)
    onboarded_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)

    competitors = relationship(
        "Competitor", back_populates="brand", cascade="all, delete-orphan"
    )
    kanban_cards = relationship(
        "KanbanCard", back_populates="brand", cascade="all, delete-orphan"
    )
    customers = relationship(
        "Customer", back_populates="brand", cascade="all, delete-orphan"
    )
    products = relationship(
        "Product", back_populates="brand", cascade="all, delete-orphan"
    )
    segments = relationship(
        "Segment", back_populates="brand", cascade="all, delete-orphan"
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


class KanbanCard(Base):
    __tablename__ = "kanban_cards"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    board_id = Column(String, nullable=True)
    board_name = Column(String, nullable=True)
    column = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    labels = Column(JSON, default=list)
    due_date = Column(DateTime, nullable=True)
    moved_at = Column(DateTime, nullable=True)
    url = Column(String, nullable=True)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="kanban_cards")

    __table_args__ = (
        UniqueConstraint(
            "brand_id",
            "provider",
            "external_id",
            name="ux_kanban_card_external",
        ),
    )


class Customer(Base):
    __tablename__ = "customers"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    provider = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    email = Column(String, nullable=False)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    attributes = Column(JSON, default=dict)
    tags = Column(JSON, default=list)
    signup_at = Column(DateTime, nullable=True)
    last_active_at = Column(DateTime, nullable=True)
    total_spend_cents = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="customers")
    events = relationship(
        "CustomerEvent",
        back_populates="customer",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "brand_id", "provider", "external_id", name="ux_customer_external"
        ),
    )


class CustomerEvent(Base):
    __tablename__ = "customer_events"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    customer_id = Column(
        String,
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(String, nullable=False)
    occurred_at = Column(DateTime, nullable=False, default=_now)
    payload = Column(JSON, default=dict)

    customer = relationship("Customer", back_populates="events")


class Product(Base):
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    sku = Column(String, nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    price_cents = Column(Integer, nullable=False, default=0)
    image_url = Column(String, nullable=True)
    category = Column(String, nullable=True)
    tags = Column(JSON, default=list)
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="products")


class Segment(Base):
    __tablename__ = "segments"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    rationale = Column(Text, nullable=True)
    customer_ids = Column(JSON, default=list)
    source = Column(String, nullable=False, default="ai_proposed")
    created_at = Column(DateTime, default=_now)

    brand = relationship("Brand", back_populates="segments")


class EmailSend(Base):
    __tablename__ = "email_sends"

    id = Column(String, primary_key=True, default=_uuid)
    brand_id = Column(
        String, ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    target_kind = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    html_body = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="queued")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_now)
