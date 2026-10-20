import pytest
import time
import gemini_key_manager
from gemini_key_manager import GeminiKeyManager

@pytest.fixture(autouse=True)
def mock_load_dotenv(monkeypatch):
    monkeypatch.setattr(gemini_key_manager, "load_dotenv", lambda *args, **kwargs: None)

def test_key_manager_initialization(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key1, key2, key3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    
    km = GeminiKeyManager()
    assert km.api_keys == ["key1", "key2", "key3"]
    assert km.has_valid_key() is True
    assert km.get_current_key() == "key1"

def test_key_manager_legacy_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEYS", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "legacy_single_key")
    
    km = GeminiKeyManager()
    assert km.api_keys == ["legacy_single_key"]
    assert km.has_valid_key() is True

def test_key_manager_mask_key():
    assert GeminiKeyManager._mask_key("") == "<empty>"
    assert GeminiKeyManager._mask_key("short") == "***"
    assert GeminiKeyManager._mask_key("AIzaSy1234567890ABCDEF") == "...CDEF"

def test_key_manager_rotation_on_rate_limit(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key_A, key_B")
    km = GeminiKeyManager()
    
    call_log = []
    def mock_action(key, model):
        call_log.append((key, model))
        if key == "key_A":
            raise Exception("429 Resource has been exhausted (quota)")
        return "success_from_B"
        
    res = km.execute_with_retry(mock_action, max_retries_per_key=1, fallback_models=["gemini-2.5-flash"])
    assert res == "success_from_B"
    assert call_log[0][0] == "key_A"
    assert call_log[1][0] == "key_B"
    # key_A should be in cooldown
    assert "key_A" in km._key_cooldowns
    assert km._key_cooldowns["key_A"] > time.time()

def test_key_manager_all_keys_rate_limited_fail_fast(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "key_1, key_2")
    km = GeminiKeyManager()
    
    # Pre-park all keys
    future = time.time() + 60.0
    km._key_cooldowns["key_1"] = future
    km._key_cooldowns["key_2"] = future
    
    with pytest.raises(Exception) as exc_info:
        km.execute_with_retry(lambda k, m: "never_called")
    assert "rate-limited" in str(exc_info.value).lower()

def test_key_manager_fallback_models_on_404(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "test_key")
    km = GeminiKeyManager()
    
    models_attempted = []
    def mock_action(key, model):
        models_attempted.append(model)
        if model == "gemini-2.5-flash":
            raise Exception("404 Model not found")
        return f"success_with_{model}"
        
    res = km.execute_with_retry(
        mock_action, 
        fallback_models=["gemini-2.5-flash", "gemini-2.0-flash"]
    )
    assert res == "success_with_gemini-2.0-flash"
    assert models_attempted == ["gemini-2.5-flash", "gemini-2.0-flash"]
