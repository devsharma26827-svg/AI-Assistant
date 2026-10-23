"""
YouTube Tools for Cynthia AI Assistant.
Provides safe, metadata-only video/song playback, video search, channel search,
and headless background playback controls (pause, resume, seek, next, previous, status)
via Windows Global System Media Transport Controls (GSMTC).
Does NOT download any media files to disk, construct arbitrary shell commands,
or steal keyboard/window focus from active applications.
"""
import asyncio
import datetime
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

# Global flag for WinRT Windows Media Control (GSMTC)
_WINSDK_INSTALLED = False
try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus,
    )
    _WINSDK_INSTALLED = True
except (ImportError, AttributeError):
    logger.warning("winsdk is not installed or not supported on this platform. Windows media session controls will be unavailable.")


# Common browser & YouTube identifiers in Windows GSMTC SourceAppUserModelId
BROWSER_APP_KEYWORDS = (
    "youtube",
    "chrome",
    "msedge",
    "edge",
    "firefox",
    "brave",
    "opera",
    "vivaldi",
    "arc",
    "browser",
)


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


# ---------------------------------------------------------------------------
# Background YouTube / Browser Playback Controls via Windows GSMTC
# ---------------------------------------------------------------------------

def _format_duration(seconds: float) -> str:
    """Formats a duration in seconds into M:SS or H:MM:SS (standard YouTube player style)."""
    secs = int(max(0, round(seconds)))
    hrs = secs // 3600
    mins = (secs % 3600) // 60
    rem_secs = secs % 60
    if hrs > 0:
        return f"{hrs}:{mins:02d}:{rem_secs:02d}"
    return f"{mins}:{rem_secs:02d}"


async def _get_youtube_media_session():
    """
    Finds the active media session for YouTube or a supported web browser
    using Windows Global System Media Transport Controls (GSMTC).
    Does NOT steal window focus or simulate global keyboard presses.
    """
    if not _WINSDK_INSTALLED:
        return None

    try:
        mgr = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        if not mgr:
            return None

        # 1. Prioritize current active session if it matches a browser or YouTube
        current = mgr.get_current_session()
        if current:
            app_id = (current.source_app_user_model_id or "").lower()
            if any(k in app_id for k in BROWSER_APP_KEYWORDS):
                return current

        # 2. Inspect all active sessions
        sessions = mgr.get_sessions()
        if not sessions:
            return current

        # A) Explicit YouTube session (AppId contains "youtube")
        for s in sessions:
            app_id = (s.source_app_user_model_id or "").lower()
            if "youtube" in app_id:
                return s

        # B) Browser session that is currently PLAYING
        for s in sessions:
            app_id = (s.source_app_user_model_id or "").lower()
            if any(k in app_id for k in BROWSER_APP_KEYWORDS):
                info = s.get_playback_info()
                if info and info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
                    return s

        # C) Browser session that is currently PAUSED
        for s in sessions:
            app_id = (s.source_app_user_model_id or "").lower()
            if any(k in app_id for k in BROWSER_APP_KEYWORDS):
                info = s.get_playback_info()
                if info and info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED:
                    return s

        # D) Any session matching browser keywords
        for s in sessions:
            app_id = (s.source_app_user_model_id or "").lower()
            if any(k in app_id for k in BROWSER_APP_KEYWORDS):
                return s

        # E) Return current session if present
        return current
    except Exception as e:
        logger.error(f"Error querying Windows media session: {e}")
        return None


async def _get_session_title(session) -> str:
    """Helper to extract media title from a GSMTC session."""
    if not session:
        return ""
    try:
        props = await session.try_get_media_properties_async()
        if props and props.title:
            return props.title.strip()
    except Exception as e:
        logger.debug(f"Could not read media properties title: {e}")
    return ""


@function_tool
async def youtube_pause_playback() -> str:
    """
    Pauses currently playing YouTube video, song, or browser media in the background without switching windows or stealing focus.
    
    Use this when the user asks to PAUSE playback:
    - "YouTube pause karo"
    - "Song pause karo"
    - "Video pause karo"
    - "YouTube ko band nahi, bas pause karo"
    - "Roko", "pause"
    
    Do NOT use this to close or stop an application.
    """
    if not _WINSDK_INSTALLED:
        return "❌ Boss, background playback control ke liye 'winsdk' library zaroori hai. Kripya 'pip install winsdk' karein."

    session = await _get_youtube_media_session()
    if not session:
        return "ℹ Boss, koi active YouTube playback ya browser media session nahi mila. Kripya pehle browser mein YouTube video start karein."

    try:
        info = session.get_playback_info()
        title = await _get_session_title(session)
        display_name = f"'{title}'" if title else "YouTube video"

        if info and info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED:
            return f"Boss, {display_name} pehle se hi paused hai."

        success = await session.try_pause_async()
        if success:
            return f"✅ Boss, {display_name} pause kar diya hai."
        else:
            return f"❌ Boss, {display_name} pause nahi ho paya. Browser media controls allow hone chahiye."
    except Exception as e:
        logger.error(f"Error pausing playback: {e}")
        return f"❌ Playback pause karne mein error aaya: {e}"


