"""
YouTube Tools for Cynthia AI Assistant.
Provides safe, metadata-only video/song playback, video search, and channel search in the default web browser.
Does NOT download any media files to disk or construct arbitrary shell commands.
"""
import asyncio
import logging
import re
import urllib.parse
import webbrowser
from livekit.agents import function_tool

# Configure logger
logger = logging.getLogger("youtube_tools")
logger.setLevel(logging.INFO)

# Global flag for lazy-checking yt_dlp
_YT_DLP_INSTALLED = False
try:
    import yt_dlp
    _YT_DLP_INSTALLED = True
except ImportError:
    logger.warning("yt-dlp is not installed. Direct video resolution will fall back to YouTube search.")


def _clean_query(query: str) -> str:
    """Removes conversational command noise while preserving songs, artists, channels, and topics."""
    if not query:
        return ""
    cleaned = query.strip().strip('"\'')

    # Strip common leading command phrases
    leading_patterns = [
        r"^(please\s+)?(play|chalao|baja\s+do|chala\s+do|open\s+karo|open|kholo|search\s+for|search\s+karo|dhoondo|find)\s+",
        r"^(youtube\s+pe|youtube\s+par|youtube\s+mein|youtube)\s+",
        r"^(cynthia\s*,?\s*)",
    ]
    for pat in leading_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    # Strip trailing phrases like "on youtube", "chalao", "play karo"
    trailing_patterns = [
        r"\s+(on\s+youtube|youtube\s+pe|youtube\s+par|youtube\s+mein|youtube)$",
        r"\s+(chalao|baja\s+do|chala\s+do|play\s+karo|play|search\s+karo|dhoondo|kholo)$",
    ]
    for pat in trailing_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE).strip()

    return cleaned or query.strip()


