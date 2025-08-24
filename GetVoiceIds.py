import requests
import os

API_KEY = os.getenv("ELEVENLABS_API_KEY")

response = requests.get(
    "https://api.elevenlabs.io/v1/voices",
    headers={"xi-api-key": API_KEY}
)

voices = response.json().get("voices", [])

for v in voices:
    print(f"{v['name']}: {v['voice_id']}")
