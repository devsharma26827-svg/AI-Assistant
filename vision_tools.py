import asyncio
import io
import logging
import os
import re
from livekit.agents import function_tool
from dotenv import load_dotenv
from gemini_key_manager import gemini_key_manager

# Configure logger
logger = logging.getLogger("vision_tools")
logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv(".env")
load_dotenv(".env.local", override=True)

# Vision Model Configuration
GEMINI_VISION_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.5-flash-lite").strip()
GEMINI_VISION_FALLBACK_MODEL = os.getenv("GEMINI_VISION_FALLBACK_MODEL", "gemini-flash-lite-latest").strip()
try:
    GEMINI_VISION_TIMEOUT = float(os.getenv("GEMINI_VISION_TIMEOUT", "15"))
except ValueError:
    GEMINI_VISION_TIMEOUT = 15.0

VISION_FALLBACK_MODELS = [GEMINI_VISION_MODEL]
if GEMINI_VISION_FALLBACK_MODEL and GEMINI_VISION_FALLBACK_MODEL != GEMINI_VISION_MODEL:
    VISION_FALLBACK_MODELS.append(GEMINI_VISION_FALLBACK_MODEL)

# Global dependencies (lazy load to avoid startup crashes if missing)
_PIL_INSTALLED = False
_GENAI_INSTALLED = False

try:
    from PIL import Image, ImageGrab
    _PIL_INSTALLED = True
except ImportError:
    logger.warning("Pillow (PIL) not installed. Screen capture will be disabled.")

try:
    from google import genai
    from google.genai import types
    _GENAI_INSTALLED = True
except ImportError:
    logger.warning("google-genai not installed. Vision analysis will be disabled.")

_MAX_VISION_EDGE = 1280

def _mask_sensitive_text(text: str) -> str:
    """Sanitizes any accidental API key exposure from strings."""
    if not text:
        return text
    text = re.sub(r"AIza[0-9A-Za-z-_]{20,}", "[REDACTED_KEY]", str(text))
    text = re.sub(r"AQ\.[0-9A-Za-z-_\.]{40,}", "[REDACTED_KEY]", text)
    return text

def _downscale(img):
    try:
        w, h = img.size
        longest = max(w, h)
        if longest > _MAX_VISION_EDGE:
            ratio = _MAX_VISION_EDGE / float(longest)
            img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    except Exception as e:
        logger.debug(f"vision downscale skipped: {e}")
    return img

def _capture_screen_bytes(custom_image=None) -> bytes:
    """Captures or accepts a screen image and returns downscaled JPEG bytes."""
    if custom_image is not None:
        img = _downscale(custom_image)
    else:
        screenshot = ImageGrab.grab()
        img = _downscale(screenshot)
        
    img_byte_arr = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(img_byte_arr, format="JPEG", quality=85)
    return img_byte_arr.getvalue()

def _analyze_image(image_bytes: bytes, prompt: str) -> str:
    """Sends image bytes and prompt to Gemini using key rotation and verified fallback models."""
    def _api_call(active_key: str, model_name: str) -> str:
        client = genai.Client(
            api_key=active_key,
            http_options=types.HttpOptions(timeout=int(GEMINI_VISION_TIMEOUT * 1000))
        )
        image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
        response = client.models.generate_content(
            model=model_name,
            contents=[image_part, prompt]
        )
        try:
            if response.text:
                return response.text.strip()
        except (ValueError, AttributeError):
            pass

        if hasattr(response, "candidates") and response.candidates:
            finish_reason = getattr(response.candidates[0], "finish_reason", None)
            if finish_reason and str(finish_reason).upper() not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
                return f"⚠ Vision response blocked by content safety filters (Reason: {finish_reason})."
        return "⚠ Vision response was empty or blocked."

    return gemini_key_manager.execute_with_retry(
        _api_call,
        max_retries_per_key=1,
        fallback_models=VISION_FALLBACK_MODELS
    )

