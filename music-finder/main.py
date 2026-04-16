import asyncio
import json
import shutil

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from downloader import download_audio
from recognizer import identify_songs

app = FastAPI(title="Music Finder")
app.mount("/static", StaticFiles(directory="static"), name="static")


class DetectRequest(BaseModel):
    url: str
    start_time: float | None = None
    end_time: float | None = None


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.post("/api/detect")
async def detect(req: DetectRequest):
    """
    Stream progress and results as Server-Sent Events.

    Event types:
      {"type": "status",            "phase": "download"|"analyze", "message": str}
      {"type": "download_progress", "percent": int}
      {"type": "result",            "song": {...}}   — emitted per song as found
      {"type": "done",              "video_title": str, "total": int}
      {"type": "error",             "message": str}
    """
    def _err_stream(message: str):
        async def _gen():
            yield f'data: {json.dumps({"type": "error", "message": message})}\n\n'
        return StreamingResponse(_gen(), media_type="text/event-stream")

    if req.start_time is not None and req.start_time < 0:
        return _err_stream("start_time must be non-negative")
    if req.end_time is not None and req.end_time < 0:
        return _err_stream("end_time must be non-negative")
    if (
        req.start_time is not None
        and req.end_time is not None
        and req.start_time >= req.end_time
    ):
        return _err_stream("start_time must be less than end_time")

    async def event_stream():
        progress_queue: asyncio.Queue[int] = asyncio.Queue()
        result_queue: asyncio.Queue[dict] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def on_progress(pct: int):
            loop.call_soon_threadsafe(progress_queue.put_nowait, pct)

        async def on_result(song: dict):
            await result_queue.put(song)

        def sse(data: dict) -> str:
            return f"data: {json.dumps(data)}\n\n"

        # --- Download phase ---
        yield sse({"type": "status", "phase": "download", "message": "Downloading audio..."})

        download_task = asyncio.create_task(
            asyncio.to_thread(
                download_audio, req.url, req.start_time, req.end_time, on_progress
            )
        )

        while not download_task.done():
            try:
                pct = await asyncio.wait_for(progress_queue.get(), timeout=0.2)
                yield sse({"type": "download_progress", "percent": pct})
            except asyncio.TimeoutError:
                pass

        while not progress_queue.empty():
            yield sse({"type": "download_progress", "percent": progress_queue.get_nowait()})

        try:
            tmp_dir, mp3_path, video_title = download_task.result()
        except Exception as e:
            yield sse({"type": "error", "message": str(e)})
            return

        # --- Analysis phase ---
        yield sse({"type": "status", "phase": "analyze", "message": "Analysing audio..."})

        try:
            analyze_task = asyncio.create_task(
                identify_songs(mp3_path, req.start_time, req.end_time, on_result)
            )

            while not analyze_task.done():
                try:
                    song = await asyncio.wait_for(result_queue.get(), timeout=0.2)
                    yield sse({"type": "result", "song": song})
                except asyncio.TimeoutError:
                    pass

            while not result_queue.empty():
                yield sse({"type": "result", "song": result_queue.get_nowait()})

            songs = analyze_task.result()
            yield sse({"type": "done", "video_title": video_title, "total": len(songs)})

        except Exception as e:
            yield sse({"type": "error", "message": f"Analysis failed: {e}"})
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
