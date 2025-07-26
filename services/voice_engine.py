# This module handles Text-to-Speech (TTS) synthesis using the Coqui TTS library.
# It is responsible for converting generated debate text into audio files.

import os
import torch
from pathlib import Path
from TTS.api import TTS

# A dictionary mapping character names to their corresponding voice sample files.
# These .wav or .mp3 files are used by the XTTS model for voice cloning.
# The character name key should be lowercase.
VOICES = {
    "donald trump": "backend/voices/trump.wav",
    "thanos": "backend/voices/thanos.mp3"
}

# The directory where generated audio files will be saved.
# These files are served statically by the FastAPI application.
OUTPUT_DIR = "backend/static/audio/"

# Ensure the output directory exists before the application starts.
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Initialize the TTS model.
# We use the XTTSv2 model, which is a powerful multilingual voice cloning model.
# 'gpu=torch.cuda.is_available()' automatically enables GPU acceleration if a
# compatible NVIDIA GPU and CUDA are detected, which significantly speeds up synthesis.
tts = TTS(
    model_name="tts_models/multilingual/multi-dataset/xtts_v2",
    progress_bar=True,
    gpu=torch.cuda.is_available()
)

def synthesize_xtts(text: str, character: str, filename: str ="output.wav") -> str:
    """
    Synthesizes text into an audio file using a specific character's voice.

    Args:
        text (str): The text to be converted to speech.
        character (str): The name of the character whose voice should be used.
                         Must be a key in the VOICES dictionary.
        filename (str): The desired filename for the output audio file.

    Returns:
        str: The full path to the generated audio file, or None if synthesis fails.
    """
    character = character.lower().strip()
    if character not in VOICES:
        print(f"No voices for {character}")
        return None
    
    speaker_wav = VOICES[character]
    out_path = os.path.join(OUTPUT_DIR, filename)

    try:
        tts.tts_to_file(
            text=text,
            speaker_wav=speaker_wav,
            language="en",
            file_path=out_path
        )
        if os.path.exists(out_path):
            return out_path
        
        else:
            print(f"File not found: {out_path}")
            return None
    except Exception as e:
        print(f"Error synthesizing audio: {e}")
        return None