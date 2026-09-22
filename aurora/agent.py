"""The LLM brain: sends the transcript to Claude, runs any tool calls locally, returns spoken text."""
from datetime import datetime

import anthropic

from aurora import config
from aurora.tools import TOOLS, execute_tool

SYSTEM_PROMPT = """\
You are Aurora, a voice assistant running on the user's Windows PC. Your reply is read aloud \
by a text-to-speech engine, so write the way people talk: one or two short sentences, no \
markdown, lists, emoji or URLs.

Use your tools to act on the PC. After a tool result, confirm briefly what happened, or say \
plainly what went wrong. Never claim you did something a tool did not confirm.

The user's words come from speech recognition and may contain mistakes; infer what they meant. \
If a request is genuinely ambiguous, ask one short question. You have no live data such as \
weather or news; say so and offer to open a web search instead.\
"""


class Agent:
    def __init__(self) -> None:
        self.client = anthropic.Anthropic()
        self.messages: list[dict] = []

    def respond(self, user_text: str) -> str:
        """Handle one spoken command and return the text to say back."""
        checkpoint = len(self.messages)
        self._trim()
        self.messages.append({"role": "user", "content": user_text})
        try:
            return self._run_loop()
        except Exception:
            # Don't leave a dangling tool_use in the history; the next turn would be rejected.
            del self.messages[checkpoint:]
            raise

    def _run_loop(self) -> str:
        for _ in range(config.MAX_TOOL_STEPS):
            response = self.client.messages.create(
                model=config.LLM_MODEL,
                max_tokens=config.LLM_MAX_TOKENS,
                system=f"{SYSTEM_PROMPT}\n\nCurrent local time: {datetime.now():%A, %Y-%m-%d %H:%M}.",
                tools=TOOLS,
                output_config={"effort": config.LLM_EFFORT},
                messages=self.messages,
            )
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "Sorry, I can't help with that."
            if response.stop_reason != "tool_use":
                text = " ".join(b.text for b in response.content if b.type == "text").strip()
                return text or "Done."

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    output, is_error = execute_tool(block.name, block.input)
                    print(f"  [tool] {block.name}({block.input}) -> {output}")
                    results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": output,
                        "is_error": is_error,
                    })
            self.messages.append({"role": "user", "content": results})

        return "Sorry, I got stuck on that one."

    def _trim(self) -> None:
        """Cap history length, cutting only at a fresh user utterance so tool pairs stay intact."""
        while len(self.messages) > config.MAX_HISTORY_MESSAGES:
            cut = next(
                (i for i in range(1, len(self.messages))
                 if self.messages[i]["role"] == "user" and isinstance(self.messages[i]["content"], str)),
                None,
            )
            if cut is None:
                break
            del self.messages[:cut]
