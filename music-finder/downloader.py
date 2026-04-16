import os
import tempfile
import yt_dlp


def download_audio(
    url: str,
    start_time: float | None = None,
    end_time: float | None = None,
    on_progress: callable | None = None,
) -> tuple[str, str, str]:
    """
    Download audio from a video URL using yt-dlp.

    If start_time and/or end_time are given, only that segment is downloaded.
    on_progress(percent: int) is called periodically with download progress 0-100.

    Returns:
        (tmp_dir, mp3_path, video_title)

    Raises:
        ValueError: if the video cannot be downloaded (private, geo-blocked, etc.)
    """
    tmp = tempfile.mkdtemp()

    def _hook(d):
        if on_progress is None:
            return
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                on_progress(int(downloaded / total * 100))
        elif d["status"] == "finished":
            on_progress(100)

    ydl_opts = {
        # Prefer a single-file audio stream to avoid slow DASH multi-fragment downloads
        "format": "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
        "noplaylist": True,  # never download an entire playlist, just the single video
        "outtmpl": os.path.join(tmp, "%(title)s.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "concurrent_fragment_downloads": 4,
        "progress_hooks": [_hook],
    }

    if start_time is not None or end_time is not None:
        try:
            ydl_opts["download_ranges"] = yt_dlp.utils.download_range_func(
                None,
                [[start_time or 0, end_time or float("inf")]],
            )
            ydl_opts["force_keyframes_at_cuts"] = True
        except AttributeError:
            pass  # older yt-dlp — fall back to full download

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get("title", "Unknown")
    except yt_dlp.utils.DownloadError as e:
        raise ValueError(str(e)) from e

    mp3_files = [f for f in os.listdir(tmp) if f.endswith(".mp3")]
    if not mp3_files:
        raise ValueError("Audio extraction failed — ffmpeg may not be installed.")

    return tmp, os.path.join(tmp, mp3_files[0]), title
