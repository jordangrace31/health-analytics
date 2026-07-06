from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, constr
from sqlalchemy.orm import Session
from app.db import get_db
from app.models import User
from app.security import hash_password, verify_password, get_current_user, login_rate_limit

router = APIRouter(prefix="/api/auth", tags=["auth"])

class RegisterCredentials(BaseModel):
    username: constr(min_length=1, max_length=50)
    password: constr(min_length=6, max_length=200)

class LoginCredentials(BaseModel):
    username: constr(min_length=1, max_length=50)
    password: constr(min_length=1, max_length=200)

@router.post("/register", status_code=201)
def register(body: RegisterCredentials, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="Username taken")
    db.add(User(username=body.username, password_hash=hash_password(body.password)))
    db.commit()
    return {"status": "created"}

@router.post("/login")
def login(body: LoginCredentials, request: Request, db: Session = Depends(get_db),
          _: None = Depends(login_rate_limit)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    request.session["user_id"] = user.id
    return {"status": "ok", "username": user.username}

@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "ok"}

@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"id": user.id, "username": user.username}
