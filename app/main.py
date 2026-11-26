from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from . import models  # noqa: F401  (registers tables)
from . import service
from .auth import get_actor, get_current_firm
from .database import Base, engine, get_db
from .schemas import BulkIn, ReverseIn, TransactionIn

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Tenant Ledger")


@app.exception_handler(service.LedgerError)
def ledger_error_handler(_request, exc: service.LedgerError):
    return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/me")
def me(firm: models.Firm = Depends(get_current_firm)):
    return {"firm_id": firm.id, "name": firm.name}


@app.post("/transactions")
def create_transaction(body: TransactionIn, firm: models.Firm = Depends(get_current_firm),
                       actor: str = Depends(get_actor), db: Session = Depends(get_db)):
    """Idempotent on external_ref: a retry of the same payload returns 200 with the original row."""
    r = service.ingest_batch(db, firm.id, [body.model_dump(mode="json")], actor)[0]
    if r.status == "accepted":
        return JSONResponse(status_code=201, content={"status": "accepted", "transaction": service.txn_out(r.transaction)})
    if r.status == "duplicate":
        return JSONResponse(status_code=200, content={"status": "duplicate", "transaction": service.txn_out(r.transaction)})
    http = 409 if r.code == "external_ref_conflict" else 422
    return JSONResponse(status_code=http, content={"error": {"code": r.code, "message": r.error}})


@app.post("/transactions/bulk")
def bulk_transactions(body: BulkIn, firm: models.Firm = Depends(get_current_firm),
                      actor: str = Depends(get_actor), db: Session = Depends(get_db)):
    """Partial success: good rows are saved, bad rows come back with the row index and reason."""
    results = service.ingest_batch(db, firm.id, body.transactions, actor)
    summary = {"accepted": 0, "duplicates": 0, "rejected": 0}
    items = []
    for r in results:
        summary[{"accepted": "accepted", "duplicate": "duplicates", "rejected": "rejected"}[r.status]] += 1
        items.append({"index": r.index, "status": r.status,
                      "transaction_id": r.transaction.id if r.transaction else None,
                      "code": r.code, "error": r.error})
    return {"summary": summary, "results": items}


@app.post("/transactions/{txn_id}/reverse", status_code=201)
def reverse(txn_id: int, body: ReverseIn | None = None, firm: models.Firm = Depends(get_current_firm),
            actor: str = Depends(get_actor), db: Session = Depends(get_db)):
    body = body or ReverseIn()
    rev = service.reverse_transaction(db, firm.id, txn_id, body.external_ref, body.reason, actor)
    return {"status": "reversed", "transaction": service.txn_out(rev)}


@app.get("/transactions/{txn_id}")
def read_transaction(txn_id: int, firm: models.Firm = Depends(get_current_firm), db: Session = Depends(get_db)):
    return service.txn_out(service.get_transaction(db, firm.id, txn_id))


@app.get("/clients/{client_ref}/transactions")
def client_transactions(client_ref: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                        firm: models.Firm = Depends(get_current_firm), db: Session = Depends(get_db)):
    return [service.txn_out(t) for t in service.list_transactions(db, firm.id, client_ref, limit, offset)]


@app.get("/clients/{client_ref}/balance")
def client_balance(client_ref: str, as_of: date | None = None,
                   firm: models.Firm = Depends(get_current_firm), db: Session = Depends(get_db)):
    """Balance per currency as of a date (default today). Answers 'what was the balance at quarter-end?'"""
    as_of = as_of or service._today()
    return {"client_ref": client_ref, "as_of": as_of.isoformat(),
            "balances": service.balances_as_of(db, firm.id, client_ref, as_of)}


@app.get("/clients/{client_ref}/summary")
def client_summary(client_ref: str, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                   firm: models.Firm = Depends(get_current_firm), db: Session = Depends(get_db)):
    year, mon = int(month[:4]), int(month[5:])
    if year < 1900:
        raise HTTPException(status_code=422, detail="invalid month")
    return {"client_ref": client_ref, "month": month,
            "currencies": service.monthly_summary(db, firm.id, client_ref, year, mon)}


@app.get("/audit-log")
def audit_log(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              firm: models.Firm = Depends(get_current_firm), db: Session = Depends(get_db)):
    return service.list_audit(db, firm.id, limit, offset)
