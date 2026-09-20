"""
Shared "human-like" text entry helper used by every tool that types into a
UI element (WhatsApp messages, dictated notes, generic human_type_text, etc.).

Rules (intentional product behavior, not a bug):
- SHORT content -> typed character-by-character so it visibly looks like the
  assistant is actually typing (feels like a real assistant at work).
- LONG content -> pasted instantly via the clipboard (typing it out char-by-char
  would take too long, block the UI, and is what caused the "spam typing"
  and un-stoppable long-typing bugs).

Unicode note: pyautogui.write() can ONLY type plain ASCII (US keyboard) text —
it silently fails or mis-types anything else (Hindi/Devanagari, emoji, etc.).
So for non-ASCII short text we still "type" it visibly, but do it via a
per-character clipboard paste instead of pyautogui.write(), which works for
any language while still producing the same on-screen "typing" effect.

All functions in this module are BLOCKING (they call pyautogui directly) —
callers must run them off the asyncio event loop, e.g.:
    await loop.run_in_executor(None, human_like_type, text)
"""
import time
import pyautogui
import pyperclip

# Content at or under this length gets the visible "typed" effect.
# Anything longer is pasted instantly instead.
SHORT_TEXT_THRESHOLD = 60

# Delay between characters when simulating typing.
ASCII_TYPE_INTERVAL = 0.045
UNICODE_TYPE_DELAY = 0.035


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def _paste(text: str):
    """Instant clipboard paste. Works for any language/script."""
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")


def human_like_type(text: str, short_threshold: int = SHORT_TEXT_THRESHOLD) -> None:
    """
    Types `text` into whatever UI element currently has keyboard focus.

    - len(text) > short_threshold  -> instant clipboard paste.
    - len(text) <= short_threshold and pure ASCII -> real character-by-character
      typing via pyautogui.write() (cheapest, most natural-looking option).
    - len(text) <= short_threshold and non-ASCII (Hindi, emoji, etc.) -> typed
      effect simulated via per-character clipboard paste, since pyautogui can't
      type Unicode directly.

    Blocking call — run via run_in_executor/asyncio.to_thread.
    """
    if not text:
        return

    if len(text) > short_threshold:
        _paste(text)
        return

    if _is_ascii(text):
        pyautogui.write(text, interval=ASCII_TYPE_INTERVAL)
    else:
        for ch in text:
            pyperclip.copy(ch)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(UNICODE_TYPE_DELAY)
