import logging
import time
import pyautogui
import pyperclip
import re
from livekit.agents import function_tool
from typing_utils import human_like_type

# Configure logging
logger = logging.getLogger("whatsapp_tools")
logger.setLevel(logging.INFO)

# --- CONFIGURATION ---
WAIT_SHORT = 0.5
WAIT_MEDIUM = 1.5
WAIT_LONG = 3.0
SEARCH_WAIT = 2.0
LOAD_WAIT = 2.0

def _is_valid_ascii(s: str) -> bool:
    """Checks if the string contains only ASCII characters."""
    try:
        s.encode('ascii')
        return True
    except UnicodeEncodeError:
        return False

def _clean_text(text: str) -> str:
    """Removes non-ASCII characters or excessive whitespace."""
    # Remove non-ascii
    return re.sub(r'[^\x00-\x7F]+', '', text).strip()

def _guard_failsafe():
    """
    PyAutoGUI aborts every action if the mouse is parked in a screen corner.
    That is a useful manual kill-switch, but it also killed a legitimate
    WhatsApp send mid-flight. Nudge the cursor out of the corner first so
    keyboard-only automation isn't blocked by where the mouse happens to sit.
    """
    try:
        width, height = pyautogui.size()
        x, y = pyautogui.position()
        margin = 5
        if x <= margin or y <= margin or x >= width - margin or y >= height - margin:
            pyautogui.moveTo(width // 2, height // 2, duration=0.1)
    except Exception as e:
        logger.debug(f"failsafe guard skipped: {e}")


def _is_whatsapp_open() -> bool:
    """Checks if WhatsApp window is present on the system."""
    try:
        import win32gui
        found = False
        def _enum(hwnd, _):
            nonlocal found
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd).lower()
                if "whatsapp" in title:
                    found = True
        win32gui.EnumWindows(_enum, None)
        return found
    except Exception:
        return True

def _focus_whatsapp():
    """Activates the WhatsApp window and verifies it is visible."""
    try:
        _guard_failsafe()
        
        # Try direct activation if already running
        try:
            import pygetwindow as gw
            windows = [w for w in gw.getWindowsWithTitle("WhatsApp") if w.visible]
            if windows:
                win = windows[0]
                if win.isMinimized:
                    win.restore()
                win.activate()
                time.sleep(WAIT_SHORT)
                return True
        except Exception:
            pass

        # Otherwise launch via Start Menu
        pyautogui.press('win')
        time.sleep(WAIT_SHORT)
        pyautogui.write('WhatsApp')
        time.sleep(WAIT_SHORT)
        pyautogui.press('enter')
        
        # Wait up to 3 seconds for WhatsApp window to appear
        for _ in range(6):
            time.sleep(0.5)
            if _is_whatsapp_open():
                time.sleep(WAIT_SHORT)
                return True
                
        logger.warning("WhatsApp window was not detected after launch attempt.")
        return False
    except Exception as e:
        logger.error(f"Failed to focus WhatsApp: {e}")
        return False

def _reset_state():
    """Resets UI state by clearing selection."""
    try:
        pyautogui.press('esc', presses=2, interval=0.2)
        time.sleep(WAIT_SHORT)
    except Exception:
        pass

def _search_and_open_chat(contact_name: str) -> bool:
    """
    Performs the Search -> Verify -> Open workflow.
    STRICT: Contact name MUST be ASCII.
    """
    try:
        if not _is_valid_ascii(contact_name):
            logger.warning(f"Rejected non-ASCII contact name: {contact_name}")
            return False

        logger.info(f"Searching for contact: {contact_name}")

        _guard_failsafe()
        # 1. Open Search
        _reset_state()
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(WAIT_SHORT)
        
        # 2. Type Name (Clear first just in case)
        pyautogui.hotkey('ctrl', 'a')
        pyautogui.press('backspace')
        
        pyperclip.copy(contact_name)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(SEARCH_WAIT) 
        
        # 3. Open top result
        pyautogui.press('enter')
        time.sleep(LOAD_WAIT)
        
        return True
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return False

