import pytest
import json
import asyncio
from unittest.mock import MagicMock, patch
from security_tools import scan_text_for_secrets, scan_file_safety, validate_action_safety
from reply_intelligence_tools import auto_reply_decision
from translation_tools import _normalize_language
from google_search_tools import get_current_datetime

def test_security_secret_scanner():
    # OpenAI key
    safe, masked, warn = scan_text_for_secrets("My key is sk-1234567890abcdef1234567890")
    assert safe is False
    assert "OpenAI API Key" in warn
    assert "sk" in masked and "*" in masked
    
    # Gemini / Google key
    safe, masked, warn = scan_text_for_secrets("Key: AIzaSyD1234567890abcdef1234567890abc")
    assert safe is False
    assert "Google / Gemini API Key" in warn
    
    # Password
    safe, masked, warn = scan_text_for_secrets("password='SuperSecretPassword123!'")
    assert safe is False
    assert "Hardcoded Password" in warn
    
    # Clean text
    safe, masked, warn = scan_text_for_secrets("Hello Cynthia, how are you today?")
    assert safe is True
    assert warn is None

def test_security_file_safety(tmp_path):
    safe_file = tmp_path / "notes.txt"
    safe_file.write_text("hello", encoding="utf-8")
    is_safe, warn = scan_file_safety(str(safe_file))
    assert is_safe is True
    assert warn is None
    
    exe_file = tmp_path / "malware.exe"
    exe_file.write_text("binary", encoding="utf-8")
    is_safe, warn = scan_file_safety(str(exe_file))
    assert is_safe is False
    assert "restricted" in warn.lower()

def test_validate_action_safety():
    async def _test():
        # Destructive command
        block_msg = await validate_action_safety("execute_command", "rm -rf /")
        assert "⛔ SECURITY BLOCK" in block_msg
        assert "Destructive command" in block_msg
        
        ps_block = await validate_action_safety("execute_command", "Remove-Item -Recurse C:\\Windows")
        assert "⛔ SECURITY BLOCK" in ps_block
        
        # Safe command
        safe_msg = await validate_action_safety("execute_command", "Get-Process")
        assert "✅ Scan Safe" in safe_msg
        
    asyncio.run(_test())

def test_auto_reply_decision_financial_and_otp():
    async def _test():
        # OTP message
        res_otp = json.loads(await auto_reply_decision("Unknown", "Your OTP is 492812", "notification", "unknown"))
        assert res_otp["decision"] == "DO_NOT_REPLY"
        assert "Sensitive/Financial" in res_otp["reason"]
        
        # Bank transfer / UPI
        res_bank = json.loads(await auto_reply_decision("Rahul", "Please send money via UPI", "request", "friend"))
        assert res_bank["decision"] == "DO_NOT_REPLY"
        
        # Safe casual message from friend
        res_safe = json.loads(await auto_reply_decision("Rahul", "Hey, are you free today?", "casual", "friend", average_confidence=0.85))
        assert res_safe["decision"] == "AUTO_SEND"
        
    asyncio.run(_test())

def test_translation_language_normalization():
    assert _normalize_language("hindi") == "hi"
    assert _normalize_language("Hinglish") == "hi"
    assert _normalize_language("English") == "en"
    assert _normalize_language("SPANISH") == "es"
    assert _normalize_language("fr") == "fr"

def test_get_current_datetime_ist():
    async def _test():
        dt_str = await get_current_datetime()
        assert "IST" in dt_str
        # Contains day, month, time
        assert any(day in dt_str for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
        
    asyncio.run(_test())
