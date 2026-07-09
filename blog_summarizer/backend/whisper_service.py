"""
Whisper speech-to-text service.
Uses faster-whisper for optimized CPU transcription (4-10x faster than openai-whisper).
"""

from faster_whisper import WhisperModel

# ──────────────────────────────────────────────
# Model Loading (lazy, cached)
# ──────────────────────────────────────────────

_model = None
MODEL_SIZE = "tiny"  # ~75MB. Options: tiny, base, small, medium, large-v3


def _get_model():
    """Load the faster-whisper model lazily (only on first use)."""
    global _model
    if _model is None:
        print(f"🎙️ Loading faster-whisper '{MODEL_SIZE}' model...")
        _model = WhisperModel(
            MODEL_SIZE,
            device="cpu",
            compute_type="int8",  # Quantized for speed on CPU
        )
        print("✅ Whisper model loaded (faster-whisper, int8)")
    return _model


# ──────────────────────────────────────────────
# Transcription
# ──────────────────────────────────────────────

def transcribe_audio(audio_path: str) -> dict:
    """
    Transcribe an audio file using faster-whisper.

    Args:
        audio_path: Path to audio file (.wav, .mp3, .m4a, etc.)

    Returns:
        dict with keys: text, language

    Raises:
        RuntimeError: If transcription fails.
    """
    try:
        model = _get_model()

        print("🎙️ Transcribing audio with faster-whisper...")
        segments, info = model.transcribe(
            audio_path,
            beam_size=1,         # Greedy decoding = fastest
            best_of=1,
            vad_filter=True,     # Skip silence segments = faster
        )

        # Collect all segment text
        text = " ".join(segment.text.strip() for segment in segments).strip()
        language = info.language or "unknown"

        if not text or len(text) < 20:
            raise RuntimeError(
                "Transcription produced too little text. "
                "The audio may be music-only, silent, or in an unsupported language."
            )

        print(f"✅ Transcribed {len(text)} chars, language: {language}")

        return {
            "text": text,
            "language": language,
        }

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Whisper transcription failed: {str(e)}")
