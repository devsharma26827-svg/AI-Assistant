"""
Unit tests for WhatsApp fuzzy matching, Devanagari transliteration,
safe WhatsApp Desktop validation (no Chrome opening), and junk input handling.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

import whatsapp_tools
from whatsapp_tools import (
    resolve_contact_name,
    _transliterate_devanagari,
    whatsapp_message,
    is_whatsapp_desktop_installed,
)
import youtube_tools
from youtube_tools import (
    youtube_previous_video,
    youtube_next_video,
    youtube_pause_playback,
)


def test_devanagari_transliteration():
    assert _transliterate_devanagari("कुशाग्र") == "kushagr"
    assert _transliterate_devanagari("कुशागर") == "kushagar"
    assert _transliterate_devanagari("नमस्ते") == "namaste"


def test_fuzzy_contact_resolution_kushagar_variants():
    # All speech-to-text variations of Kushagar must resolve to canonical 'Kushagar'
    variants = ["Kushagar", "Kushagra", "Kushagr", "kushagar", "kushagra", "kushagr", "कुशाग्र", "कुशागर"]
    for v in variants:
        resolved, err = resolve_contact_name(v)
        assert err is None, f"Failed resolving {v}: {err}"
        assert resolved == "Kushagar", f"Expected 'Kushagar' for variant {v}, got {resolved}"


def test_fuzzy_contact_resolution_unknown():
    resolved, err = resolve_contact_name("XyzRandomUnknownPerson123")
    # Clean fallback title or not found
    assert resolved is not None or "not found" in err.lower()


def test_fuzzy_contact_resolution_empty():
    resolved, err = resolve_contact_name("")
    assert resolved is None
    assert "empty" in err.lower()


@pytest.mark.asyncio
async def test_whatsapp_desktop_not_installed_returns_failure(monkeypatch):
    monkeypatch.setattr(whatsapp_tools, "is_whatsapp_desktop_installed", lambda: False)
    opened_urls = []
    # Ensure no browser / Chrome is called
    monkeypatch.setattr(whatsapp_tools.subprocess, "Popen", lambda *a, **kw: opened_urls.append(a))

    res = await whatsapp_message(contact="Kushagar", message="Hello")
    assert "failed:" in res
    assert "WhatsApp Desktop not found" in res
    # Assert Chrome/browser was NEVER touched
    assert len(opened_urls) == 0


@pytest.mark.asyncio
async def test_whatsapp_focus_failure_aborts_without_keystrokes(monkeypatch):
    monkeypatch.setattr(whatsapp_tools, "is_whatsapp_desktop_installed", lambda: True)
    monkeypatch.setattr(whatsapp_tools, "_focus_whatsapp", lambda: False)

    typed_text = []
    monkeypatch.setattr(whatsapp_tools.pyautogui, "write", lambda t: typed_text.append(t))
    monkeypatch.setattr(whatsapp_tools.pyautogui, "press", lambda k, **kw: typed_text.append(k))
    monkeypatch.setattr(whatsapp_tools.pyautogui, "hotkey", lambda *k: typed_text.append(k))

    res = await whatsapp_message(contact="Kushagar", message="Hello")
    assert "failed:" in res
    assert "could not focus" in res.lower()
    # Zero keystrokes sent
    assert len(typed_text) == 0


@pytest.mark.asyncio
async def test_junk_transcript_pajaro_does_not_trigger_playback(monkeypatch):
    # A single noisy word like 'Pajaro' when nothing is playing returns clean failure
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=None))

    res_prev = await youtube_previous_video()
    assert "failed: nothing is playing" in res_prev

    res_next = await youtube_next_video()
    assert "failed: nothing is playing" in res_next

    res_pause = await youtube_pause_playback()
    assert "failed: nothing is playing" in res_pause
