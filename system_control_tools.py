import os
import subprocess
import logging
import sys
import asyncio
import time
import ctypes
import uuid
import win32com.client
from fuzzywuzzy import process
from livekit.agents import function_tool
from ctypes import cast, POINTER, wintypes
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
_FILE_INDEX_LOCK = asyncio.Lock()

# Serialises Start Menu app launches and shell invocations, which are global
# shared resources — parallel use corrupts both.
_LAUNCH_LOCK = asyncio.Lock()
_SHELL_LOCK = asyncio.Lock()

# Folder/file names we never want to walk into — these are huge and irrelevant
# for "open my X folder" style commands, and scanning them wastes minutes.
_EXCLUDED_DIR_NAMES = {
    "$recycle.bin", "system volume information", "windows", "programdata",
    "node_modules", ".git", "$windows.~bt", "$windows.~ws",
    "program files", "program files (x86)", "appdata",
}
# _APP_INDEX_CACHE is no longer strictly needed for the "Start Menu automation" method,
# but we might keep it if we ever want to revert or use fallback. 
# For now, we follow rules causing us to rely on Windows search.

# Spoken app names rarely match the real window title ("VS Code" vs
# "... - Visual Studio Code"), which made close/focus report "window not found"
# for apps that were clearly open. Expand known aliases before matching.
_WINDOW_ALIASES = {
    "vs code": ["visual studio code", "code"],
    "vscode": ["visual studio code", "code"],
    "visual studio code": ["visual studio code", "code"],
    "chrome": ["google chrome", "chrome"],
    "google chrome": ["google chrome", "chrome"],
    "notepad": ["notepad"],
    "whatsapp": ["whatsapp"],
    "explorer": ["file explorer", "explorer"],
    "powershell": ["powershell", "windows powershell"],
    "cmd": ["command prompt", "cmd"],
    "terminal": ["terminal", "command prompt", "powershell"],
    "word": ["word"],
    "excel": ["excel"],
}


def _title_candidates(name: str):
    """Returns the list of lowercase substrings to match a window title against."""
    key = (name or "").lower().strip()
    return _WINDOW_ALIASES.get(key, [key])


def _title_matches(window_title: str, name: str) -> bool:
    title = (window_title or "").lower()
    return any(c and c in title for c in _title_candidates(name))


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
        if _title_matches(window.title, title_keyword):
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
_KNOWN_FOLDER_GUIDS = {
    "desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "downloads": "{374DE290-123F-4565-9164-39C4925E467B}",
    "pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}
_known_folder_cache: dict[str, str | None] = {}


def _get_known_folder(name: str) -> str | None:
    """Resolve a Windows known folder (Desktop, Documents, ...) via the real
    Shell API instead of guessing `%USERPROFILE%\\Desktop`.

    Why this matters: on most Windows 11 machines with OneDrive "Backup"
    turned on, Desktop/Documents/Pictures are silently REDIRECTED to
    `%USERPROFILE%\\OneDrive\\Desktop` etc. `%USERPROFILE%\\Desktop` may still
    exist as an empty leftover folder, so the old code created folders there
    "successfully" — while File Explorer (which follows the redirect) showed
    nothing. SHGetKnownFolderPath returns the REAL, redirect-aware path.
    """
    if name in _known_folder_cache:
        return _known_folder_cache[name]

    guid = _KNOWN_FOLDER_GUIDS.get(name)
    result_path = None
    if guid and os.name == "nt":
        try:
            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
                ]
            rfid = GUID()
            ctypes.memmove(ctypes.byref(rfid), uuid.UUID(guid).bytes_le, 16)

            path_ptr = ctypes.c_wchar_p()
            hresult = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(rfid), 0, 0, ctypes.byref(path_ptr)
            )
            if hresult == 0 and path_ptr.value:
                result_path = path_ptr.value
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
        except Exception as e:
            logger.warning(f"SHGetKnownFolderPath failed for {name}: {e}")

    _known_folder_cache[name] = result_path
    return result_path


