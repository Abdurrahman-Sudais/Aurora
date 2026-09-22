"""Central settings. Override any of these via environment variables or a .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Windows without Developer Mode can't symlink; the model cache still works, so hide the warning.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
NOTES_DIR = DATA_DIR / "notes"
REMINDERS_FILE = DATA_DIR / "reminders.json"

# Push-to-talk key (any name/combo the `keyboard` library understands, e.g. "f9", "ctrl+alt+a").
HOTKEY = os.getenv("AURORA_HOTKEY", "f9")

# Speech-to-text (faster-whisper). Models: tiny.en, base.en, small.en, ...
WHISPER_MODEL = os.getenv("AURORA_WHISPER_MODEL", "base.en")
SAMPLE_RATE = 16000

# Hands-free wake word (openWakeWord). Either a pretrained name (hey_jarvis, alexa, hey_mycroft,
# hey_rhasspy) or a path to a custom .onnx model, e.g. models/hey_aurora.onnx.
WAKE_WORD = os.getenv("AURORA_WAKE_WORD", "hey_jarvis")
WAKE_THRESHOLD = float(os.getenv("AURORA_WAKE_THRESHOLD", "0.5"))  # lower = more sensitive
WAKE_CHIME = os.getenv("AURORA_CHIME", "1") == "1"  # short beep when she starts listening
END_SILENCE = 0.9  # seconds of quiet that ends a command
NO_SPEECH_TIMEOUT = 5.0  # give up if nothing is said after waking
MAX_COMMAND_SECONDS = 15.0

# LLM. Effort "low" keeps voice round-trips fast; raise it if answers feel shallow.
LLM_MODEL = os.getenv("AURORA_MODEL", "claude-opus-5")
LLM_EFFORT = os.getenv("AURORA_EFFORT", "low")
LLM_MAX_TOKENS = 4096
MAX_TOOL_STEPS = 6
MAX_HISTORY_MESSAGES = 40

# Text-to-speech (pyttsx3 / Windows SAPI5). Substring of a voice name, e.g. "Zira" or "David".
TTS_VOICE = os.getenv("AURORA_VOICE", "Zira")
TTS_RATE = int(os.getenv("AURORA_TTS_RATE", "185"))
