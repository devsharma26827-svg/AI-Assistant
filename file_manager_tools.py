import os
import asyncio
import logging
import time
import pyautogui
from datetime import datetime
from livekit.agents import function_tool
from memory_store import MemoryStore
from system_control_tools import focus_window, open_app

# Initialize Memory
memory = MemoryStore()
logger = logging.getLogger("file_manager")

@function_tool
async def save_file_as(file_name: str, folder: str = "Documents") -> str:
    r"""
    Saves the CURRENTLY OPEN document/code (in Notepad, VS Code, etc.) to a file.
    Uses 'Ctrl+Shift+S' (Save As) automation.
    
    Arguments:
    - file_name: Name of the file (e.g., "story.txt", "main.py").
    - folder: Folder to save in (e.g., "Desktop", "Documents", "D:\Projects").
    """
    try:
        # 1. Determine Path
        # Handle common folders
        if folder.lower() in ["desktop", "documents", "downloads"]:
            user_profile = os.environ.get("USERPROFILE", "C:\\")
            target_dir = os.path.join(user_profile, folder.capitalize())
        elif ":" in folder: # Absolute path
            target_dir = folder
        else:
            # Default to Documents if unsure
            target_dir = os.path.join(os.environ.get("USERPROFILE"), "Documents")
            
        full_path = os.path.join(target_dir, file_name)

        # SAFETY: refuse to silently clobber an existing file. The Save-As
        # dialog raises a "confirm overwrite" prompt, and blindly pressing
        # Enter through it destroyed a user's existing file during testing.
        if os.path.exists(full_path):
            return (
                f"⚠ '{file_name}' already exists in {target_dir}. I haven't saved "
                f"anything. Tell me a different name, or say \"overwrite kar do\" "
                f"if you want me to replace it."
            )

        # 2. Automate Save Dialog
        # Assume user is ALREADY in the editor (Context continuity)
        def _save():
            # Press Save As Shortcut
            # Notepad / Common Apps: Ctrl + Shift + S or Ctrl + S (if new)
            # We'll use Ctrl + Shift + S first (safer for Save As)
            pyautogui.hotkey('ctrl', 'shift', 's')
            time.sleep(1.5)  # Wait for dialog

            # Type Path
            pyautogui.write(full_path, interval=0.01)
            time.sleep(0.5)
            pyautogui.press('enter')

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _save)

        # Wait for the file to actually land on disk before claiming success.
        saved = False
        for _ in range(8):
            await asyncio.sleep(0.4)
            if os.path.exists(full_path):
                saved = True
                break

        if not saved:
            return (
                f"❌ I ran Save As for {full_path}, but the file didn't appear on disk. "
                f"The app may not support Ctrl+Shift+S, or a dialog is still open — "
                f"please check the screen."
            )

        # 3. Update Memory
        memory.set_active_file(full_path)
        memory.log_interaction("save_file_as", f"Saved file: {file_name}")

        return f"✅ File saved to: {full_path}"
        
    except Exception as e:
        return f"❌ Failed to save file: {e}"

@function_tool
async def open_current_file() -> str:
    """
    Opens the file that was most recently saved or worked on.
    Uses context memory.
    """
    path = memory.get_active_file()
    if not path:
        return "❌ I don't remember any active file context. Please tell me the filename."
        
    if not os.path.exists(path):
        return f"❌ The last file '{path}' no longer exists."
        
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, os.startfile, path)
        memory.log_interaction("open_current_file", f"Opened file: {os.path.basename(path)}")
        return f"✅ Opened active file: {os.path.basename(path)}"
    except Exception as e:
        return f"❌ Failed to open file: {e}"
