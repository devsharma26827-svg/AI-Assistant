"""
Cynthia AI Assistant - Main LiveKit Voice Agent Entry Point.
Coordinates WebRTC voice streams, real-time input configuration (VAD), 
Gemini model execution, tool invocation, and memory synchronization.
"""
import os
import asyncio
import logging
import subprocess
from dotenv import load_dotenv
from prompts import INSTRUCTIONS_PROMPT, REPLY_PROMPT
from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io
from livekit.plugins import (
    google,
    noise_cancellation,
)
from gemini_key_manager import gemini_key_manager
import google.genai.types as genai_types

load_dotenv(".env.local", override=True)

# Pre-warm the SSL default context with a cached wrapper synchronously.
# This eliminates the 683ms "event loop blocked" stall at ssl.py create_default_context
# when the Gemini Realtime client initializes, caching both no-arg and certifi-specific contexts.
import ssl as _ssl
import threading as _threading
import certifi

_orig_create_default_context = _ssl.create_default_context
_ssl_cache = {}
_ssl_cache_lock = _threading.Lock()

def _make_ssl_cache_key(*args, **kwargs):
    try:
        kw_items = tuple(sorted((k, str(v)) for k, v in kwargs.items()))
        return (args, kw_items)
    except Exception:
        return None

def _cached_create_default_context(*args, **kwargs):
    key = _make_ssl_cache_key(*args, **kwargs)
    if key is not None and key in _ssl_cache:
        return _ssl_cache[key]
    with _ssl_cache_lock:
        if key is not None and key in _ssl_cache:
            return _ssl_cache[key]
        ctx = _orig_create_default_context(*args, **kwargs)
        if key is not None:
            _ssl_cache[key] = ctx
        return ctx

_ssl.create_default_context = _cached_create_default_context

def _warmup_ssl_sync():
    """Synchronously pre-warm SSL contexts so the event loop never stalls on TLS initialization."""
    try:
        _ssl.create_default_context()
        cafile = os.environ.get("SSL_CERT_FILE", certifi.where())
        capath = os.environ.get("SSL_CERT_DIR")
        _ssl.create_default_context(cafile=cafile, capath=capath)
    except Exception:
        pass

_warmup_ssl_sync()

ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Cynthia")
ASSISTANT_VOICE = os.getenv("ASSISTANT_VOICE", "Aoede")
ASSISTANT_LANGUAGE = os.getenv("ASSISTANT_LANGUAGE", "").strip()
PERSONALITY_PROFILE_PROMPT = f"""
Identity and personality profile:
- Assistant name: {ASSISTANT_NAME}
- Gender identity: Female assistant
- Voice: {ASSISTANT_VOICE}
- Role: the user's responsible, friendly, emotionally aware personal AI assistant.
- Character: feminine, caring, dependable, organized, respectful, and gently confident.
- Voice characteristics: warm, friendly, clear, naturally expressive, and calm under pressure.
- Accent and tone: Indian English / Hinglish feel through wording and rhythm.
- Speaking style: concise first, helpful next. Use soft confidence, not robotic formality.
- Self-reference: use feminine Hindi/Hinglish phrasing such as "मैं तैयार हूँ", "मैं कर देती हूँ", "मैं संभाल लूँगी", and "मैं आपकी मदद कर सकती हूँ".
- Do not speak like a male butler or call yourself male. Avoid masculine self-phrases like "कर सकता हूँ" for yourself.
- Address policy: use the user's name only during the first introduction. After that, address the user as "Boss", "ji Boss", or "aap". Do not combine the user's full name with "sir" in normal replies.
- Be responsible: confirm risky actions, remember context, keep responses clear, and take ownership when fixing problems.
- Be friendly: warm, lightly witty, encouraging, and supportive without becoming childish or overdramatic.
- Keep the original assistant speed, tool skills, productivity focus, and responsiveness.
"""


def _realtime_voice_options() -> dict[str, str]:
    opts = {"voice": ASSISTANT_VOICE}
    if ASSISTANT_LANGUAGE:
        opts["language"] = ASSISTANT_LANGUAGE
    return opts

# The Gemini Live/Realtime model. We pin this explicitly instead of relying
# on the plugin's built-in default: Google regularly retires dated preview
# Live models every few months (this is exactly what caused your
# "1008 policy violation: Requested entity was not found" crash — the old
# default, gemini-2.5-flash-native-audio-preview-12-2025, is no longer being
# served). gemini-3.1-flash-live-preview is Google's currently recommended
# model for all Live API use cases. If Google renames/retires this one too in
# the future, you can switch it without touching code via .env.local:
#   GEMINI_LIVE_MODEL=whatever-the-new-model-is-called
GEMINI_LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview").strip()

