"""Milestone 1: STT + TTS with no LLM. Hold the hotkey, speak, hear it echoed back.

Run from the project root:  .venv\\Scripts\\python -m scripts.echo_test
"""
from aurora import config
from aurora.stt import SpeechToText
from aurora.tts import speak


def main() -> None:
    print(f"Loading '{config.WHISPER_MODEL}'...")
    stt = SpeechToText()
    speak("Echo test ready.")
    print(f"Hold {config.HOTKEY}, speak, release. Ctrl+C to quit.")
    while True:
        text = stt.transcribe(stt.record())
        print(f"heard: {text!r}")
        if text:
            speak(f"You said: {text}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
