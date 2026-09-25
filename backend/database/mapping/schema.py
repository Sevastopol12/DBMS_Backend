from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.base import Base


class HeaderMapping(Base):
    __tablename__ = "header_mapping"
    __table_args__ = (
        CheckConstraint(
            "btrim(normalized_alias) <> ''",
            name="header_mapping_normalized_alias_nonblank",
        ),
        CheckConstraint(
            "tier IN ('DIRECT', 'DYNAMIC')",
            name="header_mapping_tier_valid",
        ),
        CheckConstraint(
            "btrim(target) <> ''",
            name="header_mapping_target_nonblank",
        ),
        {"schema": "Mapping"},
    )

    normalized_alias: Mapped[str] = mapped_column(Text, primary_key=True)
    tier: Mapped[str] = mapped_column(Text, primary_key=True)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["HeaderMapping"]
