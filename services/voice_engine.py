# services/voice_engine.py
"""
ElevenLabs TTS integration for DebateAI.

• We never send the canonical political/celebrity name to ElevenLabs.
• Instead, we look up an already-provisioned ElevenLabs voice by a SAFE ALIAS
  (e.g., "the titan", "the businessman") stored in a local JSON mapping.

voice_id.json example:
{
  "the titan": "VOICE_ID_aaaa_bbbb_cccc",
  "the businessman": "VOICE_ID_xxxx_yyyy_zzzz",
  "shared narrator": "VOICE_ID_1234_5678_90ab"
}

Key ideas:
- Aliases are strictly for *lookup on our side*; we only pass the voice_id to ElevenLabs.
- We normalize alias keys (lowercase, strip, remove specials) to prevent mismatch bugs.
- You can return either:
    a) a filesystem path + public /static URL
    b) a data: URL (base64) if you don’t want to serve files
"""

# Import standard Python libraries for interacting with the operating system,
# regular expressions, JSON data, base64 encoding, logging, and in-memory bytes handling.
import os
import re
import json
import base64
import logging
from io import BytesIO
# Import Path for object-oriented filesystem paths, making path manipulation safer and easier.
from pathlib import Path
# Import typing for type hints, improving code readability and maintainability.
from typing import Dict, Optional, Tuple

# --- ElevenLabs SDK import (compat across versions) ---
# This try-except block handles different import paths for the ElevenLabs SDK,
# ensuring the code works with both newer and older versions of the library.
try:
    from elevenlabs.client import ElevenLabs   # new packaging
except Exception:  # pragma: no cover
    from elevenlabs import ElevenLabs          # legacy packaging

logger = logging.getLogger(__name__)

# Set up a logger for this module to record events and errors.
# =============================================================================
# Config
# =============================================================================

# Backend root
BASE_DIR = Path(__file__).resolve().parents[1]

# Define the directory for static files, which are served directly by the web server.
# It first checks for an environment variable 'STATIC_DIR' for custom configuration,
# otherwise, it defaults to 'backend/static'.

STATIC_DIR = (os.getenv("STATIC_DIR") and Path(os.getenv("STATIC_DIR")).resolve()) or (BASE_DIR / "static")

# Define the directory where generated audio files will be stored.
# It also checks for an environment variable 'AUDIO_GEN_DIR' first,
# defaulting to 'static/audio/generated'.
GEN_DIR = (os.getenv("AUDIO_GEN_DIR") and Path(os.getenv("AUDIO_GEN_DIR")).resolve()) or (STATIC_DIR / "audio" / "generated")

# Create the generated audio directory if it doesn't already exist.
# `parents=True` creates any necessary parent directories.
# `exist_ok=True` prevents an error if the directory already exists.
GEN_DIR.mkdir(parents=True, exist_ok=True)

# Path to your alias -> voice_id map
# Define the path to the JSON file that maps character aliases to ElevenLabs voice IDs.
# It checks for an environment variable 'VOICE_ID_JSON' for flexibility.
VOICE_CACHE_FILE = (os.getenv("VOICE_ID_JSON") and Path(os.getenv("VOICE_ID_JSON")).resolve()) or (BASE_DIR / "voice_id.json")

# ElevenLabs config
# Get the ElevenLabs API key from environment variables. It checks two common names.
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY") or os.getenv("ELEVENLABS_API_KEY")
# Get the ElevenLabs model ID to use for TTS, defaulting to 'eleven_multilingual_v2'.
ELEVEN_MODEL_ID = os.getenv("ELEVEN_MODEL_ID", "eleven_multilingual_v2")
# Get the desired output format for the audio, defaulting to 'wav'.
ELEVEN_OUTPUT_FORMAT = os.getenv("ELEVEN_OUTPUT_FORMAT", "wav")  # "wav" | "mp3_44100_128" etc.
# Get the latency optimization level, defaulting to "0" (no optimization).
ELEVEN_LATENCY = os.getenv("ELEVEN_LATENCY_OPT", "0")            # "0", "1", "2", "3"

