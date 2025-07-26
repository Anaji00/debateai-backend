#auth
 
from fastapi import APIRouter, Depends, HTTPException, status # Core FastAPI components.
from fastapi.security import OAuth2PasswordRequestForm # A dependency class that extracts username and password from a form body.
from sqlalchemy.orm import Session # For type hinting the database session.
 
from crud import user as crud_user # Import the user module from the crud package.
import schemas # The module containing our Pydantic schemas.
from core.security import create_access_token, verify_password # Security utility for token creation.
from dependencies import get_db # Import the shared get_db dependency.
 
# Create a new router object. This helps organize endpoints.
router = APIRouter()
 
# Endpoint for user registration.
@router.post("/users/", response_model=schemas.User, status_code=status.HTTP_201_CREATED)
def register_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Check if a user with the same username already exists.
    db_user = crud_user.get_user(db, username=user.username)
    if db_user:
        # If the user exists, raise an HTTP exception indicating a conflict.
        raise HTTPException(status_code=400, detail="Username already registered")
    # If the username is available, create the new user.
    return crud_user.create_user(db=db, user=user)
 
# Endpoint for user login, which returns a JWT.
@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Use the username from the form data to look up the user in the database.
    user = crud_user.get_user(db, form_data.username)
    # Check if the user exists and if the provided password is correct.
    if not user or not verify_password(form_data.password, user.hashed_password):
        # If not, raise an unauthorized error. Note: use 'detail' not 'details'.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect username or password", headers={"WWW-Authenticate": "Bearer"})
    # If credentials are correct, create a new access token for the user.
    # The 'sub' (subject) of the token is the username.
    token = create_access_token({"sub": user.username})
    # Return the token in the format defined by the 'Token' schema.
    return {"access_token": token, "token_type": "bearer"}
