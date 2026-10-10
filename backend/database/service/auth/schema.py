from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base


class AppUser(Base):
    __tablename__ = "app_user"
    __table_args__ = (
        Index(
            "app_user_username_lower_idx",
            text("lower(username)"),
            unique=True,
        ),
        {"schema": "Auth"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    facility_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
