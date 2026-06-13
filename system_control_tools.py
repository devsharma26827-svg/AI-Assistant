import os
import subprocess
import logging
import sys
import asyncio
import win32com.client
from fuzzywuzzy import process
from livekit.agents import function_tool
from ctypes import cast, POINTER
from comtypes import CLSCTX_ALL

try:
    import win32gui
    import win32con
except ImportError:
    win32gui = None
    win32con = None

try:
    import pygetwindow as gw
except ImportError:
    gw = None

try:
    import pyautogui
except ImportError:
    pyautogui = None

# Setup encoding and logger
sys.stdout.reconfigure(encoding='utf-8')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Cache for file index
_FILE_INDEX_CACHE = None
# _APP_INDEX_CACHE is no longer strictly needed for the "Start Menu automation" method,
# but we might keep it if we ever want to revert or use fallback. 
# For now, we follow rules causing us to rely on Windows search.

# -------------------------
# Global focus utility
# -------------------------
async def focus_window(title_keyword: str) -> bool:
    if not gw:
        logger.warning("⚠ pygetwindow")
        return False

    await asyncio.sleep(2.0)  # Give slightly more time for window to appear
    title_keyword = title_keyword.lower().strip()

    for window in gw.getAllWindows():
        if title_keyword in window.title.lower():
            try:
                if window.isMinimized:
                    window.restore()
                window.activate()
                return True
            except Exception as e:
                logger.warning(f"⚠ pygetwindow failed to activate '{window.title}': {e}")
                # Fallback to win32gui
                if win32gui:
                    try:
                        hwnd = window._hWnd
                        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                        win32gui.SetForegroundWindow(hwnd)
                        return True
                    except Exception as e2:
                        logger.error(f"❌ win32gui fallback also failed: {e2}")
    return False

# -------------------------
# Optimized File Indexing
# -------------------------
async def get_file_index():
    global _FILE_INDEX_CACHE
    if _FILE_INDEX_CACHE is not None:
        return _FILE_INDEX_CACHE
        
    logger.info("🔄 Indexing files (First time only)...")
    base_dirs = ["D:/"]
    item_index = []
    
    # Run in thread to avoid blocking main loop, although here we await it.
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
            
        # Limit depth or exclude system folders if needed to speed up
        for root, dirs, files in os.walk(base_dir):
            if "$RECYCLE.BIN" in root or "System Volume Information" in root:
                continue
                
            for d in dirs:
                item_index.append({"name": d, "path": os.path.join(root, d), "type": "folder"})
            for f in files:
                item_index.append({"name": f, "path": os.path.join(root, f), "type": "file"})
                
    _FILE_INDEX_CACHE = item_index
    logger.info(f"✅ Indexed {len(item_index)} items.")
    return item_index

async def search_item(query, index, item_type):
    filtered = [item for item in index if item["type"] == item_type]
    choices = [item["name"] for item in filtered]
    if not choices or not query:
        return None
        
    # If the AI passes a giant sentence, trim it to help fuzzy match
    if len(query.split()) > 4:
        # Just use the last few words which are usually the file name
        query = " ".join(query.split()[-3:])
        
    best_match, score = process.extractOne(query, choices)
    logger.info(f"🔍 Matched '{query}' to '{best_match}' with score {score}")
    
    # Increase threshold to prevent weird false positives
    if score >= 88:
        for item in filtered:
            if item["name"] == best_match:
                return item
    return None

# File/folder actions
async def open_folder(path):
    try:
        os.startfile(path)
        await focus_window(os.path.basename(path))
    except Exception as e:
        logger.error(f"❌ Error opening folder: {e}")

async def play_file(path):
    try:
        os.startfile(path)
        await focus_window(os.path.basename(path))
    except Exception as e:
        logger.error(f"❌ Error opening file: {e}")

def resolve_location(location: str) -> str:
    """Helper to resolve common location names into absolute Windows paths."""
    location = location.lower().strip()
    user_profile = os.environ.get("USERPROFILE", "C:\\")
    
    # Common mappings
    if location in ["desktop", "documents", "downloads", "music", "pictures", "videos"]:
        return os.path.join(user_profile, location.capitalize())
        
    if location in ["c drive", "c:"]: return "C:\\"
    if location in ["d drive", "d:"]: return "D:\\"
    
    # If absolute path is provided by LLM (e.g. C:/Users/Dev/Downloads)
    if ":" in location or location.startswith("/"):
        return location
        
    # Default fallback
    return os.path.join(user_profile, "Desktop")

