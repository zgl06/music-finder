# Music Finder

Paste any video link and identify every song playing in it. Supports YouTube, Instagram, TikTok, and 1,700+ other sites. Results include song title, artist, album art, the timestamp it appears, and a Spotify link.

## How it works

1. Audio is downloaded via **yt-dlp**
2. The audio is sliced into 15-second chunks at regular intervals
3. Each chunk is sent to **Shazam** (free, no API key needed)
4. Detected songs are deduplicated and returned with Spotify links

Songs stream to the UI as they are identified — you don't wait for the whole video to finish.

---

## Setup

### Requirements
- Python 3.10+
- ffmpeg on PATH

**Install ffmpeg (Windows):**
```powershell
winget install ffmpeg
```

**Install Python dependencies:**
```powershell
cd music-finder
pip install -r requirements.txt
```

### Run
```powershell
uvicorn main:app --port 8000
```
Then open http://localhost:8000.

**Or on Windows:** double-click `run.bat` — it checks dependencies and opens the browser automatically.

---

## Optional: Spotify exact track links

Without this, the Spotify button opens a search — functional but not a direct link to the song.

1. Go to https://developer.spotify.com/dashboard and create a free app (2 minutes, no credit card)
2. Copy your **Client ID** and **Client Secret**
3. Set them before starting the server:

```powershell
$env:SPOTIFY_CLIENT_ID     = "your_client_id"
$env:SPOTIFY_CLIENT_SECRET = "your_client_secret"
uvicorn main:app --port 8000
```

With credentials, the Spotify button opens directly on the exact song page.

---

## Usage

1. Paste a video URL (YouTube, Instagram, TikTok, etc.)
2. Optionally set a time range — e.g. `1:30` to `3:00` — to analyse only part of the video
3. Click **Detect** and watch songs appear as they are identified

**Time range formats accepted:** `1:30`, `90`, `1:30:00`

## Notes

- **Sampling:** videos ≤5 min are sampled every 30 s; longer videos scale automatically to ~30 samples total, so a 2-hour video and a 10-minute video take similar analysis time
- **Instagram:** public Reels work; private accounts and Stories may fail
- **No results:** the music may be too quiet, heavily mixed with speech, or not in Shazam's database
- **Limits:** yt-dlp and Shazam have no hard usage limits for personal use