def _index_base_dirs() -> list[str]:
    """Where we actually look for the user's files.

    IMPORTANT: This used to be hardcoded to ["D:/"] only, which meant anything
    created on the C: drive (Desktop, Documents, Downloads — the defaults every
    other tool in this file uses!) could never be found by folder_file(). That
    was the #1 cause of "wrong folder opened" bugs. We now index the common
    user folders first (small + high hit-rate — resolved via the real Windows
    known-folder API so OneDrive-redirected paths are covered too), then any
    extra data drives.
    """
    user_profile = os.environ.get("USERPROFILE", "C:\\")
    names = ["desktop", "documents", "downloads", "pictures", "videos"]
    dirs = []
    for name in names:
        dirs.append(_get_known_folder(name) or os.path.join(user_profile, name.capitalize()))
    for drive in ("D:/", "E:/", "F:/"):
        if os.path.exists(drive):
            dirs.append(drive)
    return dirs


def _build_file_index_sync() -> list[dict]:
    """Blocking directory walk. MUST be called via asyncio.to_thread — never
    directly on the event loop, or the whole voice session freezes (this is
    what caused the ~40s freezes / dropped WebSocket connections you saw)."""
    item_index = []
    for base_dir in _index_base_dirs():
        if not os.path.exists(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            # Prune excluded dirs IN PLACE so os.walk doesn't descend into them
            dirs[:] = [d for d in dirs if d.lower() not in _EXCLUDED_DIR_NAMES]
            for d in dirs:
                item_index.append({"name": d, "path": os.path.join(root, d), "type": "folder"})
            for f in files:
                item_index.append({"name": f, "path": os.path.join(root, f), "type": "file"})
    return item_index


async def get_file_index(force_refresh: bool = False):
    global _FILE_INDEX_CACHE
    async with _FILE_INDEX_LOCK:
        if _FILE_INDEX_CACHE is not None and not force_refresh:
            return _FILE_INDEX_CACHE

        logger.info("🔄 Indexing files (first time only, running off the main thread)...")
        # asyncio.to_thread keeps the voice/RTC event loop alive while this runs
        item_index = await asyncio.to_thread(_build_file_index_sync)
        _FILE_INDEX_CACHE = item_index
        logger.info(f"✅ Indexed {len(item_index)} items.")
        return item_index


def _add_to_index_cache(name: str, path: str, item_type: str) -> None:
    """Incrementally add a freshly created item instead of dropping the whole
    cache (which would force a slow full re-walk on the very next command)."""
    global _FILE_INDEX_CACHE
    if _FILE_INDEX_CACHE is not None:
        _FILE_INDEX_CACHE.append({"name": name, "path": path, "type": item_type})


async def search_item(query, index, item_type):
    filtered = [item for item in index if item["type"] == item_type]
    if not filtered or not query:
        return None

    query_clean = query.strip()
    # If the AI passes a giant sentence, trim it to help fuzzy match
    if len(query_clean.split()) > 4:
        query_clean = " ".join(query_clean.split()[-3:])
    query_lower = query_clean.lower()

    # 1. Exact (case-insensitive) match first — fast, deterministic, and avoids
    #    the fuzzy scorer entirely for the common case.
    for item in filtered:
        if item["name"].lower() == query_lower:
            return item

    # 2. Unambiguous substring match (e.g. "project" -> "My First Project")
    substring_hits = [item for item in filtered if query_lower in item["name"].lower()]
    if len(substring_hits) == 1:
        return substring_hits[0]

    # 3. Fuzzy fallback only — on a huge, unrelated name pool this can produce
    #    odd high scores, so it stays a last resort with a strict threshold.
    choices = [item["name"] for item in filtered]
    best_match, score = process.extractOne(query_clean, choices)
    logger.info(f"🔍 Matched '{query_clean}' to '{best_match}' with score {score}")

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
        known = _get_known_folder(location)
        if known:
            return known
        return os.path.join(user_profile, location.capitalize())
        
    if location in ["c drive", "c:"]: return "C:\\"
    if location in ["d drive", "d:"]: return "D:\\"
    
    # If absolute path is provided by LLM (e.g. C:/Users/Dev/Downloads)
    if ":" in location or location.startswith("/"):
        return location
        
    # Default fallback
    return _get_known_folder("desktop") or os.path.join(user_profile, "Desktop")

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
        _add_to_index_cache(folder_name, full_path, "folder")
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

        _add_to_index_cache(file_name, full_path, "file")
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
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: subprocess.run(f'start chrome "{url}"', shell=True)
            )
            return f"🌐 Opening website: {url}"
        except Exception as e:
            return f"❌ Failed to open website: {e}"

    # 2. Assume Desktop App -> Use Start Menu Automation
    try:
        loop = asyncio.get_running_loop()

        # Start Menu automation is a GLOBAL, shared resource: it types into
        # whatever search box is open. When a workflow fires two launches in
        # the same turn, the second Win-press lands while the first is still
        # typing, so both searches get mangled and one or both apps fail to
        # open. Serialising launches (and waiting for the window to actually
        # appear) makes multi-step routines reliable.
        async with _LAUNCH_LOCK:
            before = await loop.run_in_executor(None, _count_windows, app_title)

            def _launch():
                pyautogui.press('win')
                time.sleep(0.7)  # Wait for start menu animation
                # Clear anything the previous launch may have left behind.
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('backspace')
                pyautogui.write(app_title, interval=0.05)
                time.sleep(0.9)  # Wait for search results to resolve
                pyautogui.press('enter')

            await loop.run_in_executor(None, _launch)

            # Wait (up to ~8s) for the app window to actually show up so the
            # caller — and any following workflow step — knows it's ready.
            for _ in range(16):
                await asyncio.sleep(0.5)
                now = await loop.run_in_executor(None, _count_windows, app_title)
                if now > before:
                    return f"✅ Opened {app_title}."

        return (
            f"🚀 Sent launch command for {app_title} via Start Menu, but I couldn't "
            f"confirm its window opened yet — it may still be loading."
        )
    except Exception as e:
        return f"❌ Failed to launch app via Start Menu: {e}"