@function_tool
async def create_system_folder(folder_name: str, location: str = "Desktop") -> str:
    """
    Creates a new folder at the specified location.
    
    Arguments:
    - folder_name: The name of the new folder (e.g. "My Projects")
    - location: The place to create it (e.g. "Desktop", "Documents", "D:", "C:/Users/..."). Defaults to Desktop.
    """
    try:
        base_path = resolve_location(location)
        full_path = os.path.join(base_path, folder_name)
        
        if os.path.exists(full_path):
            return f"⚠ Folder already exists at: {full_path}"
            
        os.makedirs(full_path, exist_ok=True)
        return f"✅ Folder '{folder_name}' successfully created at: {base_path}"
    except Exception as e:
        return f"❌ Failed to create folder: {e}"

@function_tool
async def create_system_file(file_name: str, content: str = "", location: str = "Desktop") -> str:
    """
    Creates a new file with optional text content at the specified location.
    
    Arguments:
    - file_name: The name of the new file including extension (e.g. "notes.txt", "script.py")
    - content: Optional text to write into the file.
    - location: The place to create it (e.g. "Desktop", "Documents"). Defaults to Desktop.
    """
    try:
        base_path = resolve_location(location)
        full_path = os.path.join(base_path, file_name)
        
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
            
        return f"✅ File '{file_name}' successfully created at: {base_path}"
    except Exception as e:
        return f"❌ Failed to create file: {e}"

async def create_folder(path):
    try:
        os.makedirs(path, exist_ok=True)
        return f"✅ Folder create हो गया।: {path}"
    except Exception as e:
        return f"❌ फ़ाइल create करने में error आया।: {e}"

async def rename_item(old_path, new_path):
    try:
        os.rename(old_path, new_path)
        return f"✅ नाम बदलकर {new_path} कर दिया गया।"
    except Exception as e:
        return f"❌ नाम बदलना fail हो गया: {e}"

async def delete_item(path):
    try:
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
        return f"🗑️ Deleted: {path}"
    except Exception as e:
        return f"❌ Delete नहीं हुआ।: {e}"

# -------------------------
# Web & Smart App Opener
# -------------------------
def is_website(name: str) -> bool:
    """Checks if the request is likely a website."""
    name = name.lower().strip()
    
    # Common websites
    web_keywords = [
        "youtube", "google", "gmail", "facebook", "instagram", 
        "linkedin", "twitter", "x.com", "reddit", "chatgpt", "github", 
        "amazon", "flipkart", "netflix", "hotstar", "prime video"
    ]
    
    if any(k in name for k in web_keywords):
        return True
        
    if "." in name and not name.endswith(".exe"): # e.g. "example.com"
        return True
        
    return False

def get_url(name: str) -> str:
    """Constructs a valid URL from the name."""
    name = name.lower().strip()
    
    # Map common names to specific URLs
    url_map = {
        "youtube": "https://www.youtube.com",
        "google": "https://www.google.com",
        "gmail": "https://mail.google.com",
        "chatgpt": "https://chat.openai.com",
        "github": "https://github.com",
        "instagram": "https://www.instagram.com"
    }
    
    for key in url_map:
        if key in name:
            return url_map[key]
            
    # Default fallback
    if not name.startswith("http"):
        return f"https://www.{name}" if "." in name else f"https://www.google.com/search?q={name}"
        
    return name

# App control
@function_tool
async def open_app(app_title: str) -> str:
    """
    Smartly opens apps or websites based on user request.
    
    Rules:
    1. If it's a website (YouTube, Google, etc.) -> Opens in Chrome.
    2. If it's an app (Notepad, Word, etc.) -> Opens via Start Menu (Win+Type+Enter).
    
    Example prompts:
    - "Open YouTube" -> Opens Chrome with YouTube.
    - "Open Notepad" -> Presses Win, types 'Notepad', presses Enter.
    """
    if not pyautogui:
        return "❌ pyautogui module missing. Please install it."

    app_title = app_title.lower().strip()
    
    # 1. Check if Website
    if is_website(app_title):
        url = get_url(app_title)
        try:
            # Open chrome directly
            subprocess.run(f'start chrome "{url}"', shell=True)
            return f"🌐 Opening website: {url}"
        except Exception as e:
            return f"❌ Failed to open website: {e}"

    # 2. Assume Desktop App -> Use Start Menu Automation
    try:
        # Simulate Win key -> Type -> Enter
        pyautogui.press('win')
        await asyncio.sleep(0.5) # Wait for start menu animation
        
        pyautogui.write(app_title, interval=0.05)
        await asyncio.sleep(0.5) # Wait for search results
        
        pyautogui.press('enter')
        
        return f"🚀 Launching app via Start Menu: {app_title}"
    except Exception as e:
        return f"❌ Failed to launch app via Start Menu: {e}"