def _resolve_top_video_metadata(search_term: str, timeout_seconds: float = 6.0) -> tuple[str | None, str | None]:
    """
    Uses yt-dlp in flat-extraction mode to resolve the top video's ID and title.
    Returns (video_id, video_title) or (None, None).
    Guaranteed NOT to download any video or audio files.
    """
    if not _YT_DLP_INSTALLED:
        return None, None

    ydl_opts = {
        "extract_flat": True,
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": timeout_seconds,
        "noplaylist": True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{search_term}", download=False)
            entries = info.get("entries", [])
            if entries:
                first = entries[0]
                video_id = first.get("id")
                title = first.get("title", search_term)
                if video_id:
                    return str(video_id), str(title)
    except Exception as e:
        logger.warning(f"yt-dlp metadata resolution failed for '{search_term}': {e}")

    return None, None


def _open_url_safely(url: str) -> bool:
    """Opens a URL in the user's default browser."""
    try:
        return webbrowser.open(url, new=2)
    except Exception as e:
        logger.error(f"Failed to open URL in browser: {e}")
        return False


@function_tool
async def youtube_play_video(query: str) -> str:
    """
    Finds and plays a specific song or video on YouTube by opening its watch page in the default browser.
    
    Use this when the user wants to PLAY or LISTEN to a song or video:
    - "YouTube pe Arijit Singh ka Tum Hi Ho song chalao"
    - "Play the Interstellar theme on YouTube"
    - "YouTube par latest Python tutorial play karo"
    - "CarryMinati ki latest video chalao"
    - "baja do", "play karo", "chalao"
    
    Do NOT use this if the user only wants to SEARCH or browse results without playback.
    """
    raw_query = (query or "").strip()
    if not raw_query:
        return "❌ Error: Video ya song ka naam khaali nahi ho sakta."

    clean_term = _clean_query(raw_query) or raw_query
    logger.info(f"Resolving YouTube playback for query: '{raw_query}' (cleaned: '{clean_term}')")

    loop = asyncio.get_running_loop()

    # 1. Attempt metadata-only resolution off the event loop
    video_id, title = await loop.run_in_executor(None, _resolve_top_video_metadata, clean_term)

    if video_id:
        watch_url = f"https://www.youtube.com/watch?v={video_id}"
        logger.info(f"Found YouTube video: {video_id} ('{title}'). Opening watch page.")
        success = await loop.run_in_executor(None, _open_url_safely, watch_url)
        if success:
            safe_title = title if title else clean_term
            return f"✅ Boss, '{safe_title}' video YouTube par open kar diya hai."
        else:
            return f"❌ Browser open karne mein error aaya. Video link: {watch_url}"

    # 2. Fallback: If metadata resolution failed or yt-dlp unavailable, open YouTube search results
    encoded = urllib.parse.quote_plus(clean_term)
    fallback_search_url = f"https://www.youtube.com/results?search_query={encoded}"
    logger.info(f"Direct video resolution unavailable. Falling back to search URL: {fallback_search_url}")

    success = await loop.run_in_executor(None, _open_url_safely, fallback_search_url)
    if success:
        return f"⚠ Boss, exact video direct resolve nahi ho paya, isliye '{clean_term}' ke YouTube search results open kar diye hain."
    else:
        return "❌ Failed to open YouTube search results in browser."


@function_tool
async def youtube_search_videos(query: str) -> str:
    """
    Searches YouTube and displays search results in the default web browser without automatically playing a video.
    
    Use this when the user asks to SEARCH, FIND, or BROWSE videos/tutorials/topics:
    - "YouTube pe React JS tutorials search karo"
    - "lo-fi study music dhoondo YouTube par"
    - "Search for Indian startup podcasts on YouTube"
    - "results dikhao", "search karo", "dhoondo", "find"
    
    Do NOT use this if the user asks to PLAY or START a song/video.
    """
    raw_query = (query or "").strip()
    if not raw_query:
        return "❌ Error: Search query khaali nahi ho sakta."

    clean_term = _clean_query(raw_query) or raw_query
    logger.info(f"Opening YouTube search for: '{clean_term}'")

    encoded = urllib.parse.quote_plus(clean_term)
    search_url = f"https://www.youtube.com/results?search_query={encoded}"

    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, _open_url_safely, search_url)

    if success:
        return f"✅ Boss, '{clean_term}' ke YouTube search results open kar diye hain."
    else:
        return "❌ Browser mein YouTube search results open karne mein error aaya."


@function_tool
async def youtube_search_channels(channel_name: str) -> str:
    """
    Searches specifically for YouTube channels and opens channel-focused results in the default web browser.
    
    Use this when the user asks to find a creator's or official channel:
    - "YouTube pe MrBeast ka channel search karo"
    - "CarryMinati ka channel kholo"
    - "CodeWithHarry ka YouTube channel dhoondo"
    - "Find the official NASA channel on YouTube"
    - "channel search karo", "official channel"
    """
    raw_name = (channel_name or "").strip()
    if not raw_name:
        return "❌ Error: Channel ka naam khaali nahi ho sakta."

    clean_name = _clean_query(raw_name) or raw_name
    # Remove words like "channel", "official channel" from search query to get the best YouTube channel filter results
    clean_name = re.sub(r"\b(official\s+)?channel\b", "", clean_name, flags=re.IGNORECASE).strip() or clean_name
    logger.info(f"Searching YouTube channel for: '{clean_name}'")

    encoded = urllib.parse.quote_plus(clean_name)
    # sp=EgIQAg%253D%253D is YouTube's standard filter for Type: Channel
    channel_search_url = f"https://www.youtube.com/results?search_query={encoded}&sp=EgIQAg%253D%253D"

    loop = asyncio.get_running_loop()
    success = await loop.run_in_executor(None, _open_url_safely, channel_search_url)

    if success:
        return f"✅ Boss, '{clean_name}' ke channel results YouTube par open kar diye hain."
    else:
        return "❌ Browser mein YouTube channel search open karne mein error aaya."
