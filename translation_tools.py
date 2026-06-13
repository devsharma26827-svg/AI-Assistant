import logging
import os
from deep_translator import GoogleTranslator
from livekit.agents import function_tool
from memory_store import memory

logger = logging.getLogger("translation_tools")
logger.setLevel(logging.INFO)

@function_tool
async def translate_text(text: str, target_language: str) -> str:
    """
    Translates text to the specified target language using Google Translate.
    
    Arguments:
    - text: The text to translate.
    - target_language: The target language code or name (e.g., 'es', 'spanish', 'hindi', 'hi').
    """
    try:
        # Auto-correct common language names to codes if needed, but deep-translator handles names well.
        # "hinglish" is not standard, map to Hindi or keep as is? 
        # Deep translator doesn't support "hinglish". Map to Hindi.
        if target_language.lower() in ["hinglish", "hindish"]:
            target_language = "hindi"
            
        translator = GoogleTranslator(source='auto', target=target_language)
        translated = translator.translate(text)
        return f"Translated ({target_language}): {translated}"
    except Exception as e:
        logger.error(f"Translation failed: {e}")
        return f"❌ Translation failed: {e}"

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