async def _get_gemini_vision_response(full_prompt: str, custom_image=None) -> str:
    """Internal helper to capture screen and send to Gemini Vision. Optional custom_image allows passing a cropped PIL Image."""
    if not _PIL_INSTALLED:
        return "❌ Error: Pillow library not installed. Cannot capture screen."
    if not _GENAI_INSTALLED:
        return "❌ Error: google-genai library not installed. Cannot analyze images."
    if not gemini_key_manager.has_valid_key():
        return "❌ Error: GEMINI_API_KEY not found in environment variables."

    total_timeout = max(30.0, GEMINI_VISION_TIMEOUT * 2 + 5.0)

    try:
        loop = asyncio.get_running_loop()
        image_bytes = await loop.run_in_executor(None, _capture_screen_bytes, custom_image)
        response_text = await asyncio.wait_for(
            loop.run_in_executor(None, _analyze_image, image_bytes, full_prompt),
            timeout=total_timeout,
        )
        return response_text
    except asyncio.TimeoutError:
        logger.error(f"Vision analysis timed out after {int(total_timeout)}s")
        return "❌ Vision check timed out — Gemini took too long to respond. Try again in a moment."
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Vision analysis failed: {_mask_sensitive_text(error_msg)}")
        err_lower = error_msg.lower()
        if any(term in err_lower for term in ["rate-limited", "quota", "429", "resource_exhausted"]):
            return "❌ Gemini API quota exceeded or rate-limited. Please wait a moment and try again."
        elif any(term in err_lower for term in ["api_key_invalid", "401", "403", "unauthorized", "permission denied", "invalid api key"]):
            return "❌ Gemini API authentication failed. Please check your API key in .env.local."
        elif any(term in err_lower for term in ["404", "not found", "not supported", "is no longer available"]):
            return "❌ The configured vision model is not supported or was not found."
        elif "screen grab failed" in err_lower or "oserror" in err_lower and "grab" in err_lower:
            return "❌ Could not capture the Windows screen. Ensure your desktop is active and not locked."
        else:
            return f"❌ Failed to analyze screen: {_mask_sensitive_text(error_msg)}"

@function_tool
async def analyze_screen(query: str) -> str:
    """
    Captures the current screen and uses a vision model to respond to generic queries.
    Use this when the user asks "What is on my screen?", "Read this", or a general question.
    """
    logger.info(f"Analyzing screen with general query: {query}")
    prompt = (
        f"User Question: {query}\n"
        "Instruction: You are looking at the user's computer screen. "
        "Provide a concise, helpful answer suitable for reading aloud. "
        "Limit response to 2-3 sentences max. Focus on the active window."
    )
    return await _get_gemini_vision_response(prompt)

@function_tool
async def detect_ui_element(element_name: str) -> str:
    """
    Checks if a specific UI element (e.g., 'Send button', 'Search bar') is visible on screen.
    Use this BEFORE executing risky UI actions to verify the screen state.
    """
    logger.info(f"Detecting UI element: {element_name}")
    prompt = (
        f"Can you clearly see a '{element_name}' on the screen right now?\n"
        "Instruction: Answer ONLY with 'YES' followed by a short description of where it is, "
        "or 'NO' if it is not clearly visible. Do not guess or hallucinate."
    )
    return await _get_gemini_vision_response(prompt)

@function_tool
async def detect_error_popups() -> str:
    """
    Scans the screen for any error messages, warning dialogs, or failure notifications.
    Use this when debugging or if a previous action failed unexpectedly.
    """
    logger.info("Scanning for error popups")
    prompt = (
        "Are there any error messages, warning popups, or failure notifications visible on the screen?\n"
        "Instruction: If there are errors, read the exact error text. "
        "If everything looks normal and there are no errors, reply exactly with: 'No errors detected.'"
    )
    return await _get_gemini_vision_response(prompt)

@function_tool
async def summarize_screen_state() -> str:
    """
    Provides a structured summary of the current active application and its state.
    Use this to understand context, like finding out if a form is blank or what app is open.
    """
    logger.info("Summarizing screen state")
    prompt = (
        "Summarize the current state of the active window.\n"
        "1. What application is open?\n"
        "2. What is the main content or context?\n"
        "3. Are there any obvious pending actions (e.g., an unsent message, a blank form)?\n"
        "Instruction: Keep it structured and concise. No more than 3 bullet points."
    )
    return await _get_gemini_vision_response(prompt)


@function_tool
async def read_screen_text(region: str = "full") -> str:
    """
    Extracts and reads visible text from the current screen using high-accuracy vision OCR,
    preserving indentation, code snippets, numbers, and layout formatting.
    
    Parameters:
    - region: 'full' (entire screen) or descriptive area (e.g. 'terminal', 'active editor', 'dialog box').
    """
    logger.info(f"Extracting screen text with region: {region}")
    prompt = (
        f"Extract all readable text from this screen capture (focus area: {region}).\n"
        "Instruction: Transcribe the visible text accurately. "
        "Preserve code indentation, line breaks, file names, and error tracebacks. "
        "If text is unreadable or blurry, explicitly mention that. "
        "Do not hallucinate or summarize — return the raw extracted text."
    )
    return await _get_gemini_vision_response(prompt)
