import logging
import os
from deep_translator import GoogleTranslator
from livekit.agents import function_tool
from memory_store import memory

logger = logging.getLogger("translation_tools")
logger.setLevel(logging.INFO)

# deep-translator only accepts its own language names/codes. The model often
# passes a capitalised English name ("Hindi") or a variant that the library
# rejects outright ("Hindi --> No support for the provided language"), so
# normalise the common cases to ISO codes before calling it.
_LANG_ALIASES = {
    "hindi": "hi", "hinglish": "hi", "hindish": "hi",
    "english": "en", "spanish": "es", "french": "fr", "german": "de",
    "japanese": "ja", "chinese": "zh-CN", "mandarin": "zh-CN",
    "arabic": "ar", "russian": "ru", "portuguese": "pt", "italian": "it",
    "korean": "ko", "bengali": "bn", "punjabi": "pa", "gujarati": "gu",
    "marathi": "mr", "tamil": "ta", "telugu": "te", "kannada": "kn",
    "malayalam": "ml", "urdu": "ur", "nepali": "ne", "sanskrit": "sa",
}


def _normalize_language(target_language: str) -> str:
    key = (target_language or "").strip().lower()
    return _LANG_ALIASES.get(key, key)

@function_tool
async def translate_text(text: str, target_language: str) -> str:
    """
    Translates text to the specified target language using Google Translate.
    
    Arguments:
    - text: The text to translate.
    - target_language: The target language code or name (e.g., 'es', 'spanish', 'hindi', 'hi').
    """
    try:
        target_language = _normalize_language(target_language)

        import asyncio

        def _translate():
            return GoogleTranslator(source='auto', target=target_language).translate(text)

        loop = asyncio.get_running_loop()
        # Google's free endpoint rate-limits aggressively; retry with backoff
        # instead of failing the whole request on the first 429.
        last_error = None
        for attempt in range(3):
            try:
                translated = await asyncio.wait_for(
                    loop.run_in_executor(None, _translate), timeout=12
                )
                return f"Translated ({target_language}): {translated}"
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                if attempt < 2 and ("many requests" in msg or "server error" in msg):
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
                break

        # Fallback: Google Translate is rate-limited or down, so ask Gemini.
        # Translation stays usable instead of failing outright.
        fallback = await _gemini_translate(text, target_language)
        if fallback:
            return f"Translated ({target_language}): {fallback}"

        raise last_error
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return f"❌ Translation failed: {e}"


async def _gemini_translate(text: str, target_language: str):
    """Translates via Gemini when the primary translator is unavailable."""
    try:
        import asyncio
        import google.generativeai as genai
        from gemini_key_manager import gemini_key_manager

        prompt = (
            f"Translate the following text into {target_language}. "
            f"Reply with ONLY the translation, no quotes, no explanation.\n\n{text}"
        )

        def _call():
            def _api(active_key, model_name):
                genai.configure(api_key=active_key)
                return genai.GenerativeModel(model_name).generate_content(prompt).text
            return gemini_key_manager.execute_with_retry(_api)

        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _call), timeout=20
        )
        return (result or "").strip() or None
    except Exception as e:
        logger.warning(f"Gemini translation fallback failed: {e}")
        return None

@function_tool
async def translate_document(file_path: str, target_language: str) -> str:
    """
    Translates the content of a text-based file and saves it as a new file.
    Supported: .txt, .md, .py (translates comments/strings logic is hard, so just treats as text for now).
    
    Arguments:
    - file_path: Absolute path to the file.
    - target_language: Target language.
    """
    import asyncio
    
    if not os.path.exists(file_path):
        return "❌ File not found."
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Chunking might be needed for large files (5000 chars limit usually for free APIs)
        # Deep translator handles chunking internally? No, need to be careful.
        # Let's do simple naive chunking if needed, or just let it try.
        # Deep translator `translate` takes text. 
        # For simplicity, if content > 4000 chars, warn.
        if len(content) > 4000:
            return "❌ File too large for free translation (limit 4000 chars)."
        
        loop = asyncio.get_running_loop()
        translator = GoogleTranslator(source='auto', target=target_language)
        translated_content = await loop.run_in_executor(None, translator.translate, content)
        
        # Save new file
        dir_name = os.path.dirname(file_path)
        base_name = os.path.basename(file_path)
        name, ext = os.path.splitext(base_name)
        new_filename = f"{name}_{target_language}{ext}"
        new_path = os.path.join(dir_name, new_filename)
        
        with open(new_path, 'w', encoding='utf-8') as f:
            f.write(translated_content)
            
        return f"✅ Document translated and saved to: {new_path}"
        
    except Exception as e:
        return f"❌ Document translation failed: {e}"

@function_tool
async def set_language_mode(primary_language: str, mode: str = "auto") -> str:
    """
    Sets the agent's primary language mode.
    
    Arguments:
    - primary_language: e.g., "Hindi", "English", "Spanish".
    - mode: "strict" (always reply in this lang) or "auto" (adapt to user).
    """
    memory.update_language_preference(primary=primary_language, mode=mode)
    return f"✅ Language set to {primary_language} ({mode} mode)."
