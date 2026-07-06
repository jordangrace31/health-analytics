import time
from collections import defaultdict
from fastapi import Depends, HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User

_pwd = CryptContext(schemes=["argon2"], deprecated="auto")

def hash_password(pw: str) -> str:
    return _pwd.hash(pw)

def verify_password(pw: str, h: str) -> bool:
    return _pwd.verify(pw, h)

def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

_attempts: dict[str, list[float]] = defaultdict(list)

def login_rate_limit(request: Request):
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    window = [t for t in _attempts[ip] if now - t < 60]
    if len(window) >= 10:
        raise HTTPException(status_code=429, detail="Too many attempts")
    window.append(now)
    _attempts[ip] = window
