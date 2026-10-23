import asyncio
import pytest
from unittest.mock import MagicMock, patch

import youtube_tools
from youtube_tools import (
    youtube_play_video,
    youtube_search_videos,
    youtube_search_channels,
    _clean_query,
    _resolve_top_video_metadata,
)
import agent

def test_query_cleaning():
    assert _clean_query("play Tum Hi Ho on youtube") == "Tum Hi Ho"
    assert _clean_query("YouTube pe Arijit Singh song chalao") == "Arijit Singh song"
    assert _clean_query("Cynthia, Interstellar theme play karo") == "Interstellar theme"
    assert _clean_query("baja do Kesariya") == "Kesariya"
    assert _clean_query("search for Python tutorials on youtube") == "Python tutorials"
    assert _clean_query("   ") == ""

@pytest.mark.asyncio
async def test_youtube_play_video_empty_query():
    res1 = await youtube_play_video("")
    res2 = await youtube_play_video("   ")
    assert "khaali nahi ho sakta" in res1
    assert "khaali nahi ho sakta" in res2

@pytest.mark.asyncio
async def test_youtube_play_video_success(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_resolve_top_video_metadata", lambda term, **kw: ("UDVtMYqUAyw", "Interstellar Main Theme"))
    
    opened_urls = []
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: opened_urls.append(url) or True)

    res = await youtube_play_video("play Interstellar theme on YouTube")
    assert "Interstellar Main Theme" in res
    assert "open kar diya hai" in res
    assert opened_urls == ["https://www.youtube.com/watch?v=UDVtMYqUAyw"]

@pytest.mark.asyncio
async def test_youtube_play_video_browser_failure(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_resolve_top_video_metadata", lambda term, **kw: ("UDVtMYqUAyw", "Interstellar Main Theme"))
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: False)

    res = await youtube_play_video("Interstellar theme")
    assert "Browser open karne mein error aaya" in res
    assert "https://www.youtube.com/watch?v=UDVtMYqUAyw" in res

@pytest.mark.asyncio
async def test_youtube_play_video_fallback_on_resolution_failure(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_resolve_top_video_metadata", lambda term, **kw: (None, None))
    
    opened_urls = []
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: opened_urls.append(url) or True)

    res = await youtube_play_video("obscure indie track")
    assert "direct resolve nahi ho paya" in res
    assert "search results open kar diye hain" in res
    assert len(opened_urls) == 1
    assert "https://www.youtube.com/results?search_query=obscure+indie+track" in opened_urls[0]

@pytest.mark.asyncio
async def test_youtube_search_videos_empty_query():
    res = await youtube_search_videos("")
    assert "khaali nahi ho sakta" in res

@pytest.mark.asyncio
async def test_youtube_search_videos_success(monkeypatch):
    opened_urls = []
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: opened_urls.append(url) or True)

    res = await youtube_search_videos("React JS tutorials")
    assert "React JS tutorials" in res
    assert "search results open kar diye hain" in res
    assert opened_urls == ["https://www.youtube.com/results?search_query=React+JS+tutorials"]

@pytest.mark.asyncio
async def test_youtube_search_videos_browser_failure(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: False)
    res = await youtube_search_videos("React JS tutorials")
    assert "error aaya" in res

@pytest.mark.asyncio
async def test_youtube_search_channels_empty_query():
    res = await youtube_search_channels("")
    assert "khaali nahi ho sakta" in res

@pytest.mark.asyncio
async def test_youtube_search_channels_success(monkeypatch):
    opened_urls = []
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: opened_urls.append(url) or True)

    res = await youtube_search_channels("CarryMinati channel")
    assert "CarryMinati" in res
    assert "channel results YouTube par open kar diye hain" in res
    assert len(opened_urls) == 1
    assert "search_query=CarryMinati" in opened_urls[0]
    assert "sp=EgIQAg%253D%253D" in opened_urls[0]

@pytest.mark.asyncio
async def test_youtube_search_channels_browser_failure(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_open_url_safely", lambda url: False)
    res = await youtube_search_channels("CarryMinati")
    assert "error aaya" in res

def test_no_accidental_download_in_ytdlp_opts(monkeypatch):
    """Verify that YoutubeDL is only invoked with metadata extraction options and download=False."""
    captured_opts = {}
    download_arg_passed = []

    class MockYoutubeDL:
        def __init__(self, opts):
            captured_opts.update(opts)
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def extract_info(self, url, download=True):
            download_arg_passed.append(download)
            return {"entries": [{"id": "test1234", "title": "Test Title"}]}

    monkeypatch.setattr(youtube_tools, "_YT_DLP_INSTALLED", True)
    monkeypatch.setattr(youtube_tools.yt_dlp, "YoutubeDL", MockYoutubeDL)

    vid, title = _resolve_top_video_metadata("test query")
    assert vid == "test1234"
    assert title == "Test Title"
    assert captured_opts.get("extract_flat") is True
    assert captured_opts.get("skip_download") is True
    assert download_arg_passed == [False]

def test_tool_registration_in_core_tools():
    """Verify all 3 tools are registered in CORE_TOOLS and existing tools are preserved."""
    assert youtube_play_video in agent.CORE_TOOLS
    assert youtube_search_videos in agent.CORE_TOOLS
    assert youtube_search_channels in agent.CORE_TOOLS

    # Verify key existing tools are still present
    for existing_tool_name in [
        "get_weather", "get_current_datetime", "serp_search", "open_app",
        "close_app", "whatsapp_message", "write_text", "remember_fact",
        "save_file_as", "translate_text", "run_shell_command", "run_code_file"
    ]:
        tool_names = [getattr(t, "__name__", "") or getattr(t, "name", "") for t in agent.CORE_TOOLS]
        assert existing_tool_name in tool_names, f"{existing_tool_name} missing from CORE_TOOLS"

def test_availability_in_active_tools_with_core_mode(monkeypatch):
    """Verify tools are in ACTIVE_TOOLS when TOOL_MODE=core."""
    monkeypatch.setenv("TOOL_MODE", "core")
    # Re-evaluate ACTIVE_TOOLS logic
    active = agent.CORE_TOOLS + agent.EXTENDED_TOOLS if agent.TOOL_MODE == "full" else agent.CORE_TOOLS
    assert youtube_play_video in active
    assert youtube_search_videos in active
    assert youtube_search_channels in active
