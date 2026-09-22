"""Local actions Aurora can perform on the user's PC (Windows).

v1 is deliberately non-destructive (PRD §9): nothing here deletes, overwrites, or runs
arbitrary commands. Model-supplied strings are never passed through a shell.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional, TypeVar
from urllib.parse import quote_plus

from aurora import config

T = TypeVar("T")


class ToolError(Exception):
    """A failure whose message is safe and useful to hand back to the model."""


# --------------------------------------------------------------------------- helpers


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _best_match(query: str, candidates: Iterable[tuple[str, T]]) -> Optional[T]:
    """Pick the candidate whose name equals, else contains, the query (shortest name wins)."""
    q = _norm(query)
    best: Optional[tuple[tuple[int, int], T]] = None
    for name, payload in candidates:
        n = _norm(name)
        if not q or q not in n or "uninstall" in n:
            continue
        rank = (0 if q == n else 1, len(n))
        if best is None or rank < best[0]:
            best = (rank, payload)
    return best[1] if best else None


def _fmt_dt(dt: datetime) -> str:
    return f"{dt:%A, %B} {dt.day} at {dt.strftime('%I:%M %p').lstrip('0')}"


# --------------------------------------------------------------------------- open_app

APP_ALIASES = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "file explorer": "explorer.exe",
    "explorer": "explorer.exe",
    "task manager": "taskmgr.exe",
    "command prompt": "cmd.exe",
    "terminal": "wt.exe",
    "powershell": "powershell.exe",
    "settings": "ms-settings:",
}


def _start_menu_shortcuts() -> Iterable[tuple[str, Path]]:
    for var in ("ProgramData", "APPDATA"):
        if var in os.environ:
            root = Path(os.environ[var]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
            for lnk in root.rglob("*.lnk"):
                yield lnk.stem, lnk


def _start_apps() -> list[tuple[str, str]]:
    """Installed apps incl. Microsoft Store ones, as (name, AppID). Slow (~1s), so used last."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json"],
            capture_output=True, text=True, timeout=20,
        ).stdout
        apps = json.loads(out) if out.strip() else []
    except (subprocess.SubprocessError, json.JSONDecodeError):
        return []
    if isinstance(apps, dict):
        apps = [apps]
    return [(a["Name"], a["AppID"]) for a in apps if a.get("Name") and a.get("AppID")]


def open_app(app_name: str) -> str:
    alias = APP_ALIASES.get(app_name.strip().lower())
    if alias:
        os.startfile(alias)
        return f"Opened {app_name}."

    shortcut = _best_match(app_name, _start_menu_shortcuts())
    if shortcut:
        os.startfile(shortcut)
        return f"Opened {shortcut.stem}."

    app_id = _best_match(app_name, _start_apps())
    if app_id:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"])
        return f"Opened {app_name}."

    # Last resort: a bare program name on PATH. Paths are refused so the model can't
    # point us at an arbitrary executable.
    if not re.search(r"[\\/:]", app_name):
        exe = shutil.which(app_name)
        if exe:
            subprocess.Popen([exe])
            return f"Opened {app_name}."

    raise ToolError(f"Couldn't find an app called '{app_name}'.")


# --------------------------------------------------------------------------- open_file

BLOCKED_SUFFIXES = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".lnk", ".reg", ".dll", ".jar",
}
SKIP_DIRS = {"node_modules", ".git", ".venv", "__pycache__", "AppData"}
SEARCH_DEPTH = 4
SEARCH_LIMIT = 30000  # max entries examined, keeps a huge Documents folder from stalling a command


def _known_folders() -> dict[str, Path]:
    home = Path.home()
    return {
        "downloads": home / "Downloads",
        "documents": home / "Documents",
        "desktop": home / "Desktop",
        "pictures": home / "Pictures",
        "music": home / "Music",
        "videos": home / "Videos",
        "notes": config.NOTES_DIR,
    }


def _search_paths(query: str) -> Optional[Path]:
    roots = [config.NOTES_DIR] + [_known_folders()[k] for k in ("desktop", "documents", "downloads")]
    candidates: list[tuple[str, Path]] = []
    seen = 0
    for root in roots:
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS and not d.startswith(".")
                and len(Path(dirpath).parts) - base_depth < SEARCH_DEPTH
            ]
            for entry in dirnames + filenames:
                p = Path(dirpath) / entry
                candidates.append((p.stem if p.is_file() else p.name, p))
                candidates.append((p.name, p))
            seen += len(dirnames) + len(filenames)
            if seen > SEARCH_LIMIT:
                break
    return _best_match(query, candidates)


def open_file(name: str) -> str:
    """Open a file or folder in its default app. Searches Desktop, Documents, Downloads, notes."""
    folder = _known_folders().get(re.sub(r"^(my|the)\s+|\s+folder$", "", name.strip().lower()))
    if folder and folder.is_dir():
        os.startfile(folder)
        return f"Opened your {folder.name} folder."

    path: Optional[Path] = None
    raw = Path(name)
    if raw.is_absolute() and raw.exists():
        # Only paths inside the user's home directory.
        if Path.home() in raw.resolve().parents:
            path = raw.resolve()
    else:
        path = _search_paths(name)

    if path is None:
        raise ToolError(f"Couldn't find a file or folder called '{name}'.")
    if path.is_file() and path.suffix.lower() in BLOCKED_SUFFIXES:
        raise ToolError(f"'{path.name}' is a program or script, so I won't open it as a file.")
    os.startfile(path)
    return f"Opened {path.name}."