def _count_windows(name: str) -> int:
    """Counts visible windows whose title contains `name` (lowercased match)."""
    if not win32gui:
        return 0
    name = (name or "").lower()
    count = 0
    def _enum(hwnd, _):
        nonlocal count
        try:
            if win32gui.IsWindowVisible(hwnd):
                if name and _title_matches(win32gui.GetWindowText(hwnd), name):
                    count += 1
        except Exception as e:
            logger.debug(f"_count_windows: skipping {hwnd}: {e}")
    win32gui.EnumWindows(_enum, None)
    return count


@function_tool
async def close_app(target: str) -> str:
    """
    Closes the applications window by its title or name.
    
    Arguments:
    - target: The name or title of the app to close (e.g., "Notepad", "Chrome").
    """
    if not win32gui:
        return "❌ win32gui load नहीं हुआ।"

    def _do_close():
        closed = 0
        def enumHandler(hwnd, _):
            nonlocal closed
            try:
                if win32gui.IsWindowVisible(hwnd):
                    if _title_matches(win32gui.GetWindowText(hwnd), target):
                        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                        closed += 1
            except Exception as e:
                logger.debug(f"close_app: skipping window {hwnd}: {e}")
        win32gui.EnumWindows(enumHandler, None)
        return closed

    loop = asyncio.get_running_loop()
    closed_count = await loop.run_in_executor(None, _do_close)

    if closed_count == 0:
        return f"❌ {target} की कोई window नहीं मिली।"

    # Verify it actually closed instead of blindly reporting success.
    await asyncio.sleep(0.8)
    still_open = await loop.run_in_executor(None, _count_windows, target)
    if still_open:
        return (
            f"⚠ {target} ko close command bheja, par window abhi bhi khuli hai — "
            f"shayad unsaved changes save karne ka prompt aaya hai. Screen check kijiye."
        )
    return f"✅ {target} बंद कर दिया गया।"

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
            # alt+f4 only closes whatever happens to be focused, and silently
            # "succeeds" even when nothing closed (this is why Notepad kept
            # reporting closed while still being open). Close the real window
            # by handle instead, then verify it actually went away.
            def _close_by_title(name: str) -> int:
                if not win32gui:
                    return -1
                closed = 0
                def _enum(hwnd, _):
                    nonlocal closed
                    try:
                        if win32gui.IsWindowVisible(hwnd):
                            if name and _title_matches(win32gui.GetWindowText(hwnd), name):
                                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                                closed += 1
                    except Exception as e:
                        logger.debug(f"close: skipping window {hwnd}: {e}")
                win32gui.EnumWindows(_enum, None)
                return closed

            loop = asyncio.get_running_loop()
            closed_count = await loop.run_in_executor(None, _close_by_title, target)

            if closed_count == -1:
                pyautogui.hotkey('alt', 'f4')
                return f"✅ Sent close command to {target}."
            if closed_count == 0:
                return f"❌ No open window matching '{target}' — nothing to close."

            await asyncio.sleep(0.8)
            still_open = await loop.run_in_executor(None, _count_windows, target)
            if still_open:
                return (
                    f"⚠ Sent close to {target}, but a window is still open — "
                    f"it may be asking to save unsaved changes. Check the screen."
                )
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
        except Exception as e:
            logger.warning(f"swap_windows: could not move/resize '{app1}': {e}")

        # Apply 1's rect to 2
        try:
            w2.moveTo(rect1[0], rect1[1])
            w2.resizeTo(rect1[2], rect1[3])
        except Exception as e:
            logger.warning(f"swap_windows: could not move/resize '{app2}': {e}")

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

        # Register it as the active file so "open it" / open_current_file works
        # right after taking a screenshot (previously the path was never stored,
        # so open_current_file had no idea what to open).
        try:
            from memory_store import memory as _memory
            _memory.set_active_file(filepath)
        except Exception as e:
            logger.warning(f"take_screenshot: could not record active file: {e}")

        return f"📸 Screenshot saved: {filepath}"
    except Exception as e:
        return f"❌ Screenshot failed: {e}"

