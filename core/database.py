# This file configures the database connection for the application using SQLAlchemy.
 
# --- Imports ---
# Import necessary components from the SQLAlchemy library.
from sqlalchemy import create_engine # Used to create a database engine.
from sqlalchemy.ext.declarative import declarative_base # Used to create a base class for ORM models.
from sqlalchemy.orm import sessionmaker # Used to create a session factory.
 
# --- Database Configuration ---
# Define the connection string for the database.
# This uses a local SQLite database file named 'debate.db' in the same directory.
SQLALCHEMY_DATABASE_URL = "sqlite:///./debate.db"
 
# Create the SQLAlchemy engine, which is the entry point to the database.
# The 'connect_args' is needed only for SQLite to allow the database to be used by multiple threads,
# which is how FastAPI works.
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
 
# Create a configured "Session" class. This will be a factory for new database session objects.
# autocommit=False and autoflush=False mean that we will manually control when to save data to the database.
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# Create a Base class for our declarative models.
# Any database model we create (like the User model) will inherit from this class.
Base = declarative_base()