# --------------------------------------------------------------------------- search_web


def search_web(query: str) -> str:
    webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
    return f"Opened a web search for '{query}'."


# --------------------------------------------------------------------------- notes


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "note"


def create_note(content: str, name: Optional[str] = None) -> str:
    config.NOTES_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slug(name) if name else datetime.now().strftime("note-%Y%m%d-%H%M%S")
    path = config.NOTES_DIR / f"{slug}.txt"
    n = 2
    while path.exists():  # never overwrite an existing note
        path = config.NOTES_DIR / f"{slug}-{n}.txt"
        n += 1
    path.write_text(content, encoding="utf-8")
    return f"Saved note '{path.stem}'."


def read_note(name: Optional[str] = None) -> str:
    notes = sorted(config.NOTES_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not notes:
        raise ToolError("There are no saved notes yet.")
    note = _best_match(name, ((p.stem, p) for p in notes)) if name else notes[0]
    if note is None:
        raise ToolError(f"No note matching '{name}'. Available: {', '.join(p.stem for p in notes[:10])}.")
    text = note.read_text(encoding="utf-8")
    return f"Note '{note.stem}':\n{text[:2000]}"


# --------------------------------------------------------------------------- reminders


class ReminderStore:
    """Reminders persisted to a JSON file; a background thread announces them when due."""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(items, indent=2), encoding="utf-8")

    def add(self, text: str, due: datetime) -> None:
        with self._lock:
            items = self._load()
            items.append({"id": uuid.uuid4().hex[:8], "text": text, "due": due.isoformat()})
            self._save(items)

    def pop_due(self, now: datetime) -> list[dict]:
        with self._lock:
            items = self._load()
            due = [i for i in items if datetime.fromisoformat(i["due"]) <= now]
            if due:
                self._save([i for i in items if i not in due])
            return due


reminders = ReminderStore(config.REMINDERS_FILE)


def start_reminder_loop(on_due: Callable[[str], None], poll_seconds: float = 1.0) -> threading.Thread:
    def loop():
        while True:
            for item in reminders.pop_due(datetime.now()):
                on_due(item["text"])
            time.sleep(poll_seconds)

    thread = threading.Thread(target=loop, name="aurora-reminders", daemon=True)
    thread.start()
    return thread


def set_reminder(text: str, time: str) -> str:  # noqa: A002 - "time" is the tool's parameter name
    try:
        due = datetime.fromisoformat(time)
    except ValueError:
        raise ToolError(f"'{time}' isn't a valid ISO 8601 date-time like 2026-09-21T15:30.")
    if due.tzinfo is not None:
        due = due.astimezone().replace(tzinfo=None)
    if due <= datetime.now():
        raise ToolError("That time is already in the past.")
    reminders.add(text, due)
    return f"Reminder set for {_fmt_dt(due)}: {text}"


# --------------------------------------------------------------------------- time


def get_datetime() -> str:
    now = datetime.now()
    return f"{now:%A, %B} {now.day}, {now.year}, {now.strftime('%I:%M %p').lstrip('0')}"


# --------------------------------------------------------------------------- registry

TOOL_FUNCS: dict[str, Callable[..., str]] = {
    "open_app": open_app,
    "open_file": open_file,
    "search_web": search_web,
    "create_note": create_note,
    "read_note": read_note,
    "set_reminder": set_reminder,
    "get_datetime": get_datetime,
}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    _tool(
        "open_app",
        "Launch an installed application on the PC by name, e.g. Spotify, Chrome, Notepad, Calculator.",
        {"app_name": {"type": "string", "description": "The app's common name."}},
        ["app_name"],
    ),
    _tool(
        "open_file",
        "Open a file or folder in its default app. Searches Desktop, Documents, Downloads and "
        "saved notes by name. Also opens well-known folders such as 'downloads' or 'documents'. "
        "Cannot open programs or scripts.",
        {"name": {"type": "string", "description": "File or folder name, partial names are fine."}},
        ["name"],
    ),
    _tool(
        "search_web",
        "Open the default browser with a web search for the query.",
        {"query": {"type": "string"}},
        ["query"],
    ),
    _tool(
        "create_note",
        "Save a new text note. Never overwrites existing notes.",
        {
            "content": {"type": "string", "description": "The note text."},
            "name": {"type": "string", "description": "Optional short title used as the filename."},
        },
        ["content"],
    ),
    _tool(
        "read_note",
        "Read back a saved note. With no name, returns the most recent note.",
        {"name": {"type": "string", "description": "Optional note name; partial names are fine."}},
        [],
    ),
    _tool(
        "set_reminder",
        "Set a reminder that Aurora will announce out loud at the given local time. "
        "Convert relative times ('in 10 minutes', 'tomorrow at 9') using the current time from the system prompt.",
        {
            "text": {"type": "string", "description": "What to remind the user about."},
            "time": {"type": "string", "description": "Local date-time in ISO 8601, e.g. 2026-09-21T15:30."},
        },
        ["text", "time"],
    ),
    _tool(
        "get_datetime",
        "Get the current local date and time.",
        {},
        [],
    ),
]


def execute_tool(name: str, args: dict) -> tuple[str, bool]:
    """Run a tool. Returns (result_text, is_error) for feeding back to the model."""
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return f"Unknown tool: {name}", True
    try:
        return fn(**args), False
    except ToolError as e:
        return str(e), True
    except Exception as e:  # a bad tool call must never crash the voice loop
        return f"{name} failed: {e}", True
