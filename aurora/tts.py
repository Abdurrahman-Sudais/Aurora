"""Text-to-speech using the offline Windows voices via pyttsx3."""
import threading

import pyttsx3

from aurora import config

# Reminders speak from a background thread; SAPI can't handle two utterances at once.
_speak_lock = threading.Lock()

# Set while Aurora is talking, so the wake-word listener can ignore her own voice.
speaking = threading.Event()


def speak(text: str) -> None:
    if not text.strip():
        return
    with _speak_lock:
        speaking.set()
        # A fresh engine per call avoids pyttsx3's known "runAndWait hangs on the 2nd call" bug.
        engine = pyttsx3.init()
        try:
            engine.setProperty("rate", config.TTS_RATE)
            if config.TTS_VOICE:
                for voice in engine.getProperty("voices"):
                    if config.TTS_VOICE.lower() in voice.name.lower():
                        engine.setProperty("voice", voice.id)
                        break
            engine.say(text)
            engine.runAndWait()
        finally:
            engine.stop()
            speaking.clear()
