# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

All commands run from the `music-finder/` directory:

```bash
# Install dependencies
pip install -r requirements.txt

# Start the development server (hot-reload)
uvicorn main:app --reload --port 8000
```

Open http://localhost:8000. On Windows, `run.bat` does the full install-and-launch in one step.

**External requirement:** `ffmpeg` must be on PATH (`winget install ffmpeg` on Windows).

## Optional Spotify API

Set `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` env vars for exact Spotify track links. Without them, the app falls back to a Spotify search URL.

## Architecture

Single FastAPI endpoint streaming results to the browser over **Server-Sent Events (SSE)**.

```
main.py           — FastAPI app, SSE event_stream, input validation
downloader.py     — yt-dlp wrapper; returns (tmp_dir, mp3_path, video_title)
recognizer.py     — audio chunking, parallel Shazam calls, Spotify lookup
_shazam/          — vendored Shazam client (stripped from shazamio 0.4.0.1, no Rust required)
static/index.html — single-page frontend (vanilla JS, no build step)
```

**Request flow for `POST /api/detect`:**
1. `downloader.download_audio` runs in a thread (`asyncio.to_thread`), streams download progress via a Queue
2. `recognizer.identify_songs` slices the MP3 into 15 s chunks at regular intervals, fires up to 5 concurrent Shazam requests, deduplicates by `(title, artist)`, fetches Spotify URLs, calls `on_result` per song so the SSE stream emits results incrementally
3. A `done` SSE event closes the stream; temp dir cleaned up in `finally`

**Sampling strategy** (`recognizer.py`): starts at `START_OFFSET_S=5`, interval = `max(30, span // 30)` seconds — scales to ~30 samples regardless of video length, no hard cap.

**`_shazam/`** is a vendored copy of shazamio 0.4.0.1 stripped of pydantic dependencies. Its only public API is `Shazam.recognize_song(data)` where data can be bytes, a file path, or an AudioSegment. Do not replace this with `pip install shazamio` — newer versions require a Rust extension (`shazamio-core`) that fails to build on Python 3.14 without MSVC.

## Branch layout

| Branch | Contents |
|--------|----------|
| `main` | Previous working prototype |
| `v1.0` | Current development branch |
