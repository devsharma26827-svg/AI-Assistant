import asyncio
import logging
import re
import io
from livekit.agents import function_tool
import pyautogui
from PIL import ImageGrab, ImageDraw, ImageFont
from vision_tools import _get_gemini_vision_response
from typing_utils import human_like_type

# Configure logger
logger = logging.getLogger("human_computer_tools")
logger.setLevel(logging.INFO)

# PyAutoGUI Safety settings
pyautogui.FAILSAFE = True  # Stop if mouse is thrown to the corner

# Serializes actual keyboard/mouse input across all human_* tools. Without this,
# two overlapping tool calls (e.g. the model firing a new typing call before a
# previous one finished) send keystrokes/clicks to the OS at the same time,
# which interleaves and garbles whatever is on screen. Only the actual
# input-emitting step is held under this lock — slow vision lookups happen
# outside it so they don't block unrelated quick actions.
_INPUT_LOCK = asyncio.Lock()


def _guard_failsafe():
    """
    PyAutoGUI aborts if the cursor sits in a screen corner. Keyboard-only
    actions shouldn't be blocked by mouse position, so move it out of the
    corner before acting.
    """
    try:
        width, height = pyautogui.size()
        x, y = pyautogui.position()
        margin = 5
        if x <= margin or y <= margin or x >= width - margin or y >= height - margin:
            pyautogui.moveTo(width // 2, height // 2, duration=0.1)
    except Exception as e:
        logger.debug(f"failsafe guard skipped: {e}")

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

    # The screenshot is in PHYSICAL pixels, while pyautogui clicks in LOGICAL
    # coordinates. On any display with DPI scaling (125%/150%, very common on
    # laptops) these differ, so mixing them makes every click land in the wrong
    # place. Track both spaces explicitly and convert at the end.
    img_width, img_height = full_screenshot.size
    scale_x = img_width / float(screen_width) if screen_width else 1.0
    scale_y = img_height / float(screen_height) if screen_height else 1.0
    if abs(scale_x - 1.0) > 0.01 or abs(scale_y - 1.0) > 0.01:
        logger.info(
            f"Display scaling detected: screenshot {img_width}x{img_height} vs "
            f"logical {screen_width}x{screen_height} (scale {scale_x:.2f}x{scale_y:.2f})"
        )
    
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
            rough_x, rough_y = int((x_norm / 1000.0) * img_width), int((y_norm / 1000.0) * img_height)
        else:
            return f"❌ Could not find general area for '{target_description}'."
    else:
        y1, x1, y2, x2 = map(int, match1.groups())
        rough_x = int(((x1 + x2) / 2000.0) * img_width)
        rough_y = int(((y1 + y2) / 2000.0) * img_height)
    
    # Pass 2: Zoom-In Refinement WITH SET-OF-MARK (GRID POINTS)
    # Taskbar / system-tray icons are far smaller than typical UI elements, so
    # a 400px crop leaves them only a few pixels wide in pass 2 and the model
    # picks the wrong grid cell. Zoom in much tighter for those, and anchor the
    # crop to the tray region (bottom-right) which pass 1 often misjudges.
    _desc = (target_description or "").lower()
    _is_tray = any(k in _desc for k in
                   ("taskbar", "task bar", "system tray", "tray", "notification area"))
    if _is_tray:
        crop_size = 220
        # The tray always lives in the bottom-right strip; trust geometry over
        # pass 1 for the vertical position.
        rough_y = int(img_height - (img_height * 0.022))
        rough_x = max(rough_x, int(img_width * 0.80))
    else:
        crop_size = 400
    half_crop = crop_size // 2
    left = max(0, rough_x - half_crop)
    top = max(0, rough_y - half_crop)
    right = min(img_width, left + crop_size)
    bottom = min(img_height, top + crop_size)
    
    # Adjust if crop got cut off at edges
    if right - left < crop_size: left = max(0, right - crop_size)
    if bottom - top < crop_size: top = max(0, bottom - crop_size)
    
    cropped_img = full_screenshot.crop((left, top, right, bottom))
    
    # A 220px tray crop is too small for the model to read reliably — upscale
    # it before annotating. Grid maths below stays in crop coordinates, so the
    # mapping back to screen pixels is unaffected.
    _render_scale = 1
    if crop_size < 300:
        _render_scale = 2
        cropped_img = cropped_img.resize(
            (cropped_img.width * _render_scale, cropped_img.height * _render_scale)
        )

    # Draw Set-of-Mark grid (Numbered Dots) on the cropped image
    draw = ImageDraw.Draw(cropped_img)
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except Exception as e:
        logger.debug(f"arial.ttf unavailable, using default font: {e}")
        font = ImageFont.load_default()
        
    # Keep roughly a 10x10 grid whatever the crop size, so a tighter tray crop
    # gets proportionally finer targeting instead of 5 huge cells.
    grid_spacing = max(20, crop_size // 10)
    num_cols = crop_size // grid_spacing
    num_rows = crop_size // grid_spacing
    
    dot_index = 1
    mapping = {}
    
    for row in range(num_rows):
        for col in range(num_cols):
            cx = (col * grid_spacing) + (grid_spacing // 2)
            cy = (row * grid_spacing) + (grid_spacing // 2)
            # Where to DRAW on the (possibly upscaled) render.
            dx, dy = cx * _render_scale, cy * _render_scale
            text = str(dot_index)
            # Estimate text bounding box
            text_w = len(text) * 7
            text_h = 10
            # Draw tiny yellow background with red border
            draw.rectangle([dx-2, dy-2, dx+text_w+2, dy+text_h+2], fill="yellow", outline="red")
            # Draw black text
            draw.text((dx, dy), text, fill="black", font=font)
            # mapping stays in CROP coordinates so translation back to screen
            # pixels below is independent of the render upscale.
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
        img_x, img_y = rough_x, rough_y
        logger.warning(f"Pass 2 precision failed (no ID returned), using Pass 1 rough coordinates: {img_x}, {img_y}")
    else:
        chosen_id = int(match2.group(1))
        
        if chosen_id in mapping:
            local_x, local_y = mapping[chosen_id]
            # Translate back to full-screenshot (physical pixel) coordinates
            img_x = left + local_x
            img_y = top + local_y
            logger.info(f"Target locked on Grid ID {chosen_id} at Local({local_x}, {local_y}) -> Image({img_x}, {img_y})")
        else:
            logger.warning(f"Invalid Grid ID {chosen_id} returned. Using rough coords.")
            img_x, img_y = rough_x, rough_y

    # Convert from screenshot pixels to the logical coordinate space pyautogui
    # actually clicks in (identity when the display isn't DPI-scaled).
    x = int(img_x / scale_x)
    y = int(img_y / scale_y)
    if (x, y) != (img_x, img_y):
        logger.info(f"Scaled click target Image({img_x}, {img_y}) -> Screen({x}, {y})")

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

        async with _INPUT_LOCK:
            await asyncio.to_thread(_perform_click)
        return f"✅ Clicked on '{target_description}' at ({x}, {y})."
        
    except Exception as e:
        logger.error(f"Failed to move/click: {e}")
        return f"❌ Human click failed: {e}"


@function_tool
async def human_type_text(text: str) -> str:
    """
    Types text into whatever UI element currently has focus (message box, search
    bar, editor, etc.). Short text is typed out character-by-character so it
    visibly looks like real typing; longer text is pasted instantly instead of
    being typed out slowly. Works for any language/script, not just English.
    Call this AFTER clicking on a text box or search bar.

    Arguments:
    - text: The text to type out.
    """
    logger.info(f"Human typing text: {text}")
    try:
        async with _INPUT_LOCK:
            await asyncio.to_thread(_guard_failsafe)
            await asyncio.to_thread(human_like_type, text)
        return f"✅ Typed text."
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
            _guard_failsafe()
            pyautogui.hotkey(*key_list)

        async with _INPUT_LOCK:
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

        async with _INPUT_LOCK:
            await asyncio.to_thread(_perform_scroll)
        return f"✅ Scrolled {direction} successfully."
    except Exception as e:
        return f"❌ Failed to scroll: {e}"
