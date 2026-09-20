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

load_dotenv(".env.local")

# Pre-warm the SSL default context in a background thread as soon as this
# module loads. Without this, the first Gemini connection pays a ~500ms
# synchronous "event loop blocked" stall (seen in your logs, at ssl.py line
# 770) the moment GenAIClient builds its own SSL context — because that's the
# first time the certifi CA bundle gets read/parsed. Doing it here, off the
# event loop and well before the RealtimeModel is created, means that cost is
# already paid by the time the real connection happens.
import ssl as _ssl
import threading as _threading
_threading.Thread(target=_ssl.create_default_context, daemon=True).start()

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
from whatsapp_tools import whatsapp_message
from content_writer_tools import write_text, write_code

from memory_store import memory
from intelligence_tools import remember_fact, update_emotional_state, update_life_phase, get_user_context, learn_habit, forget_habit, set_communication_style
from file_manager_tools import save_file_as, open_current_file
from translation_tools import translate_text, translate_document, set_language_mode
from project_tools import create_project, add_task_to_project, get_project_status, update_task_status
from environment_tools import set_system_volume, set_screen_brightness, activate_mode, get_environment_state
from learning_tools import manage_self_learning
from vision_tools import analyze_screen, detect_ui_element, detect_error_popups, summarize_screen_state
from reply_intelligence_tools import smart_auto_reply, auto_reply_decision
from workflow_tools import create_workflow, list_workflows, trigger_workflow
from human_computer_tools import human_click_element, human_type_text, human_press_shortcut, human_scroll

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
    remember_fact, get_user_context,
    save_file_as, open_current_file,
    translate_text,
    set_system_volume, set_screen_brightness,
    run_shell_command, run_code_file,
]

EXTENDED_TOOLS = [
    arrange_window, swap_windows,
    update_emotional_state, update_life_phase, learn_habit, forget_habit,
    translate_document, set_language_mode, set_communication_style,
    create_project, add_task_to_project, get_project_status, update_task_status,
    activate_mode, get_environment_state, manage_self_learning,
    smart_auto_reply, auto_reply_decision,
    analyze_screen, detect_ui_element, detect_error_popups, summarize_screen_state,
    create_workflow, list_workflows, trigger_workflow,
    human_click_element, human_type_text, human_press_shortcut, human_scroll,
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

@server.rtc_session()
async def my_agent(ctx: agents.JobContext):
    
    # Supress annoying WinError 64 tracebacks from livekit background tasks
    loop = asyncio.get_running_loop()
    loop.set_exception_handler(custom_asyncio_exception_handler)
    
    # Load Memory & Format Prompt
    memory_context = memory.get_formatted_context()
    formatted_instructions = build_agent_instructions(memory_context)

    # Accelerate Voice Activity Detection (VAD)
    # Reduces the time JARVIS waits after you stop speaking from 800ms+ down to 400ms
    fast_vad_config = genai_types.RealtimeInputConfig(
        automatic_activity_detection=genai_types.AutomaticActivityDetection(
            silence_duration_ms=400 
        )
    )

    session = AgentSession(
        llm=google.beta.realtime.RealtimeModel(
            model=GEMINI_LIVE_MODEL,
            instructions=formatted_instructions,
            api_key=gemini_key_manager.get_current_key(),
            **_realtime_voice_options(),
            realtime_input_config=fast_vad_config
        ),
        tools=ACTIVE_TOOLS
    )

    # NOTE on the tools list below: registering every tool on every session
    # makes the Realtime API process a much bigger function-calling schema on
    # every turn, which adds latency and makes the model more likely to pick
    # the wrong tool. Set TOOL_MODE=full in .env only if you actively need the
    # rarer tools (vision/workflow) in a given session.

    # Play startup sound BEFORE connecting to Gemini so no API deadlines are running
    await play_startup_sound()

    await session.start(
        room=ctx.room,
        agent=Assistant(),
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony() if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP else noise_cancellation.BVC(),
            ),
        ),
    )

    reply_instructions = f"Current Context: {memory_context}\n\n{REPLY_PROMPT}"
    await session.generate_reply(
        instructions=reply_instructions
    )


if __name__ == "__main__":
    agents.cli.run_app(server)
