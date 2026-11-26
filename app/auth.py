import hashlib

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import Firm


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def get_current_firm(
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Firm:
    """The API key *is* the tenant. Every query downstream filters by this firm's id."""
    if not x_api_key:
        raise HTTPException(status_code=401, detail="Missing API key")
    firm = db.scalar(select(Firm).where(Firm.api_key_hash == hash_key(x_api_key)))
    if firm is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return firm


def get_actor(firm: Firm = Depends(get_current_firm), x_actor: str | None = Header(default=None)) -> str:
    """Who performed the action, for the audit log. Self-declared via X-Actor (see NOTES.md)."""
    return (x_actor or f"key:{firm.name}")[:64]
