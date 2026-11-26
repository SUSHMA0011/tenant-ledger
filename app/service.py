"""Business logic. All functions take firm_id explicitly and filter on it - this is the tenant boundary."""
import json
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import CURRENCY_EXPONENT
from .models import AuditLog, Transaction
from .schemas import TransactionIn

SIGN = {"deposit": 1, "withdrawal": -1, "fee": -1}

# Serialises the "check then write" sequence (duplicate check, overdraft check) inside one process.
# The DB unique constraints remain the real safety net across processes (see NOTES.md).
_write_lock = threading.Lock()


class LedgerError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


@dataclass
class RowResult:
    index: int
    status: str                      # accepted | duplicate | rejected
    transaction: Transaction | None = None
    code: str | None = None
    error: str | None = None


# ---------- money helpers (integers only; never floats) ----------

def to_minor(amount: Decimal, currency: str) -> int:
    return int(amount * (10 ** CURRENCY_EXPONENT[currency]))


def from_minor(minor: int, currency: str) -> str:
    exp = CURRENCY_EXPONENT[currency]
    return f"{Decimal(minor).scaleb(-exp):.{exp}f}"


def txn_out(t: Transaction) -> dict:
    return {
        "id": t.id,
        "client_ref": t.client_ref,
        "type": t.type,
        "currency": t.currency,
        "amount": from_minor(t.amount_minor, t.currency),
        "signed_amount": from_minor(t.signed_minor, t.currency),
        "effective_date": t.effective_date.isoformat(),
        "external_ref": t.external_ref,
        "reverses_id": t.reverses_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _audit(db: Session, firm_id: int, actor: str, action: str, entity_id: int | None, detail: dict) -> None:
    db.add(AuditLog(firm_id=firm_id, actor=actor, action=action, entity_id=entity_id,
                    detail=json.dumps(detail, sort_keys=True)))


def _balance_minor(db: Session, firm_id: int, client_ref: str, currency: str) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Transaction.signed_minor), 0)).where(
            Transaction.firm_id == firm_id,
            Transaction.client_ref == client_ref,
            Transaction.currency == currency,
        )
    )


def _find_by_ref(db: Session, firm_id: int, external_ref: str) -> Transaction | None:
    return db.scalar(select(Transaction).where(
        Transaction.firm_id == firm_id, Transaction.external_ref == external_ref))


def _classify_existing(existing: Transaction, row: TransactionIn, minor: int):
    """Same external_ref seen before: identical payload = harmless retry; different = conflict."""
    same = (existing.client_ref, existing.type, existing.amount_minor, existing.currency,
            existing.effective_date) == (row.client_ref, row.type, minor, row.currency, row.effective_date)
    if same:
        return "duplicate", existing, None, None
    return ("rejected", None, "external_ref_conflict",
            "external_ref already used by a transaction with different details")


# ---------- ingestion ----------

def _insert_one(db: Session, firm_id: int, row: TransactionIn, actor: str):
    minor = to_minor(row.amount, row.currency)

    existing = _find_by_ref(db, firm_id, row.external_ref)
    if existing is not None:
        return _classify_existing(existing, row, minor)

    if row.type == "withdrawal" and _balance_minor(db, firm_id, row.client_ref, row.currency) < minor:
        return "rejected", None, "insufficient_funds", "withdrawal exceeds available balance"

    txn = Transaction(
        firm_id=firm_id, client_ref=row.client_ref, type=row.type, amount_minor=minor,
        signed_minor=SIGN[row.type] * minor, currency=row.currency,
        effective_date=row.effective_date, external_ref=row.external_ref,
    )
    try:
        with db.begin_nested():          # SAVEPOINT: a lost race only undoes this row
            db.add(txn)
            db.flush()
    except IntegrityError:
        # Another writer inserted the same external_ref between our check and insert.
        existing = _find_by_ref(db, firm_id, row.external_ref)
        if existing is None:
            raise
        return _classify_existing(existing, row, minor)

    _audit(db, firm_id, actor, "transaction.created", txn.id,
           {"type": row.type, "client_ref": row.client_ref, "external_ref": row.external_ref})
    return "accepted", txn, None, None


def _format_validation_error(e: ValidationError) -> str:
    parts = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "row"
        msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts)


def ingest_batch(db: Session, firm_id: int, raw_rows: list[Any], actor: str) -> list[RowResult]:
    """Partial success: valid rows are committed, invalid rows are reported back with the reason."""
    results: list[RowResult | None] = [None] * len(raw_rows)
    parsed: list[tuple[int, TransactionIn]] = []
    for i, raw in enumerate(raw_rows):
        try:
            parsed.append((i, TransactionIn.model_validate(raw)))
        except ValidationError as e:
            results[i] = RowResult(i, "rejected", code="validation_error", error=_format_validation_error(e))

    # Oldest first, so a deposit and a later withdrawal in the same file are evaluated in a sensible order.
    parsed.sort(key=lambda p: (p[1].effective_date, p[0]))

    with _write_lock:
        try:
            for i, row in parsed:
                status, txn, code, err = _insert_one(db, firm_id, row, actor)
                results[i] = RowResult(i, status, txn, code, err)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return results  # type: ignore[return-value]


