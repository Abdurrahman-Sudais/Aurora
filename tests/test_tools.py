from datetime import datetime, timedelta

import pytest

from aurora import config, tools


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NOTES_DIR", tmp_path / "notes")
    monkeypatch.setattr(tools, "reminders", tools.ReminderStore(tmp_path / "reminders.json"))
    started = []
    monkeypatch.setattr(tools.os, "startfile", lambda p: started.append(str(p)), raising=False)
    return started


def test_notes_roundtrip_and_no_overwrite():
    assert "shopping-list" in tools.create_note("milk, eggs", name="Shopping List!")
    assert "shopping-list-2" in tools.create_note("bread", name="Shopping List!")
    assert "milk, eggs" in tools.read_note("shopping")
    assert "bread" in tools.read_note()  # most recent


def test_read_note_errors():
    with pytest.raises(tools.ToolError):
        tools.read_note()
    tools.create_note("x", name="alpha")
    with pytest.raises(tools.ToolError):
        tools.read_note("zzz")


def test_reminder_fires_once_when_due():
    tools.set_reminder("stretch", (datetime.now() + timedelta(minutes=5)).isoformat())
    assert tools.reminders.pop_due(datetime.now()) == []
    due = tools.reminders.pop_due(datetime.now() + timedelta(minutes=6))
    assert [r["text"] for r in due] == ["stretch"]
    assert tools.reminders.pop_due(datetime.now() + timedelta(minutes=7)) == []


def test_reminder_rejects_past_and_garbage():
    with pytest.raises(tools.ToolError):
        tools.set_reminder("x", (datetime.now() - timedelta(minutes=1)).isoformat())
    with pytest.raises(tools.ToolError):
        tools.set_reminder("x", "tomorrow-ish")


def test_open_file_finds_by_partial_name_and_opens(tmp_path, monkeypatch, isolated_data):
    docs = tmp_path / "home" / "Documents"
    docs.mkdir(parents=True)
    (docs / "Budget 2026.xlsx").write_text("x")
    monkeypatch.setattr(tools.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    assert "Budget 2026.xlsx" in tools.open_file("budget")
    assert isolated_data == [str(docs / "Budget 2026.xlsx")]


def test_open_file_refuses_programs(tmp_path, monkeypatch, isolated_data):
    desktop = tmp_path / "home" / "Desktop"
    desktop.mkdir(parents=True)
    (desktop / "installer.exe").write_text("x")
    monkeypatch.setattr(tools.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    with pytest.raises(tools.ToolError):
        tools.open_file("installer")
    assert isolated_data == []


def test_open_file_opens_known_folder(tmp_path, monkeypatch, isolated_data):
    (tmp_path / "home" / "Downloads").mkdir(parents=True)
    monkeypatch.setattr(tools.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    tools.open_file("my downloads folder")
    assert isolated_data == [str(tmp_path / "home" / "Downloads")]


def test_open_app_alias_and_unknown(monkeypatch, isolated_data):
    monkeypatch.setattr(tools, "_start_menu_shortcuts", lambda: [])
    monkeypatch.setattr(tools, "_start_apps", lambda: [])
    tools.open_app("Notepad")
    assert isolated_data == ["notepad.exe"]
    with pytest.raises(tools.ToolError):
        tools.open_app("definitely-not-an-app-xyz")
    with pytest.raises(tools.ToolError):  # explicit paths are refused
        tools.open_app("C:\\Windows\\System32\\whoami.exe")


def test_open_app_prefers_exact_shortcut(tmp_path, monkeypatch, isolated_data):
    shortcuts = [("Spotify Uninstall", tmp_path / "u.lnk"), ("Spotify Helper Tool", tmp_path / "h.lnk"),
                 ("Spotify", tmp_path / "s.lnk")]
    monkeypatch.setattr(tools, "_start_menu_shortcuts", lambda: shortcuts)
    tools.open_app("spotify")
    assert isolated_data == [str(tmp_path / "s.lnk")]


def test_execute_tool_never_raises():
    assert tools.execute_tool("nope", {}) == ("Unknown tool: nope", True)
    out, is_error = tools.execute_tool("create_note", {"wrong_arg": 1})
    assert is_error and "create_note failed" in out
    out, is_error = tools.execute_tool("get_datetime", {})
    assert not is_error and str(datetime.now().year) in out


def test_tool_schemas_match_functions():
    import inspect

    assert {t["name"] for t in tools.TOOLS} == set(tools.TOOL_FUNCS)
    for t in tools.TOOLS:
        params = set(inspect.signature(tools.TOOL_FUNCS[t["name"]]).parameters)
        assert set(t["input_schema"]["properties"]) == params, t["name"]
