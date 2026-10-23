"""
Unit tests for Cynthia's YouTube Background Playback Controls.
Tests pause, resume, seek, next, previous, status, duration formatting,
bounds clamping, session resolution, and CORE_TOOLS registration.
"""
import datetime
from unittest.mock import AsyncMock, MagicMock
import pytest

import youtube_tools
from youtube_tools import (
    _format_duration,
    _get_youtube_media_session,
    youtube_pause_playback,
    youtube_resume_playback,
    youtube_seek_playback,
    youtube_next_video,
    youtube_previous_video,
    youtube_get_playback_status,
)
import agent


def test_format_duration():
    assert _format_duration(0) == "0:00"
    assert _format_duration(45) == "0:45"
    assert _format_duration(65) == "1:05"
    assert _format_duration(3600) == "1:00:00"
    assert _format_duration(3665) == "1:01:05"


class MockTimeline:
    def __init__(self, position_sec=100.0, end_sec=300.0, min_seek=0.0, max_seek=300.0):
        self.position = datetime.timedelta(seconds=position_sec)
        self.end_time = datetime.timedelta(seconds=end_sec)
        self.start_time = datetime.timedelta(seconds=0)
        self.min_seek_time = datetime.timedelta(seconds=min_seek)
        self.max_seek_time = datetime.timedelta(seconds=max_seek)


class MockMediaProps:
    def __init__(self, title="Mock Video Title", artist="Mock Channel"):
        self.title = title
        self.artist = artist


class MockPlaybackInfo:
    def __init__(self, status=4):  # 4 = Playing, 5 = Paused
        self.playback_status = status


class MockSession:
    def __init__(self, app_id="chrome.exe", status=4, pos=100.0, end=300.0, title="Mock Song"):
        self.source_app_user_model_id = app_id
        self._status = status
        self._pos = pos
        self._end = end
        self._title = title
        self.try_pause_async = AsyncMock(return_value=True)
        self.try_play_async = AsyncMock(return_value=True)
        self.try_skip_next_async = AsyncMock(return_value=True)
        self.try_skip_previous_async = AsyncMock(return_value=True)
        self.try_change_playback_position_async = AsyncMock(return_value=True)

    def get_playback_info(self):
        return MockPlaybackInfo(self._status)

    async def try_get_media_properties_async(self):
        return MockMediaProps(title=self._title, artist="Mock Artist")

    def get_timeline_properties(self):
        return MockTimeline(position_sec=self._pos, end_sec=self._end)


@pytest.mark.asyncio
async def test_pause_playback_when_playing(monkeypatch):
    mock_s = MockSession(status=4, title="Tum Hi Ho")
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_pause_playback()
    assert "pause kar diya hai" in res
    assert "Tum Hi Ho" in res
    mock_s.try_pause_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_pause_playback_already_paused(monkeypatch):
    mock_s = MockSession(status=5, title="Tum Hi Ho")
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_pause_playback()
    assert "pehle se hi paused hai" in res
    mock_s.try_pause_async.assert_not_called()


@pytest.mark.asyncio
async def test_resume_playback_when_paused(monkeypatch):
    mock_s = MockSession(status=5, title="Tum Hi Ho")
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_resume_playback()
    assert "resume kar diya hai" in res
    assert "Tum Hi Ho" in res
    mock_s.try_play_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_playback_already_playing(monkeypatch):
    mock_s = MockSession(status=4, title="Tum Hi Ho")
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_resume_playback()
    assert "pehle se hi chal rahi hai" in res
    mock_s.try_play_async.assert_not_called()


@pytest.mark.asyncio
async def test_seek_playback_forward(monkeypatch):
    mock_s = MockSession(pos=60.0, end=300.0)
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_seek_playback(seconds=20, direction="forward")
    assert "video 20 second aage kar diya hai" in res
    assert "1:20 / 5:00" in res
    # 60 + 20 = 80 seconds -> 80 * 10,000,000 ticks = 800,000,000
    mock_s.try_change_playback_position_async.assert_awaited_once_with(800_000_000)


