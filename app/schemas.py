from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from .config import CURRENCY_EXPONENT, MAX_AMOUNT_MINOR, MAX_BULK_ROWS


class TransactionIn(BaseModel):
    """One incoming row. The sign comes from `type`, so amount must always be positive."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_ref: str = Field(min_length=1, max_length=64)
    type: Literal["deposit", "withdrawal", "fee"]
    currency: str
    amount: Decimal
    effective_date: date
    external_ref: str = Field(min_length=1, max_length=128)

    @field_validator("currency", mode="before")
    @classmethod
    def _currency(cls, v: Any) -> str:
        if not isinstance(v, str) or v.strip().upper() not in CURRENCY_EXPONENT:
            raise ValueError(f"unsupported currency; allowed: {sorted(CURRENCY_EXPONENT)}")
        return v.strip().upper()

    @field_validator("amount")
    @classmethod
    def _amount(cls, v: Decimal, info: ValidationInfo) -> Decimal:
        if not v.is_finite():
            raise ValueError("amount must be a finite number")
        if v <= 0:
            raise ValueError("amount must be greater than zero")
        exp = CURRENCY_EXPONENT.get(info.data.get("currency"))
        if exp is not None:
            if -v.as_tuple().exponent > exp:
                raise ValueError(f"too many decimal places for {info.data['currency']} (max {exp})")
            if v * (10**exp) > MAX_AMOUNT_MINOR:
                raise ValueError("amount exceeds the maximum allowed per transaction")
        return v

    @field_validator("effective_date")
    @classmethod
    def _not_future(cls, v: date) -> date:
        if v > datetime.now(timezone.utc).date():
            raise ValueError("effective_date cannot be in the future")
        return v


class BulkIn(BaseModel):
    # Rows stay raw (Any) so ONE malformed row cannot reject the whole file;
    # each row is validated individually in the service layer.
    transactions: list[Any] = Field(min_length=1, max_length=MAX_BULK_ROWS)


class ReverseIn(BaseModel):
    external_ref: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=200)