from livekit.plugins.google.realtime.realtime_api import RealtimeModel, RealtimeSession
from livekit.agents.voice.agent_session import CloseReason, CloseEvent
from livekit.agents import APIConnectionError, utils, llm

# Pre-warm modules to eliminate startup event loop stall warnings
try:
    import anyio._core._sockets
except Exception:
    pass

class ResilientRealtimeSession(RealtimeSession):
    """
    Subclassed RealtimeSession providing self-healing session resumption:
    1. Resets stale _session_resumption_handle on retry to prevent 1011 -> 1008 rejection loops.
    2. Signals connected status to model via _report_connection_acquired.
    3. Prevents premature timeout during high-latency mobile hotspot handshakes.
    """
    def _build_connect_config(self) -> genai_types.LiveConnectConfig:
        if self._num_retries > 0:
            logging.info(
                f"[RESILIENCE] Reconnecting attempt #{self._num_retries}: clearing stale session_resumption handle "
                "so Gemini server does not reject with 1008 session expired."
            )
            self._session_resumption_handle = None
            self._resumption_chat_ctx = None
        return super()._build_connect_config()

    def _mark_restart_needed(self, on_error: bool = False) -> None:
        if on_error:
            self._session_resumption_handle = None
            self._resumption_chat_ctx = None
        super()._mark_restart_needed(on_error=on_error)

    def _report_connection_acquired(self, acquire_time: float) -> None:
        super()._report_connection_acquired(acquire_time)
        if hasattr(self._realtime_model, "set_connected"):
            self._realtime_model.set_connected()