@function_tool
async def close_app(target: str) -> str:
    """
    Closes the applications window by its title or name.
    
    Arguments:
    - target: The name or title of the app to close (e.g., "Notepad", "Chrome").
    """
    if not win32gui:
        return "❌ win32gui load नहीं हुआ।"

    closed_count = 0
    def enumHandler(hwnd, _):
        nonlocal closed_count
        if win32gui.IsWindowVisible(hwnd):
            curr_title = win32gui.GetWindowText(hwnd).lower()
            if target.lower() in curr_title:
                try:
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    closed_count += 1
                except Exception:
                    pass

    win32gui.EnumWindows(enumHandler, None)
    
    if closed_count > 0:
        return f"✅ {target} बंद कर दिया गया।"
    return f"❌ {target} की कोई window नहीं मिली।"

# Jarvis command logic
@function_tool
async def folder_file(command: str) -> str:
    """
    Handles folder and file actions like open, rename, or delete.
    Note: For CREATING folders or files, use 'create_system_folder' or 'create_system_file' tools.
    Example: "Open Projects folder", "Rename Old to New", "Delete test file"
    """
    global _FILE_INDEX_CACHE
    index = await get_file_index()
    command_lower = command.lower()

    if "create folder" in command_lower or "create file" in command_lower:
        return "❌ Please use the specialized 'create_system_folder' or 'create_system_file' tools."

    if "rename" in command_lower:
        parts = command_lower.split(" to ") # stricter split
        if len(parts) == 2:
            old_name_raw = parts[0].replace("rename", "").strip()
            new_name = parts[1].strip()
            
            # Find the item to rename
            item = await search_item(old_name_raw, index, "folder")
            if not item:
                 item = await search_item(old_name_raw, index, "file")
                 
            if item:
                new_path = os.path.join(os.path.dirname(item["path"]), new_name)
                # Invalidate cache after rename
                _FILE_INDEX_CACHE = None
                return await rename_item(item["path"], new_path)
                
        return "❌ Rename format गलत है। बोलिए: 'Rename OldName to NewName'"

    if "delete" in command_lower:
        target = command.replace("delete", "").replace("folder", "").replace("file", "").strip()
        item = await search_item(target, index, "folder") or await search_item(target, index, "file")
        if item:
            _FILE_INDEX_CACHE = None
            return await delete_item(item["path"])
        return "❌ Delete करने के लिए item नहीं मिला।"

    if "folder" in command_lower or "open folder" in command_lower:
        target = command.replace("open folder", "").replace("folder", "").strip()
        item = await search_item(target, index, "folder")
        if item:
            await open_folder(item["path"])
            return f"✅ Folder opened: {item['name']}"
        return f"❌ Folder '{target}' नहीं मिला।"

    # Default: Try to open file
    target = command.replace("open", "").replace("play", "").replace("file", "").strip()
    item = await search_item(target, index, "file")
    if item:
        await play_file(item["path"])
        return f"✅ File opened: {item['name']}"

    return "⚠ कुछ भी match नहीं हुआ।"

