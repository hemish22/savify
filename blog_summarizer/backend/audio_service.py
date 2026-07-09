"""
Audio download service.
Downloads audio from YouTube/Instagram videos using yt-dlp.
"""

import os
import tempfile
import uuid
import subprocess
import shutil


# Temporary directory for downloaded audio files
TEMP_DIR = os.path.join(tempfile.gettempdir(), "blog_summarizer_audio")
os.makedirs(TEMP_DIR, exist_ok=True)


def download_audio(url: str) -> str:
    """
    Download audio from a video URL using yt-dlp.

    Args:
        url: YouTube or Instagram video URL.

    Returns:
        Path to the downloaded .wav file.

    Raises:
        RuntimeError: If download fails.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        )

    output_path = os.path.join(TEMP_DIR, f"{uuid.uuid4().hex}.wav")

    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "--output", output_path.replace(".wav", ".%(ext)s"),
        "--quiet",
        "--no-warnings",
        "--socket-timeout", "30",
    ]

    # Instagram increasingly requires login — pass cookies if configured.
    # Only for IG URLs so YouTube downloads stay cookie-free.
    if "instagram.com" in url:
        cookies_browser = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "")
        cookies_file = os.getenv("YTDLP_COOKIES_FILE", "")
        if cookies_browser:
            cmd += ["--cookies-from-browser", cookies_browser]
        elif cookies_file and os.path.exists(cookies_file):
            cmd += ["--cookies", cookies_file]

    cmd.append(url)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 min max for download
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "login required" in error_msg or "rate-limit reached" in error_msg:
                raise RuntimeError(
                    "Instagram wants a login for this content. Set "
                    "YTDLP_COOKIES_FROM_BROWSER (e.g. 'chrome') in .env so "
                    "yt-dlp can use your browser's Instagram session."
                )
            if "Private video" in error_msg or "Sign in" in error_msg:
                raise RuntimeError("This video is private or requires login.")
            if "not a valid URL" in error_msg:
                raise RuntimeError(f"Invalid video URL: {url}")
            raise RuntimeError(f"yt-dlp failed: {error_msg[:300]}")

        # yt-dlp may create the file with a slightly different name
        if not os.path.exists(output_path):
            # Look for any wav file in temp dir with our uuid
            base = output_path.replace(".wav", "")
            for f in os.listdir(TEMP_DIR):
                if f.startswith(os.path.basename(base)):
                    output_path = os.path.join(TEMP_DIR, f)
                    break

        if not os.path.exists(output_path):
            raise RuntimeError("Audio file was not created. Download may have failed.")

        # Verify file is not empty
        if os.path.getsize(output_path) < 1000:
            cleanup_audio(output_path)
            raise RuntimeError("Downloaded audio file is too small or corrupted.")

        # ── Convert to 16kHz mono WAV for faster Whisper processing ──
        optimized_path = output_path.replace(".wav", "_16k.wav")
        try:
            conv_result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", output_path,
                    "-ar", "16000",   # 16kHz sample rate (Whisper native)
                    "-ac", "1",       # mono
                    "-c:a", "pcm_s16le",
                    optimized_path,
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if conv_result.returncode == 0 and os.path.exists(optimized_path):
                cleanup_audio(output_path)  # Remove original
                output_path = optimized_path
                print(f"✅ Audio converted to 16kHz mono ({os.path.getsize(output_path) // 1024}KB)")
        except Exception:
            pass  # If conversion fails, use original file

        return output_path

    except subprocess.TimeoutExpired:
        raise RuntimeError("Audio download timed out (>2 minutes).")
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to download audio: {str(e)}")


def cleanup_audio(file_path: str) -> None:
    """Remove a temporary audio file."""
    try:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
    except OSError:
        pass


def cleanup_all() -> None:
    """Remove all temporary audio files."""
    try:
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)
            os.makedirs(TEMP_DIR, exist_ok=True)
    except OSError:
        pass