@pytest.mark.asyncio
async def test_seek_playback_backward_hinglish(monkeypatch):
    mock_s = MockSession(pos=90.0, end=300.0)
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_seek_playback(seconds=30, direction="peeche")
    assert "video 30 second peeche kar diya hai" in res
    assert "1:00 / 5:00" in res
    # 90 - 30 = 60 seconds -> 60 * 10,000,000 ticks = 600,000,000
    mock_s.try_change_playback_position_async.assert_awaited_once_with(600_000_000)


@pytest.mark.asyncio
async def test_seek_playback_clamping_to_duration(monkeypatch):
    mock_s = MockSession(pos=280.0, end=300.0)
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_seek_playback(seconds=60, direction="forward")
    assert "video 60 second aage kar diya hai" in res
    assert "5:00 / 5:00" in res
    # Clamped to 300.0s -> 3,000,000,000 ticks
    mock_s.try_change_playback_position_async.assert_awaited_once_with(3_000_000_000)


@pytest.mark.asyncio
async def test_seek_playback_clamping_to_zero(monkeypatch):
    mock_s = MockSession(pos=15.0, end=300.0)
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_seek_playback(seconds=45, direction="rewind")
    assert "video 45 second peeche kar diya hai" in res
    assert "0:00 / 5:00" in res
    # Clamped to 0.0s -> 0 ticks
    mock_s.try_change_playback_position_async.assert_awaited_once_with(0)


@pytest.mark.asyncio
async def test_seek_playback_invalid_seconds():
    res1 = await youtube_seek_playback(seconds=0)
    assert "0 se zyada honi chahiye" in res1
    res2 = await youtube_seek_playback(seconds=-5)
    assert "0 se zyada honi chahiye" in res2
    res3 = await youtube_seek_playback(seconds="abc")
    assert "valid number" in res3


@pytest.mark.asyncio
async def test_next_and_previous_video(monkeypatch):
    mock_s = MockSession()
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    next_res = await youtube_next_video()
    assert "agle video/song par skip" in next_res
    mock_s.try_skip_next_async.assert_awaited_once()

    prev_res = await youtube_previous_video()
    assert "pichle video/song par skip" in prev_res
    mock_s.try_skip_previous_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_playback_status(monkeypatch):
    mock_s = MockSession(status=4, pos=125.0, end=300.0, title="Interstellar Theme")
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=mock_s))

    res = await youtube_get_playback_status()
    assert "Interstellar Theme" in res
    assert "Mock Artist" in res
    assert "Status: Playing" in res
    assert "[2:05 / 5:00]" in res


@pytest.mark.asyncio
async def test_no_media_session_found(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", True)
    monkeypatch.setattr(youtube_tools, "_get_youtube_media_session", AsyncMock(return_value=None))

    res_pause = await youtube_pause_playback()
    assert "koi active YouTube playback" in res_pause

    res_resume = await youtube_resume_playback()
    assert "koi active YouTube playback" in res_resume

    res_seek = await youtube_seek_playback(10)
    assert "koi active YouTube playback" in res_seek

    res_status = await youtube_get_playback_status()
    assert "koi YouTube ya browser media playback active nahi" in res_status


@pytest.mark.asyncio
async def test_winsdk_not_installed(monkeypatch):
    monkeypatch.setattr(youtube_tools, "_WINSDK_INSTALLED", False)

    res = await youtube_pause_playback()
    assert "winsdk" in res
    res = await youtube_resume_playback()
    assert "winsdk" in res
    res = await youtube_seek_playback(10)
    assert "winsdk" in res


def test_core_tools_registration():
    """Verify all 9 YouTube tools are registered in agent.CORE_TOOLS."""
    expected_tools = [
        youtube_tools.youtube_play_video,
        youtube_tools.youtube_search_videos,
        youtube_tools.youtube_search_channels,
        youtube_tools.youtube_pause_playback,
        youtube_tools.youtube_resume_playback,
        youtube_tools.youtube_seek_playback,
        youtube_tools.youtube_next_video,
        youtube_tools.youtube_previous_video,
        youtube_tools.youtube_get_playback_status,
    ]
    for t in expected_tools:
        assert t in agent.CORE_TOOLS, f"Tool {t} not found in agent.CORE_TOOLS"
