import asyncio
import logging
import pyautogui
from livekit.agents import function_tool
from system_control_tools import open_app, focus_window
import win32clipboard
from memory_store import MemoryStore
from typing_utils import human_like_type

# Initialize Memory
memory = MemoryStore()

logger = logging.getLogger("content_writer")

def copy_to_clipboard(text):
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    win32clipboard.CloseClipboard()

@function_tool
async def write_text(content: str, app_name: str = "notepad", create_new_file: bool = True) -> str:
    """
    Writes dictated text into the specified application or file.
    
    Arguments:
    - content: The text content to write.
    - app_name: The editor to use ("notepad", "word", etc.) or a specific filename (e.g., "notes.txt").
    - create_new_file: If True, explicitly opens a new blank document (e.g., Ctrl+N).
    """
    try:
        # 1. Open/Focus App
        target = "Notepad" if app_name.lower() == "notepad" else app_name
        
        found = await focus_window(target)
        if not found:
            await open_app(target)
            
        await asyncio.sleep(1.5)
        
        # 2. Create New Document if requested
        if create_new_file:
            pyautogui.hotkey('ctrl', 'n')
            await asyncio.sleep(0.5)
            
        # 3. Type Content — short content is typed out character-by-character
        #    (looks like a real assistant actively working); longer content is
        #    pasted instantly instead of slowly typed out. Works for any
        #    language/script. Run off-thread since pyautogui blocks.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, human_like_type, content)

        memory.log_interaction("write_text", f"Wrote text to {app_name}: {content[:30]}...")
        return f"✅ Text written to {app_name}."

    except Exception as e:
        return f"❌ Failed to write text: {e}"

@function_tool
async def write_code(language: str, code: str, target_window: str = "") -> str:
    """
    Pastes generated code into a code editor (code is always pasted, never typed
    character-by-character, since char-by-char typing triggers editor
    autocomplete/auto-bracket-closing and corrupts the code).

    Arguments:
    - language: e.g., "Python", "HTML", "JavaScript"
    - code: The actual code logic relative to the request.
    - target_window: Leave EMPTY (default) to paste into whichever window is
      CURRENTLY focused — use this whenever the user already has an editor/new
      file open (the most common case). Pass "new notepad" to open a fresh
      blank Notepad file first. Pass any other value to switch to a specific
      already-open window by title before pasting.
    """
    try:
        tw = target_window.strip().lower()

        if tw in ("", "current", "this", "focused"):
            # Trust whatever window is currently focused — do NOT silently
            # switch to a different app. This is what "write it here" means.
            pass
        elif tw in ("new notepad", "new project", "notepad"):
            await open_app("Notepad")
            await asyncio.sleep(1.2)
            pyautogui.hotkey('ctrl', 'n')
            await asyncio.sleep(0.4)
        else:
            # SAFETY: never paste code into a window matched only by a fuzzy
            # title. Doing that once dumped a whole program into the user's
            # existing file and corrupted it. Require the caller to either
            # target the focused window or explicitly ask for a new file.
            return (
                f"❌ Refused to paste into '{target_window}' — I won't write code into an "
                f"existing window matched by name, because that can overwrite your work. "
                f"Focus the editor/tab you want and call this again with no target_window, "
                f"or pass 'new notepad' for a fresh file."
            )

        await asyncio.sleep(0.5)
        
        # 2. Prepare Formatted Content
        formatted_content = f"############################################\n"
        formatted_content += f"# Language: {language}\n"
        formatted_content += f"############################################\n\n"
        formatted_content += code
        
        # 3. Paste Code
        loop = asyncio.get_running_loop()
        def _paste_code():
            copy_to_clipboard(formatted_content)
            pyautogui.hotkey('ctrl', 'v')
        await loop.run_in_executor(None, _paste_code)
        
        memory.log_interaction("write_code", f"Generated {language} code for {target_window or 'current window'}")
        return f"✅ {language} code pasted into {'the current window' if not tw or tw in ('current','this','focused') else target_window}."

    except Exception as e:
        return f"❌ Failed to generate code: {e}"
