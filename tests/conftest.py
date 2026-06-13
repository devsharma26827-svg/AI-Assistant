import pytest
import os
import sys

# Ensure project root is in path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

@pytest.fixture(autouse=True)
def mock_env(monkeypatch):
    """Set default environment variables for testing."""
    monkeypatch.setenv("ASSISTANT_NAME", "Cynthia")
    monkeypatch.setenv("ASSISTANT_VOICE", "Aoede")
    monkeypatch.setenv("PLAY_STARTUP_SOUND", "false")
    monkeypatch.setenv("GEMINI_API_KEYS", "test_key")