@function_tool
async def youtube_resume_playback() -> str:
    """
    Resumes or unpauses the currently paused YouTube video, song, or browser media in the background without switching windows.
    
    Use this when the user asks to RESUME, PLAY, or UNPAUSE an existing paused video:
    - "Song play karo" / "Song resume karo"
    - "Video resume karo" / "YouTube resume karo"
    - "YouTube chalao" (when video is already open/paused, NOT searching for a new song)
    - "Unpause karo", "continue karo"
    
    Do NOT use this if the user asks to search or play a BRAND NEW song/title.
    """
    if not _WINSDK_INSTALLED:
        return "❌ Boss, background playback control ke liye 'winsdk' library zaroori hai. Kripya 'pip install winsdk' karein."

    session = await _get_youtube_media_session()
    if not session:
        return "ℹ Boss, koi active YouTube playback ya browser media session nahi mila. Kripya pehle browser mein YouTube video open karein."

    try:
        info = session.get_playback_info()
        title = await _get_session_title(session)
        display_name = f"'{title}'" if title else "YouTube video"

        if info and info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
            return f"Boss, {display_name} pehle se hi chal rahi hai."

        success = await session.try_play_async()
        if success:
            return f"✅ Boss, {display_name} resume kar diya hai."
        else:
            return f"❌ Boss, {display_name} resume nahi ho paya."
    except Exception as e:
        logger.error(f"Error resuming playback: {e}")
        return f"❌ Playback resume karne mein error aaya: {e}"


@function_tool
async def youtube_seek_playback(seconds: int = 10, direction: str = "forward") -> str:
    """
    Seeks forward or backward in the currently playing YouTube video by a specific number of seconds in the background.
    
    Parameters:
    - seconds: Number of seconds to jump (e.g. 10, 20, 30, 45, 60 for 1 minute, 120 for 2 minutes).
    - direction: "forward" (default, "aage", "skip") or "backward" ("peeche", "back", "rewind").
    
    Use this when the user asks to SKIP, JUMP, FORWARD, or REWIND time in the current video:
    - "10 second aage karo" -> seconds=10, direction="forward"
    - "20 seconds skip karo" -> seconds=20, direction="forward"
    - "30 second forward karo" -> seconds=30, direction="forward"
    - "Is video ko 45 seconds aage kar do" -> seconds=45, direction="forward"
    - "Ek minute aage skip karo" -> seconds=60, direction="forward"
    - "10 second peeche karo" -> seconds=10, direction="backward"
    - "20 seconds rewind karo" -> seconds=20, direction="backward"
    - "30 second back jao" -> seconds=30, direction="backward"
    - "Ek minute rewind karo" -> seconds=60, direction="backward"
    
    Do NOT confuse this with searching for a new video or playing a new song!
    """
    if not _WINSDK_INSTALLED:
        return "❌ Boss, background playback control ke liye 'winsdk' library zaroori hai. Kripya 'pip install winsdk' karein."

    try:
        dur = int(seconds)
    except (ValueError, TypeError):
        return "❌ Error: Seek duration valid number honi chahiye."

    if dur <= 0:
        return "❌ Error: Seek duration 0 se zyada honi chahiye."

    dir_clean = (direction or "forward").strip().lower()
    if dir_clean in {"backward", "back", "rewind", "peeche", "peche", "reverse"}:
        delta = -dur
        dir_label = "peeche"
    else:
        delta = dur
        dir_label = "aage"

    session = await _get_youtube_media_session()
    if not session:
        return "ℹ Boss, koi active YouTube playback ya browser media session nahi mila."

    try:
        timeline = session.get_timeline_properties()
        if not timeline or timeline.position is None:
            return "❌ Boss, video ki current timeline read nahi ho saki. Browser mein media controls support hona zaroori hai."

        current_sec = timeline.position.total_seconds()
        min_sec = timeline.min_seek_time.total_seconds() if (timeline and timeline.min_seek_time) else 0.0
        max_sec = 0.0
        if timeline and timeline.max_seek_time and timeline.max_seek_time.total_seconds() > 0:
            max_sec = timeline.max_seek_time.total_seconds()
        elif timeline and timeline.end_time and timeline.end_time.total_seconds() > 0:
            max_sec = timeline.end_time.total_seconds()

        target_sec = current_sec + delta
        if max_sec > 0:
            target_sec = max(min_sec, min(max_sec, target_sec))
        else:
            target_sec = max(min_sec, target_sec)

        # 100-nanosecond ticks for Windows TimeSpan
        ticks = int(target_sec * 10_000_000)
        success = await session.try_change_playback_position_async(ticks)

        if success:
            pos_str = _format_duration(target_sec)
            dur_str = f" / {_format_duration(max_sec)}" if max_sec > 0 else ""
            return f"✅ Boss, video {dur} second {dir_label} kar diya hai ({pos_str}{dur_str} par)."
        else:
            return "❌ Boss, YouTube video position change karne mein error aaya."
    except Exception as e:
        logger.error(f"Error seeking playback: {e}")
        return f"❌ Seek karne mein error aaya: {e}"


