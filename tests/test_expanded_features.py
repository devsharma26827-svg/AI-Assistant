"""
Comprehensive automated unit tests for Cynthia's expanded features:
- Empathy Voice Conversations
- AI Code Fixer, Builder, and Explainer
- AI Website Template Builder
- WhatsApp Messaging, Calling, and Chat Search
- System Volume and Display Brightness Controls
- Power Manager (Shutdown, Restart, Sleep, Cancel)
- OCR Screen Text Reader & Interaction Safety
- Community Support Tickets (SQLite)
- SMTP Email Automation
- Spotify Music Integration
- Windows Network Manager (netsh)
- Windows Defender Antivirus Scanner
- Tool registration integrity in agent.py
"""
import os
import shutil
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

import agent
import empathy_tools
import code_assistant_tools
import website_builder_tools
import whatsapp_tools
import environment_tools
import power_tools
import vision_tools
import human_computer_tools
import support_ticket_tools
import email_tools
import spotify_tools
import network_tools
import defender_tools


# ---------------------------------------------------------------------------
# 1. Empathy Voice Conversations
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_adapt_conversational_tone():
    res_stressed = await empathy_tools.adapt_conversational_tone("stressed")
    assert "Ultra-brief" in res_stressed
    assert "Done, Boss." in res_stressed

    res_frustrated = await empathy_tools.adapt_conversational_tone("frustrated")
    assert "apologize once" in res_frustrated

    res_sad = await empathy_tools.adapt_conversational_tone("sad")
    assert "supportive" in res_sad

    res_calm = await empathy_tools.adapt_conversational_tone("calm")
    assert "Tone adapted to 'Calm'" in res_calm


# ---------------------------------------------------------------------------
# 2. Code Assistant, Fixer, Builder, and Explainer
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_explain_code():
    snippet = "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n"
    res = await code_assistant_tools.explain_code(code_snippet=snippet)
    assert "add" in res
    assert "sub" in res

@pytest.mark.asyncio
async def test_analyze_error_and_suggest_fix():
    err = 'Traceback (most recent call last):\n  File "server.py", line 42, in start\nModuleNotFoundError: No module named "redis"'
    res = await code_assistant_tools.analyze_error_and_suggest_fix(error_message=err)
    assert "server.py" in res
    assert "Line 42" in res
    assert "pip install" in res

@pytest.mark.asyncio
async def test_apply_code_fix():
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".py") as f:
        f.write("def calculate():\n    return 10 / 0\n")
        temp_path = f.name

    try:
        search = "return 10 / 0"
        replace = "return 10 / 2"
        res = await code_assistant_tools.apply_code_fix(temp_path, search, replace)
        assert "safely apply kar diya gaya hai" in res
        assert "Backup saved" in res

        # Verify target file updated
        with open(temp_path, "r") as f:
            content = f.read()
        assert "return 10 / 2" in content
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@pytest.mark.asyncio
async def test_generate_unit_tests():
    snippet = "def multiply(x, y):\n    return x * y\n"
    res = await code_assistant_tools.generate_unit_tests(code_snippet=snippet)
    assert "test_multiply_success" in res
    assert "pytest" in res

@pytest.mark.asyncio
async def test_read_clipboard_text(monkeypatch):
    monkeypatch.setattr(code_assistant_tools.pyperclip, "paste", lambda: "Hello from clipboard")
    res = await code_assistant_tools.read_clipboard_text()
    assert "Hello from clipboard" in res
    assert "20 chars" in res

@pytest.mark.asyncio
async def test_solve_coding_problem():
    res = await code_assistant_tools.solve_coding_problem("Find two numbers that sum up to target")
    assert "Problem Breakdown" in res
    assert "Time Complexity" in res


# ---------------------------------------------------------------------------
# 3. Website Template Builder
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_build_website_template():
    p_name = "test_sample_site"
    res = await website_builder_tools.build_website_template(
        project_name=p_name,
        description="A cool testing website",
        include_canvas=True
    )
    assert "successfully generate" in res
    target_dir = os.path.join(website_builder_tools.OUTPUT_BASE_DIR, p_name)
    assert os.path.exists(os.path.join(target_dir, "index.html"))
    assert os.path.exists(os.path.join(target_dir, "style.css"))
    assert os.path.exists(os.path.join(target_dir, "app.js"))

    # Cleanup test output
    shutil.rmtree(target_dir, ignore_errors=True)

