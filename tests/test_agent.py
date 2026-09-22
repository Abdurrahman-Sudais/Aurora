from types import SimpleNamespace as NS

import pytest

from aurora import agent as agent_mod
from aurora import config


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, **inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


def reply(stop_reason, *blocks):
    return NS(stop_reason=stop_reason, content=list(blocks))


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def make_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(agent_mod, "execute_tool", lambda name, args: (f"ran {name} {args}", False))

    def build(*replies):
        a = agent_mod.Agent()
        a.client = FakeClient(replies)
        return a

    return build


def test_plain_answer(make_agent):
    a = make_agent(reply("end_turn", text("It is sunny.")))
    assert a.respond("hi") == "It is sunny."
    call = a.client.calls[0]
    assert call["model"] == config.LLM_MODEL
    assert call["output_config"] == {"effort": config.LLM_EFFORT}


def test_tool_call_then_final_answer(make_agent):
    a = make_agent(
        reply("tool_use", tool_use("t1", "open_app", app_name="Spotify")),
        reply("end_turn", text("Opened Spotify.")),
    )
    assert a.respond("open spotify") == "Opened Spotify."
    # Second request must carry the assistant tool_use and a matching tool_result.
    sent = a.client.calls[1]["messages"]
    assert sent[-1]["role"] == "user"
    result = sent[-1]["content"][0]
    assert result["tool_use_id"] == "t1" and result["is_error"] is False
    assert "Spotify" in result["content"]


def test_parallel_tool_calls_answered_in_one_message(make_agent):
    a = make_agent(
        reply("tool_use", tool_use("a", "get_datetime"), tool_use("b", "open_app", app_name="x")),
        reply("end_turn", text("ok")),
    )
    a.respond("go")
    results = a.client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b"]


def test_api_error_rolls_back_history(make_agent):
    a = make_agent(
        reply("tool_use", tool_use("t1", "get_datetime")),
        RuntimeError("network down"),
    )
    with pytest.raises(RuntimeError):
        a.respond("what time is it")
    assert a.messages == []  # no dangling tool_use


def test_refusal_and_runaway_loop(make_agent, monkeypatch):
    a = make_agent(reply("refusal"))
    assert "can't help" in a.respond("x")

    monkeypatch.setattr(config, "MAX_TOOL_STEPS", 3)
    b = make_agent(*[reply("tool_use", tool_use(f"t{i}", "get_datetime")) for i in range(3)])
    assert "stuck" in b.respond("loop forever")


def test_trim_cuts_only_at_user_utterances(make_agent, monkeypatch):
    monkeypatch.setattr(config, "MAX_HISTORY_MESSAGES", 4)
    a = make_agent()
    a.messages = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": [tool_use("t1", "get_datetime")]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}]},
        {"role": "assistant", "content": [text("done")]},
        {"role": "user", "content": "two"},
        {"role": "assistant", "content": [text("ok")]},
    ]
    a._trim()
    assert a.messages[0] == {"role": "user", "content": "two"}
