import logging
import time
import pyautogui
import pyperclip
import re
from livekit.agents import function_tool

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

def _focus_whatsapp():
    """Activates the WhatsApp window."""
    try:
        pyautogui.press('win')
        time.sleep(WAIT_SHORT)
        pyautogui.write('WhatsApp')
        time.sleep(WAIT_SHORT)
        pyautogui.press('enter')
        time.sleep(LOAD_WAIT) 
        return True
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
        pyperclip.copy(message)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(WAIT_SHORT)
        pyautogui.press('enter')
        
        time.sleep(WAIT_SHORT)
        return f"✅ Sent message to {contact}."
        
    except Exception as e:
        return f"❌ Message failed: {str(e)}"

@function_tool
async def whatsapp_file(contact: str, file_path: str) -> str:
    """
    Sends a file. Strict ASCII enforcement for contact name.
    """
    import os
    import subprocess
    
    try:
        if not os.path.exists(file_path):
            return f"❌ File not found: {file_path}"
            
        if not _is_valid_ascii(contact):
             return f"❌ Validation Error: Contact name '{contact}' contains non-English characters."

        if not _focus_whatsapp():
             return "❌ Failed to focus WhatsApp."
             
        if not _search_and_open_chat(contact):
            return f"❌ Could not open chat for: {contact}"
            
        # Copy file to clipboard (PowerShell)
        cmd = f"Set-Clipboard -Path '{file_path}'"
        subprocess.run(["powershell", "-Command", cmd], check=True)
        time.sleep(WAIT_SHORT)
        
        # Paste and Send
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(WAIT_MEDIUM) 
        pyautogui.press('enter') 
        time.sleep(WAIT_MEDIUM)
        
        return f"✅ Sent file to {contact}: {os.path.basename(file_path)}"
        
    except Exception as e:
        return f"❌ File send failed: {str(e)}"

@function_tool
async def read_last_message(contact: str = None) -> str:
    """
    Reads the last message.
    """
    import asyncio
    import json
    
    try:
        await asyncio.sleep(0.1)  # allow event loop

        # Call the synchronous implementation
        msg = _read_message_impl(contact)

        if not msg or "Error" in msg or "Failed" in msg:
             return json.dumps({
                "status": "error",
                "message": msg if msg else "Unknown error"
            })

        return json.dumps({
            "status": "success",
            "message": str(msg)
        })

    except Exception as e:
        return json.dumps({
            "status": "error",
            "message": str(e)
        })

def _read_message_impl(contact: str = None) -> str:
    """
    Internal synchronous implementation of reading logic.
    """
    try:
        print("[DEBUG] Starting _read_message_impl...")
        if not _focus_whatsapp(): return "❌ Failed to focus WhatsApp."
        
        # Maximize
        pyautogui.hotkey('win', 'up')
        time.sleep(0.5)
        pyautogui.press('esc') # Clear dialogs
        time.sleep(0.5)

        if contact:
            print(f"[DEBUG] Searching for: {contact}")
            if not _search_and_open_chat(contact):
                 return f"❌ Could not find chat for: {contact}"
        
        # 2. Focus Chat History
        screen_w, screen_h = pyautogui.size()
        
        # Click DEEP into the right side
        click_x = screen_w - 200
        click_y = screen_h * 0.5
        
        print(f"[DEBUG] Clicking at: {click_x}, {click_y}")
        pyautogui.moveTo(click_x, click_y)
        time.sleep(0.2)
        pyautogui.click()
        time.sleep(WAIT_SHORT)
        
        # 3. Copy Sequence
        print("[DEBUG] Selecting & Copying...")
        try:
            pyperclip.copy("") # Clear
        except: pass
        
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.5)
        pyautogui.hotkey('ctrl', 'c')
        time.sleep(1.0) 

        chat_text = pyperclip.paste()
        print(f"[DEBUG] Clipboard length: {len(chat_text) if chat_text else 0}")
        
        if not chat_text:
            return "⚠️ Clipboard is empty. Selection failed."
            
        # 4. Clean & Parse
        safe_text = str(chat_text).encode('ascii', errors='ignore').decode('ascii')
        lines = [line.strip() for line in safe_text.splitlines() if line.strip()]
        
        if not lines: return "⚠️ Chat text appears empty/unreadable."
             
        # Extract last few lines
        relevant_lines = lines[-12:]
        return "📄 Last Messages:\n" + "\n".join(relevant_lines)

    except BaseException as e:
        import traceback
        tb = traceback.format_exc()
        print(f"[ERROR] CRITICAL READ FAILURE: {tb}")
        return f"❌ System Error reading chat: {str(e)}"

@function_tool
async def whatsapp_call(contact: str, video: bool = False) -> str:
    """Initiates call (Placeholder)."""
    return "⚠️ Calling capability is currently manual only."

@function_tool
async def whatsapp_reply(message: str) -> str:
    """Replies to current chat."""
    try:
        if not _focus_whatsapp(): return "❌ Focus failed."
        
        pyperclip.copy(message)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(WAIT_SHORT)
        pyautogui.press('enter')
        return "✅ Replied to active chat."
    except Exception as e:
        return f"❌ Reply failed: {str(e)}"