@pytest.mark.asyncio
async def test_preview_website(monkeypatch):
    monkeypatch.setattr(website_builder_tools.webbrowser, "open", lambda *args, **kw: True)
    # create temporary folder
    p_name = "preview_test"
    target_dir = os.path.join(website_builder_tools.OUTPUT_BASE_DIR, p_name)
    os.makedirs(target_dir, exist_ok=True)
    with open(os.path.join(target_dir, "index.html"), "w") as f:
        f.write("<h1>Test</h1>")

    try:
        res = await website_builder_tools.preview_website(p_name)
        assert "browser mein open" in res
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 4. WhatsApp Extensions
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_whatsapp_extensions(monkeypatch):
    monkeypatch.setattr(whatsapp_tools, "_focus_whatsapp", lambda: True)
    monkeypatch.setattr(whatsapp_tools, "_search_and_open_chat", lambda c: True)
    monkeypatch.setattr(whatsapp_tools, "human_like_type", lambda text: None)

    res_open = await whatsapp_tools.whatsapp_open_chat("Rahul")
    assert "chat for 'Rahul' open kar diya hai" in res_open

    res_draft = await whatsapp_tools.whatsapp_draft_message("Rahul", "Meeting at 5pm")
    assert "Draft message for 'Rahul'" in res_draft

    res_call = await whatsapp_tools.whatsapp_call("Rahul", call_type="video")
    assert "Video Call request initiate" in res_call


# ---------------------------------------------------------------------------
# 5. System Volume and Screen Brightness Controls
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_volume_and_brightness_controls(monkeypatch):
    monkeypatch.setattr(environment_tools, "_get_volume", lambda: (75, False))
    monkeypatch.setattr(environment_tools, "_set_volume", lambda lvl: True)
    monkeypatch.setattr(environment_tools, "_set_mute", lambda m: True)
    monkeypatch.setattr(environment_tools.sbc, "get_brightness", lambda: [60])
    monkeypatch.setattr(environment_tools.sbc, "set_brightness", lambda lvl: None)

    res_vol = await environment_tools.get_system_volume()
    assert "75%" in res_vol

    res_adj_vol = await environment_tools.adjust_system_volume(10)
    assert "badha diya hai (ab 85% par hai)" in res_adj_vol

    res_mute = await environment_tools.mute_system_volume(True)
    assert "mute kar diya hai" in res_mute

    res_bright = await environment_tools.get_screen_brightness()
    assert "60%" in res_bright

    res_adj_bright = await environment_tools.adjust_screen_brightness(-20)
    assert "kam kar di hai (ab 40% par hai)" in res_adj_bright


# ---------------------------------------------------------------------------
# 6. Power Manager
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_power_manager(monkeypatch):
    # Unconfirmed operations should request confirmation
    res_unconfirmed_shut = await power_tools.power_shutdown(confirmed=False)
    assert "Confirmation" in res_unconfirmed_shut or "Confirm" in res_unconfirmed_shut

    res_unconfirmed_rest = await power_tools.power_restart(confirmed=False)
    assert "Confirmation" in res_unconfirmed_rest or "Confirm" in res_unconfirmed_rest

    # Confirmed operations mock subprocess execution
    monkeypatch.setattr(power_tools, "_run_cmd_safe", lambda args: (0, "", ""))

    res_shut = await power_tools.power_shutdown(confirmed=True, delay_seconds=60)
    assert "60 seconds mein shutdown" in res_shut

    res_status = await power_tools.power_get_status()
    assert "shutdown" in res_status

    res_cancel = await power_tools.power_cancel_scheduled_shutdown()
    assert "cancel kar diya gaya hai" in res_cancel


# ---------------------------------------------------------------------------
# 7. OCR Screen Text & Safety Checks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_human_click_destructive_safety():
    res = await human_computer_tools.human_click_element("Delete database table")
    assert "SAFETY BLOCK" in res
    assert "consequential/destructive" in res

@pytest.mark.asyncio
async def test_read_screen_text(monkeypatch):
    monkeypatch.setattr(vision_tools, "_get_gemini_vision_response", AsyncMock(return_value="Detected text: print('Hello')"))
    res = await vision_tools.read_screen_text("terminal")
    assert "Detected text" in res


# ---------------------------------------------------------------------------
# 8. Support Tickets (SQLite)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_support_tickets_lifecycle():
    res_create = await support_ticket_tools.create_support_ticket(
        subject="Test Bug",
        description="Audio device not found",
        contact_email="dev@example.com",
        priority="high"
    )
    assert "Support Ticket #" in res_create
    tid = res_create.split("Support Ticket #")[1].split(" ")[0].strip()

    res_list = await support_ticket_tools.list_support_tickets(status_filter="all", limit=5)
    assert tid in res_list

    res_get = await support_ticket_tools.get_support_ticket(tid)
    assert "Test Bug" in res_get
    assert "Audio device not found" in res_get

    res_update = await support_ticket_tools.update_ticket_status(tid, "resolved", "Fixed in patch")
    assert "RESOLVED" in res_update


# ---------------------------------------------------------------------------
# 9. SMTP Email Automation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_email_draft_and_send(monkeypatch):
    res_draft = await email_tools.draft_email("boss@example.com", "Project Status", "Everything is working.")
    assert "Email draft prepare" in res_draft

    res_get = await email_tools.get_email_draft()
    assert "boss@example.com" in res_get
    assert "Project Status" in res_get

    # Unconfirmed send
    res_unconfirmed = await email_tools.send_email(confirmed=False)
    assert "Confirmation Required" in res_unconfirmed

    # Confirmed send with missing credentials
    monkeypatch.setenv("SMTP_HOST", "")
    res_missing_cred = await email_tools.send_email(confirmed=True)
    assert "SMTP configuration missing" in res_missing_cred


