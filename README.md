# Aurora

Voice-controlled desktop agent (Windows). Hold a key, speak, Aurora acts and talks back.
See `Aurora_PRD_v1.md` for scope.

## Setup

```powershell
py -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then put your ANTHROPIC_API_KEY in .env
```

## Run

```powershell
.\.venv\Scripts\python -m scripts.echo_test   # milestone 1: mic -> Whisper -> speaker, no LLM
.\.venv\Scripts\python -m aurora              # hands-free: say the wake word, then your command
.\.venv\Scripts\python -m aurora --ptt        # push-to-talk instead (hold F9)
.\.venv\Scripts\python -m aurora --text       # type instead of speak (debugging)
.\.venv\Scripts\python -m pytest              # tests (no mic or API key needed)
```

## Tools (v1, all non-destructive)

`open_app`, `open_file`, `search_web`, `create_note`, `read_note`, `set_reminder`, `get_datetime`.
Notes and reminders live in `data/`. Settings are in `aurora/config.py` (override via `.env`).
