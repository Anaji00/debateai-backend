# CRUD OPS
 
from sqlalchemy.orm import Session # Import Session to enable type hinting for the database session.
import schemas # Import the schemas module to access Pydantic models.
from core.security import hash_password # Import the password hashing function.
from models.User import User # Import the User model from the models module.
 
# Function to retrieve a user from the database by their username.
def get_user(db: Session, username: str):
    # Queries the database for a User where the username matches the one provided.
    # .first() returns the first result or None if not found.
    return db.query(User).filter(User.username == username).first()
 
# Function to create a new user in the database.
# It takes the Pydantic schema 'UserCreate' as input for data validation.
def create_user(db: Session, user: schemas.UserCreate):
    # Creates a new SQLAlchemy User model instance.
    # The plain-text password from the input 'user' object is hashed before being stored.
    db_user = User(username=user.username, email=user.email, hashed_password=hash_password(user.password))
    db.add(db_user) # Add the new user object to the database session.
    db.commit() # Commit the transaction to save the user to the database.
    db.refresh(db_user) # Refresh the user object to get its state from the database (e.g., auto-generated IDs).
    return db_user
