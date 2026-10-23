import asyncio
import io
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

import vision_tools
from vision_tools import (
    analyze_screen,
    detect_ui_element,
    detect_error_popups,
    summarize_screen_state,
    _get_gemini_vision_response,
)

@pytest.fixture(autouse=True)
def reset_key_manager():
    vision_tools.gemini_key_manager._key_cooldowns.clear()
    vision_tools.gemini_key_manager.current_index = 0
    yield
    vision_tools.gemini_key_manager._key_cooldowns.clear()
    vision_tools.gemini_key_manager.current_index = 0

@pytest.fixture
def dummy_image():
    return Image.new("RGB", (200, 200), color="blue")

@pytest.fixture
def mock_genai_client():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "This is a test screen analysis."
    mock_client.models.generate_content.return_value = mock_response
    return mock_client

@pytest.mark.asyncio
async def test_missing_pillow_dependency(monkeypatch):
    monkeypatch.setattr(vision_tools, "_PIL_INSTALLED", False)
    res = await analyze_screen("What is this?")
    assert "Pillow library not installed" in res

@pytest.mark.asyncio
async def test_missing_genai_dependency(monkeypatch):
    monkeypatch.setattr(vision_tools, "_GENAI_INSTALLED", False)
    res = await analyze_screen("What is this?")
    assert "google-genai library not installed" in res

@pytest.mark.asyncio
async def test_missing_api_key(monkeypatch):
    mock_km = MagicMock()
    mock_km.has_valid_key.return_value = False
    mock_km.api_keys = [""]
    monkeypatch.setattr(vision_tools, "gemini_key_manager", mock_km)
    res = await analyze_screen("What is this?")
    assert "GEMINI_API_KEY not found" in res

@pytest.mark.asyncio
async def test_successful_screen_capture_and_analysis(monkeypatch, dummy_image, mock_genai_client):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)
    monkeypatch.setattr(vision_tools.genai, "Client", lambda **kwargs: mock_genai_client)

    res = await analyze_screen("What is on my screen?")
    assert res == "This is a test screen analysis."
    assert mock_genai_client.models.generate_content.called
    call_args, call_kwargs = mock_genai_client.models.generate_content.call_args
    contents = call_kwargs.get("contents")
    assert len(contents) == 2
    # Check that image part and prompt are passed
    assert hasattr(contents[0], "inline_data") or hasattr(contents[0], "part") or "Part" in str(type(contents[0]))
    assert "What is on my screen?" in contents[1]

@pytest.mark.asyncio
async def test_custom_image_support(monkeypatch, dummy_image, mock_genai_client):
    monkeypatch.setattr(vision_tools.genai, "Client", lambda **kwargs: mock_genai_client)
    res = await _get_gemini_vision_response("Analyze cropped region", custom_image=dummy_image)
    assert res == "This is a test screen analysis."
    assert mock_genai_client.models.generate_content.called

@pytest.mark.asyncio
async def test_unsupported_model_fallback_success(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)
    monkeypatch.setattr(vision_tools, "VISION_FALLBACK_MODELS", ["gemini-unsupported", "gemini-fallback"])

    call_history = []

    def mock_client_factory(**kwargs):
        client = MagicMock()
        def mock_generate(model, contents, **kwargs):
            call_history.append(model)
            if model == "gemini-unsupported":
                raise Exception("404 Model gemini-unsupported not found")
            res = MagicMock()
            res.text = "Success from fallback model"
            return res
        client.models.generate_content.side_effect = mock_generate
        return client

    monkeypatch.setattr(vision_tools.genai, "Client", mock_client_factory)

    res = await analyze_screen("Test query")
    assert res == "Success from fallback model"
    assert call_history == ["gemini-unsupported", "gemini-fallback"]

@pytest.mark.asyncio
async def test_all_models_unsupported_error(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)

    def mock_client_factory(**kwargs):
        client = MagicMock()
        client.models.generate_content.side_effect = Exception("404 Model not found")
        return client

    monkeypatch.setattr(vision_tools.genai, "Client", mock_client_factory)

    res = await analyze_screen("Test query")
    assert "not supported or was not found" in res