@function_tool
async def set_volume(level: int) -> str:
    """
    Sets the system volume to a specific level (0-100).
    """
    try:
        level = max(0, min(100, int(level)))

        def _apply():
            # COM must be initialised on whichever thread talks to the Windows
            # audio endpoint; without this the call fails on worker threads.
            from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            CoInitialize()
            try:
                devices = AudioUtilities.GetSpeakers()
                interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                volume = interface.QueryInterface(IAudioEndpointVolume)
                volume.SetMasterVolumeLevelScalar(max(0.0, min(1.0, level / 100.0)), None)
            finally:
                try:
                    CoUninitialize()
                except Exception:
                    pass

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _apply)
        return f"🔊 Volume set to {level}%."
    except ImportError:
        return "❌ pycaw/comtypes missing. Install them for volume control."
    except Exception as e:
        logger.error(f"set_volume failed: {e}")
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
        except Exception as e:
            logger.warning(f"get_connected_devices: audio device query failed: {e}")
            return [], []

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
        except Exception as e:
            logger.warning(f"get_connected_devices: camera scan failed: {e}")
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
        except Exception as e:
            logger.warning(f"get_connected_devices: ADB scan failed: {e}")
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
         except Exception as e:
             logger.warning(f"get_connected_devices: USB device scan failed: {e}")
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


@function_tool
async def run_shell_command(command: str, timeout_seconds: int = 20) -> str:
    """
    Runs a Windows PowerShell command DIRECTLY (no GUI automation involved —
    no opening a terminal window, no typing into it) and returns its real
    output as text.

    Use this for anything that needs a system/diagnostic command — checking
    connected Bluetooth devices, current Wi-Fi network, disk space, running
    processes, etc. — instead of manually opening PowerShell and typing into
    it, which is slow and unreliable.

    Arguments:
    - command: The full PowerShell command to run,
      e.g. "Get-PnpDevice | Where-Object { $_.Class -eq 'Bluetooth' }".
    - timeout_seconds: Max seconds to wait before giving up (default 20).
    """
    def _run():
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True, text=True, timeout=timeout_seconds,
                # Without an explicit cwd, PowerShell inherits whatever
                # directory the agent happens to be in, which produced
                # intermittent "file not found" results for relative paths.
                cwd=os.path.expanduser("~"),
            )
            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if result.returncode != 0 and error:
                return f"❌ Command failed: {error[:500]}"
            return output[:2000] if output else "✅ Command ran successfully with no output."
        except subprocess.TimeoutExpired:
            return f"❌ Command timed out after {timeout_seconds}s."
        except Exception as e:
            return f"❌ Failed to run command: {e}"

    loop = asyncio.get_running_loop()
    # Serialise: concurrent PowerShell launches were causing sporadic
    # "resource already in use" failures.
    async with _SHELL_LOCK:
        result = await loop.run_in_executor(None, _run)
        # One transient-failure retry (console/resource contention).
        if result.startswith("❌") and "already in use" in result.lower():
            await asyncio.sleep(1.0)
            result = await loop.run_in_executor(None, _run)
        return result


# Which interpreter to use for a given saved file's extension.
_RUNNERS = {
    ".py": ["python"],
    ".js": ["node"],
    ".ps1": ["powershell", "-NoProfile", "-File"],
}

