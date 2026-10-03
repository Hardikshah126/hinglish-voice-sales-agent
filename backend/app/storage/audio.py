"""Audio storage abstraction. The MVP stores files on local disk (data/audio).

To move to S3/R2, implement AudioStorage with the same three methods and swap it in
`get_audio_storage`. Nothing else in the app touches the filesystem for audio.
"""

import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import get_settings

_SAFE_KEY = re.compile(r"^[0-9a-f]{32}\.(mp3|wav|webm|ogg|m4a)$")

CONTENT_TYPES = {
    "mp3": "audio/mpeg",
    "wav": "audio/wav",
    "webm": "audio/webm",
    "ogg": "audio/ogg",
    "m4a": "audio/mp4",
}


class AudioStorage(Protocol):
    def save(self, data: bytes, extension: str) -> str:
        """Persist audio and return an opaque storage key."""

    def url_for(self, key: str) -> str:
        """Public URL (relative to the API) from which the audio can be fetched."""

    def local_path(self, key: str) -> Path | None:
        """Filesystem path for the key if it exists and is valid, else None."""


class LocalAudioStorage:
    def __init__(self, directory: Path):
        self._dir = directory

    def save(self, data: bytes, extension: str) -> str:
        self._dir.mkdir(parents=True, exist_ok=True)
        key = f"{uuid.uuid4().hex}.{extension}"
        (self._dir / key).write_bytes(data)
        return key

    def url_for(self, key: str) -> str:
        return f"/api/audio/{key}"

    def local_path(self, key: str) -> Path | None:
        if not _SAFE_KEY.match(key):  # blocks path traversal and arbitrary filenames
            return None
        path = self._dir / key
        return path if path.is_file() else None


@lru_cache
def get_audio_storage() -> AudioStorage:
    return LocalAudioStorage(get_settings().audio_dir)
