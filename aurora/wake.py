"""Hands-free activation: wait for a wake word, then record until the user stops talking."""
import queue
import threading
import winsound
from pathlib import Path

import numpy as np
import openwakeword
import sounddevice as sd
from openwakeword.model import Model
from openwakeword.vad import VAD

from aurora import config, tts

RATE = config.SAMPLE_RATE
WAKE_BLOCK = 1280  # 80 ms, the frame size openWakeWord expects
VAD_BLOCK = 480  # 30 ms, the frame size the VAD expects
SPEECH_PROB = 0.5
# Ignore the VAD right after waking: the tail of the wake phrase would otherwise count as
# "the user started talking", and the pause before the real command as "the user finished".
WARMUP_SECONDS = 0.5


def _ensure_models() -> None:
    models = Path(openwakeword.__file__).parent / "resources" / "models"
    needed = ["embedding_model.onnx", "melspectrogram.onnx", "silero_vad.onnx"]
    if config.WAKE_WORD.endswith(".onnx"):
        if not Path(config.WAKE_WORD).exists():
            raise FileNotFoundError(f"Custom wake word model not found: {config.WAKE_WORD}")
    else:
        needed.append(f"{config.WAKE_WORD}_v0.1.onnx")
    if not all((models / n).exists() for n in needed):
        openwakeword.utils.download_models()  # small (~10 MB), one-time


def wake_phrase() -> str:
    return Path(config.WAKE_WORD).stem.replace("_", " ")


class WakeListener:
    """Owns the always-open microphone stream. Use as a context manager."""

    def __init__(self) -> None:
        _ensure_models()
        custom = config.WAKE_WORD.endswith(".onnx")
        self._key = Path(config.WAKE_WORD).stem if custom else config.WAKE_WORD
        self._model = Model(wakeword_models=[config.WAKE_WORD], inference_framework="onnx")
        self._vad = VAD()
        self._blocks: queue.Queue[np.ndarray] = queue.Queue(maxsize=200)
        self._stream = sd.InputStream(
            samplerate=RATE, channels=1, dtype="int16", blocksize=WAKE_BLOCK, callback=self._on_audio
        )

    def __enter__(self) -> "WakeListener":
        self._stream.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stream.stop()
        self._stream.close()

    def _on_audio(self, indata, frames, time_info, status) -> None:
        try:
            self._blocks.put_nowait(indata[:, 0].copy())
        except queue.Full:  # consumer is busy (e.g. waiting on the LLM); drop, don't grow
            pass

    def _next_block(self, timeout: float = 0.5):
        try:
            return self._blocks.get(timeout=timeout)
        except queue.Empty:
            return None

    def _drain(self) -> None:
        while self._next_block(timeout=0) is not None:
            pass

    def wait_for_wake(self) -> None:
        """Block until the wake word is heard."""
        self._drain()  # anything captured while she was busy or talking is stale
        self._model.reset()
        while True:
            block = self._next_block()  # short timeout keeps Ctrl+C responsive on Windows
            if block is None or tts.speaking.is_set():
                continue  # ignore her own voice (e.g. a reminder going off)
            if self._model.predict(block)[self._key] >= config.WAKE_THRESHOLD:
                return

    def record_command(self) -> np.ndarray:
        """Record after a wake until the speaker pauses. Returns float32 audio, empty if silent."""
        if config.WAKE_CHIME:
            threading.Thread(target=winsound.Beep, args=(1100, 90), daemon=True).start()

        self._vad.reset_states()
        blocks: list[np.ndarray] = []
        pending = np.zeros(0, dtype=np.int16)
        started, silence, elapsed = False, 0.0, 0.0

        while elapsed < config.MAX_COMMAND_SECONDS:
            block = self._next_block(timeout=2.0)
            if block is None:
                break
            blocks.append(block)
            elapsed += len(block) / RATE
            if elapsed < WARMUP_SECONDS:
                continue

            pending = np.concatenate([pending, block])
            while len(pending) >= VAD_BLOCK:
                prob = self._vad.predict(pending[:VAD_BLOCK])
                pending = pending[VAD_BLOCK:]
                if prob >= SPEECH_PROB:
                    started, silence = True, 0.0
                elif started:
                    silence += VAD_BLOCK / RATE

            if started and silence >= config.END_SILENCE:
                break
            if not started and elapsed >= config.NO_SPEECH_TIMEOUT:
                return np.zeros(0, dtype=np.float32)

        if not started:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(blocks).astype(np.float32) / 32768.0
