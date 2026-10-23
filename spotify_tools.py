"""
Spotify Music Integration Tools for Cynthia AI Assistant.
Provides Spotify track, album, and playlist searching, playback controls, and web/desktop launching.
Completely decoupled from YouTube tools to prevent playback command collisions.
"""
import os
import urllib.parse
import webbrowser
import logging
from livekit.agents import function_tool

logger = logging.getLogger("spotify_tools")
logger.setLevel(logging.INFO)

# Optional Spotipy client check
_SPOTIPY_AVAILABLE = False
try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
    _SPOTIPY_AVAILABLE = True
except ImportError:
    pass


def _get_spotify_client():
    """Initializes and returns an authenticated Spotipy client if credentials exist."""
    if not _SPOTIPY_AVAILABLE:
        return None

    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback").strip()

    if not client_id or not client_secret:
        return None

    try:
        sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scope="user-read-playback-state user-modify-playback-state user-read-currently-playing"
        ))
        return sp
    except Exception as e:
        logger.warning(f"Spotify authentication failed: {e}")
        return None


@function_tool
async def spotify_search(query: str, search_type: str = "track") -> str:
    """
    Searches for tracks, artists, albums, or playlists on Spotify.
    
    Parameters:
    - query: Search query (e.g. 'Kesariya', 'Coldplay', 'Lofi Beats').
    - search_type: 'track' (default), 'artist', 'album', or 'playlist'.
    """
    clean_q = (query or "").strip()
    if not clean_q:
        return "❌ Error: Search query khaali nahi ho sakta."

    sp = _get_spotify_client()
    if sp:
        try:
            stype = search_type.lower() if search_type in {"track", "artist", "album", "playlist"} else "track"
            results = sp.search(q=clean_q, limit=3, type=stype)
            items = results.get(f"{stype}s", {}).get("items", [])
            if items:
                lines = [f"🎵 Spotify Search Results for '{clean_q}':"]
                for it in items:
                    name = it.get("name")
                    artist = it.get("artists", [{}])[0].get("name", "") if "artists" in it else ""
                    artist_str = f" by {artist}" if artist else ""
                    lines.append(f"• {name}{artist_str} ({it.get('external_urls', {}).get('spotify', '')})")
                return "\n".join(lines)
        except Exception as e:
            logger.warning(f"Spotipy query error: {e}")

    # Fallback to browser search
    encoded = urllib.parse.quote_plus(clean_q)
    url = f"https://open.spotify.com/search/{encoded}"
    try:
        webbrowser.open(url, new=2)
        return f"✅ Boss, Spotify par '{clean_q}' search results browser mein open kar diye hain."
    except Exception as e:
        return f"❌ Spotify open karne mein error aaya: {e}"


@function_tool
async def spotify_play(query: str = "", uri: str = "") -> str:
    """
    Starts playback of a track, album, or playlist on Spotify.
    
    Parameters:
    - query: Name of the track, artist, or playlist.
    - uri: Specific Spotify URI if available (e.g. 'spotify:track:xxx').
    """
    clean_q = (query or "").strip()
    sp = _get_spotify_client()

    if sp:
        try:
            devices = sp.devices().get("devices", [])
            if not devices:
                return "ℹ Spotify par koi active device nahi mila. Kripya pehle apne phone ya PC par Spotify app open karein."
            
            device_id = devices[0]["id"]
            if uri:
                sp.start_playback(device_id=device_id, uris=[uri] if "track" in uri else None, context_uri=uri if "track" not in uri else None)
                return f"✅ Spotify active device '{devices[0]['name']}' par playback start kar diya hai."
            elif clean_q:
                results = sp.search(q=clean_q, limit=1, type="track")
                tracks = results.get("tracks", {}).get("items", [])
                if tracks:
                    track_uri = tracks[0]["uri"]
                    track_name = tracks[0]["name"]
                    sp.start_playback(device_id=device_id, uris=[track_uri])
                    return f"✅ Spotify par '{track_name}' play kar diya hai ({devices[0]['name']} par)."
        except Exception as e:
            logger.warning(f"Spotipy playback start error: {e}")

    # Fallback: Open in browser/desktop app
    encoded = urllib.parse.quote_plus(clean_q)
    fallback_url = f"https://open.spotify.com/search/{encoded}"
    try:
        webbrowser.open(fallback_url, new=2)
        return (
            f"✅ Boss, '{clean_q}' Spotify web player mein open kar diya hai.\n"
            f"(Note: Direct API playback control ke liye `.env.local` mein Spotify credentials configure karein)."
        )
    except Exception as e:
        return f"❌ Spotify open karne mein error aaya: {e}"


@function_tool
async def spotify_playback_control(action: str) -> str:
    """
    Controls Spotify playback: 'pause', 'resume', 'next', 'previous', or 'status'.
    
    Parameters:
    - action: One of 'pause', 'resume', 'next', 'previous', 'status'.
    """
    act = (action or "status").strip().lower()
    sp = _get_spotify_client()

    if not sp:
        return (
            "ℹ Spotify API credentials (`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`) "
            "configure nahi hain. Kripya `.env.local` check karein."
        )

    try:
        if act in {"pause", "stop"}:
            sp.pause_playback()
            return "✅ Spotify playback pause kar diya hai."
        elif act in {"resume", "play", "unpause"}:
            sp.start_playback()
            return "✅ Spotify playback resume kar diya hai."
        elif act in {"next", "skip"}:
            sp.next_track()
            return "✅ Spotify par agla track play kar diya hai."
        elif act in {"previous", "back"}:
            sp.previous_track()
            return "✅ Spotify par pichla track play kar diya hai."
        elif act == "status":
            current = sp.current_playback()
            if current and current.get("is_playing"):
                item = current.get("item", {})
                title = item.get("name", "Unknown")
                artist = item.get("artists", [{}])[0].get("name", "Unknown")
                return f"🎵 Currently playing on Spotify: '{title}' by {artist}."
            return "ℹ Spotify abhi paused hai ya koi track play nahi ho raha."
        else:
            return f"❌ Unknown Spotify action '{action}'."
    except Exception as e:
        logger.error(f"Spotify control error: {e}")
        return f"❌ Spotify action failed: {e}"


@function_tool
async def spotify_get_status() -> str:
    """
    Checks and returns the currently playing track and artist on Spotify.
    """
    return await spotify_playback_control("status")
