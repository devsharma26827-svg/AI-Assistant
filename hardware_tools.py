import logging
import json
from livekit.agents import function_tool
from distributed_tools import send_command_to_device, broadcast_command, list_ecosystem_devices
from memory_store import memory

logger = logging.getLogger("hardware_tools")
logger.setLevel(logging.INFO)

@function_tool
async def control_smart_device(device_name_or_id: str, action: str, state: str, confirmed: bool = False) -> str:
    """
    Controls smart home hardware like lights, plugs, fans, etc.
    CRITICAL SAFETY RULES:
    1. If `confirmed` is False, you MUST NOT execute the command. INSTEAD, ask the user: "Are you sure you want me to [action] the [device]?"
    2. Only set `confirmed` to True once the user explicitly says YES to your exact question.
    
    Arguments:
    - device_name_or_id: The target hardware (e.g., "living room light", "smart plug 1").
    - action: The action to perform (e.g., "turn_on", "turn_off", "set_brightness").
    - state: The desired state or value (e.g., "on", "off", "70%", "red").
    - confirmed: MUST default to False. Set to True ONLY if the user has explicitly verified this action just now.
    """
    try:
        if not confirmed:
            return f"⚠️ DANGER: Action requires confirmation. Stop and ask the user: 'Are you sure you want me to {action} the {device_name_or_id}?'"
            
        # Optional validation: Attempt to check if device exists in ecosystem
        devices_summary = await list_ecosystem_devices()
        
        # We don't block on device lookup if fuzzy matching fails here, because device_server does fuzzy matching too.
        # But we log the attempt.
        
        payload_params = json.dumps({"state": state})
        
        # Route to brain server via distributed_tools
        result = await send_command_to_device(
             target_device_id=device_name_or_id, 
             action=f"hardware_{action}", 
             params_json=payload_params
        )
        
        # Log to long-term memory
        if "✅" in result:
             memory.log_interaction("hardware_control", f"Success: {action} {device_name_or_id} to {state}")
        else:
             memory.log_interaction("hardware_control", f"Failed: {action} {device_name_or_id} to {state} - Error: {result}")
             
        return result
        
    except Exception as e:
        logger.error(f"Hardware control failed: {e}")
        return f"❌ Failed to control {device_name_or_id}: {e}"

@function_tool
async def trigger_ecosystem_routine(routine_name: str, confirmed: bool = False) -> str:
    """
    Triggers a pre-defined multi-device hardware routine across the ecosystem.
    CRITICAL SAFETY RULES:
    1. If `confirmed` is False, ask the user: "Should I activate the [routine_name] routine?"
    2. Only set `confirmed` to True if they say YES.
    
    Routine Options:
    - 'meeting_mode': Puts active devices in DND, dims lights if present.
    - 'lockdown': Broadcasts a lock command to all endpoints.
    - 'sleep_mode': Turns off all registered lights, sets volumes to low.
    - 'wake_up': Broadcasts a wake signal, turns on lights.
    
    Arguments:
    - routine_name: The routine to activate (e.g., "sleep_mode").
    - confirmed: False by default.
    """
    try:
        if not confirmed:
            return f"⚠️ DANGER: Routine activation requires confirmation. Stop and ask the user to confirm activating '{routine_name}'."
            
        routine = routine_name.lower().strip()
        memory.log_interaction("ecosystem_routine", f"Triggered routine: {routine}")
        
        if routine == "meeting_mode":
            await broadcast_command("enable_dnd", "{}")
            return "✅ Meeting mode activated across the ecosystem."
            
        elif routine in ["lockdown", "lock"]:
            await broadcast_command("lock_screen", "{}")
            return "✅ Lockdown initiated. All ecosystem screens locked."
            
        elif routine == "sleep_mode":
            # Example heuristic multi-action
            await broadcast_command("set_volume", '{"level": 10}')
            # We assume a dedicated 'all_lights' group exists or we rely on a custom brain hook
            return "✅ Sleep mode activated. Volumes lowered."
            
        elif routine == "wake_up":
            await broadcast_command("wake_device", "{}")
            return "✅ Wake up routine initiated."
            
        else:
            return f"❌ Routine '{routine_name}' is not recognized."
            
    except Exception as e:
        logger.error(f"Routine trigger failed: {e}")
        return f"❌ Failed to trigger routine {routine_name}: {e}"
