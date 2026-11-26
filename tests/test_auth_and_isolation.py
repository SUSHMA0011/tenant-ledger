from tests.conftest import A, B, tx


def test_missing_and_invalid_key_rejected(client):
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"X-API-Key": "nope"}).status_code == 401


def test_firm_cannot_read_or_reverse_another_firms_transaction(client):
    txn_id = client.post("/transactions", json=tx("r1"), headers=A).json()["transaction"]["id"]
    assert client.get(f"/transactions/{txn_id}", headers=B).status_code == 404
    assert client.post(f"/transactions/{txn_id}/reverse", headers=B).status_code == 404
    assert client.get(f"/transactions/{txn_id}", headers=A).status_code == 200


def test_same_client_ref_and_external_ref_are_separate_per_firm(client):
    assert client.post("/transactions", json=tx("same-ref"), headers=A).status_code == 201
    assert client.post("/transactions", json=tx("same-ref"), headers=B).status_code == 201  # not a duplicate
    bal_b = client.get("/clients/c1/balance", headers=B).json()["balances"]
    assert bal_b == [{"currency": "INR", "balance": "100.00"}]


def test_balances_history_and_audit_are_tenant_scoped(client):
    client.post("/transactions", json=tx("r1", client="shared"), headers=A)
    assert client.get("/clients/shared/balance", headers=B).json()["balances"] == []
    assert client.get("/clients/shared/transactions", headers=B).json() == []
    assert client.get("/audit-log", headers=B).json() == []
    assert len(client.get("/audit-log", headers=A).json()) == 1
