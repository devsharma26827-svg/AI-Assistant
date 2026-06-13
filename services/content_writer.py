import asyncio
import logging
import pyautogui
from livekit.agents import function_tool
from utils.system_control import open_app, focus_window
import win32clipboard
from src.memory_store import MemoryStore

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
            
        # 3. Type Content
        if len(content) < 200:
            pyautogui.write(content, interval=0.01)
        else:
            # Clipboard for long text to avoid errors
            copy_to_clipboard(content)
            pyautogui.hotkey('ctrl', 'v')
            
        memory.log_interaction("write_text", f"Wrote text to {app_name}: {content[:30]}...")
        return f"✅ Text written to {app_name}."

    except Exception as e:
        return f"❌ Failed to write text: {e}"

@function_tool
async def write_code(language: str, code: str, target_window: str = "new project") -> str:
    """
    Generates a coding project snippet in an editor.
    
    Arguments:
    - language: e.g., "Python", "HTML", "JavaScript"
    - code: The actual code logic relative to the request.
    - target_window: "new project" to create a new file, or a specific filename.
    """
    try:
        # 1. Open Notepad or specific existing window
        if target_window.lower() == "new project":
            await open_app("Notepad")
            await asyncio.sleep(1.5)
            pyautogui.hotkey('ctrl', 'n')
            await asyncio.sleep(0.5)
        else:
            found = await focus_window(target_window)
            if not found:
                await open_app("Notepad") # fallback
                
        await asyncio.sleep(1.0)
        
        # 2. Prepare Formatted Content
        formatted_content = f"############################################\n"
        formatted_content += f"# Language: {language}\n"
        formatted_content += f"############################################\n\n"
        formatted_content += code
        
        # 3. Paste Code
        copy_to_clipboard(formatted_content)
        pyautogui.hotkey('ctrl', 'v')
        
        memory.log_interaction("write_code", f"Generated {language} code for {target_window}")
        return f"✅ Generic {language} code generated in {target_window}."

    except Exception as e:
        return f"❌ Failed to generate code: {e}"
