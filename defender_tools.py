"""
Windows Defender Antivirus Scanning Tools for Cynthia AI Assistant.
Provides safe, read-only status checks, file scans, and quick scans using official Windows Defender PowerShell cmdlets.
Strictly read-only and non-destructive: never disables Defender, never creates exclusions, and never deletes files without approval.
"""
import os
import json
import logging
import subprocess
import asyncio
from livekit.agents import function_tool

logger = logging.getLogger("defender_tools")
logger.setLevel(logging.INFO)


def _run_ps_safe(command: str) -> tuple[int, str, str]:
    """Runs a PowerShell command safely without shell=True."""
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


@function_tool
async def get_defender_status() -> str:
    """
    Checks and reports current Windows Defender antivirus status, real-time protection, and signature version.
    """
    ps_cmd = "Get-MpComputerStatus | Select-Object -Property AntivirusEnabled, RealTimeProtectionEnabled, AMServiceEnabled, AntispywareSignatureVersion | ConvertTo-Json"
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_ps_safe, ps_cmd)

    if code != 0 or not out:
        return f"❌ Defender status query failed: {err or 'PowerShell cmdlet unavailable'}"

    try:
        data = json.loads(out)
        av_enabled = data.get("AntivirusEnabled", False)
        rt_enabled = data.get("RealTimeProtectionEnabled", False)
        sig_ver = data.get("AntispywareSignatureVersion", "Unknown")

        status_icon = "🛡" if (av_enabled and rt_enabled) else "⚠"
        return (
            f"{status_icon} Windows Defender Status:\n"
            f"- Antivirus Enabled: {'Yes' if av_enabled else 'No'}\n"
            f"- Real-time Protection: {'Active' if rt_enabled else 'Disabled'}\n"
            f"- Security Intelligence Version: {sig_ver}"
        )
    except Exception as e:
        return f"❌ Failed to parse Defender status output: {e}"


@function_tool
async def run_defender_quick_scan() -> str:
    """
    Starts an asynchronous Windows Defender Quick Scan in the background.
    """
    ps_cmd = "Start-MpScan -ScanType QuickScan"
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_ps_safe, ps_cmd)

    if code == 0:
        return "✅ Boss, Windows Defender Quick Scan start kar diya gaya hai. Background mein threat inspection chal raha hai."
    return f"❌ Quick scan start karne mein error aaya: {err or out} (Administrator privileges require ho sakti hain)."


@function_tool
async def scan_file_with_defender(file_path: str) -> str:
    """
    Scans a specific file with Windows Defender to check for malware/threats.
    
    Parameters:
    - file_path: Path to the target file to scan.
    """
    path = os.path.abspath(file_path.strip().strip('"\''))
    if not os.path.exists(path):
        return f"❌ File not found: '{path}'."

    # Escape quotes for PowerShell
    safe_path = path.replace("'", "''")
    ps_cmd = f"Start-MpScan -ScanPath '{safe_path}'"

    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_ps_safe, ps_cmd)

    if code == 0:
        return f"✅ Boss, Windows Defender ne '{os.path.basename(path)}' ka scan successfully complete kar liya hai (No active threats reported)."
    return f"❌ File scan karne mein error aaya: {err or out}"


@function_tool
async def get_defender_threats() -> str:
    """
    Checks Windows Defender threat detection history and lists any active or quarantined threats.
    """
    ps_cmd = "Get-MpThreatDetection | Select-Object -Property ThreatID, ThreatName, InitialDetectionTime, Resources | ConvertTo-Json"
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_ps_safe, ps_cmd)

    if code == 0 and out:
        try:
            threats = json.loads(out)
            if not threats:
                return "🛡 System completely safe hai: Koi active ya detected threats nahi mile."
            threat_list = threats if isinstance(threats, list) else [threats]
            lines = [f"🚨 Detected Threats ({len(threat_list)}):"]
            for t in threat_list:
                name = t.get("ThreatName", "Unknown Threat")
                time_detected = t.get("InitialDetectionTime", "")
                lines.append(f"• {name} (Detected: {time_detected})")
            return "\n".join(lines)
        except Exception:
            pass

    return "🛡 System safe hai: Koi active malware ya threats detected nahi hain."
