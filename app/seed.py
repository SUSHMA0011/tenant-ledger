import secrets
import sys

from .auth import hash_key
from .database import Base, SessionLocal, engine
from .models import Firm

if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    name = sys.argv[1] if len(sys.argv) > 1 else "Demo Firm"
    key = secrets.token_urlsafe(32)
    with SessionLocal() as db:
        db.add(Firm(name=name, api_key_hash=hash_key(key)))
        db.commit()
    print(f"Firm: {name}\nAPI key (save it, shown once): {key}")
