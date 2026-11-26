import os
import tempfile
from datetime import date, timedelta

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"  # must be set before importing app

import pytest
from fastapi.testclient import TestClient

from app.auth import hash_key
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import Firm

A = {"X-API-Key": "key-a"}
B = {"X-API-Key": "key-b"}


def days_ago(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def tx(ref, amount="100.00", type="deposit", client="c1", currency="INR", when=None):
    return {"client_ref": client, "type": type, "currency": currency, "amount": amount,
            "effective_date": when or days_ago(10), "external_ref": ref}


@pytest.fixture
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all([Firm(name="Firm A", api_key_hash=hash_key("key-a")),
                    Firm(name="Firm B", api_key_hash=hash_key("key-b"))])
        db.commit()
    return TestClient(app)
