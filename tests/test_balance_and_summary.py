from datetime import date, timedelta

from tests.conftest import A, tx

# Use last calendar month so dates are never in the future whatever "today" is.
first_this = date.today().replace(day=1)
prev_end = first_this - timedelta(days=1)
prev_start = prev_end.replace(day=1)
two_back_end = prev_start - timedelta(days=1)
MONTH = prev_start.strftime("%Y-%m")


def test_balance_as_of_ignores_later_transactions(client):
    client.post("/transactions", json=tx("d1", "100.00", when=two_back_end.isoformat()), headers=A)
    client.post("/transactions", json=tx("d2", "50.00", when=prev_start.isoformat()), headers=A)
    past = client.get(f"/clients/c1/balance?as_of={two_back_end.isoformat()}", headers=A).json()
    assert past["balances"] == [{"currency": "INR", "balance": "100.00"}]
    assert client.get("/clients/c1/balance", headers=A).json()["balances"][0]["balance"] == "150.00"


def test_balance_for_unknown_client_is_empty(client):
    assert client.get("/clients/nobody/balance", headers=A).json()["balances"] == []


def test_monthly_summary(client):
    rows = [
        tx("d0", "100.00", when=two_back_end.isoformat()),                    # opening balance
        tx("d1", "200.00", when=prev_start.isoformat()),                      # inflow
        tx("w1", "30.00", "withdrawal", when=prev_end.isoformat()),           # outflow
        tx("f1", "5.00", "fee", when=prev_end.isoformat()),                   # fee
        tx("d2", "999.00", when=date.today().isoformat()),                    # outside the month
    ]
    client.post("/transactions/bulk", json={"transactions": rows}, headers=A)
    s = client.get(f"/clients/c1/summary?month={MONTH}", headers=A).json()["currencies"][0]
    assert s == {"currency": "INR", "opening_balance": "100.00", "inflows": "200.00", "outflows": "30.00",
                 "fees": "5.00", "reversals_net": "0.00", "net_change": "165.00", "closing_balance": "265.00"}


def test_summary_rejects_bad_month(client):
    assert client.get("/clients/c1/summary?month=2026-13", headers=A).status_code == 422
    assert client.get("/clients/c1/summary", headers=A).status_code == 422
