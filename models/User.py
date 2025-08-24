from sqlalchemy import Column, ForeignKey, Integer, String # Import Column and String types for defining database columns.
from core.database import Base # Import the Base class from your database configuration. All SQLAlchemy models will inherit from this.
from sqlalchemy.orm import relationship
 
# This class defines the User model for the database.
# It inherits from Base, making it a SQLAlchemy ORM model.
class User(Base):
    # __tablename__ tells SQLAlchemy the name of the table to use in the database for this model.
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    # Defines the 'username' column as a string, the primary key for the table, and indexed for faster lookups.
    username = Column(String, unique=True, index=True)
    # Defines the 'email' column as a unique string and indexed. 'unique=True' ensures no two users can have the same email.
    email = Column(String, unique=True, index=True)
    # Defines the 'hashed_password' column as a string to store the user's hashed password for security.
    hashed_password = Column(String)

    # models/user.py
    sessions = relationship("Session", back_populates="user")
    session_tokens = relationship("SessionToken", back_populates="user", cascade="all, delete-orphan")


class SessionToken(Base):
    __tablename__ = "session_tokens"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    token = Column(String, unique=True)

    user = relationship("User", back_populates="session_tokens")
    