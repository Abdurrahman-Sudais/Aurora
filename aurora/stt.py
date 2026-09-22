"""Push-to-talk recording and local speech-to-text (faster-whisper)."""
import time

import keyboard
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from aurora import config

MIN_SECONDS = 0.3  # ignore accidental taps


class SpeechToText:
    def __init__(self, model_name: str = config.WHISPER_MODEL):
        # int8 on CPU: small download, no GPU needed, fast enough for short commands.
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")

    def record(self, hotkey: str = config.HOTKEY) -> np.ndarray:
        """Block until `hotkey` is pressed, record while it is held, return mono float32 audio."""
        keyboard.wait(hotkey)
        chunks: list[np.ndarray] = []

        def on_audio(indata, frames, time_info, status):
            chunks.append(indata.copy())

        with sd.InputStream(
            samplerate=config.SAMPLE_RATE, channels=1, dtype="float32", callback=on_audio
        ):
            while keyboard.is_pressed(hotkey):
                time.sleep(0.02)

        if not chunks:
            return np.zeros(0, dtype="float32")
        return np.concatenate(chunks).flatten()

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < MIN_SECONDS * config.SAMPLE_RATE:
            return ""
        # vad_filter drops silence, which also stops Whisper hallucinating text on quiet clips.
        segments, _ = self._model.transcribe(
            audio, language="en", beam_size=1, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()
