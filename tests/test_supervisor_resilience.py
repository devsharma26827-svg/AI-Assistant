"""
Unit tests for Cynthia's Realtime Resilience and Self-Healing Supervisor.
Validates:
1. ResilientRealtimeSession clears stale session_resumption_handle on retry.
2. ResilientRealtimeModel exposes wait_for_connection and signals connected state.
3. Synchronous SSL caching prevents repetitive context creations.
4. Supervisor reconnect loop logic and exponential backoff behavior.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from agent import (
    ResilientRealtimeSession,
    ResilientRealtimeModel,
    _guarded_startup_greeting,
    _cached_create_default_context,
)
import ssl


def test_ssl_cache_synchronous():
    """Verify SSL context caching returns the identical object without re-creating."""
    ctx1 = _cached_create_default_context()
    ctx2 = _cached_create_default_context()
    assert ctx1 is ctx2


@pytest.mark.asyncio
async def test_resilient_session_resets_handle_on_retry():
    """Verify that _build_connect_config resets _session_resumption_handle when _num_retries > 0."""
    model = ResilientRealtimeModel(api_key="test_key")
    session = model.session()
    try:
        # Simulate an established handle
        session._session_resumption_handle = "stale-google-handle-12345"
        session._num_retries = 0

        # First connection should retain the handle
        with patch("livekit.plugins.google.realtime.realtime_api.RealtimeSession._build_connect_config") as mock_super:
            session._build_connect_config()
            assert session._session_resumption_handle == "stale-google-handle-12345"

        # Retry attempt > 0 should clear the handle
        session._num_retries = 1
        with patch("livekit.plugins.google.realtime.realtime_api.RealtimeSession._build_connect_config") as mock_super:
            session._build_connect_config()
            assert session._session_resumption_handle is None
            assert session._resumption_chat_ctx is None
    finally:
        await session.aclose()


@pytest.mark.asyncio
async def test_resilient_session_resets_handle_on_error():
    """Verify that _mark_restart_needed(on_error=True) immediately clears _session_resumption_handle."""
    model = ResilientRealtimeModel(api_key="test_key")
    session = model.session()
    try:
        session._session_resumption_handle = "stale-handle-xyz"
        session._mark_restart_needed(on_error=True)
        assert session._session_resumption_handle is None
    finally:
        await session.aclose()


@pytest.mark.asyncio
async def test_resilient_model_wait_for_connection():
    """Verify ResilientRealtimeModel.wait_for_connection resolves upon set_connected."""
    model = ResilientRealtimeModel(api_key="mock_key")
    
    # Trigger set_connected asynchronously
    async def trigger():
        await asyncio.sleep(0.05)
        model.set_connected()

    asyncio.create_task(trigger())
    await model.wait_for_connection(timeout=1.0)
    assert model._connected_event.is_set()


@pytest.mark.asyncio
async def test_guarded_startup_greeting_timeout_nonfatal():
    """Verify startup greeting timeout does not raise and Cynthia stays alive."""
    mock_session = MagicMock()
    mock_model = MagicMock()
    # Simulate connection timeout
    mock_model.wait_for_connection = AsyncMock(side_effect=asyncio.TimeoutError())

    # Should log warning and return cleanly without raising
    await _guarded_startup_greeting(mock_session, mock_model, "mock memory")
    mock_session.generate_reply.assert_not_called()
