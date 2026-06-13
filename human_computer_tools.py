import asyncio
import logging
import re
import io
from livekit.agents import function_tool
import pyautogui
from PIL import ImageGrab, ImageDraw, ImageFont
from vision_tools import _get_gemini_vision_response

# Configure logger
logger = logging.getLogger("human_computer_tools")
logger.setLevel(logging.INFO)

# PyAutoGUI Safety settings
pyautogui.FAILSAFE = True  # Stop if mouse is thrown to the corner

@function_tool
async def human_click_element(target_description: str) -> str:
    """
    Finds a UI element on the screen by description and clicks it like a human.
    Use this to navigate GUI apps, click buttons, or select text boxes.
    
    Arguments:
    - target_description: What to click (e.g. "Search bar at the top", "Download button in MS Store", "Close (X) icon").
    """
    logger.info(f"Attempting to human-click: {target_description}")
    
    # Get current screen size
    screen_width, screen_height = pyautogui.size()
    
    # Pass 1: Global Coordinate Search
    prompt_pass1 = (
        f"Find the UI element: '{target_description}'.\n"
        f"Return its bounding box in exactly this format: [ymin, xmin, ymax, xmax]\n"
        f"These values must be integers between 0 and 1000, representing normalized screen coordinates.\n"
        f"Do not include any other text."
    )
    
    # Capture the full screen ourselves
    def _capture():
        return ImageGrab.grab()
    
    loop = asyncio.get_running_loop()
    full_screenshot = await loop.run_in_executor(None, _capture)
    
    response_pass1 = await _get_gemini_vision_response(prompt_pass1, custom_image=full_screenshot)
    if not response_pass1 or response_pass1.startswith("❌"):
        return f"❌ Failed to see screen in pass 1: {response_pass1}"
        
    # Extract bounding box from pass 1
    match1 = re.search(r'\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]', response_pass1.strip())
    
    if not match1:
        # Fallback to single coordinate
        fallback_match = re.search(r'(\d+)\s*,\s*(\d+)', response_pass1.strip())
        if fallback_match:
            x_norm, y_norm = int(fallback_match.group(1)), int(fallback_match.group(2))
            rough_x, rough_y = int((x_norm / 1000.0) * screen_width), int((y_norm / 1000.0) * screen_height)
        else:
            return f"❌ Could not find general area for '{target_description}'."
    else:
        y1, x1, y2, x2 = map(int, match1.groups())
        rough_x = int(((x1 + x2) / 2000.0) * screen_width)
        rough_y = int(((y1 + y2) / 2000.0) * screen_height)
    
    # Pass 2: Zoom-In Refinement WITH SET-OF-MARK (GRID POINTS)
    crop_size = 400
    half_crop = crop_size // 2
    left = max(0, rough_x - half_crop)
    top = max(0, rough_y - half_crop)
    right = min(screen_width, left + crop_size)
    bottom = min(screen_height, top + crop_size)
    
    # Adjust if crop got cut off at edges
    if right - left < crop_size: left = max(0, right - crop_size)
    if bottom - top < crop_size: top = max(0, bottom - crop_size)
    
    cropped_img = full_screenshot.crop((left, top, right, bottom))
    
    # Draw Set-of-Mark grid (Numbered Dots) on the cropped image
    draw = ImageDraw.Draw(cropped_img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except:
        font = ImageFont.load_default()
        
    grid_spacing = 40 # 10x10 grid on a 400x400 crop
    num_cols = crop_size // grid_spacing
    num_rows = crop_size // grid_spacing
    
    dot_index = 1
    mapping = {}
    
    for row in range(num_rows):
        for col in range(num_cols):
            cx = (col * grid_spacing) + (grid_spacing // 2)
            cy = (row * grid_spacing) + (grid_spacing // 2)
            text = str(dot_index)
            # Estimate text bounding box
            text_w = len(text) * 7
            text_h = 10
            # Draw tiny yellow background with red border
            draw.rectangle([cx-2, cy-2, cx+text_w+2, cy+text_h+2], fill="yellow", outline="red")
            # Draw black text
            draw.text((cx, cy), text, fill="black", font=font)
            mapping[dot_index] = (cx, cy)
            dot_index += 1
    
    prompt_pass2 = (
        f"Here is a zoomed-in section of the screen containing '{target_description}'.\n"
        f"I have overlaid a grid of numbered yellow tags (from 1 to {dot_index-1}).\n"
        f"Which tag number is exactly on top of or closest to the center of '{target_description}'?\n"
        f"Reply ONLY with the integer tag number. Do not include any other text or explanation."
    )
    
    response_pass2 = await _get_gemini_vision_response(prompt_pass2, custom_image=cropped_img)
    
    # Extract the chosen dot ID
    match2 = re.search(r'\b(\d+)\b', response_pass2.strip())
    
    if not match2:
        # If Pass 2 fails, just use Pass 1 rough coordinates
        x, y = rough_x, rough_y
        logger.warning(f"Pass 2 precision failed (no ID returned), using Pass 1 rough coordinates: {x}, {y}")
    else:
        chosen_id = int(match2.group(1))
        
        if chosen_id in mapping:
            local_x, local_y = mapping[chosen_id]
            # Translate back to global screen coordinates
            x = left + local_x
            y = top + local_y
            logger.info(f"Target locked on Grid ID {chosen_id} at Local({local_x}, {local_y}) -> Global({x}, {y})")
        else:
            logger.warning(f"Invalid Grid ID {chosen_id} returned. Using rough coords.")
            x, y = rough_x, rough_y
        
    # Validate final bounds
    if x < 0 or x >= screen_width or y < 0 or y >= screen_height:
         return f"❌ AI returned out-of-bounds coordinates ({x}, {y}) for screen {screen_width}x{screen_height}."
    
    try:
        # HUMAN EASE IN/OUT MOVEMENT
        current_x, current_y = pyautogui.position()
        distance = ((x - current_x)**2 + (y - current_y)**2)**0.5
        
        # Calculate dynamic duration based on distance to feel natural (min 0.5s, max 1.5s)
        duration = max(0.5, min(1.5, distance / 1000.0))
        
        # Move on main thread (PyAutoGUI is blocking, using to_thread so we don't freeze LiveKit)
        def _perform_click():
            pyautogui.moveTo(x, y, duration=duration, tween=pyautogui.easeInOutQuad)
            pyautogui.click()
            
        await asyncio.to_thread(_perform_click)
        return f"✅ Clicked on '{target_description}' at ({x}, {y})."
        
    except Exception as e:
        logger.error(f"Failed to move/click: {e}")
        return f"❌ Human click failed: {e}"


@function_tool
async def human_type_text(text: str) -> str:
    """
    Types text using the keyboard, simulating human typing speed.
    Call this AFTER clicking on a text box or search bar.
    
    Arguments:
    - text: The text to type out.
    """
    logger.info(f"Human typing text: {text}")
    try:
        def _perform_typing():
            pyautogui.write(text, interval=0.08) # 80ms delay between keys
            
        await asyncio.to_thread(_perform_typing)
        return f"✅ Typed text smoothly."
    except Exception as e:
        return f"❌ Failed to type text: {e}"


@function_tool
async def human_press_shortcut(keys: str) -> str:
    """
    Presses a keyboard shortcut or single key (e.g., 'enter', 'tab', 'ctrl+c').
    Uses PyAutoGUI key strings.
    
    Arguments:
    - keys: The keys to press, separated by '+' (e.g., 'enter', 'ctrl+shift+esc').
    """
    logger.info(f"Pressing shortcut: {keys}")
    try:
        key_list = [k.strip() for k in keys.split("+")]
        
        def _perform_hotkey():
            pyautogui.hotkey(*key_list)
            
        await asyncio.to_thread(_perform_hotkey)
        return f"✅ Pressed shortcut: {keys}"
    except Exception as e:
        return f"❌ Failed to press shortcut: {e}"

@function_tool
async def human_scroll(direction: str, amount: int = 500) -> str:
    """
    Scrolls the screen up or down.
    Use this when looking for UI elements that might be off-screen.
    
    Arguments:
    - direction: 'up' or 'down'.
    - amount: Number of pixels/units to scroll (default 500, use 1000 for large scrolls).
    """
    logger.info(f"Human scrolling {direction} by {amount}")
    try:
        def _perform_scroll():
            # pyautogui.scroll takes positive for up, negative for down
            scroll_val = amount if direction.lower() == 'up' else -amount
            pyautogui.scroll(scroll_val)
            
        await asyncio.to_thread(_perform_scroll)
        return f"✅ Scrolled {direction} successfully."
    except Exception as e:
        return f"❌ Failed to scroll: {e}"