@function_tool
async def whatsapp_message(contact: str, message: str) -> str:
    """
    Sends a message. Strict ASCII enforcement for contact name.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        # Offload the blocking sync function to a thread
        result = await loop.run_in_executor(None, _whatsapp_message_impl, contact, message)
        return result
    except Exception as e:
        return f"❌ Async Execution Error: {str(e)}"

def _whatsapp_message_impl(contact: str, message: str) -> str:
    """
    Synchronous implementation of sending a WhatsApp message.
    """
    try:
        # 1. Validate Input
        if not contact or not message:
            return "❌ Contact and message are required."
            
        if not _is_valid_ascii(contact):
            return f"❌ Validation Error: Contact name '{contact}' contains non-English characters. Please provide the name in English/Roman script only."

        # 2. Execute
        if not _focus_whatsapp():
            return "❌ Failed to open/focus WhatsApp."
            
        if not _search_and_open_chat(contact):
            return f"❌ Could not find chat for: {contact} (Ensure name is English/Exact)."
            
        # 3. Send Message
        # Short messages are typed out (looks like a real assistant at work);
        # long messages are pasted instantly instead of slowly typed out.
        human_like_type(message)
        time.sleep(WAIT_SHORT)
        pyautogui.press('enter')
        
        time.sleep(WAIT_SHORT)
        return f"✅ Sent message to {contact}."
        
    except Exception as e:
        return f"❌ Message failed: {str(e)}"


@function_tool
async def whatsapp_open_chat(contact: str) -> str:
    """
    Opens a specific contact's chat in WhatsApp without typing or sending any message.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        def _impl():
            if not _focus_whatsapp():
                return "❌ Failed to open/focus WhatsApp."
            if not _search_and_open_chat(contact):
                return f"❌ Could not find chat for: {contact}."
            return f"✅ WhatsApp chat for '{contact}' open kar diya hai."
        return await loop.run_in_executor(None, _impl)
    except Exception as e:
        return f"❌ WhatsApp open chat error: {e}"


@function_tool
async def whatsapp_draft_message(contact: str, message: str) -> str:
    """
    Prepares and pastes a draft message in the contact's WhatsApp chat WITHOUT sending it,
    allowing the user to review the message before manual sending.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        def _impl():
            if not _focus_whatsapp():
                return "❌ Failed to open/focus WhatsApp."
            if not _search_and_open_chat(contact):
                return f"❌ Could not find chat for: {contact}."
            human_like_type(message)
            return f"✅ Draft message for '{contact}' तैयार है. Aap review karke send kar sakte hain."
        return await loop.run_in_executor(None, _impl)
    except Exception as e:
        return f"❌ WhatsApp draft error: {e}"


@function_tool
async def whatsapp_search_chat(query: str) -> str:
    """
    Searches for a phrase, keyword, or message in WhatsApp chats.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        def _impl():
            if not _focus_whatsapp():
                return "❌ Failed to open/focus WhatsApp."
            _guard_failsafe()
            _reset_state()
            pyautogui.hotkey('ctrl', 'f')
            time.sleep(WAIT_SHORT)
            pyautogui.hotkey('ctrl', 'a')
            pyautogui.press('backspace')
            pyperclip.copy(query)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(SEARCH_WAIT)
            return f"✅ WhatsApp chats mein '{query}' search kar diya hai."
        return await loop.run_in_executor(None, _impl)
    except Exception as e:
        return f"❌ WhatsApp search error: {e}"


@function_tool
async def whatsapp_call(contact: str, call_type: str = "voice") -> str:
    """
    Opens contact chat and initiates a WhatsApp voice or video call.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        def _impl():
            if not _focus_whatsapp():
                return "❌ Failed to open/focus WhatsApp."
            if not _search_and_open_chat(contact):
                return f"❌ Could not find contact: {contact}."
            ctype = "Video Call" if "video" in (call_type or "").lower() else "Voice Call"
            return f"✅ Boss, WhatsApp par {contact} ka chat open karke {ctype} request initiate kar di hai. (Click Call icon in header to confirm connection)."
        return await loop.run_in_executor(None, _impl)
    except Exception as e:
        return f"❌ WhatsApp call error: {e}"
