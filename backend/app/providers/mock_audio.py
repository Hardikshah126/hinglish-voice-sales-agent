"""Mock STT / TTS providers.

MockTTS returns a real, playable WAV made of short tone bursts (one per word) so the UI
audio player works without any API key. MockSTT cannot transcribe: it returns a canned
Hinglish phrase and is clearly flagged as mock throughout the API and UI.
"""

import hashlib
import io
import math
import struct
import time
import wave

from app.providers.base import STTProvider, STTResult, TTSProvider, TTSResult

CANNED_TRANSCRIPTS = (
    "Hum abhi Excel pe leads manage karte hain.",
    "Price toh kaafi zyada lag raha hai yaar.",
    "Hum Zoho CRM use kar rahe hain already.",
    "Mujhe FlowDesk ka demo dekhna hai.",
)

SAMPLE_RATE = 8000


class MockSTTProvider(STTProvider):
    name = "mock"
    is_mock = True

    def transcribe(self, audio: bytes, filename: str, content_type: str) -> STTResult:
        start = time.perf_counter()
        idx = int(hashlib.sha256(audio).hexdigest()[:8], 16) % len(CANNED_TRANSCRIPTS)
        text = CANNED_TRANSCRIPTS[idx]
        return STTResult(
            text=text, latency_ms=(time.perf_counter() - start) * 1000, model="mock-stt"
        )


class MockTTSProvider(TTSProvider):
    name = "mock"
    is_mock = True

    def synthesize(self, text: str) -> TTSResult:
        start = time.perf_counter()
        frames = bytearray()
        for i, _word in enumerate(text.split()[:60]):
            freq = 180 + (i % 5) * 30
            burst = int(SAMPLE_RATE * 0.07)
            for n in range(burst):
                envelope = math.sin(math.pi * n / burst)
                sample = int(6000 * envelope * math.sin(2 * math.pi * freq * n / SAMPLE_RATE))
                frames += struct.pack("<h", sample)
            frames += b"\x00\x00" * int(SAMPLE_RATE * 0.04)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(bytes(frames))
        return TTSResult(
            audio=buf.getvalue(),
            content_type="audio/wav",
            extension="wav",
            latency_ms=(time.perf_counter() - start) * 1000,
            model="mock-tts",
        )