# Libraries that open their own persistent GUI window and don't exit on their
# own (games, guis, animations). Running these with subprocess.run(timeout=..)
# blocks the tool call until the window is closed or the timeout hits — which,
# if the model retries while the previous call is still blocked, stacks up
# multiple long-running calls on top of each other. For these we launch the
# process and return immediately instead of waiting for it to exit.
_GUI_MARKERS = (
    "import pygame", "import tkinter", "from tkinter", "import turtle",
    "import PyQt5", "import PyQt6", "import PySide2", "import PySide6",
    "import wx", "import kivy", "from kivy",
)

# Guards against the model re-issuing run_code_file for the same GUI file
# multiple times in quick succession (e.g. because it didn't get a reply in
# time and retried) — that would otherwise open several duplicate windows.
_RECENT_GUI_LAUNCHES = {}
_GUI_LAUNCH_COOLDOWN = 15  # seconds


@function_tool
async def run_code_file(file_path: str) -> str:
    """
    Runs a code file that has ALREADY been saved to disk (via save_file_as)
    and returns its real output — directly through the interpreter, no GUI
    typing into a terminal involved.

    IMPORTANT: file_path must be a real path on disk. If you don't know
    whether/where the current code has been saved, do NOT guess a path —
    ask the user what filename to save it as, call save_file_as (its reply
    tells you the exact saved path), and then call this tool with that path.

    For games/GUI apps (pygame, tkinter, turtle, etc.) this launches the
    window and returns immediately — it does NOT wait for the window to
    close, since that would block the conversation until the user quits it.

    Arguments:
    - file_path: Full path to the saved file, e.g. "D:\\inventory management system.py".
      This is exactly what save_file_as's success reply gives you.
    """
    path = (file_path or "").strip().strip('"')

    # save_file_as drives a GUI Save-As dialog, so the file can take a moment to
    # actually appear on disk. Without this wait, running right after saving
    # wrongly reported NEEDS_SAVE even though the save had been requested.
    if path and not os.path.exists(path):
        for _ in range(6):
            await asyncio.sleep(0.5)
            if os.path.exists(path):
                break

    if not path or not os.path.exists(path):
        return (
            "❌ NEEDS_SAVE: This file hasn't been saved to disk yet (or the path "
            "is wrong). Ask the user what filename/location to save it as, call "
            "save_file_as, then call run_code_file again with the path it returns."
        )

    ext = os.path.splitext(path)[1].lower()
    runner = _RUNNERS.get(ext)
    if not runner:
        return f"❌ I don't know how to run '{ext}' files yet."

    # Detect GUI/game code so we don't block waiting for a window that won't
    # close on its own.
    is_gui = False
    if ext == ".py":
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                head = f.read(4000)
            is_gui = any(marker in head for marker in _GUI_MARKERS)
        except Exception:
            pass

    def _launch_gui():
        now = time.time()
        last = _RECENT_GUI_LAUNCHES.get(path)
        if last and (now - last) < _GUI_LAUNCH_COOLDOWN:
            return "✅ Already launched a few seconds ago — the window should already be open on your screen."
        try:
            # Fire-and-forget: don't wait for the window to be closed.
            subprocess.Popen(
                runner + [path],
                creationflags=subprocess.CREATE_NEW_CONSOLE
                if hasattr(subprocess, "CREATE_NEW_CONSOLE") else 0,
            )
            _RECENT_GUI_LAUNCHES[path] = now
            return "✅ Launched — the window should be opening on your screen now."
        except Exception as e:
            return f"❌ Failed to launch: {e}"

    def _run_and_capture():
        try:
            result = subprocess.run(
                runner + [path], capture_output=True, text=True, timeout=15
            )
            output = (result.stdout or "").strip()
            error = (result.stderr or "").strip()
            if result.returncode != 0:
                return f"❌ Ran with errors:\n{(error or output)[:1500]}"
            return output[:2000] if output else "✅ Ran successfully with no output."
        except subprocess.TimeoutExpired:
            return (
                "❌ The code is still running after 15s (possible infinite loop, "
                "a GUI window, or it's waiting for input) — if this opened a "
                "window/game, it's already on screen; no need to run it again."
            )
        except Exception as e:
            return f"❌ Failed to run file: {e}"

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _launch_gui if is_gui else _run_and_capture)