@function_tool
async def youtube_next_video() -> str:
    """
    Skips to the next video or track in the current YouTube playlist or queue in the background.
    
    Use this when the user asks to skip to the NEXT video:
    - "Isko next video par le jao"
    - "Next song chalao"
    - "Agla video lagao"
    - "Skip to next"
    """
    if not _WINSDK_INSTALLED:
        return "❌ Boss, background playback control ke liye 'winsdk' library zaroori hai. Kripya 'pip install winsdk' karein."

    session = await _get_youtube_media_session()
    if not session:
        return "ℹ Boss, koi active YouTube playback ya browser media session nahi mila."

    try:
        success = await session.try_skip_next_async()
        if success:
            return "✅ Boss, agle video/song par skip kar diya hai."
        else:
            return "❌ Boss, next video par skip karne ki koshish fail hui."
    except Exception as e:
        logger.error(f"Error skipping next: {e}")
        return f"❌ Next video par jane mein error aaya: {e}"


@function_tool
async def youtube_previous_video() -> str:
    """
    Skips to the previous video or track in the current YouTube playlist or queue in the background.
    
    Use this when the user asks to go back to the PREVIOUS video:
    - "Previous video chalao"
    - "Pichla song lagao"
    - "Pichle video par jao"
    - "Play previous"
    """
    if not _WINSDK_INSTALLED:
        return "❌ Boss, background playback control ke liye 'winsdk' library zaroori hai. Kripya 'pip install winsdk' karein."

    session = await _get_youtube_media_session()
    if not session:
        return "ℹ Boss, koi active YouTube playback ya browser media session nahi mila."

    try:
        success = await session.try_skip_previous_async()
        if success:
            return "✅ Boss, pichle video/song par skip kar diya hai."
        else:
            return "❌ Boss, previous video par skip karne ki koshish fail hui."
    except Exception as e:
        logger.error(f"Error skipping previous: {e}")
        return f"❌ Previous video par jane mein error aaya: {e}"


@function_tool
async def youtube_get_playback_status() -> str:
    """
    Checks and returns the current YouTube playback state, title, artist, and time position in the background.
    
    Use this when the user asks about current media status:
    - "Kaunsa song chal raha hai?"
    - "YouTube par kya chal raha hai?"
    - "Video kitni bachi hai?"
    - "What is currently playing?"
    """
    if not _WINSDK_INSTALLED:
        return "❌ Boss, background playback control ke liye 'winsdk' library zaroori hai. Kripya 'pip install winsdk' karein."

    session = await _get_youtube_media_session()
    if not session:
        return "ℹ Boss, abhi koi YouTube ya browser media playback active nahi hai."

    try:
        info = session.get_playback_info()
        status_name = "Unknown"
        if info:
            if info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PLAYING:
                status_name = "Playing"
            elif info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.PAUSED:
                status_name = "Paused"
            elif info.playback_status == GlobalSystemMediaTransportControlsSessionPlaybackStatus.STOPPED:
                status_name = "Stopped"

        props = await session.try_get_media_properties_async()
        title = props.title.strip() if props and props.title else "Unknown Title"
        artist = props.artist.strip() if props and props.artist else ""

        timeline = session.get_timeline_properties()
        pos_str = ""
        dur_str = ""
        if timeline and timeline.position is not None:
            pos_str = _format_duration(timeline.position.total_seconds())
            max_sec = 0.0
            if timeline.max_seek_time and timeline.max_seek_time.total_seconds() > 0:
                max_sec = timeline.max_seek_time.total_seconds()
            elif timeline.end_time and timeline.end_time.total_seconds() > 0:
                max_sec = timeline.end_time.total_seconds()
            if max_sec > 0:
                dur_str = f" / {_format_duration(max_sec)}"

        time_part = f" [{pos_str}{dur_str}]" if pos_str else ""
        artist_part = f" by {artist}" if artist else ""

        icon = "🎵" if status_name == "Playing" else ("⏸" if status_name == "Paused" else "⏹")
        return f"{icon} Boss, YouTube: '{title}'{artist_part} - Status: {status_name}{time_part}"
    except Exception as e:
        logger.error(f"Error getting playback status: {e}")
        return f"❌ Playback status lene mein error aaya: {e}"

