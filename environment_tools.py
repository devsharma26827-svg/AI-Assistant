import logging
import screen_brightness_control as sbc
from livekit.agents import function_tool
from tool_serializer import serialized_tool
from memory_store import memory

# Setup Logger
logger = logging.getLogger("environment_tools")
logger.setLevel(logging.INFO)

# --- Volume Control (PyCAW) ---
try:
    from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    import math

    def _set_volume(level_percent: int):
        # PyCAW talks to Windows audio over COM. When this runs on a worker
        # thread (asyncio.to_thread / run_in_executor) that thread has no COM
        # apartment initialised, and every call fails with a COM error — this
        # is why volume control failed while brightness (no COM) worked.
        # Initialise COM for this thread, and always uninitialise afterwards.
        CoInitialize()
        try:
            speakers = AudioUtilities.GetSpeakers()
            if not speakers:
                return False
            # Newer pycaw returns an AudioDevice wrapper (no .Activate); older
            # versions return the raw IMMDevice pointer. Support both.
            dev = speakers if hasattr(speakers, "Activate") else getattr(speakers, "_dev", speakers)
            if not dev:
                return False
            interface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)

            # SetMasterVolumeLevelScalar takes 0.0 - 1.0
            scalar = max(0.0, min(1.0, level_percent / 100.0))
            volume.SetMasterVolumeLevelScalar(scalar, None)
            return True
        finally:
            try:
                CoUninitialize()
            except Exception:
                pass

    def _get_volume() -> tuple[int, bool]:
        CoInitialize()
        try:
            speakers = AudioUtilities.GetSpeakers()
            if not speakers:
                return 50, False
            dev = speakers if hasattr(speakers, "Activate") else getattr(speakers, "_dev", speakers)
            if not dev:
                return 50, False
            interface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            cur = round(volume.GetMasterVolumeLevelScalar() * 100)
            mute = bool(volume.GetMute())
            return cur, mute
        finally:
            try:
                CoUninitialize()
            except Exception:
                pass

    def _set_mute(mute: bool) -> bool:
        CoInitialize()
        try:
            speakers = AudioUtilities.GetSpeakers()
            if not speakers:
                return False
            dev = speakers if hasattr(speakers, "Activate") else getattr(speakers, "_dev", speakers)
            if not dev:
                return False
            interface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume = interface.QueryInterface(IAudioEndpointVolume)
            volume.SetMute(1 if mute else 0, None)
            return True
        finally:
            try:
                CoUninitialize()
            except Exception:
                pass
except ImportError:
    logger.error("PyCAW not found. Volume control will fail.")
    def _get_volume() -> tuple[int, bool]:
        return 50, False
    def _set_mute(mute: bool) -> bool:
        return False
    def _set_volume(level_percent: int):
        return False

@function_tool
@serialized_tool("set_system_volume")
async def set_system_volume(level: int, step: int = 1, total_steps: int = 1) -> str:
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
            return f"done: Volume set to {level}%."
        else:
            return "failed: Volume control failed (Audio device or dependency missing)."
    except Exception as e:
        logger.error(f"set_system_volume failed: {e}")
        return f"❌ Error setting volume: {e}"

@function_tool
@serialized_tool("set_screen_brightness")
async def set_screen_brightness(level: int, step: int = 1, total_steps: int = 1) -> str:
    """
    Sets the primary screen brightness to a specific percentage (0-100).
    """
    import asyncio
    try:
        level = max(0, min(100, int(level)))
        # Offload blocking DDC/CI call
        await asyncio.to_thread(sbc.set_brightness, level)
        return f"done: Brightness set to {level}%."
    except Exception as e:
        return f"failed: Failed to set brightness ({level}%): {e}. Note: External monitors or some laptop displays do not support DDC/CI software brightness control."


@function_tool
async def get_system_volume() -> str:
    """
    Reads and reports the current system master volume percentage and mute status.
    """
    import asyncio
    try:
        vol, muted = await asyncio.to_thread(_get_volume)
        mute_status = " (Muted)" if muted else ""
        return f"🔊 Current system volume: {vol}%{mute_status}."
    except Exception as e:
        logger.error(f"get_system_volume failed: {e}")
        return f"❌ Volume read error: {e}"


@function_tool
@serialized_tool("adjust_system_volume")
async def adjust_system_volume(delta_percent: int, step: int = 1, total_steps: int = 1) -> str:
    """
    Increases or decreases system volume by a relative percentage (e.g. +10, -20).
    """
    import asyncio
    try:
        current_vol, _ = await asyncio.to_thread(_get_volume)
        new_vol = max(0, min(100, current_vol + int(delta_percent)))
        success = await asyncio.to_thread(_set_volume, new_vol)
        if success:
            direction = "badha" if delta_percent > 0 else "kam kar"
            return f"done: Volume {abs(delta_percent)}% {direction} diya hai (ab {new_vol}% par hai)."
        return "failed: Volume adjust karne mein error aaya."
    except Exception as e:
        logger.error(f"adjust_system_volume failed: {e}")
        return f"❌ Error adjusting volume: {e}"


@function_tool
@serialized_tool("mute_system_volume")
async def mute_system_volume(mute: bool = True, step: int = 1, total_steps: int = 1) -> str:
    """
    Mutes or unmutes the system master audio.
    """
    import asyncio
    try:
        success = await asyncio.to_thread(_set_mute, mute)
        if success:
            action = "mute" if mute else "unmute"
            return f"done: System audio {action} kar diya hai."
        return "failed: Audio mute/unmute control failed."
    except Exception as e:
        logger.error(f"mute_system_volume failed: {e}")
        return f"❌ Error toggling mute: {e}"


@function_tool
async def get_screen_brightness() -> str:
    """
    Reads and reports the current primary display brightness percentage.
    """
    import asyncio
    try:
        brightness_list = await asyncio.to_thread(sbc.get_brightness)
        if brightness_list and isinstance(brightness_list, list):
            b_val = brightness_list[0]
            return f"🔆 Current screen brightness: {b_val}%."
        elif isinstance(brightness_list, int):
            return f"🔆 Current screen brightness: {brightness_list}%."
        return "ℹ Screen brightness read nahi ho saki (display DDC/CI unsupported ho sakta hai)."
    except Exception as e:
        logger.error(f"get_screen_brightness failed: {e}")
        return f"❌ Brightness check error: {e}. Note: External monitors may not support DDC/CI."


@function_tool
@serialized_tool("adjust_screen_brightness")
async def adjust_screen_brightness(delta_percent: int, step: int = 1, total_steps: int = 1) -> str:
    """
    Increases or decreases screen brightness by a relative percentage (e.g. +20, -15).
    """
    import asyncio
    try:
        brightness_list = await asyncio.to_thread(sbc.get_brightness)
        current_b = 50
        if brightness_list and isinstance(brightness_list, list):
            current_b = brightness_list[0]
        elif isinstance(brightness_list, int):
            current_b = brightness_list

        new_b = max(0, min(100, current_b + int(delta_percent)))
        await asyncio.to_thread(sbc.set_brightness, new_b)
        direction = "badha" if delta_percent > 0 else "kam kar"
        return f"✅ Brightness {abs(delta_percent)}% {direction} di hai (ab {new_b}% par hai)."
    except Exception as e:
        logger.error(f"adjust_screen_brightness failed: {e}")
        return f"❌ Error adjusting brightness: {e}."

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
    def apply_settings():
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
                except Exception as e:
                    logger.warning(f"activate_mode: brightness change failed: {e}")
                
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