@function_tool
async def control_window(action: str, target: str = "current") -> str:
    """
    Controls window state (minimize, maximize, close, restore, focus).

    Arguments:
    - action: "minimize", "maximize", "close", "restore", "focus"
    - target: 
        - "current" OR "this" (default) -> The active window
        - "all" OR "desktop" -> All windows
        - [App Name] -> e.g., "Notepad", "Chrome" (Finds and controls specific app)

    Examples:
    - "Minimize chrome"
    - "Close this window"
    - "Maximize notepad"
    - "Minimize all windows"
    """
    if not pyautogui:
        return "❌ pyautogui missing."

    action = action.lower().strip()
    target = target.lower().strip()
    
    # Normalize synonyms
    if target in ["this", "ye", "isko", "abhi wali window"]:
        target = "current"
    if target in ["sab", "saari windows", "desktop", "everything"]:
        target = "all"
        
    logger.info(f"🪟 Window Control: {action} on {target}")

    # --- HANDLE "ALL" WINDOWS ---
    if target == "all":
        if action == "minimize":
            pyautogui.hotkey('win', 'd') # Show desktop
            return "✅ All windows minimized (Show Desktop)."
        elif action == "restore":
            pyautogui.hotkey('win', 'd') # Toggle back
            return "✅ Restoring desktop state."
        elif action == "close":
            return "⚠ SAFETY WARNING: I cannot close ALL windows automatically. Please ask me to close specific apps."
        elif action == "maximize":
            return "⚠ Cannot maximize ALL windows at once."
        return f"⚠ Action '{action}' not supported for ALL windows."

    # --- HANDLE SPECIFIC APP (Focus it first) ---
    if target != "current":
        # Try to focus the target app first
        found = await focus_window(target)
        if not found:
            # Try finding via fuzzy match against open apps if direct fail (optional, but focus_window does substrings)
            return f"❌ Window for '{target}' not found or could not be focused."
        await asyncio.sleep(0.5) # Wait for focus

    # --- EXECUTE ACTION ON CURRENT (OR NOW FOCUSED) WINDOW ---
    try:
        if action == "minimize":
            pyautogui.hotkey('win', 'down')
            await asyncio.sleep(0.1)
            pyautogui.hotkey('win', 'down') # Double down ensures minimize from max state
            return f"✅ Minimized {target} window."
            
        elif action == "maximize":
            pyautogui.hotkey('win', 'up')
            return f"✅ Maximized {target} window."
            
        elif action == "restore":
            pyautogui.hotkey('win', 'up') # Up usually restores from min
            return f"✅ Restored {target} window."
            
        elif action == "close":
            pyautogui.hotkey('alt', 'f4')
            return f"✅ Closed {target} window."
            
        elif action == "focus" or action == "switch":
            # Already focused above if target was specific
            return f"✅ Switched to {target}."
            
    except Exception as e:
        return f"❌ Action failed: {e}"

    return f"⚠ Unknown action: {action}"

@function_tool
async def arrange_window(target: str, position: str) -> str:
    """
    Arranges (snaps) windows to specific positions or screens.

    Arguments:
    - target: App name or "current"/"this"
    - position:
        - "left", "right", "top", "bottom"
        - "top-left", "top-right", "bottom-left", "bottom-right"
        - "maximize", "minimize"
        - "next monitor", "previous monitor"

    Examples:
    - "Chrome left side lagao"
    - "Notepad top right corner me set karo"
    - "Move this window to next monitor"
    """
    if not pyautogui:
        return "❌ pyautogui missing."

    target = target.lower().strip()
    position = position.lower().strip()
    
    # Normalize target
    if target in ["this", "ye", "isko", "abhi wali window"]:
        target = "current"
        
    # --- FOCUS TARGET FIRST ---
    if target != "current":
        found = await focus_window(target)
        if not found:
            return f"❌ Window for '{target}' not found."
        await asyncio.sleep(0.5)

    msg = f"✅ Arranged {target} to {position}."
    
    try:
        # Standard Snap
        if "left" in position and "top" in position:
            pyautogui.hotkey('win', 'left')
            await asyncio.sleep(0.1)
            pyautogui.hotkey('win', 'up')
            
        elif "right" in position and "top" in position:
            pyautogui.hotkey('win', 'right')
            await asyncio.sleep(0.1)
            pyautogui.hotkey('win', 'up')
            
        elif "left" in position and "bottom" in position:
            pyautogui.hotkey('win', 'left')
            await asyncio.sleep(0.1)
            pyautogui.hotkey('win', 'down')
            
        elif "right" in position and "bottom" in position:
            pyautogui.hotkey('win', 'right')
            await asyncio.sleep(0.1)
            pyautogui.hotkey('win', 'down')
            
        elif position == "left":
            pyautogui.hotkey('win', 'left')
            
        elif position == "right":
            pyautogui.hotkey('win', 'right')
            
        elif position == "top": # Maximize usually
            pyautogui.hotkey('win', 'up')
            
        elif position == "bottom": # Minimize usually, but could be restore
            pyautogui.hotkey('win', 'down')
            
        elif position == "maximize" or "full" in position:
            pyautogui.hotkey('win', 'up')
            
        elif position == "minimize":
            pyautogui.hotkey('win', 'down')
            await asyncio.sleep(0.1)
            pyautogui.hotkey('win', 'down')

        # Monitor Move
        elif "next" in position and "monitor" in position:
            pyautogui.hotkey('win', 'shift', 'right')
            msg = f"✅ Moved {target} to next monitor."
            
        elif "previous" in position and "monitor" in position:
            pyautogui.hotkey('win', 'shift', 'left')
            msg = f"✅ Moved {target} to previous monitor."
            
        else:
            return f"⚠ Unknown position '{position}'."
            
        return msg

    except Exception as e:
        return f"❌ Arrangement failed: {e}"

