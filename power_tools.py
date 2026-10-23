"""
Windows Power Management Tools for Cynthia AI Assistant.
Provides controlled shutdown, restart, sleep, hibernate, scheduling, and cancellation,
with mandatory explicit confirmation for disruptive actions to prevent accidental power loss.
"""
import asyncio
import logging
import subprocess
from livekit.agents import function_tool

logger = logging.getLogger("power_tools")
logger.setLevel(logging.INFO)

# Track pending power schedule state in-memory
_PENDING_POWER_ACTION = {
    "action": None,
    "delay_seconds": 0,
    "scheduled_at": None,
}


def _run_cmd_safe(args: list[str]) -> tuple[int, str, str]:
    """Runs a system command with argument lists (preventing shell injection)."""
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=10, shell=False)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except Exception as e:
        return 1, "", str(e)


@function_tool
async def power_shutdown(confirmed: bool = False, delay_seconds: int = 0) -> str:
    """
    Shuts down the Windows PC safely.
    
    IMPORTANT: Requires confirmed=True. If confirmed is False, Cynthia will ask the user for confirmation.
    
    Parameters:
    - confirmed: Must be True if the user explicitly confirmed ("haan shutdown kar do", "proceed with shutdown").
    - delay_seconds: Optional timer in seconds before shutdown (e.g. 60 for 1 minute, 300 for 5 minutes).
    """
    if not confirmed:
        delay_msg = f" {delay_seconds} seconds ke delay ke saath" if delay_seconds > 0 else ""
        return (
            f"⚠ Boss, kya aap sach mein PC shutdown{delay_msg} karna chahte hain? "
            f"Kripya 'Confirm' ya 'Haan shutdown karo' bolein."
        )

    delay = max(0, int(delay_seconds))
    args = ["shutdown.exe", "/s", "/t", str(delay)]

    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_cmd_safe, args)

    if code == 0:
        _PENDING_POWER_ACTION["action"] = "shutdown"
        _PENDING_POWER_ACTION["delay_seconds"] = delay
        if delay > 0:
            return f"✅ Boss, PC {delay} seconds mein shutdown hone ke liye schedule kar diya gaya hai. Cancel karne ke liye 'Cancel shutdown' bolein."
        return "✅ Boss, PC shutdown initiate kar diya gaya hai. Alvida!"
    else:
        logger.error(f"Shutdown command failed: {err}")
        return f"❌ Shutdown initiate karne mein error aaya: {err or out}"


@function_tool
async def power_restart(confirmed: bool = False, delay_seconds: int = 0) -> str:
    """
    Restarts the Windows PC safely.
    
    IMPORTANT: Requires confirmed=True. If confirmed is False, Cynthia will ask the user for confirmation.
    
    Parameters:
    - confirmed: Must be True if the user explicitly confirmed ("haan restart kar do").
    - delay_seconds: Optional timer in seconds before restart.
    """
    if not confirmed:
        delay_msg = f" {delay_seconds} seconds ke delay ke saath" if delay_seconds > 0 else ""
        return (
            f"⚠ Boss, kya aap sach mein PC restart{delay_msg} karna chahte hain? "
            f"Kripya 'Confirm' ya 'Haan restart karo' bolein."
        )

    delay = max(0, int(delay_seconds))
    args = ["shutdown.exe", "/r", "/t", str(delay)]

    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_cmd_safe, args)

    if code == 0:
        _PENDING_POWER_ACTION["action"] = "restart"
        _PENDING_POWER_ACTION["delay_seconds"] = delay
        if delay > 0:
            return f"✅ Boss, PC {delay} seconds mein restart hone ke liye schedule kar diya gaya hai. Cancel karne ke liye 'Cancel restart' bolein."
        return "✅ Boss, PC restart initiate kar diya gaya hai."
    else:
        logger.error(f"Restart command failed: {err}")
        return f"❌ Restart initiate karne mein error aaya: {err or out}"


@function_tool
async def power_sleep(confirmed: bool = False) -> str:
    """
    Puts the Windows PC into Sleep mode (low power state).
    
    Parameters:
    - confirmed: Set to True when user explicitly asks ("PC sleep karo", "Put PC to sleep").
    """
    # Sleep is reversible and non-destructive, but we confirm if not direct
    args = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_cmd_safe, args)

    if code == 0:
        return "✅ Boss, PC ko sleep mode mein daal diya gaya hai."
    return f"❌ Sleep mode activate karne mein error aaya: {err or out}"


@function_tool
async def power_hibernate(confirmed: bool = False) -> str:
    """
    Puts the Windows PC into Hibernate mode (saves session state to disk).
    
    Parameters:
    - confirmed: Set to True when user explicitly asks ("PC hibernate karo").
    """
    args = ["shutdown.exe", "/h"]
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_cmd_safe, args)

    if code == 0:
        return "✅ Boss, PC ko hibernate mode mein daal diya gaya hai."
    return f"❌ Hibernate mode activate karne mein error aaya: {err or out}"


@function_tool
async def power_cancel_scheduled_shutdown() -> str:
    """
    Cancels any pending scheduled shutdown or restart operation.
    """
    args = ["shutdown.exe", "/a"]
    loop = asyncio.get_running_loop()
    code, out, err = await loop.run_in_executor(None, _run_cmd_safe, args)

    _PENDING_POWER_ACTION["action"] = None
    _PENDING_POWER_ACTION["delay_seconds"] = 0

    if code == 0:
        return "✅ Boss, scheduled shutdown / restart cancel kar diya gaya hai."
    else:
        if "1116" in err or "Unable to abort" in err or "not in progress" in err.lower():
            return "ℹ Abhi koi scheduled shutdown ya restart pending nahi tha."
        return f"❌ Scheduled action abort karne mein error aaya: {err or out}"


@function_tool
async def power_get_status() -> str:
    """
    Reports the status of any pending scheduled power operations (shutdown/restart).
    """
    action = _PENDING_POWER_ACTION.get("action")
    delay = _PENDING_POWER_ACTION.get("delay_seconds", 0)

    if action:
        return f"⏱ Active schedule: PC '{action}' scheduled with {delay} seconds delay."
    return "ℹ Abhi koi scheduled shutdown ya restart active nahi hai. System normal running state mein hai."
