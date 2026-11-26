"""Real threads, each with its own DB session, hitting the same rows at once."""
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app import service
from app.database import SessionLocal
from app.models import Transaction
from tests.conftest import tx

FIRM_ID = 1


def _ingest(rows):
    with SessionLocal() as db:
        return service.ingest_batch(db, FIRM_ID, rows, "test")


def test_concurrent_retries_of_the_same_transaction_create_one_row(client):
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda _: _ingest([tx("same-ref")])[0].status, range(10)))
    assert results.count("accepted") == 1
    assert results.count("duplicate") == 9
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Transaction)) == 1


def test_concurrent_withdrawals_cannot_overdraw(client):
    _ingest([tx("seed", "100.00")])
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(lambda i: _ingest([tx(f"w{i}", "100.00", "withdrawal")])[0].status, range(10)))
    assert results.count("accepted") == 1
    with SessionLocal() as db:
        total = db.scalar(select(func.sum(Transaction.signed_minor)))
        assert total == 0