@function_tool
async def swap_windows(app1: str, app2: str) -> str:
    """
    Swaps the position and size of two windows.

    Arguments:
    - app1: Name of first window (or "this"/"current")
    - app2: Name of second window (or "this"/"current")

    Examples:
    - "Swap Chrome and Notepad"
    - "Exchange this window with VS Code"
    """
    if not gw:
        return "❌ pygetwindow missing."

    app1 = app1.lower().strip()
    app2 = app2.lower().strip()
    
    # Helper to find window object
    def get_window_obj(name):
        if name in ["this", "current", "ye", "isko", "abhi wali window"]:
            return gw.getActiveWindow()
        
        # Fuzzy match
        for window in gw.getAllWindows():
            if name in window.title.lower() and window.visible:
                return window
        return None

    try:
        w1 = get_window_obj(app1)
        w2 = get_window_obj(app2)

        if not w1: return f"❌ Window 1 ('{app1}') not found."
        if not w2: return f"❌ Window 2 ('{app2}') not found."
        if w1._hWnd == w2._hWnd: return "⚠ Both targets are the same window."

        # Capture states
        rect1 = (w1.left, w1.top, w1.width, w1.height)
        rect2 = (w2.left, w2.top, w2.width, w2.height)
        
        isMax1 = w1.isMaximized
        isMax2 = w2.isMaximized
        
        # Perform Swap
        # We must restore them first to move them reliably
        if isMax1: w1.restore()
        if isMax2: w2.restore()

        # Apply 2's rect to 1
        # Use simple move/resize to avoid animation lag if possible
        try:
            w1.moveTo(rect2[0], rect2[1])
            w1.resizeTo(rect2[2], rect2[3])
        except: pass # Ignore if move fails 

        # Apply 1's rect to 2
        try:
            w2.moveTo(rect1[0], rect1[1])
            w2.resizeTo(rect1[2], rect1[3])
        except: pass

        # Restore max state if needed
        # Logic: If W1 IS taking W2's place, and W2 WAS Max, then W1 should become Max.
        if isMax2: 
            w1.maximize()
        if isMax1: 
            w2.maximize()

        return f"✅ Swapped '{app1}' and '{app2}'."

    except Exception as e:
        return f"❌ Swap failed: {e}"

# -------------------------
# System Hardware Controls
# -------------------------

@function_tool
async def take_screenshot() -> str:
    """
    Takes a screenshot of the entire screen and saves it to the desktop.
    Returns the file path of the saved screenshot.
    """
    try:
        if not pyautogui:
            return "❌ pyautogui missing."
            
        desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
        filename = f"screenshot_{int(asyncio.get_event_loop().time())}.png"
        filepath = os.path.join(desktop_path, filename)
        
        # Run in executor to avoid blocking
        await asyncio.get_event_loop().run_in_executor(None, pyautogui.screenshot, filepath)
        
        return f"📸 Screenshot saved: {filepath}"
    except Exception as e:
        return f"❌ Screenshot failed: {e}"

