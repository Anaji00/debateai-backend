import requests

url = "https://vocloner.com/tts_processprova.php"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Origin": "https://vocloner.com",
    "Referer": "https://vocloner.com/",
    "Cookie": "PHPSESSID=vo9jhnem3al8vjm1b012r2ckne"  # Must be current from browser
}

# Send all fields as 'files' to force multipart/form-data
files = {
    "voce[name]": (None, "mario"),
    "testo": (None, "This is a test from DebateAI."),
    "format": (None, "mp3")
}

response = requests.post(url, headers=headers, files=files)
print("Status:", response.status_code)
print("Response:", response.text)
