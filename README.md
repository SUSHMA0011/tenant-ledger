# Tenant Ledger (FastAPI + SQLite)
1. `pip install -r requirements.txt`
2. `python -m app.seed "Northbridge Advisory"` -> prints an API key (send it as the `X-API-Key` header)
3. `uvicorn app.main:app --reload` -> interactive docs at http://127.0.0.1:8000/docs
4. `pytest -q` -> runs the full test suite