class ResilientRealtimeModel(RealtimeModel):
    """
    Subclassed RealtimeModel that instantiates ResilientRealtimeSession
    and exposes connection readiness futures.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connected_event = asyncio.Event()

    def session(self, *, turn_detection_disabled: bool = False) -> ResilientRealtimeSession:
        sess = ResilientRealtimeSession(self)
        self._sessions.add(sess)
        return sess

    def set_connected(self) -> None:
        self._connected_event.set()

    def reset_connected(self) -> None:
        self._connected_event.clear()

    async def wait_for_connection(self, timeout: float = 15.0) -> None:
        await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)


def build_agent_instructions(memory_context: str = "") -> str:
    return (
        PERSONALITY_PROFILE_PROMPT
        + "\n"
        + INSTRUCTIONS_PROMPT.format(memory_context=memory_context)
    )

class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(instructions=build_agent_instructions())

server = AgentServer()

from jarvis_get_whether import get_weather
from google_search_tools import serp_search, get_current_datetime
from system_control_tools import (
    open_app, close_app, folder_file, control_window, arrange_window, swap_windows,
    take_screenshot, set_volume, get_battery_status, get_connected_devices,
    create_system_folder, create_system_file, run_shell_command, run_code_file
)
from whatsapp_tools import whatsapp_message, whatsapp_open_chat, whatsapp_draft_message, whatsapp_search_chat, whatsapp_call
from tool_serializer import reset_tool_barrier
from content_writer_tools import write_text, write_code

from memory_store import memory
from intelligence_tools import remember_fact, forget_fact, update_emotional_state, update_life_phase, get_user_context, learn_habit, forget_habit, set_communication_style
from file_manager_tools import save_file_as, open_current_file
from translation_tools import translate_text, translate_document, set_language_mode
from project_tools import create_project, add_task_to_project, get_project_status, update_task_status
from environment_tools import set_system_volume, set_screen_brightness, activate_mode, get_environment_state, get_system_volume, adjust_system_volume, mute_system_volume, get_screen_brightness, adjust_screen_brightness
from learning_tools import manage_self_learning
from vision_tools import analyze_screen, detect_ui_element, detect_error_popups, summarize_screen_state, read_screen_text
from reply_intelligence_tools import smart_auto_reply, auto_reply_decision
from workflow_tools import create_workflow, list_workflows, trigger_workflow
from human_computer_tools import human_click_element, human_type_text, human_press_shortcut, human_scroll
from youtube_tools import (
    youtube_play_video,
    youtube_search_videos,
    youtube_search_channels,
    youtube_pause_playback,
    youtube_resume_playback,
    youtube_seek_playback,
    youtube_next_video,
    youtube_previous_video,
    youtube_get_playback_status,
)
from empathy_tools import adapt_conversational_tone
from code_assistant_tools import explain_code, analyze_error_and_suggest_fix, apply_code_fix, generate_unit_tests, read_clipboard_text, solve_coding_problem
from website_builder_tools import build_website_template, preview_website
from power_tools import power_shutdown, power_restart, power_sleep, power_hibernate, power_cancel_scheduled_shutdown, power_get_status
from support_ticket_tools import create_support_ticket, list_support_tickets, get_support_ticket, update_ticket_status
from email_tools import draft_email, get_email_draft, send_email
from spotify_tools import spotify_search, spotify_play, spotify_playback_control, spotify_get_status
from network_tools import get_wifi_status, list_wifi_networks, list_saved_wifi_profiles, connect_wifi_profile, disconnect_wifi
from defender_tools import get_defender_status, run_defender_quick_scan, scan_file_with_defender, get_defender_threats
from scheduler_tools import (
    scheduler,
    get_current_time,
    schedule_reminder,
    schedule_action,
    list_scheduled_tasks,
    cancel_scheduled_task,
    resolve_missed_task,
)

# -----------------------------------------------------------------------
# Tool footprint control (see note near session.tools below for why this
# matters for latency and tool-selection accuracy).
#
# TOOL_MODE=core (default): the everyday local-assistant tools.
# TOOL_MODE=full: also loads the rarer vision/workflow tools below.
#                 Set this in .env if you need them.
# -----------------------------------------------------------------------
TOOL_MODE = os.getenv("TOOL_MODE", "core").strip().lower()

CORE_TOOLS = [
    get_weather, get_current_datetime, serp_search, get_connected_devices,
    open_app, close_app, folder_file, control_window,
    take_screenshot, set_volume, get_battery_status,
    create_system_folder, create_system_file,
    whatsapp_message,
    write_text, write_code,
    remember_fact, forget_fact, forget_habit, get_user_context,
    save_file_as, open_current_file,
    translate_text,
    set_system_volume, set_screen_brightness,
    run_shell_command, run_code_file,
    youtube_play_video, youtube_search_videos, youtube_search_channels,
    youtube_pause_playback, youtube_resume_playback, youtube_seek_playback,
    youtube_next_video, youtube_previous_video, youtube_get_playback_status,
    whatsapp_open_chat, whatsapp_draft_message, whatsapp_search_chat, whatsapp_call,
    get_system_volume, adjust_system_volume, mute_system_volume, get_screen_brightness, adjust_screen_brightness,
    adapt_conversational_tone,
    explain_code, analyze_error_and_suggest_fix, apply_code_fix, read_clipboard_text, solve_coding_problem,
    build_website_template, preview_website,
    power_shutdown, power_restart, power_sleep, power_hibernate, power_cancel_scheduled_shutdown, power_get_status,
    create_support_ticket, list_support_tickets, get_support_ticket, update_ticket_status,
    draft_email, get_email_draft, send_email,
    spotify_search, spotify_play, spotify_playback_control, spotify_get_status,
    get_wifi_status, list_wifi_networks, list_saved_wifi_profiles, connect_wifi_profile, disconnect_wifi,
    get_current_time, schedule_reminder, schedule_action, list_scheduled_tasks, cancel_scheduled_task, resolve_missed_task,
]

EXTENDED_TOOLS = [
    arrange_window, swap_windows,
    update_emotional_state, update_life_phase, learn_habit,
    translate_document, set_language_mode, set_communication_style,
    create_project, add_task_to_project, get_project_status, update_task_status,
    activate_mode, get_environment_state, manage_self_learning,
    smart_auto_reply, auto_reply_decision,
    analyze_screen, detect_ui_element, detect_error_popups, summarize_screen_state,
    create_workflow, list_workflows, trigger_workflow,
    human_click_element, human_type_text, human_press_shortcut, human_scroll,
    generate_unit_tests, read_screen_text,
    get_defender_status, run_defender_quick_scan, scan_file_with_defender, get_defender_threats,
]

ACTIVE_TOOLS = CORE_TOOLS + EXTENDED_TOOLS if TOOL_MODE == "full" else CORE_TOOLS

# Optional legacy startup sound. Disabled by default so the female assistant
# does not start with an old male Jarvis audio clip.
_STARTUP_SOUND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sound effects", "Jarvis startup voice.mp3")
PLAY_STARTUP_SOUND = os.getenv("PLAY_STARTUP_SOUND", "false").lower() in {"1", "true", "yes", "on"}

async def play_startup_sound():
    """Play the JARVIS startup sound using Windows WinMM API (non-blocking)."""
    try:
        if not PLAY_STARTUP_SOUND:
            return

        if not os.path.exists(_STARTUP_SOUND):
            logging.warning(f"Startup sound not found at: {_STARTUP_SOUND}")
            return

        import ctypes
        winmm = ctypes.WinDLL("winmm")

        # Use MCI (Media Control Interface) — works with .mp3 without extra packages
        sound_path = _STARTUP_SOUND.replace("/", "\\")
        open_cmd  = f'open "{sound_path}" type mpegvideo alias jarvis_sound'
        play_cmd  = 'play jarvis_sound'   # No 'wait' — non-blocking
        close_cmd = 'close jarvis_sound'

        # Open & start playback (runs in background thread, returns immediately)
        def _start_sound():
            winmm.mciSendStringW(open_cmd, None, 0, None)
            winmm.mciSendStringW(play_cmd, None, 0, None)

        def _stop_sound():
            winmm.mciSendStringW(close_cmd, None, 0, None)

        await asyncio.to_thread(_start_sound)
        await asyncio.sleep(3)        # Give sound ~3 sec to play while event loop stays alive
        await asyncio.to_thread(_stop_sound)

    except Exception as e:
        logging.warning(f"Could not play startup sound: {e}")



_disconnect_event_count = 0

def custom_asyncio_exception_handler(loop, context):
    """
    IMPORTANT: this only SUPPRESSES the traceback for known noisy disconnect
    errors — it does NOT reconnect anything. LiveKit's own worker/job system
    is what recovers a dropped job. If you keep seeing these often, the real
    fix is removing whatever is blocking the event loop (see get_file_index /
    time.sleep-in-async fixes) rather than tuning this handler further.
    """
    global _disconnect_event_count
    exception = context.get('exception')
    msg = context.get('message', '')

    if exception is not None:
        exc_str = str(exception)
        is_known_disconnect = (
            (isinstance(exception, OSError) and getattr(exception, 'winerror', None) == 64)
            or "no close frame received or sent" in exc_str or "no close frame" in msg
            or ("1008" in exc_str and "policy violation" in exc_str)
            or ("1011" in exc_str and ("internal error" in exc_str or "deadline" in exc_str.lower()))
        )
        if is_known_disconnect:
            _disconnect_event_count += 1
            logging.warning(f"⚠️ Connection drop #{_disconnect_event_count} suppressed: {exc_str[:120]}")
            if _disconnect_event_count >= 3:
                logging.error(
                    "🚨 3+ connection drops this session — this usually means something is "
                    "blocking the event loop (a slow tool call). Check for time.sleep() or "
                    "unthreaded blocking work in your @function_tool functions."
                )
            return

    # Call default handler for everything else
    loop.default_exception_handler(context)


async def _guarded_startup_greeting(
    session: AgentSession,
    model: ResilientRealtimeModel,
    memory_context: str
) -> None:
    """
    Safely plays startup greeting:
    1. Waits up to 15s for the Realtime connection handshake to be established.
    2. Tries generate_reply with 1 retry on timeout/error.
    3. NEVER crashes the session if greeting fails; Cynthia stays alive and listening.
    """
    reply_instructions = f"Current Context: {memory_context}\n\n{REPLY_PROMPT}"
    
    # 1. Wait for connection readiness
    try:
        logging.info("Awaiting Gemini Realtime connection handshake before greeting...")
        await model.wait_for_connection(timeout=15.0)
        logging.info("Gemini Realtime connection handshake confirmed ready.")
    except (asyncio.TimeoutError, Exception) as e:
        logging.warning(f"⚠️ Did not confirm connection before greeting timeout ({e}). Skipping startup greeting.")
        return

    await asyncio.sleep(0.3)  # Brief settle window

    # 2. Greeting attempt with 1 retry
    for attempt in range(1, 3):
        try:
            logging.info(f"Generating startup greeting (attempt {attempt}/2)...")
            handle = session.generate_reply(instructions=reply_instructions)
            await asyncio.wait_for(handle, timeout=12.0)
            if handle.exception():
                raise handle.exception()
            logging.info("Startup greeting completed successfully.")
            return
        except Exception as e:
            logging.warning(f"⚠️ Startup greeting attempt {attempt}/2 failed: {e}")
            if attempt == 1:
                await asyncio.sleep(1.0)
            else:
                logging.warning("⚠️ Startup greeting failed after 2 attempts. Continuing session in listening mode.")


@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    reset_tool_barrier()
    
    # Suppress annoying WinError 64 tracebacks from livekit background tasks
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(custom_asyncio_exception_handler)
    
    # Load Memory & Format Prompt
    memory_context = memory.get_formatted_context()
    formatted_instructions = build_agent_instructions(memory_context)

    # Accelerate Voice Activity Detection (VAD)
    # Reduces the time JARVIS waits after you stop speaking from 800ms+ down to 400ms
    fast_vad_config = genai_types.RealtimeInputConfig(
        automatic_activity_detection=genai_types.AutomaticActivityDetection(
            silence_duration_ms=int(os.getenv("VAD_SILENCE_DURATION_MS", "500")) 
        )
    )

    # Play startup sound BEFORE connecting to Gemini so no API deadlines are running
    await play_startup_sound()

    max_attempts = 5
    attempt = 0
    backoff = 1.0

    # Simulation hook for Task B verification
    simulate_crash = os.getenv("SIMULATE_REALTIME_CRASH", "").strip().lower() in ("1", "true", "yes")

    shutdown_event = asyncio.Event()

    async def _on_shutdown(reason: str = ""):
        shutdown_event.set()
        scheduler.stop()

    ctx.add_shutdown_callback(_on_shutdown)
    scheduler.start()

    while not shutdown_event.is_set():
        attempt += 1
        model = ResilientRealtimeModel(
            model=GEMINI_LIVE_MODEL,
            instructions=formatted_instructions,
            api_key=gemini_key_manager.get_current_key(),
            **_realtime_voice_options(),
            realtime_input_config=fast_vad_config
        )

        session = AgentSession(
            llm=model,
            tools=ACTIVE_TOOLS
        )

        session_closed_event = asyncio.Event()
        session_close_event_holder: list[CloseEvent | None] = [None]

        @session.on("close")
        def _on_session_close(event: CloseEvent):
            session_close_event_holder[0] = event
            session_closed_event.set()

        try:
            # Ensure primary session on JobContext points to this fresh session
            ctx._primary_agent_session = None

            await session.start(
                room=ctx.room,
                agent=Assistant(),
                room_options=room_io.RoomOptions(
                    audio_input=room_io.AudioInputOptions(
                        noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                        if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                        else noise_cancellation.BVC(),
                    ),
                ),
            )

            # Update scheduler with the live session across restarts/reconnects
            scheduler.set_active_session(session)

            if simulate_crash and attempt < 3:
                logging.warning(f"[SIMULATION] Simulating Realtime crash on attempt {attempt}")
                raise APIConnectionError("Simulated Gemini Realtime APIConnectionError")

            # Guarded startup greeting (attempt 1 only)
            if attempt == 1:
                await _guarded_startup_greeting(session, model, memory_context)
                # Check for missed tasks while Cynthia/laptop was offline and notify user once
                await scheduler.check_startup_missed_tasks(session)
            else:
                logging.info(f"✨ [SUPERVISOR] Reconnection attempt {attempt-1} succeeded! Assistant is back online.")

            # Wait until either the session closes or the job is requested to shut down
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(session_closed_event.wait(), name="session-closed-wait"),
                    asyncio.create_task(shutdown_event.wait(), name="shutdown-wait"),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if shutdown_event.is_set():
                logging.info("Job shutdown requested (user exit or Ctrl+C). Exiting supervisor.")
                break

            close_ev = session_close_event_holder[0]
            if close_ev and close_ev.reason != CloseReason.ERROR:
                logging.info(f"AgentSession closed normally with reason: {close_ev.reason}. Exiting supervisor.")
                break

            error_details = close_ev.error if close_ev else "Unknown session closure"
            logging.error(f"AgentSession closed due to unrecoverable error: {error_details}")

        except asyncio.CancelledError:
            logging.info("Supervisor received CancelledError (user shutdown). Exiting cleanly.")
            break
        except Exception as e:
            logging.error(f"Session startup or execution error: {e}", exc_info=True)

        try:
            await session.aclose()
        except Exception:
            pass

        if shutdown_event.is_set():
            break

        if attempt >= max_attempts:
            msg = f"🚨 [SUPERVISOR] Maximum reconnection attempts ({max_attempts}) reached. Gemini Realtime connection could not be restored."
            logging.error(msg)
            print(f"\n{msg}\nPlease check your internet connection or Gemini API credentials.\n")
            try:
                await ctx.shutdown("max_reconnect_attempts_exceeded")
            except Exception:
                pass
            break

        delay = backoff * (2 ** (attempt - 1))  # 1s, 2s, 4s, 8s
        logging.warning(f"[RECONNECT] attempt {attempt}/{max_attempts} failed. Retrying in {delay:.1f}s...")
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=delay)
            break  # Shutdown fired during backoff
        except asyncio.TimeoutError:
            pass  # Backoff finished, retry next attempt


if __name__ == "__main__":
    agents.cli.run_app(server)