@pytest.mark.asyncio
async def test_auth_permission_error(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)

    def mock_client_factory(**kwargs):
        client = MagicMock()
        client.models.generate_content.side_effect = Exception("403 Forbidden: API_KEY_INVALID")
        return client

    monkeypatch.setattr(vision_tools.genai, "Client", mock_client_factory)

    res = await analyze_screen("Test query")
    assert "authentication failed" in res

@pytest.mark.asyncio
async def test_rate_limiting_quota_error(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)

    def mock_client_factory(**kwargs):
        client = MagicMock()
        client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED: quota exceeded")
        return client

    monkeypatch.setattr(vision_tools.genai, "Client", mock_client_factory)

    res = await analyze_screen("Test query")
    assert "quota exceeded or rate-limited" in res

@pytest.mark.asyncio
async def test_api_timeout_error(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)
    monkeypatch.setattr(vision_tools, "GEMINI_VISION_TIMEOUT", 0.05)

    def slow_analyze(*args, **kwargs):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(vision_tools, "_analyze_image", slow_analyze)

    res = await analyze_screen("Test query")
    assert "timed out" in res

@pytest.mark.asyncio
async def test_empty_and_blocked_response(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)

    # Empty response
    mock_client = MagicMock()
    empty_res = MagicMock()
    empty_res.text = ""
    empty_res.candidates = []
    mock_client.models.generate_content.return_value = empty_res
    monkeypatch.setattr(vision_tools.genai, "Client", lambda **kwargs: mock_client)

    res = await analyze_screen("Test query")
    assert "empty or blocked" in res

    # Safety blocked response
    blocked_res = MagicMock()
    blocked_res.text = None
    candidate = MagicMock()
    candidate.finish_reason = "SAFETY"
    blocked_res.candidates = [candidate]
    mock_client.models.generate_content.return_value = blocked_res

    res_blocked = await analyze_screen("Test query")
    assert "blocked by content safety filters" in res_blocked

@pytest.mark.asyncio
async def test_no_api_key_disclosure_in_error(monkeypatch, dummy_image):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)

    secret_key = "AIzaSyC71234567890abcdef1234567890abc"
    def mock_client_factory(**kwargs):
        client = MagicMock()
        client.models.generate_content.side_effect = Exception(f"Internal crash with key {secret_key} on request")
        return client

    monkeypatch.setattr(vision_tools.genai, "Client", mock_client_factory)

    res = await analyze_screen("Test query")
    assert secret_key not in res
    assert "[REDACTED_KEY]" in res

@pytest.mark.asyncio
async def test_windows_screen_grab_failure(monkeypatch):
    def failing_grab():
        raise OSError("screen grab failed")
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", failing_grab)

    res = await analyze_screen("Test query")
    assert "Could not capture the Windows screen" in res

@pytest.mark.asyncio
async def test_preservation_of_public_vision_tools(monkeypatch, dummy_image, mock_genai_client):
    monkeypatch.setattr(vision_tools.ImageGrab, "grab", lambda: dummy_image)
    monkeypatch.setattr(vision_tools.genai, "Client", lambda **kwargs: mock_genai_client)

    # 1. analyze_screen
    mock_genai_client.models.generate_content.return_value.text = "Screen content summary"
    r1 = await analyze_screen("What is this?")
    assert r1 == "Screen content summary"

    # 2. detect_ui_element
    mock_genai_client.models.generate_content.return_value.text = "YES, bottom right"
    r2 = await detect_ui_element("Send button")
    assert r2 == "YES, bottom right"

    # 3. detect_error_popups
    mock_genai_client.models.generate_content.return_value.text = "No errors detected."
    r3 = await detect_error_popups()
    assert r3 == "No errors detected."

    # 4. summarize_screen_state
    mock_genai_client.models.generate_content.return_value.text = "1. Chrome open\n2. Reading docs\n3. None"
    r4 = await summarize_screen_state()
    assert "Chrome open" in r4