# Maximum characters per TTS call (keep some headroom)
# Set the maximum number of characters allowed in a single TTS request to avoid API errors.
MAX_CHARS = int(os.getenv("ELEVEN_MAX_CHARS", "4000"))

# =============================================================================
# Utilities
# =============================================================================

def _safe_key(s: str) -> str:
    # This function normalizes a string to be used as a safe key for dictionary lookups.
    # It converts the string to lowercase, removes leading/trailing whitespace,
    # replaces underscores with spaces, and removes any characters that are not
    # letters, numbers, hyphens, or spaces.
    return re.sub(r"[^a-z0-9\- ]+", "", (s or "").strip().lower().replace("_", " "))

def _safe_filename(base: str, suffix: str = ".wav") -> str:
    # This function creates a filesystem-safe filename from a base string.
    # It uses `_safe_key` to clean the base name and replaces spaces with underscores.
    return f"{_safe_key(base).replace(' ', '_')}{suffix}"

def _public_url_for(file_path: Path) -> Optional[str]:
    # This function converts an absolute filesystem path to a public URL
    # that can be used by the frontend.
    try:
        # Get the absolute path of the file and the static directory.
        file_path = file_path.resolve()
        static_root = STATIC_DIR.resolve()
        # Calculate the relative path from the static root.
        rel = file_path.relative_to(static_root)
        # Construct the URL, ensuring forward slashes for web compatibility.
        return f"/static/{rel.as_posix()}"
    except Exception:
        # If the file is not within the static directory, return None.
        return None

# We cache JSON + its mtime so we don’t re-read on every call unnecessarily.
_VOICE_CACHE: Dict[str, str] = {}
_VOICE_CACHE_MTIME: Optional[float] = None

def _load_cache() -> Dict[str, str]:
    # This function loads the alias-to-voice_id mapping from the JSON file.
    # It caches the result and only reloads the file if it has been modified.
    global _VOICE_CACHE, _VOICE_CACHE_MTIME
    # Check if the voice cache file exists.
    if not VOICE_CACHE_FILE.exists():
        logger.warning("[VoiceEngine] voice_id.json not found at %s", VOICE_CACHE_FILE)
        _VOICE_CACHE, _VOICE_CACHE_MTIME = {}, None
        return _VOICE_CACHE

    # Get the last modification time of the file.
    mtime = VOICE_CACHE_FILE.stat().st_mtime
    # Reload the file if it's the first time or if the file has changed.
    if _VOICE_CACHE_MTIME is None or mtime != _VOICE_CACHE_MTIME:
        try:
            # Read and parse the JSON file.
            mapping = json.loads(VOICE_CACHE_FILE.read_text(encoding="utf-8"))
            # normalize keys for safety
            # Normalize the keys in the mapping for safe lookups.
            _VOICE_CACHE = { _safe_key(k): v for k, v in mapping.items() if isinstance(k, str) and isinstance(v, str) }
            # Update the cache modification time.
            _VOICE_CACHE_MTIME = mtime
            logger.info("[VoiceEngine] Loaded %d voice ids from %s", len(_VOICE_CACHE), VOICE_CACHE_FILE)
        except Exception as e:
            # Log an error if reading the file fails.
            logger.error("[VoiceEngine] Failed reading %s: %s", VOICE_CACHE_FILE, e)
            _VOICE_CACHE, _VOICE_CACHE_MTIME = {}, None
    # Return the cached mapping.
    return _VOICE_CACHE

def _eleven_client() -> ElevenLabs:
    # This function creates and returns an instance of the ElevenLabs client.
    # It warns if the API key is not set, as TTS calls will fail.
    if not ELEVEN_API_KEY:
        logger.warning("[VoiceEngine] ELEVEN_API_KEY not set; TTS calls will fail.")
    return ElevenLabs(api_key=ELEVEN_API_KEY)

def _resolve_voice_id(alias_or_name: str) -> Optional[str]:
    # This function finds the ElevenLabs voice ID for a given character alias.
    # It ensures that sensitive names are not used directly for lookups.
    # Load the mapping from the cache (or file).
    mapping = _load_cache()
    # Normalize the alias to create a safe key.
    key = _safe_key(alias_or_name)
    # Look up the voice ID in the mapping.
    vid = mapping.get(key)
    # If the voice ID is not found, log an error.
    if not vid:
        logger.error("[VoiceEngine] No voice_id for alias '%s' (key='%s'). Add it to %s", alias_or_name, key, VOICE_CACHE_FILE)
    # Return the voice ID or None if not found.
    return vid

