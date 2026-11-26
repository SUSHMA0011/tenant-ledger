from datetime import date, datetime, timezone

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Firm(Base):
    __tablename__ = "firms"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)


class Transaction(Base):
    """Append-only ledger entry. Rows are never updated or deleted;
    a correction is a new 'reversal' row pointing at the original."""

    __tablename__ = "transactions"
    __table_args__ = (
        # Re-sending the same external_ref can never create a second row (enforced by the DB).
        UniqueConstraint("firm_id", "external_ref", name="uq_firm_external_ref"),
        # A transaction can be reversed at most once (many NULLs are allowed).
        UniqueConstraint("reverses_id", name="uq_reverses_id"),
        CheckConstraint("amount_minor > 0", name="ck_amount_positive"),
        CheckConstraint("type IN ('deposit','withdrawal','fee','reversal')", name="ck_type"),
        # Balance / as-of / monthly-summary queries.
        Index("ix_firm_client_date", "firm_id", "client_ref", "effective_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id"), index=True)
    client_ref: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))        # deposit | withdrawal | fee | reversal
    amount_minor: Mapped[int] = mapped_column(Integer)   # always > 0, integer cents/paise
    signed_minor: Mapped[int] = mapped_column(Integer)   # effect on balance (+/-) so balance = SUM
    currency: Mapped[str] = mapped_column(String(3))
    effective_date: Mapped[date] = mapped_column(Date)
    external_ref: Mapped[str] = mapped_column(String(128))
    reverses_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    """Append-only record of who did what, written in the same DB transaction as the change."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    firm_id: Mapped[int] = mapped_column(ForeignKey("firms.id"), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
