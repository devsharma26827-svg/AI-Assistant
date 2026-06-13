import requests
import json
import logging
import asyncio
from livekit.agents import function_tool

logger = logging.getLogger("distributed_tools")
logger.setLevel(logging.INFO)

BRAIN_URL = "http://localhost:8000"

async def _make_request(method, url, **kwargs):
    """Helper to run blocking requests in a thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: requests.request(method, url, **kwargs))

@function_tool
async def list_ecosystem_devices() -> str:
    """
    Fetches a list of all devices currently connected to the Jarvis Brain (Ecosystem).
    Returns a string summary of devices and their capabilities.
    """
    try:
        response = await _make_request("POST", f"{BRAIN_URL}/devices")
        if response.status_code == 200:
            devices = response.json().get("devices", [])
            if not devices:
                return "No ecosystem devices are currently connected."
            
            summary = "🌐 **Ecosystem Devices Found:**\n"
            for d in devices:
                status = d.get("status", "unknown")
                summary += f"- **{d['name']}** ({d['device_type']}) [{status}]\n"
                summary += f"  ID: {d['device_id']}\n"
                summary += f"  Caps: {', '.join(d['capabilities'])}\n"
            return summary
        else:
            return f"Error connecting to Brain: {response.status_code}"
    except Exception as e:
        return f"Failed to reach Brain: {e}"

@function_tool
async def send_command_to_device(target_device_id: str, action: str, params_json: str = "{}") -> str:
    """
    Sends a command to a specific device via the Jarvis Brain.
    
    Args:
        target_device_id: The ID of the device (from list_ecosystem_devices)
        action: The action to perform (e.g., 'call', 'shell', 'popup')
        params_json: JSON string of parameters (e.g., '{"number": "123"}', '{"cmd": "dir"}')
    """
    try:
        if not target_device_id:
            return "Error: target_device_id is required."

        params = json.loads(params_json)
        payload = {
            "target_device_id": target_device_id,
            "action": action,
            "params": params
        }
        response = await _make_request("POST", f"{BRAIN_URL}/command", json=payload)
        
        if response.status_code == 200:
            return f"✅ Command '{action}' sent to {target_device_id}."
        elif response.status_code == 404:
            return f"❌ Device '{target_device_id}' not found or offline."
        else:
            return f"❌ Error sending command: {response.text}"
    except json.JSONDecodeError:
        return "Error: params_json must be a valid JSON string."
    except Exception as e:
        return f"Failed to reach Brain: {e}"

@function_tool
async def broadcast_command(action: str, params_json: str = "{}") -> str:
    """
    Sends a command to ALL connected devices.
    
    Args:
        action: The action to perform (e.g., 'popup')
        params_json: JSON string of parameters (e.g., '{"text": "Hello Everyone"}')
    """
    try:
        params = json.loads(params_json)
        payload = {
            "action": action,
            "params": params
        }
        response = await _make_request("POST", f"{BRAIN_URL}/broadcast", json=payload)
        if response.status_code == 200:
            return f"✅ Broadcast '{action}' sent to all devices."
        else:
            return f"❌ Error broadcasting: {response.text}"
    except json.JSONDecodeError:
        return "Error: params_json must be a valid JSON string."
    except Exception as e:
        return f"Failed to reach Brain: {e}"

@function_tool
async def find_device_for_capability(capability: str) -> str:
    """
    Finds which connected device has a specific capability (e.g., 'call', 'camera', 'shell').
    """
    try:
        response = await _make_request("POST", f"{BRAIN_URL}/find_device", params={"capability": capability})
        if response.status_code == 200:
            devices = response.json().get("devices", [])
            if not devices:
                return f"No devices found with capability: {capability}"
            
            summary = f"Devices with '{capability}':\n"
            for d in devices:
                summary += f"- {d['name']} ({d['device_id']})\n"
            return summary
        else:
            return f"Error querying Brain: {response.status_code}"
    except Exception as e:
        return f"Failed to reach Brain: {e}"
