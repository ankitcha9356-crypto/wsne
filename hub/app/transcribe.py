"""Speech to text with faster-whisper (runs locally, no paid API)."""
import os
import threading

MODEL_NAME = os.getenv("WHISPER_MODEL", "base.en")
_model = None
_lock = threading.Lock()


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


def transcribe(path: str) -> dict:
    """Returns {'text', 'segments': [{'start','end','text'}]}. Raises if Whisper is not installed."""
    global _model
    from faster_whisper import WhisperModel

    with _lock:
        if _model is None:
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        # The prompt nudges Whisper to keep fillers instead of silently cleaning them up.
        segments, _ = _model.transcribe(path, language="en", vad_filter=True,
                                        initial_prompt="Umm, uh, so, like, you know, I mean...")
        segs = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    return {"text": " ".join(s["text"] for s in segs).strip(), "segments": segs}
