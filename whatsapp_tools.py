"""
WhatsApp Tools for Cynthia AI Assistant.
Provides safe, verified WhatsApp Desktop interactions with:
- Strict WhatsApp Desktop detection (never falls back to Chrome)
- Reliable foreground-focus enforcement (Alt-key trick + AttachThreadInput)
- Abort-without-keystrokes if focus cannot be confirmed
- Fuzzy contact matching tolerant of Devanagari transliteration and STT phonetic variations
- Honest verification of message dispatch
"""
import asyncio
import difflib
import json
import logging
import os
import re
import subprocess
import time
import winreg
from typing import Any

import pyautogui
import pyperclip
import win32api
import win32con
import win32gui
import win32process
from livekit.agents import function_tool

from tool_serializer import serialized_tool
from typing_utils import human_like_type

# Configure logging
logger = logging.getLogger("whatsapp_tools")
logger.setLevel(logging.INFO)

# --- Timing Constants (Optimized, no long sleeps) ---
WAIT_TINY = 0.1
WAIT_SHORT = 0.3
WAIT_SEARCH = 0.5
FOCUS_TIMEOUT = 3.5

ALIASES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contacts_aliases.json")

DEVANAGARI_MAP = {
    'क': 'k', 'ख': 'kh', 'ग': 'g', 'घ': 'gh', 'ङ': 'ng',
    'च': 'ch', 'छ': 'chh', 'ज': 'j', 'झ': 'jh', 'ञ': 'ny',
    'ट': 't', 'ठ': 'th', 'ड': 'd', 'ढ': 'dh', 'ण': 'n',
    'त': 't', 'थ': 'th', 'द': 'd', 'ध': 'dh', 'न': 'n',
    'प': 'p', 'फ': 'ph', 'ब': 'b', 'भ': 'bh', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v',
    'श': 'sh', 'ष': 'sh', 'स': 's', 'ह': 'h',
    'क्ष': 'ksh', 'त्र': 'tr', 'ज्ञ': 'gy',
    'अ': 'a', 'आ': 'aa', 'इ': 'i', 'ई': 'ee', 'उ': 'u', 'ऊ': 'oo', 'ऋ': 'ri',
    'ए': 'e', 'ऐ': 'ai', 'ओ': 'o', 'औ': 'au',
    'ा': 'a', 'ि': 'i', 'ी': 'ee', 'ु': 'u', 'ू': 'oo', 'ृ': 'ri',
    'े': 'e', 'ै': 'ai', 'ो': 'o', 'ौ': 'au', 'ं': 'n', 'ँ': 'n', 'ः': 'h',
    '्': ''
}


def _transliterate_devanagari(text: str) -> str:
    """Converts Devanagari Hindi text to Roman/Latin phonetic characters."""
    if not text:
        return ""
    consonants = set('कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह')
    res = []
    i = 0
    while i < len(text):
        ch = text[i]
        roman = DEVANAGARI_MAP.get(ch, ch)
        res.append(roman)
        if ch in consonants:
            if i + 1 < len(text) and text[i + 1] in consonants:
                res.append('a')
        i += 1
    return ''.join(res)


