"""Aurora's main loop: wait for the wake word (or hotkey), listen, act, answer."""
import argparse
import contextlib
import os
import sys

import anthropic

from aurora import config
from aurora.agent import Agent
from aurora.tools import start_reminder_loop
from aurora.tts import speak

EXIT_PHRASES = {"quit", "exit", "goodbye", "goodbye aurora", "stop listening"}


def main() -> int:
    parser = argparse.ArgumentParser(prog="aurora")
    parser.add_argument("--ptt", action="store_true", help=f"push-to-talk ({config.HOTKEY}) instead of the wake word")
    parser.add_argument("--text", action="store_true", help="type commands instead of using the mic")
    parser.add_argument("--mute", action="store_true", help="print replies instead of speaking them")
    args = parser.parse_args()

    key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
    if not key or key == "your-key-here":
        print(f"No real API key found. Put your ANTHROPIC_API_KEY in {config.ROOT / '.env'} and save the file.")
        return 1

    say = (lambda text: None) if args.mute else speak

    with contextlib.ExitStack() as stack:
        stt = wake = None
        prompt = "Type a command."
        if not args.text:
            from aurora.stt import SpeechToText  # heavy imports; skipped in --text mode

            print(f"Loading speech model '{config.WHISPER_MODEL}' (first run downloads it)...")
            stt = SpeechToText()
            if args.ptt:
                prompt = f"Hold {config.HOTKEY} and speak."
            else:
                from aurora.wake import WakeListener, wake_phrase

                wake = stack.enter_context(WakeListener())
                prompt = f"Say '{wake_phrase()}', then your command."

        def listen() -> str:
            if args.text:
                return input("\nyou> ").strip()
            if wake:
                print(f"\n[waiting for '{wake_phrase()}']")
                wake.wait_for_wake()
                print("[listening...]")
                audio = wake.record_command()
            else:
                print(f"\n[hold {config.HOTKEY} to talk]")
                audio = stt.record()
            heard = stt.transcribe(audio)
            print(f"you> {heard}")
            return heard

        agent = Agent()
        start_reminder_loop(lambda text: (print(f"\n[reminder] {text}"), say(f"Reminder: {text}")))

        print(f"Aurora is ready. {prompt} Say 'quit' to exit, or press Ctrl+C.")
        say("Aurora is ready.")

        while True:
            try:
                heard = listen()
            except (EOFError, KeyboardInterrupt):
                break

            if not heard:
                continue
            if heard.lower().strip(" .!?") in EXIT_PHRASES:
                say("Goodbye.")
                break

            try:
                reply = agent.respond(heard)
            except anthropic.AuthenticationError:
                print("Your ANTHROPIC_API_KEY was rejected.")
                return 1
            except anthropic.APIError as e:
                print(f"[error] {e}")
                if "credit balance" in str(e).lower():
                    reply = "Your Anthropic API credits have run out. Please add credits in the console."
                else:
                    reply = "Sorry, I couldn't reach my brain just now."

            print(f"aurora> {reply}")
            say(reply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
