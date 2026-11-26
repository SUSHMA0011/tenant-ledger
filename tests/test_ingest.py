import pytest

from tests.conftest import A, days_ago, tx


@pytest.mark.parametrize("patch,fragment", [
    ({"amount": "-5.00"}, "greater than zero"),
    ({"amount": "0"}, "greater than zero"),
    ({"amount": "10.123"}, "decimal places"),
    ({"amount": "abc"}, "amount"),
    ({"currency": "XYZ"}, "unsupported currency"),
    ({"effective_date": "2999-01-01"}, "future"),
    ({"effective_date": "not-a-date"}, "effective_date"),
    ({"type": "gift"}, "type"),
    ({"client_ref": ""}, "client_ref"),
])
def test_bad_single_rows_are_rejected(client, patch, fragment):
    r = client.post("/transactions", json={**tx("r1"), **patch}, headers=A)
    assert r.status_code == 422
    assert fragment in r.text


def test_missing_field_rejected(client):
    body = tx("r1")
    del body["external_ref"]
    assert client.post("/transactions", json=body, headers=A).status_code == 422


def test_float_amounts_from_spreadsheets_are_exact(client):
    r = client.post("/transactions", json={**tx("r1"), "amount": 0.1}, headers=A)
    assert r.status_code == 201
    assert r.json()["transaction"]["amount"] == "0.10"


def test_bulk_one_bad_row_does_not_block_the_rest(client):
    rows = [tx("g1", "100.00"), tx("bad1", "-1"), "garbage", tx("g2", "50.00"),
            {**tx("bad2"), "currency": "ZZZ"}, {**tx("bad3"), "effective_date": "2999-01-01"}]
    r = client.post("/transactions/bulk", json={"transactions": rows}, headers=A).json()
    assert r["summary"] == {"accepted": 2, "duplicates": 0, "rejected": 4}
    assert [x["status"] for x in r["results"]] == ["accepted", "rejected", "rejected", "accepted", "rejected", "rejected"]
    assert client.get("/clients/c1/balance", headers=A).json()["balances"] == [{"currency": "INR", "balance": "150.00"}]


def test_resending_a_failed_file_does_not_double_count(client):
    rows = [tx("g1", "100.00"), tx("bad", "-1"), tx("g2", "50.00")]
    client.post("/transactions/bulk", json={"transactions": rows}, headers=A)
    r = client.post("/transactions/bulk", json={"transactions": rows}, headers=A).json()
    assert r["summary"] == {"accepted": 0, "duplicates": 2, "rejected": 1}
    assert client.get("/clients/c1/balance", headers=A).json()["balances"][0]["balance"] == "150.00"


def test_duplicate_inside_the_same_file_is_counted_once(client):
    r = client.post("/transactions/bulk", json={"transactions": [tx("x"), tx("x")]}, headers=A).json()
    assert r["summary"] == {"accepted": 1, "duplicates": 1, "rejected": 0}


def test_single_retry_is_idempotent(client):
    assert client.post("/transactions", json=tx("r1"), headers=A).status_code == 201
    again = client.post("/transactions", json=tx("r1"), headers=A)
    assert again.status_code == 200 and again.json()["status"] == "duplicate"
    assert client.get("/clients/c1/balance", headers=A).json()["balances"][0]["balance"] == "100.00"


def test_same_external_ref_with_different_details_is_a_conflict(client):
    client.post("/transactions", json=tx("r1", "100.00"), headers=A)
    r = client.post("/transactions", json=tx("r1", "999.00"), headers=A)
    assert r.status_code == 409 and r.json()["error"]["code"] == "external_ref_conflict"


def test_withdrawal_cannot_overdraw(client):
    client.post("/transactions", json=tx("d1", "100.00"), headers=A)
    r = client.post("/transactions", json=tx("w1", "100.01", "withdrawal"), headers=A)
    assert r.status_code == 422 and r.json()["error"]["code"] == "insufficient_funds"
    assert client.post("/transactions", json=tx("w2", "100.00", "withdrawal"), headers=A).status_code == 201


def test_bulk_orders_by_date_so_deposit_before_withdrawal_works(client):
    rows = [tx("w", "40.00", "withdrawal", when=days_ago(1)), tx("d", "100.00", when=days_ago(5))]
    r = client.post("/transactions/bulk", json={"transactions": rows}, headers=A).json()
    assert r["summary"]["accepted"] == 2


def test_currencies_are_tracked_separately(client):
    client.post("/transactions", json=tx("a", "100.00", currency="INR"), headers=A)
    r = client.post("/transactions", json=tx("b", "10.00", "withdrawal", currency="USD"), headers=A)
    assert r.status_code == 422  # no USD balance to draw from
    client.post("/transactions", json=tx("c", "5000", currency="JPY"), headers=A)
    bal = {b["currency"]: b["balance"] for b in client.get("/clients/c1/balance", headers=A).json()["balances"]}
    assert bal == {"INR": "100.00", "JPY": "5000"}