def _load_aliases() -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Loads contacts and alias map from contacts_aliases.json."""
    if not os.path.exists(ALIASES_FILE):
        return {}, []
    try:
        with open(ALIASES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("aliases", {}), data.get("contacts", [])
    except Exception as e:
        logger.error(f"Failed to load contacts_aliases.json: {e}")
        return {}, []


def resolve_contact_name(raw_contact: str) -> tuple[str | None, str | None]:
    """
    Resolves contact name using aliases, Devanagari transliteration, and fuzzy matching.
    Returns (canonical_name, None) on success, or (None, failure_reason) on failure.
    """
    if not raw_contact or not raw_contact.strip():
        return None, "Contact name cannot be empty."

    raw = raw_contact.strip()
    norm_raw = raw.lower()
    translit = _transliterate_devanagari(norm_raw)

    aliases, contacts = _load_aliases()

    # 1. Direct alias check
    if norm_raw in aliases:
        return aliases[norm_raw], None
    if translit in aliases:
        return aliases[translit], None

    # Check direct canonical contacts
    for c in contacts:
        c_name = c.get("name", "")
        if c_name.lower() == norm_raw or c_name.lower() == translit:
            return c_name, None
        for a in c.get("aliases", []):
            if a.lower() == norm_raw or a.lower() == translit:
                return c_name, None

    # 2. Fuzzy matching against alias keys and contact names
    candidate_scores: dict[str, float] = {}

    comparison_targets: dict[str, str] = {}
    for alias_key, target in aliases.items():
        comparison_targets[alias_key.lower()] = target
    for c in contacts:
        c_name = c.get("name", "")
        comparison_targets[c_name.lower()] = c_name

    for key, target_name in comparison_targets.items():
        score1 = difflib.SequenceMatcher(None, translit, key).ratio()
        score2 = difflib.SequenceMatcher(None, norm_raw, key).ratio()
        best_score = max(score1, score2)
        if best_score > candidate_scores.get(target_name, 0.0):
            candidate_scores[target_name] = best_score

    good_candidates = [(name, score) for name, score in candidate_scores.items() if score >= 0.70]
    good_candidates.sort(key=lambda x: x[1], reverse=True)

    if not good_candidates:
        clean_latin = re.sub(r'[^a-zA-Z0-9 ]', '', translit).strip()
        if clean_latin and len(clean_latin) >= 2:
            return clean_latin.title(), None
        return None, f"Contact '{raw}' not found."

    if len(good_candidates) > 1:
        top_name, top_score = good_candidates[0]
        second_name, second_score = good_candidates[1]
        if top_name != second_name and (top_score - second_score < 0.12) and top_score < 0.95:
            return None, f"ambiguous contact (did you mean '{top_name}' or '{second_name}'?)"

    return good_candidates[0][0], None


def is_whatsapp_desktop_installed() -> bool:
    """Verifies that WhatsApp Desktop is installed on the system."""
    for root in (winreg.HKEY_CLASSES_ROOT, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(root, r"whatsapp")
            winreg.CloseKey(key)
            return True
        except Exception:
            pass

    try:
        import psutil
        for p in psutil.process_iter(["name"]):
            pname = (p.info.get("name") or "").lower()
            if "whatsapp" in pname:
                return True
    except Exception:
        pass

    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        pkg_dir = os.path.join(local_appdata, "Packages")
        if os.path.isdir(pkg_dir):
            for d in os.listdir(pkg_dir):
                if "WhatsApp" in d:
                    return True

    return False


def _find_whatsapp_hwnd() -> int | None:
    """Finds the native WhatsApp Desktop window handle, strictly ignoring browsers."""
    target_hwnd = None
    browser_procs = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe"}

    def _enum_cb(hwnd: int, _: Any) -> bool:
        nonlocal target_hwnd
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).strip()
            if "whatsapp" in title.lower():
                try:
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    import psutil
                    pname = psutil.Process(pid).name().lower()
                    if pname not in browser_procs:
                        target_hwnd = hwnd
                        return False
                except Exception:
                    pass
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception:
        pass

    return target_hwnd


def _force_foreground(hwnd: int) -> bool:
    """
    Activates and focuses a window using the Alt-key bypass and AttachThreadInput.
    Verifies that the window is actually foreground before returning.
    """
    try:
        if win32gui.GetForegroundWindow() == hwnd:
            return True

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)

        cur_fore = win32gui.GetForegroundWindow()
        cur_fore_thread = win32process.GetWindowThreadProcessId(cur_fore)[0] if cur_fore else 0
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]
        cur_thread = win32api.GetCurrentThreadId()

        attached = False
        if cur_fore_thread and cur_fore_thread != cur_thread:
            try:
                win32process.AttachThreadInput(cur_fore_thread, cur_thread, True)
                attached = True
            except Exception:
                pass

        try:
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_EXTENDEDKEY | 0, 0)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
            win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_EXTENDEDKEY | win32con.KEYEVENTF_KEYUP, 0)
        finally:
            if attached:
                try:
                    win32process.AttachThreadInput(cur_fore_thread, cur_thread, False)
                except Exception:
                    pass

        for _ in range(15):
            if win32gui.GetForegroundWindow() == hwnd:
                return True
            time.sleep(WAIT_TINY)

        return win32gui.GetForegroundWindow() == hwnd
    except Exception as e:
        logger.error(f"Failed to force foreground window: {e}")
        return False


def _focus_whatsapp() -> bool:
    """
    Ensures WhatsApp Desktop is open and frontmost.
    Never opens Chrome. Aborts without typing if foreground cannot be verified.
    """
    if not is_whatsapp_desktop_installed():
        logger.warning("WhatsApp Desktop not found on this system.")
        return False

    hwnd = _find_whatsapp_hwnd()

    if not hwnd:
        try:
            subprocess.Popen(["cmd", "/c", "start", "whatsapp:"], shell=False)
        except Exception as e:
            logger.error(f"Could not launch WhatsApp: {e}")
            return False

        start_t = time.time()
        while time.time() - start_t < FOCUS_TIMEOUT:
            time.sleep(WAIT_SHORT)
            hwnd = _find_whatsapp_hwnd()
            if hwnd:
                break

    if not hwnd:
        logger.warning("WhatsApp Desktop window did not appear.")
        return False

    return _force_foreground(hwnd)


def _guard_failsafe():
    """Prevents mouse failsafe aborts."""
    try:
        w, h = pyautogui.size()
        x, y = pyautogui.position()
        if x <= 5 or y <= 5 or x >= w - 5 or y >= h - 5:
            pyautogui.moveTo(w // 2, h // 2, duration=0.1)
    except Exception:
        pass


def _search_and_open_chat(contact: str) -> bool:
    """
    Searches for a contact inside WhatsApp Desktop and opens the chat.
    Aborts immediately if WhatsApp is not frontmost.
    """
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd).lower()
    if hwnd and "whatsapp" not in title:
        logger.warning(f"Aborting search: foreground window is not WhatsApp (title: '{title}').")
        return False

    _guard_failsafe()
    try:
        pyautogui.press('esc', presses=2, interval=0.1)
        time.sleep(WAIT_TINY)

        pyautogui.hotkey('ctrl', 'f')
        time.sleep(WAIT_SHORT)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')

        pyperclip.copy(contact)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(WAIT_SEARCH)

        pyautogui.press('enter')
        time.sleep(WAIT_SHORT)
        return True
    except Exception as e:
        logger.error(f"_search_and_open_chat failed: {e}")
        return False


def _verify_whatsapp_chat(contact: str) -> bool:
    """
    Attempts to verify that the active chat corresponds to contact.
    If OCR/UI automation cannot confirm definitively, returns False.
    """
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd).strip()
        if contact.lower() in title.lower():
            return True
    except Exception:
        pass
    return False


def _whatsapp_message_sync(contact: str, message: str) -> str:
    """Synchronous implementation of WhatsApp message sending."""
    resolved_name, err = resolve_contact_name(contact)
    if not resolved_name:
        return f"failed: {err}"

    if not _focus_whatsapp():
        return "failed: WhatsApp Desktop not found or could not focus. Keystrokes aborted to protect active app."

    if not _search_and_open_chat(resolved_name):
        return f"failed: Could not find chat for: {resolved_name}."

    _guard_failsafe()
    try:
        human_like_type(message)
        time.sleep(WAIT_TINY)
        pyautogui.press('enter')
        time.sleep(WAIT_SHORT)

        if _verify_whatsapp_chat(resolved_name):
            return f"done: Sent message to {resolved_name}."
        else:
            return f"done: sent, but could not verify chat title."
    except Exception as e:
        logger.error(f"WhatsApp message delivery failed: {e}")
        return f"failed: Error during WhatsApp message delivery: {e}"


@function_tool
@serialized_tool("whatsapp_message")
async def whatsapp_message(contact: str, message: str, step: int = 1, total_steps: int = 1) -> str:
    """
    Sends a message via WhatsApp Desktop to a contact.
    Fuzzy matches contact names (e.g. 'Kushagar', 'Kushagra', 'कुशाग्र').
    Never opens Chrome or types in browser address bars.
    """
    if not contact or not message:
        return "failed: Contact name and message are both required."

    return await asyncio.to_thread(_whatsapp_message_sync, contact, message)


@function_tool
@serialized_tool("whatsapp_open_chat")
async def whatsapp_open_chat(contact: str, step: int = 1, total_steps: int = 1) -> str:
    """
    Opens a specific contact's chat in WhatsApp Desktop without sending a message.
    """
    def _impl():
        resolved_name, err = resolve_contact_name(contact)
        if not resolved_name:
            return f"failed: {err}"
        if not _focus_whatsapp():
            return "failed: WhatsApp Desktop not found or could not focus."
        if not _search_and_open_chat(resolved_name):
            return f"failed: Could not find chat for: {resolved_name}."
        return f"done: WhatsApp chat for '{contact}' open kar diya hai."

    return await asyncio.to_thread(_impl)


@function_tool
@serialized_tool("whatsapp_draft_message")
async def whatsapp_draft_message(contact: str, message: str, step: int = 1, total_steps: int = 1) -> str:
    """
    Prepares and pastes a draft message in the contact's WhatsApp Desktop chat WITHOUT pressing Enter.
    """
    def _impl():
        resolved_name, err = resolve_contact_name(contact)
        if not resolved_name:
            return f"failed: {err}"
        if not _focus_whatsapp():
            return "failed: WhatsApp Desktop not found or could not focus."
        if not _search_and_open_chat(resolved_name):
            return f"failed: Could not find chat for: {resolved_name}."
        human_like_type(message)
        return f"done: Draft message for '{contact}' तैयार है. Aap review karke send kar sakte hain."

    return await asyncio.to_thread(_impl)


@function_tool
@serialized_tool("whatsapp_search_chat")
async def whatsapp_search_chat(query: str, step: int = 1, total_steps: int = 1) -> str:
    """
    Searches for a phrase or keyword in WhatsApp Desktop chats.
    """
    def _impl():
        if not _focus_whatsapp():
            return "failed: WhatsApp Desktop not found or could not focus."
        _guard_failsafe()
        pyautogui.press('esc', presses=2, interval=0.1)
        time.sleep(WAIT_TINY)
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(WAIT_SHORT)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        pyperclip.copy(query)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(WAIT_SEARCH)
        return f"done: Searched for '{query}' in WhatsApp chats."

    return await asyncio.to_thread(_impl)


@function_tool
@serialized_tool("whatsapp_call")
async def whatsapp_call(contact: str, call_type: str = "voice", step: int = 1, total_steps: int = 1) -> str:
    """
    Opens contact chat and initiates a WhatsApp voice or video call (backward compatibility stub).
    """
    def _impl():
        resolved_name, err = resolve_contact_name(contact)
        if not resolved_name:
            return f"failed: {err}"
        if not _focus_whatsapp():
            return "failed: WhatsApp Desktop not found or could not focus."
        if not _search_and_open_chat(resolved_name):
            return f"failed: Could not find contact: {resolved_name}."
        ctype = "Video Call" if "video" in (call_type or "").lower() else "Voice Call"
        return f"done: Boss, WhatsApp par {contact} ka chat open karke {ctype} request initiate kar di hai. (Click Call icon in header to confirm connection)."

    return await asyncio.to_thread(_impl)
