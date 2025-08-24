from fastapi import APIRouter, Depends, HTTPException, status, Response, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
import secrets

from crud import user as crud_user
import schemas
from models import User
from core.security import verify_password
from dependencies import get_db

router = APIRouter()


# ============================
# 👤 Register User
# ============================
@router.post("/users", response_model=schemas.User, status_code=status.HTTP_201_CREATED)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = crud_user.get_user(db, user.username)  # ✅ Fixed keyword usage
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    return crud_user.create_user(db=db, user=user)


# ============================
# 🔐 Login (Set Cookie)
# ============================
@router.post("/login")
def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    user = crud_user.get_user(db, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    # Generate secure random token
    session_token = secrets.token_urlsafe(32)
    crud_user.create_session_token(db, user_id=user.id, token=session_token)

    # Set cookie on response
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        max_age=3600 * 24 * 7,  # 7 days
        secure=False,  # Set to True in production with HTTPS
        samesite="Lax"
    )

    return {"message": "Login successful"}


# ============================
# 🚪 Logout (Clear Cookie)
# ============================
@router.post("/logout")
def logout(
    response: Response,
    session_token: str = Cookie(None),
    db: Session = Depends(get_db)
):
    if session_token:
        crud_user.delete_session_token(db, token=session_token)
        response.delete_cookie("session_token")
    return {"message": "Logged out"}


# ============================
# 👀 Get Current User (/me)
# ============================
@router.get("/me", response_model=schemas.User)
def read_current_user(
    session_token: str = Cookie(None),
    db: Session = Depends(get_db)
):
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = crud_user.get_user_by_session_token(db, token=session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")

    return user
