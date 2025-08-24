# Configuration module for environment setup and API client initialization
# This module is imported by: debatesim.py (main app)
# Dependencies: python-dotenv, openai
# Purpose: Centralized configuration management and API client creation

import os  # For accessing environment variables from system
from dotenv import load_dotenv  # For loading .env files into environment
from openai import AsyncOpenAI  # OpenAI client for API calls


def load_environment():
    """
    Load environment variables from .env file and validate OpenAI API key
    Called by: debatesim.py (main app), get_openai_client()
    Returns: OpenAI API key string
    Raises: ValueError if API key is not found
    Logic: Uses dotenv to load .env file, then os.getenv to retrieve specific key
    """
    load_dotenv()  # Load variables from .env file into environment (creates os.environ entries)
    openai_key = os.getenv("OPENAI_API_KEY")  # Get API key from environment (returns None if not found)
    if not openai_key:  # Check if API key exists (handles None, empty string, etc.)
        raise ValueError("OPEN AI KEY NOT LOADED")  # Raise error if missing (stops app execution)
    return openai_key  # Return the API key for use in other modules

def get_openai_async_client():
    """
    Initialize and return OpenAI client with API key
    Called by: debatesim.py (main app) - creates client for debate_engine.py
    Returns: OpenAI client instance ready for API calls
    Logic: Gets API key first, then creates OpenAI client object
    Usage: client = get_openai_client() -> client.chat.completions.create(...)
    """
    api_key = load_environment()  # Get validated API key (calls function above)
    return AsyncOpenAI(api_key=api_key)  # Create and return OpenAI client (used in debate_engine.py)