def reverse_transaction(db: Session, firm_id: int, txn_id: int, external_ref: str | None,
                        reason: str | None, actor: str) -> Transaction:
    """Correct a mistake by appending an opposite entry. History is never edited or deleted."""
    with _write_lock:
        try:
            orig = db.scalar(select(Transaction).where(Transaction.id == txn_id, Transaction.firm_id == firm_id))
            if orig is None:
                raise LedgerError(404, "not_found", "transaction not found")
            if orig.type == "reversal":
                raise LedgerError(409, "cannot_reverse_reversal", "a reversal cannot itself be reversed")
            already = db.scalar(select(Transaction.id).where(Transaction.reverses_id == orig.id))
            if already is not None:
                raise LedgerError(409, "already_reversed", f"already reversed by transaction {already}")

            ref = external_ref or f"reversal-of-{orig.id}"
            if _find_by_ref(db, firm_id, ref) is not None:
                raise LedgerError(409, "external_ref_conflict", "external_ref already in use")

            rev = Transaction(
                firm_id=firm_id, client_ref=orig.client_ref, type="reversal",
                amount_minor=orig.amount_minor, signed_minor=-orig.signed_minor,
                currency=orig.currency, effective_date=_today(),  # today: closed periods are not rewritten
                external_ref=ref, reverses_id=orig.id,
            )
            try:
                with db.begin_nested():
                    db.add(rev)
                    db.flush()
            except IntegrityError:
                raise LedgerError(409, "already_reversed", "already reversed")
            _audit(db, firm_id, actor, "transaction.reversed", rev.id,
                   {"reverses_id": orig.id, "reason": reason})
            db.commit()
            return rev
        except Exception:
            db.rollback()
            raise


# ---------- reads ----------

def get_transaction(db: Session, firm_id: int, txn_id: int) -> Transaction:
    t = db.scalar(select(Transaction).where(Transaction.id == txn_id, Transaction.firm_id == firm_id))
    if t is None:
        raise LedgerError(404, "not_found", "transaction not found")
    return t


def list_transactions(db: Session, firm_id: int, client_ref: str, limit: int, offset: int) -> list[Transaction]:
    return list(db.scalars(
        select(Transaction)
        .where(Transaction.firm_id == firm_id, Transaction.client_ref == client_ref)
        .order_by(Transaction.effective_date, Transaction.id)
        .limit(limit).offset(offset)
    ))


def balances_as_of(db: Session, firm_id: int, client_ref: str, as_of: date) -> list[dict]:
    rows = db.execute(
        select(Transaction.currency, func.sum(Transaction.signed_minor))
        .where(Transaction.firm_id == firm_id, Transaction.client_ref == client_ref,
               Transaction.effective_date <= as_of)
        .group_by(Transaction.currency).order_by(Transaction.currency)
    ).all()
    return [{"currency": c, "balance": from_minor(total, c)} for c, total in rows]


def monthly_summary(db: Session, firm_id: int, client_ref: str, year: int, month: int) -> list[dict]:
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)

    opening = dict(db.execute(
        select(Transaction.currency, func.sum(Transaction.signed_minor))
        .where(Transaction.firm_id == firm_id, Transaction.client_ref == client_ref,
               Transaction.effective_date < start)
        .group_by(Transaction.currency)
    ).all())

    per: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cur, typ, total in db.execute(
        select(Transaction.currency, Transaction.type, func.sum(Transaction.signed_minor))
        .where(Transaction.firm_id == firm_id, Transaction.client_ref == client_ref,
               Transaction.effective_date >= start, Transaction.effective_date < end)
        .group_by(Transaction.currency, Transaction.type)
    ):
        per[cur][typ] = total

    out = []
    for cur in sorted(set(opening) | set(per)):
        p = per[cur]
        net = sum(p.values())
        open_bal = opening.get(cur, 0)
        out.append({
            "currency": cur,
            "opening_balance": from_minor(open_bal, cur),
            "inflows": from_minor(p["deposit"], cur),
            "outflows": from_minor(-p["withdrawal"], cur),
            "fees": from_minor(-p["fee"], cur),
            "reversals_net": from_minor(p["reversal"], cur),
            "net_change": from_minor(net, cur),
            "closing_balance": from_minor(open_bal + net, cur),
        })
    return out


def list_audit(db: Session, firm_id: int, limit: int, offset: int) -> list[dict]:
    rows = db.scalars(select(AuditLog).where(AuditLog.firm_id == firm_id)
                      .order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    return [{"id": a.id, "actor": a.actor, "action": a.action, "entity_id": a.entity_id,
             "detail": json.loads(a.detail or "{}"), "created_at": a.created_at.isoformat()} for a in rows]
