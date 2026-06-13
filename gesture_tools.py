import os
import sys
import subprocess
import logging
import asyncio
from livekit.agents import function_tool

logger = logging.getLogger("gesture_tools")

# Path to the gesture project's entry point
GESTURE_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Control_pc_using_Hand-Gesture")
GESTURE_MAIN   = os.path.join(GESTURE_FOLDER, "main_v3.py")

# Global reference to the running subprocess
_gesture_process: subprocess.Popen = None


@function_tool
async def toggle_gesture_mode(action: str) -> str:
    """
    Turns hand gesture PC control ON or OFF.

    Arguments:
    - action: "on" to start gesture mode, "off" to stop it.

    Examples:
    - "gestures mode on"
    - "gestures mode off"
    - "hand control band karo"
    """
    global _gesture_process
    action = action.lower().strip()

    if action in ["on", "start", "enable", "chalu", "on karo", "activate"]:
        # Already running?
        if _gesture_process is not None and _gesture_process.poll() is None:
            return "⚠️ Gesture mode is already running. Hand gestures se PC control ho raha hai."

        # Pick Python executable — prefer the venv inside the gesture folder
        gesture_venv_python = os.path.join(GESTURE_FOLDER, "venv", "Scripts", "python.exe")
        if not os.path.exists(gesture_venv_python):
            gesture_venv_python = sys.executable  # Fall back to current Python

        if not os.path.exists(GESTURE_MAIN):
            return f"❌ Gesture main file not found at: {GESTURE_MAIN}"

        try:
            _gesture_process = subprocess.Popen(
                [gesture_venv_python, GESTURE_MAIN],
                cwd=GESTURE_FOLDER,
                creationflags=subprocess.CREATE_NEW_CONSOLE  # Windows: opens in a new console window
            )
            await asyncio.sleep(1)  # Brief pause to let process start
            if _gesture_process.poll() is not None:
                return "❌ Gesture mode failed to start. Please check the gesture folder's dependencies."
            return "✅ Gesture mode ON! Ab aap haath ke gestures se PC control kar sakte hain. Rokne ke liye 'gesture mode off' bolein."
        except Exception as e:
            logger.error(f"Failed to start gesture process: {e}")
            return f"❌ Gesture mode start nahi hua: {e}"

    elif action in ["off", "stop", "disable", "band", "band karo", "deactivate"]:
        if _gesture_process is None or _gesture_process.poll() is not None:
            _gesture_process = None
            return "⚠️ Gesture mode pehle se off hai."

        try:
            _gesture_process.terminate()
            await asyncio.sleep(0.5)
            if _gesture_process.poll() is None:
                _gesture_process.kill()  # Force kill if still running
            _gesture_process = None
            return "✅ Gesture mode OFF! Hand gesture control band ho gaya."
        except Exception as e:
            logger.error(f"Failed to stop gesture process: {e}")
            return f"❌ Gesture mode band nahi hua: {e}"

    elif action in ["status", "check"]:
        if _gesture_process is not None and _gesture_process.poll() is None:
            return "✅ Gesture mode is currently ACTIVE and running."
        return "⭕ Gesture mode is currently OFF."

    else:
        return "⚠️ Samjha nahi. Bolo 'gesture mode on' ya 'gesture mode off'."