# ---------------------------------------------------------------------------
# 10. Spotify Integration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spotify_integration(monkeypatch):
    monkeypatch.setattr(spotify_tools.webbrowser, "open", lambda *a, **k: True)

    res_search = await spotify_tools.spotify_search("Kesariya")
    assert "Spotify" in res_search

    res_play = await spotify_tools.spotify_play("Kesariya")
    assert "Spotify" in res_play

    res_control = await spotify_tools.spotify_playback_control("pause")
    assert "credentials" in res_control or "pause" in res_control


# ---------------------------------------------------------------------------
# 11. Windows Network Manager (netsh)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_network_manager(monkeypatch):
    mock_interface = """
There is 1 interface on the system: 
    Name                   : Wi-Fi
    Description            : Intel Wi-Fi 6
    State                  : connected
    SSID                   : HomeNetwork-5G
    Signal                 : 95%
"""
    monkeypatch.setattr(network_tools, "_run_netsh", lambda args: (0, mock_interface, ""))

    res_status = await network_tools.get_wifi_status()
    assert "HomeNetwork-5G" in res_status
    assert "95%" in res_status

    # Disconnect requires confirmation
    res_disc_unconfirmed = await network_tools.disconnect_wifi(confirmed=False)
    assert "Caution" in res_disc_unconfirmed


# ---------------------------------------------------------------------------
# 12. Windows Defender
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_defender_tools(monkeypatch):
    def mock_ps(cmd):
        if "Get-MpComputerStatus" in cmd:
            return 0, '{"AntivirusEnabled": true, "RealTimeProtectionEnabled": true, "AntispywareSignatureVersion": "1.461.163.0"}', ""
        elif "Get-MpThreatDetection" in cmd:
            return 0, "[]", ""
        return 0, "", ""

    monkeypatch.setattr(defender_tools, "_run_ps_safe", mock_ps)

    res_status = await defender_tools.get_defender_status()
    assert "Windows Defender Status" in res_status
    assert "Real-time Protection: Active" in res_status

    res_threats = await defender_tools.get_defender_threats()
    assert "safe" in res_threats.lower()


# ---------------------------------------------------------------------------
# 13. Tool Registration & Integrity in agent.py
# ---------------------------------------------------------------------------
def test_all_expanded_tools_registered_in_core_tools():
    """Verify all requested core tools are properly registered in agent.CORE_TOOLS."""
    required_core_tools = [
        # Audio / Brightness
        environment_tools.get_system_volume,
        environment_tools.adjust_system_volume,
        environment_tools.mute_system_volume,
        environment_tools.get_screen_brightness,
        environment_tools.adjust_screen_brightness,
        # Power
        power_tools.power_shutdown,
        power_tools.power_restart,
        power_tools.power_sleep,
        power_tools.power_hibernate,
        power_tools.power_cancel_scheduled_shutdown,
        power_tools.power_get_status,
        # Code
        code_assistant_tools.explain_code,
        code_assistant_tools.analyze_error_and_suggest_fix,
        code_assistant_tools.apply_code_fix,
        code_assistant_tools.read_clipboard_text,
        code_assistant_tools.solve_coding_problem,
        # Website
        website_builder_tools.build_website_template,
        website_builder_tools.preview_website,
        # Email & Tickets
        email_tools.draft_email,
        email_tools.send_email,
        support_ticket_tools.create_support_ticket,
        support_ticket_tools.list_support_tickets,
        # Spotify & Network
        spotify_tools.spotify_search,
        spotify_tools.spotify_play,
        network_tools.get_wifi_status,
        network_tools.list_wifi_networks,
        network_tools.connect_wifi_profile,
        # WhatsApp extensions
        whatsapp_tools.whatsapp_open_chat,
        whatsapp_tools.whatsapp_draft_message,
        whatsapp_tools.whatsapp_call,
    ]
    for t in required_core_tools:
        assert t in agent.CORE_TOOLS, f"Tool {getattr(t, '__name__', str(t))} missing from CORE_TOOLS"

def test_extended_tools_registration():
    """Verify extended tools are properly registered in agent.EXTENDED_TOOLS."""
    required_ext_tools = [
        vision_tools.read_screen_text,
        code_assistant_tools.generate_unit_tests,
        defender_tools.get_defender_status,
        defender_tools.run_defender_quick_scan,
        defender_tools.scan_file_with_defender,
        defender_tools.get_defender_threats,
    ]
    for t in required_ext_tools:
        assert t in agent.EXTENDED_TOOLS, f"Tool {getattr(t, '__name__', str(t))} missing from EXTENDED_TOOLS"
