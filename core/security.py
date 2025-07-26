# JWT HASHING

from datetime import datetime, timedelta # Import datetime and timedelta for token expiration.
from jose import jwt # Import the JWT library for creating and verifying tokens.
from passlib.context import CryptContext # Import CryptContext for password hashing.
 
# --- Configuration ---
# BEST PRACTICE: For production, load these values from environment variables
# instead of hardcoding them. This keeps sensitive keys out of your source code.
SECRET_KEY = "testsecretkeyforapplication"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
 
# --- Password Hashing ---
# Create a CryptContext instance, specifying bcrypt as the hashing scheme.
# 'deprecated="auto"' will automatically handle updating hashes if you change schemes in the future.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
 
# Function to hash a plain-text password.
def hash_password(password):
    return pwd_context.hash(password)
 
# Function to verify a plain-text password against a hashed one.
def verify_password(plain: str, hashed: str):
    return pwd_context.verify(plain, hashed)
 
# --- JWT Access Token ---
# Function to create a new JWT access token.
def create_access_token(data: dict):
    # Create a copy of the data to avoid modifying the original dictionary.
    to_encode = data.copy()
    # Calculate the token's expiration time from the current UTC time.
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Add the expiration time ('exp') claim to the token payload.
    to_encode.update({"exp": expire})
    # Encode the payload into a JWT string using your secret key and algorithm.
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
