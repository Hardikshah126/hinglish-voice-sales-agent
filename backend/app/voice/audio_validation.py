"""Validation of uploaded audio before it is sent to a (billable) STT provider."""

from dataclasses import dataclass

from app.core.errors import AudioTooLargeError, InvalidAudioError, UnsupportedAudioError

# content-type (without parameters) -> filename extension
SUPPORTED_TYPES = {
    "audio/webm": "webm",
    "video/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/ogg": "ogg",
}

MIN_AUDIO_BYTES = 200


@dataclass(frozen=True)
class ValidatedAudio:
    content_type: str
    extension: str

    @property
    def filename(self) -> str:
        return f"audio.{self.extension}"


def _sniff(data: bytes) -> str | None:
    """Identify the container from magic bytes. Returns an extension or None."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    return None


def validate_audio(data: bytes, content_type: str | None, max_bytes: int) -> ValidatedAudio:
    if len(data) > max_bytes:
        raise AudioTooLargeError(f"Audio exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    if len(data) < MIN_AUDIO_BYTES:
        raise InvalidAudioError()
    base_type = (content_type or "").split(";")[0].strip().lower()
    declared = SUPPORTED_TYPES.get(base_type)
    if declared is None:
        raise UnsupportedAudioError()
    sniffed = _sniff(data)
    if sniffed is None:
        raise InvalidAudioError()
    # Trust the real container over the declared type (browsers label some containers oddly).
    return ValidatedAudio(
        content_type=f"audio/{sniffed}" if sniffed != "m4a" else "audio/mp4", extension=sniffed
    )
