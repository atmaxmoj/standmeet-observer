"""Speech-to-text using faster-whisper (local, cross-platform)."""

import logging

from faster_whisper import WhisperModel

from audio_source.config import WHISPER_COMPUTE_TYPE, WHISPER_LANGUAGE, WHISPER_MODEL

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    """Lazy-load whisper model (downloads on first use)."""
    global _model
    if _model is None:
        logger.info(
            "loading whisper model=%s compute_type=%s (first load may download)",
            WHISPER_MODEL, WHISPER_COMPUTE_TYPE,
        )
        _model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type=WHISPER_COMPUTE_TYPE,
        )
        logger.info("whisper model loaded")
    return _model


def transcribe(audio_path: str) -> dict:
    """
    Transcribe a WAV file. Returns dict with:
      - text: full transcription
      - language: detected language
      - segments: list of {start, end, text} dicts
    """
    model = get_model()
    logger.debug("transcribing %s", audio_path)

    kwargs = {"word_timestamps": True}
    if WHISPER_LANGUAGE:
        kwargs["language"] = WHISPER_LANGUAGE

    segments_iter, info = model.transcribe(audio_path, **kwargs)

    segments = []
    full_text_parts = []
    for seg in segments_iter:
        segments.append({
            "start": round(seg.start, 2),
            "end": round(seg.end, 2),
            "text": seg.text.strip(),
        })
        full_text_parts.append(seg.text.strip())

    full_text = " ".join(full_text_parts)
    logger.info(
        "transcribed %s: lang=%s prob=%.2f segments=%d chars=%d",
        audio_path, info.language, info.language_probability,
        len(segments), len(full_text),
    )
    logger.debug("transcription: %s", full_text[:200])

    return {
        "text": full_text,
        "language": info.language,
        "language_probability": info.language_probability,
        "segments": segments,
    }


def is_hallucination(result: dict) -> bool:
    """Detect whisper hallucination patterns (e.g. 'You You You You...')."""
    text = result["text"].strip()
    if not text:
        return False

    # Low language probability often indicates noise
    if result["language_probability"] < 0.5:
        logger.debug("hallucination: low lang prob %.2f", result["language_probability"])
        return True

    # Repetitive text: if one word makes up >60% of all words, it's likely hallucination
    words = text.lower().split()
    if len(words) >= 3:
        from collections import Counter
        counts = Counter(words)
        most_common_count = counts.most_common(1)[0][1]
        if most_common_count / len(words) > 0.6:
            logger.debug("hallucination: repetitive text '%s'", text[:80])
            return True

    return False