def _validate_voice_id(client: ElevenLabs, voice_id: str) -> bool:
    # This function can be used to check if a voice ID is valid by making an API call.
    # It's useful for debugging but is often disabled to reduce latency.
    try:
        # Try calling the API with the new SDK signature.
        try:
            client.voices.get(voice_id=voice_id)  # new signature
        except TypeError:
            # Fallback to the legacy signature if the new one fails.
            client.voices.get(voice_id)           # legacy signature
        return True
    except Exception as e:
        # Log an error if the API call fails.
        logger.error("[VoiceEngine] voices.get failed for '%s': %s", voice_id, e)
        return False

def _trim_text(text: str) -> str:
    # This function trims the input text to the maximum character limit.
    # It ensures the text sent to the API is not too long.
    t = (text or "").strip()
    if len(t) > MAX_CHARS:
        logger.info("[VoiceEngine] Trimming TTS text from %d -> %d chars", len(t), MAX_CHARS)
        return t[:MAX_CHARS]
    return t

# =============================================================================
# Public API
# =============================================================================

async def synthesize(
    text: str,
    alias_name: str,
    *,
    filename_hint: Optional[str] = None,
    return_data_url: bool = False
) -> Optional[str]:
    # This is the main public function for synthesizing speech.
    # It takes text and a character alias, and returns an audio URL or data URL.

    # Step 1: Resolve the voice ID from the safe alias name.
    voice_id = _resolve_voice_id(alias_name)
    if not voice_id:
        return None

    # Step 2: Create an ElevenLabs API client.
    client = _eleven_client()

    # (Optional) validate voice id once in a while. You can skip to save latency.
    # (Optional) You could uncomment this to validate the voice
    # if not _validate_voice_id(client, voice_id):
    #     return None

    # Prepare text
    tt = _trim_text(text)

    try:
        # Perform TTS; handle both new/legacy signatures
        try:
            audio_iter = client.text_to_speech.convert(
                voice_id=voice_id,
                text=tt,
                output_format=ELEVEN_OUTPUT_FORMAT,
                model_id=ELEVEN_MODEL_ID,
                optimize_streaming_latency=ELEVEN_LATENCY,
            )
        except TypeError:
            # legacy signature fallback:
            audio_iter = client.text_to_speech.convert(  # type: ignore
                voice_id, tt, None, ELEVEN_MODEL_ID, ELEVEN_OUTPUT_FORMAT, ELEVEN_LATENCY
            )

        if return_data_url:
            # Collect to memory, return base64 data URL (no files)
            buf = BytesIO()
            for chunk in audio_iter:
                if chunk:
                    buf.write(chunk)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            mime = "audio/wav" if ELEVEN_OUTPUT_FORMAT == "wav" else "audio/mpeg"
            return f"data:{mime};base64,{b64}"

        # Otherwise, stream to a file under /static/audio/generated
        suffix = ".wav" if ELEVEN_OUTPUT_FORMAT == "wav" else ".mp3"
        base = filename_hint or alias_name
        # make it unique-ish per call
        unique = os.urandom(4).hex()
        outname = _safe_filename(f"{base}_{unique}", suffix=suffix)
        outfile = GEN_DIR / outname

        with open(outfile, "wb") as f:
            for chunk in audio_iter:
                if chunk:
                    f.write(chunk)

        logger.info("[VoiceEngine] Saved TTS: %s", outfile)
        # Prefer returning a public URL; fallback to absolute path if static mapping not available
        url = _public_url_for(outfile)
        return url or str(outfile.resolve())

    except Exception as e:
        logger.error("[VoiceEngine] Synthesis failed (alias='%s'): %s", alias_name, e)
        return None

__all__ = ["synthesize", "STATIC_DIR", "GEN_DIR", "VOICE_CACHE_FILE"]
