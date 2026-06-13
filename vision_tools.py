import asyncio
import logging
import os
import io
import warnings
from livekit.agents import function_tool
from dotenv import load_dotenv
from gemini_key_manager import gemini_key_manager

# Configure logger
logger = logging.getLogger("vision_tools")
logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv(".env")
load_dotenv(".env.local")

# Global dependencies (lazy load to avoid startup crashes if missing)
_PIL_INSTALLED = False
_GENAI_INSTALLED = False

try:
    from PIL import Image, ImageGrab
    _PIL_INSTALLED = True
except ImportError:
    logger.warning("Pillow (PIL) not installed. Screen capture will be disabled.")

try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        import google.generativeai as genai
    _GENAI_INSTALLED = True
except ImportError:
    logger.warning("google-generativeai not installed. Vision analysis will be disabled.")

async def _get_gemini_vision_response(full_prompt: str, custom_image=None) -> str:
    """Internal helper to capture screen and send to Gemini Vision. Optional custom_image allows passing a cropped PIL Image."""
    if not _PIL_INSTALLED:
        return "❌ Error: Pillow library not installed. Cannot capture screen."
    if not _GENAI_INSTALLED:
        return "❌ Error: google-generativeai library not installed. Cannot analyze images."

    if not gemini_key_manager.api_keys or gemini_key_manager.api_keys == [""]:
        return "❌ Error: GEMINI_API_KEY not found in environment variables."

    def _capture_screen():
        if custom_image is not None:
             return custom_image
        screenshot = ImageGrab.grab()
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return Image.open(img_byte_arr)

    def _analyze_image(img, prompt):
        def _api_call(active_key, model_name):
            genai.configure(api_key=active_key)
            model = genai.GenerativeModel(model_name)
            response = model.generate_content([prompt, img])
            return response.text
        return gemini_key_manager.execute_with_retry(_api_call, max_retries_per_key=1)

    try:
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, _capture_screen)
        response_text = await loop.run_in_executor(None, _analyze_image, image, full_prompt)
        return response_text
    except Exception as e:
        logger.error(f"Vision analysis failed: {e}")
        return f"❌ Failed to analyze screen: {str(e)}"

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

