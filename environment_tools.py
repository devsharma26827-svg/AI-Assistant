import logging
import screen_brightness_control as sbc
from livekit.agents import function_tool
from memory_store import MemoryStore

# Setup Logger
logger = logging.getLogger("environment_tools")
logger.setLevel(logging.INFO)

# Initialize Memory
memory = MemoryStore()

# --- Volume Control (PyCAW) ---
try:
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    import math

    def _set_volume(level_percent: int):
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = interface.QueryInterface(IAudioEndpointVolume)
        
        # PyCAW uses dB, but we want scalar 0.0 to 1.0 mapped to percent
        # Actually SetMasterVolumeLevelScalar is easier: 0.0 to 1.0
        scalar = max(0.0, min(1.0, level_percent / 100.0))
        volume.SetMasterVolumeLevelScalar(scalar, None)
        return True
except ImportError:
    logger.error("PyCAW not found. Volume control will fail.")
    def _set_volume(level_percent: int):
        return False

@function_tool
async def set_system_volume(level: int) -> str:
    """
    Sets the system master volume to a specific percentage (0-100).
    """
    import asyncio
    try:
        if level < 0: level = 0
        if level > 100: level = 100
        
        # Offload blocking PyCAW call
        success = await asyncio.to_thread(_set_volume, level)
        
        if success:
            return f"✅ Volume set to {level}%."
        else:
            return "❌ Volume control failed (Dependency missing?)."
    except Exception as e:
        return f"❌ Error setting volume: {e}"

@function_tool
async def set_screen_brightness(level: int) -> str:
    """
    Sets the primary screen brightness to a specific percentage (0-100).
    """
    import asyncio
    try:
        # Offload blocking DDC/CI call
        await asyncio.to_thread(sbc.set_brightness, level)
        return f"✅ Brightness set to {level}%."
    except Exception as e:
        return f"❌ Failed to set brightness: {e}"

@function_tool
async def activate_mode(mode_name: str) -> str:
    """
    Activates a predefined environment mode (focus, relax, meeting, coding, normal).
    Adjusts volume, brightness and logs the state.
    """
    import asyncio
    mode_name = mode_name.lower().strip()
    
    # 1. Update Memory
    memory.set_active_mode(mode_name)
    
    # 2. Get Preferences
    prefs = memory.get_mode_preferences(mode_name)
    
    actions_taken = []
    
    # 3. Apply Settings (Wrap blocking calls)
    async def apply_settings():
        if not prefs:
            if mode_name == "focus":
                _set_volume(0)
                actions_taken.append("Muted Volume")
            elif mode_name == "relax":
                sbc.set_brightness(40)
                _set_volume(30)
                actions_taken.append("Dimmed Screen, Low Volume")
            elif mode_name == "meeting":
                _set_volume(80)
                actions_taken.append("High Volume")
            elif mode_name == "normal":
                sbc.set_brightness(100)
                _set_volume(50)
                actions_taken.append("Reset Brightness/Volume")
        else:
            if "volume" in prefs:
                _set_volume(prefs["volume"])
                actions_taken.append(f"Volume {prefs['volume']}%")
                
            if "brightness" in prefs:
                try:
                    sbc.set_brightness(prefs["brightness"])
                    actions_taken.append(f"Brightness {prefs['brightness']}%")
                except: pass
                
    await asyncio.to_thread(apply_settings)
            
    return f"✅ Activated '{mode_name}' mode. Actions: {', '.join(actions_taken)}."

@function_tool
async def get_environment_state() -> str:
    """
    Returns the current active mode.
    """
    # Simple memory read, but async for consistency
    import asyncio
    await asyncio.sleep(0.01) # Yield
    mode = memory.get_active_mode()
    return f"Current Environment Mode: {mode}"
