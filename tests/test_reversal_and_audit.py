from tests.conftest import A, tx


def test_reversal_restores_balance_and_keeps_history(client):
    d = client.post("/transactions", json=tx("d1", "100.00"), headers=A).json()["transaction"]["id"]
    rev = client.post(f"/transactions/{d}/reverse", json={"reason": "wrong client"}, headers=A)
    assert rev.status_code == 201
    assert rev.json()["transaction"]["reverses_id"] == d
    assert client.get("/clients/c1/balance", headers=A).json()["balances"][0]["balance"] == "0.00"
    history = client.get("/clients/c1/transactions", headers=A).json()
    assert [t["type"] for t in history] == ["deposit", "reversal"]       # original still there
    assert client.get(f"/transactions/{d}", headers=A).json()["amount"] == "100.00"  # unchanged


def test_cannot_reverse_twice_or_reverse_a_reversal(client):
    d = client.post("/transactions", json=tx("d1"), headers=A).json()["transaction"]["id"]
    rev_id = client.post(f"/transactions/{d}/reverse", headers=A).json()["transaction"]["id"]
    again = client.post(f"/transactions/{d}/reverse", headers=A)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_reversed"
    assert client.post(f"/transactions/{rev_id}/reverse", headers=A).status_code == 409


def test_reverse_unknown_transaction_404(client):
    assert client.post("/transactions/9999/reverse", headers=A).status_code == 404


def test_audit_log_records_who_what(client):
    d = client.post("/transactions", json=tx("d1"), headers={**A, "X-Actor": "priya"}).json()["transaction"]["id"]
    client.post(f"/transactions/{d}/reverse", json={"reason": "typo"}, headers={**A, "X-Actor": "sam"})
    log = client.get("/audit-log", headers=A).json()
    assert [(e["actor"], e["action"]) for e in log] == [("sam", "transaction.reversed"), ("priya", "transaction.created")]
    assert log[0]["detail"]["reason"] == "typo"


def test_rejected_rows_leave_no_audit_entries(client):
    client.post("/transactions", json=tx("bad", "-1"), headers=A)
    assert client.get("/audit-log", headers=A).json() == []
