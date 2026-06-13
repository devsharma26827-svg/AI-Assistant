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
    create_system_folder, create_system_file
)
from whatsapp_tools import whatsapp_message, whatsapp_file, read_last_message, whatsapp_call, whatsapp_reply
from content_writer_tools import write_text, write_code

from memory_store import memory
from intelligence_tools import remember_fact, update_emotional_state, update_life_phase, get_user_context, learn_habit, forget_habit, set_communication_style
from file_manager_tools import save_file_as, open_current_file
from scheduling_tools import schedule_task, get_schedule, complete_task, reschedule_task, defer_task
from translation_tools import translate_text, translate_document, set_language_mode
from project_tools import create_project, add_task_to_project, get_project_status, update_task_status
from environment_tools import set_system_volume, set_screen_brightness, activate_mode, get_environment_state
from learning_tools import manage_self_learning
from visualization_tools import generate_visual_report
from vision_tools import analyze_screen, detect_ui_element, detect_error_popups, summarize_screen_state
from reply_intelligence_tools import smart_auto_reply, auto_reply_decision
from distributed_tools import list_ecosystem_devices, send_command_to_device, broadcast_command, find_device_for_capability
from workflow_tools import create_workflow, list_workflows, trigger_workflow
from hardware_tools import control_smart_device, trigger_ecosystem_routine
from project_generator_tools import generate_full_project
from gesture_tools import toggle_gesture_mode
from human_computer_tools import human_click_element, human_type_text, human_press_shortcut, human_scroll

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



def custom_asyncio_exception_handler(loop, context):
    exception = context.get('exception')
    msg = context.get('message', '')
    
    # Catch WinError 64 (Network name is no longer available) typical for dropped websockets
    if exception is not None:
        exc_str = str(exception)
        if isinstance(exception, OSError) and getattr(exception, 'winerror', None) == 64:
            logging.warning("⚠️ Warning: LiveKit WebSocket connection dropped (WinError 64). Reconnecting...")
            return
        if "no close frame received or sent" in exc_str or "no close frame" in msg:
            logging.warning("⚠️ Warning: WebSocket closed abnormally. Handled gracefully.")
            return
        if "1008" in exc_str and "policy violation" in exc_str:
            logging.warning("⚠️ Warning: WebSocket policy violation (1008). Reconnecting...")
            return
        if "1011" in exc_str and ("internal error" in exc_str or "deadline" in exc_str.lower()):
            logging.warning("⚠️ Warning: Gemini API deadline expired (1011). Reconnecting...")
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
            instructions=formatted_instructions,
            api_key=gemini_key_manager.get_current_key(),
            **_realtime_voice_options(),
            realtime_input_config=fast_vad_config
        ),
        tools=[
            get_weather,
            get_connected_devices,
            serp_search,
            get_current_datetime,
            open_app,
            close_app,
            folder_file,
            control_window,
            arrange_window,
            swap_windows,
            take_screenshot,
            set_volume,
            get_battery_status,
            create_system_folder,
            create_system_file,
            whatsapp_message,
            whatsapp_file,
            read_last_message,
            whatsapp_call,
            whatsapp_reply,
            write_text,
            write_code,
            remember_fact,
            update_emotional_state,
            update_life_phase,
            get_user_context,
            learn_habit,
            forget_habit,
            save_file_as,
            open_current_file,
            schedule_task,
            get_schedule,
            complete_task,
            reschedule_task,
            defer_task,
            translate_text,
            translate_document,
            set_language_mode,
            set_communication_style,
            create_project,
            add_task_to_project,
            get_project_status,
            update_task_status,
            set_system_volume,
            set_screen_brightness,
            activate_mode,
            get_environment_state,
            manage_self_learning,
            generate_visual_report,
            smart_auto_reply,
            auto_reply_decision,
            list_ecosystem_devices,
            send_command_to_device,
            broadcast_command,
            find_device_for_capability,
            analyze_screen,
            detect_ui_element,
            detect_error_popups,
            summarize_screen_state,
            create_workflow,
            list_workflows,
            trigger_workflow,
            control_smart_device,
            trigger_ecosystem_routine,
            generate_full_project,
            toggle_gesture_mode,
            human_click_element,
            human_type_text,
            human_press_shortcut,
            human_scroll
        ]
    )

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