@function_tool
async def set_volume(level: int) -> str:
    """
    Sets the system volume to a specific level (0-100).
    """
    try:
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        
        devices = AudioUtilities.GetSpeakers()
        interface = devices.Activate(
            IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        volume = cast(interface, POINTER(IAudioEndpointVolume))
        
        # Clamp between 0.0 and 1.0 (vector volume not scalar db)
        # pycaw uses scalar 0.0 to 1.0? No, usually SetMasterVolumeLevelScalar
        
        scalar = max(0.0, min(1.0, level / 100.0))
        volume.SetMasterVolumeLevelScalar(scalar, None)
        
        return f"🔊 Volume set to {level}%."
    except ImportError:
        return "❌ pycaw/comtypes missing. Install them for volume control."
    except Exception as e:
        # Fallback using nircmd or sendkeys if pycaw fails? 
        # For now return error
        return f"❌ Volume control failed: {e}"

@function_tool
async def get_battery_status() -> str:
    """
    Gets the current battery percentage and charging status.
    """
    try:
        import psutil
        battery = psutil.sensors_battery()
        if not battery:
            return "🔌 PC is plugged in (No Battery Detected)."
            
        percent = battery.percent
        charging = "Charging" if battery.power_plugged else "Discharging"
        time_left = f"({battery.secsleft // 60} min left)" if battery.secsleft != -1 else ""
        
        return f"🔋 Battery: {percent}% [{charging}] {time_left}"
    except ImportError:
        return "❌ psutil missing."
    except Exception as e:
        return f"❌ Battery check failed: {e}"

# -------------------------
# Device Connectivity
# -------------------------

@function_tool
async def get_connected_devices() -> str:
    """
    Scans and returns a list of locally connected hardware devices.
    Includes:
    - Microphones & Speakers (via sounddevice)
    - Cameras (via PowerShell)
    - ADB Devices (Android phones)
    - USB Devices (Keyboards, Mice, etc.)
    
    Returns a human-readable string summary.
    """
    import sounddevice as sd
    import asyncio
    import subprocess
    import sys
    
    loop = asyncio.get_running_loop()
    output_lines = ["🔌 **Connected Hardware Report**"]

    # 1. Audio Devices
    def _get_audio():
        try:
            ds = sd.query_devices()
            ms = [d['name'] for d in ds if d['max_input_channels'] > 0]
            ss = [d['name'] for d in ds if d['max_output_channels'] > 0]
            return list(set(ms)), list(set(ss))
        except: return [], []

    # 2. Cameras (PowerShell is more robust than WMIC on Win11)
    async def scan_cameras():
        if sys.platform != 'win32': return []
        try:
            cmd = "powershell \"Get-PnpDevice -Class 'Camera' -Status 'OK' | Select-Object -ExpandProperty FriendlyName\""
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            lines = stdout.decode().strip().split('\n')
            return [line.strip() for line in lines if line.strip()]
        except:
            return []

    # 3. ADB Devices
    async def scan_adb():
        try:
            proc = await asyncio.create_subprocess_shell(
                "adb devices -l", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            lines = stdout.decode().strip().split('\n')
            phones = []
            for line in lines[1:]:
                if "device" in line and "product:" in line:
                    parts = line.split()
                    model = "Unknown"
                    for p in parts:
                        if p.startswith("model:"):
                            model = p.split(":")[1]
                    phones.append(f"{model} ({parts[0]})")
            return phones
        except:
            return []

    # 4. USB Devices (Keyboards/Mice/etc)
    async def scan_usb():
         if sys.platform != 'win32': return []
         try:
            cmd = "powershell \"Get-PnpDevice -Class 'Keyboard','Mouse','HIDClass' -Status 'OK' | Select-Object -ExpandProperty FriendlyName\""
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, _ = await proc.communicate()
            lines = stdout.decode().strip().split('\n')
            # Filter duplicates and generic names
            devices = set()
            for line in lines:
                l = line.strip()
                if l and "HID" not in l and "Device" not in l: # Filter generic "USB Input Device"
                     devices.add(l)
            return list(devices)
         except:
             return []

    try:
        audio_task = loop.run_in_executor(None, _get_audio)
        camera_task = scan_cameras()
        adb_task = scan_adb()
        usb_task = scan_usb()

        (mics, speakers), cameras, phones, usbs = await asyncio.gather(audio_task, camera_task, adb_task, usb_task)

        if mics:
            output_lines.append(f"\n🎤 **Microphones**:\n" + "\n".join([f"- {m}" for m in mics]))
        if speakers:
            output_lines.append(f"\n🔊 **Speakers**:\n" + "\n".join([f"- {s}" for s in speakers]))
        if cameras:
            output_lines.append(f"\n📷 **Cameras**:\n" + "\n".join([f"- {c}" for c in cameras]))
        if phones:
            output_lines.append(f"\n📱 **ADB Devices**:\n" + "\n".join([f"- {p}" for p in phones]))
        if usbs:
            output_lines.append(f"\n⌨️ **Peripherals**:\n" + "\n".join([f"- {u}" for u in usbs]))
        
        if len(output_lines) == 1:
            return "No active peripherals detected."
            
        return "\n".join(output_lines)

    except Exception as e:
        return f"Error scanning devices: {e}"
