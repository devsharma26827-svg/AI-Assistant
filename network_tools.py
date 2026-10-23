"""
Windows Network and Wi-Fi Management Tools for Cynthia AI Assistant.
Provides safe Wi-Fi status inspection, nearby network discovery, profile listing,
and profile connection/disconnection via Windows netsh (strictly no password exposure).
"""
import asyncio
import re
import logging
import subprocess
from livekit.agents import function_tool

logger = logging.getLogger("network_tools")
logger.setLevel(logging.INFO)


def _run_netsh(args: list[str]) -> tuple[int, str, str]:
    """Runs a netsh command safely with argument list (shell=False)."""
    try:
        cmd = ["netsh"] + args
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10, shell=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


@function_tool
async def get_wifi_status() -> str:
    """
    Checks and reports current Wi-Fi connection status, connected SSID, signal strength, and state.
    """
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_netsh, ["wlan", "show", "interfaces"])

    if code != 0:
        return f"❌ Wi-Fi status check failed: {err or out}"

    # Parse key status attributes
    ssid_match = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
    state_match = re.search(r"^\s*State\s*:\s*(.+)$", out, re.MULTILINE)
    signal_match = re.search(r"^\s*Signal\s*:\s*(.+)$", out, re.MULTILINE)
    radio_match = re.search(r"^\s*Radio status\s*:\s*(.+)$", out, re.MULTILINE)

    state = state_match.group(1).strip() if state_match else "Unknown"
    ssid = ssid_match.group(1).strip() if ssid_match else "Disconnected"
    signal = signal_match.group(1).strip() if signal_match else "N/A"

    if state.lower() == "connected":
        return f"📶 Wi-Fi Status: Connected to '{ssid}' | Signal Strength: {signal}."
    else:
        return f"📶 Wi-Fi Status: {state.capitalize()} (No active network connected)."


@function_tool
async def list_wifi_networks() -> str:
    """
    Scans and lists nearby visible Wi-Fi networks with their SSIDs and signal strength.
    """
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_netsh, ["wlan", "show", "networks"])

    if code != 0:
        return f"❌ Wi-Fi networks scan failed: {err or out}"

    ssids = re.findall(r"SSID \d+ : (.+)", out)
    signals = re.findall(r"Signal\s*:\s*(\d+%)", out)

    if not ssids:
        return "ℹ Aas-paas koi visible Wi-Fi network nahi mila."

    lines = [f"🌐 Nearby Wi-Fi Networks ({len(ssids)} found):"]
    for i, ssid in enumerate(ssids[:8]):
        sig = signals[i] if i < len(signals) else "N/A"
        clean_ssid = ssid.strip() or "(Hidden Network)"
        lines.append(f"• {clean_ssid} - Signal: {sig}")

    return "\n".join(lines)


@function_tool
async def list_saved_wifi_profiles() -> str:
    """
    Lists saved Wi-Fi network profiles on this Windows PC (strictly without passwords).
    """
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_netsh, ["wlan", "show", "profiles"])

    if code != 0:
        return f"❌ Saved Wi-Fi profiles read error: {err or out}"

    profiles = re.findall(r"All User Profile\s*:\s*(.+)", out)
    if not profiles:
        return "ℹ System par koi saved Wi-Fi profile nahi mila."

    lines = [f"💾 Saved Wi-Fi Profiles ({len(profiles)}):"]
    for p in profiles:
        lines.append(f"• {p.strip()}")

    return "\n".join(lines)


@function_tool
async def connect_wifi_profile(profile_name: str) -> str:
    """
    Connects to a saved Wi-Fi network profile by name.
    
    Parameters:
    - profile_name: Name of the saved Wi-Fi profile (e.g. 'Home-WiFi', 'Office-5G').
    """
    name = (profile_name or "").strip()
    if not name:
        return "❌ Profile name khaali nahi ho sakta."

    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_netsh, ["wlan", "connect", f"name={name}"])

    if code == 0:
        return f"✅ Boss, '{name}' Wi-Fi profile se connection request initiate kar di hai."
    return f"❌ Connection failed: {err or out}"


@function_tool
async def disconnect_wifi(confirmed: bool = False) -> str:
    """
    Disconnects the active Wi-Fi connection.
    
    IMPORTANT: Requires confirmed=True because disconnecting will terminate active internet connection.
    """
    if not confirmed:
        return (
            "⚠ Caution: Wi-Fi disconnect karne se Cynthia ka live voice session aur internet disconnect ho sakta hai. "
            "Kya aap sach mein disconnect karna chahte hain? Kripya 'Confirm disconnect' bolein."
        )

    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_netsh, ["wlan", "disconnect"])

    if code == 0:
        return "✅ Wi-Fi disconnect kar diya gaya hai."
    return f"❌ Disconnect failed: {err or out}"
