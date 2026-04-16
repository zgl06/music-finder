import asyncio
import io
import os
import time
from collections.abc import Callable, Awaitable
from urllib.parse import quote

import httpx
from pydub import AudioSegment
from _shazam import Shazam

# Duration of each sample chunk in milliseconds
CHUNK_MS = 8_000
# Skip the first N seconds of a full video to avoid silent intros
START_OFFSET_S = 5
# Max concurrent Shazam requests (rate-limit protection)
_SHAZAM_CONCURRENCY = 5

# Spotify token cache
_spotify_token: str | None = None
_spotify_token_expiry: float = 0.0


async def _get_spotify_token(
    client_id: str, client_secret: str, client: httpx.AsyncClient
) -> str | None:
    global _spotify_token, _spotify_token_expiry
    if _spotify_token and time.time() < _spotify_token_expiry:
        return _spotify_token
    try:
        resp = await client.post(
            "https://accounts.spotify.com/api/token",
            data={"grant_type": "client_credentials"},
            auth=(client_id, client_secret),
        )
        data = resp.json()
        _spotify_token = data.get("access_token")
        _spotify_token_expiry = time.time() + data.get("expires_in", 3600) - 60
        return _spotify_token
    except Exception:
        return None


async def _get_spotify_url(title: str, artist: str) -> str:
    """
    Return a Spotify URL for the given song.

    Uses the Spotify API if SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET env vars
    are set; otherwise falls back to a Spotify search URL (no credentials needed).
    """
    query = quote(f"{title} {artist}")
    fallback = f"https://open.spotify.com/search/{query}"

    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return fallback

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            token = await _get_spotify_token(client_id, client_secret, client)
            if not token:
                return fallback
            resp = await client.get(
                "https://api.spotify.com/v1/search",
                params={"q": f"{title} {artist}", "type": "track", "limit": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            items = resp.json().get("tracks", {}).get("items", [])
            if items:
                return items[0]["external_urls"]["spotify"]
    except Exception:
        pass

    return fallback


async def _recognize_chunk(
    shazam: Shazam,
    chunk: AudioSegment,
    ts: int,
    sem: asyncio.Semaphore,
) -> tuple[int, dict | None]:
    """Recognize one audio chunk via Shazam, with one retry on failure."""
    buf = io.BytesIO()
    chunk.export(buf, format="mp3")
    audio_bytes = buf.getvalue()

    async with sem:
        for attempt in range(2):
            try:
                result = await asyncio.wait_for(shazam.recognize_song(audio_bytes), timeout=20)
                if result.get("matches") or attempt == 1:
                    return ts, result
                await asyncio.sleep(0.5)
            except Exception:
                if attempt == 1:
                    return ts, None
                await asyncio.sleep(0.5)
    return ts, None


async def identify_songs(
    mp3_path: str,
    start_time: float | None = None,
    end_time: float | None = None,
    on_result: Callable[[dict], Awaitable[None]] | None = None,
    sample_interval: int | None = None,
) -> list[dict]:
    """
    Sample the audio at regular intervals and identify any songs.

    Each sample sends CHUNK_MS (8 s) of audio to Shazam starting at that timestamp.
    Audio between samples is not analyzed.

    Sampling strategy:
      - sample_interval=None (auto): interval = max(30, span // 30), targeting ~30 samples
      - sample_interval=N: use exactly N seconds between samples (minimum 8 s = chunk size)
      - Up to _SHAZAM_CONCURRENCY concurrent Shazam requests

    As each unique song is found, on_result(song_dict) is awaited immediately
    so the caller can stream results to the client incrementally.

    Returns the full list of identified songs (sorted by timestamp).
    """
    audio = AudioSegment.from_mp3(mp3_path)
    duration_s = int(len(audio) / 1000)

    effective_start = int(start_time) if start_time is not None else START_OFFSET_S
    effective_end = int(end_time) if end_time is not None else duration_s

    if effective_start >= effective_end:
        effective_start = int(start_time) if start_time is not None else 0

    span = effective_end - effective_start
    chunk_s = CHUNK_MS // 1000  # 8 s
    if sample_interval is not None:
        # User-specified interval: enforce minimum = chunk size (no point going shorter)
        interval_s = max(chunk_s, sample_interval)
    else:
        # Auto: target ~30 samples, minimum 30 s interval
        interval_s = max(30, span // 30)
    timestamps = list(range(effective_start, effective_end, interval_s))

    shazam = Shazam()
    sem = asyncio.Semaphore(_SHAZAM_CONCURRENCY)

    tasks = []
    for ts in timestamps:
        start_ms = ts * 1000
        end_ms = min(start_ms + CHUNK_MS, len(audio))
        chunk = audio[start_ms:end_ms]
        tasks.append(asyncio.create_task(_recognize_chunk(shazam, chunk, ts, sem)))

    seen: set[tuple[str, str]] = set()
    results: list[dict] = []

    for future in asyncio.as_completed(tasks):
        ts, out = await future
        if not out or not out.get("matches"):
            continue

        track = out.get("track", {})
        title = track.get("title", "")
        artist = track.get("subtitle", "")
        if not title:
            continue

        key = (title.lower(), artist.lower())
        if key in seen:
            continue
        seen.add(key)

        album = ""
        for section in track.get("sections", []):
            for meta in section.get("metadata", []):
                if meta.get("title") == "Album":
                    album = meta.get("text", "")
                    break
            if album:
                break

        images = track.get("images", {})
        cover_url = images.get("coverarthq") or images.get("coverart", "")

        spotify_url = await _get_spotify_url(title, artist)

        song = {
            "timestamp_s": ts,
            "title": title,
            "artist": artist,
            "album": album,
            "cover_url": cover_url,
            "spotify_url": spotify_url,
        }
        results.append(song)

        if on_result:
            await on_result(song)

    results.sort(key=lambda s: s["timestamp_s"])
    return results
