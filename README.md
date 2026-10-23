# Cynthia: Local Personal AI Assistant

Cynthia is a low-latency, real-time voice-driven AI assistant for your Windows laptop/PC. Built upon LiveKit's WebRTC agent framework and powered by Google's Gemini API, Cynthia controls your local machine, remembers context about you, and helps you get things done by voice or text.

---

## Overview

Cynthia combines responsive vocal interaction with local system control. She maintains a warm, helpful, emotionally aware, and gently confident female persona. Whether communicating via Hinglish or English, Cynthia remembers details, learns user habits, writes text/code, manages files, and interfaces directly with your Windows OS, screen vision tools, YouTube media playback, and external APIs.

---

## Key Features

* **Real-Time Vocal Interaction**: Fast, natural two-way voice communication using LiveKit WebRTC channels and Gemini's Live Realtime audio streaming.
* **Smart Key & Model Rotation**: Manages multiple Gemini API keys and automatically rotates across keys on quota/rate limits (429) and falls back across verified model names on unsupported model errors.
* **Independent Screen Vision**: Captures the active Windows desktop with Pillow and analyzes screen context, locates UI buttons/elements, and checks for error popups using Google's modern `google-genai` SDK with dedicated vision models (`GEMINI_VISION_MODEL`), completely independent from the realtime voice model.
* **YouTube Video & Song Playback**: Plays requested songs and videos in the default web browser via metadata-only resolution (`yt-dlp`), searches for video topics, and discovers creator channels without downloading any files or requiring paid YouTube API keys.
* **Persistent Dynamic Memory**: Structured, local file-based memory store (`memory.json`) tracking user profiles, life phases, hobbies, habits, projects, and emotional states.
* **Deep Windows System Control**: Adjusts volume and screen brightness, arranges desktop windows, captures screenshots, opens/closes applications, runs shell commands, and manages files and folders.
* **Desktop Automation**: Navigates GUI apps using keyboard shortcuts, mouse clicks, and typing.
* **Content Writing**: Generates text drafts and starter code directly into files or open windows.
* **WhatsApp Text Messaging**: Sends a WhatsApp text message to a named contact via desktop app automation. (File sharing, reading messages, replying, and calling are not supported).
* **Smart Reply Suggestions**: Generates suggested Hinglish reply options and safety recommendations for incoming messages.
* **Integrations & Workflows**: OpenWeatherMap weather forecasts, SerpAPI Google Search, document translation, lightweight task/project tracking, and user-defined workflow triggers.

---

## Architecture Overview

Cynthia runs locally on your machine with dependencies flowing inward to the active root-level modules:

```mermaid
graph TD
    A["User Microphone / Text Console"] -->|WebRTC / Console| B["Master Voice Agent (agent.py)"]
    B -->|Gemini Live Bidirectional Audio| C["LiveKit Realtime Model (gemini-3.1-flash-live-preview)"]
    B -->|Tool Invocations (TOOL_MODE=core / full)| D["Active Root Tool Modules (*_tools.py)"]
    D -->|Screen Capture & Vision Analysis| E["Gemini Vision Engine (google-genai / gemini-3.5-flash-lite)"]
    D -->|YouTube Playback & Search| F["YouTube Engine (youtube_tools.py / yt-dlp / browser)"]
    D -->|Key Rotation & Fallback Handling| G["Gemini Key Manager (gemini_key_manager.py)"]
    D -->|Local OS APIs & Automation| H["Windows OS (pywin32, pycaw, PyAutoGUI, WMI)"]
    D -->|Read / Write State| I["JSON Memory Store (memory_store.py -> memory.json)"]
```

### Active Implementation Modules

The active runtime application is comprised of the root-level Python modules imported by `agent.py`:
- `agent.py`: Master LiveKit Voice Agent entrypoint coordinating sessions, voice options, and tool registries.
- `gemini_key_manager.py`: Key rotation, cooldown tracking, sanitized logging, and model fallback management.
- `vision_tools.py`: Screen capture (`Pillow`), JPEG downscaling, and image analysis using `google-genai`.
- `youtube_tools.py`: Fast, metadata-only video/song playback, video search, channel search, and background media playback controls via Windows GSMTC.
- `memory_store.py`: Local JSON memory persistence controller.
- `system_control_tools.py`: Windows volume, brightness, process management, screenshot capture, and shell execution.
- `file_manager_tools.py` & `project_tools.py`: Local file I/O and task/project tracking.
- `whatsapp_tools.py`: Windows WhatsApp desktop automation.
- `translation_tools.py`: Text translation with Google Translator and Gemini fallback.
- `google_search_tools.py` & `jarvis_get_whether.py`: SerpAPI search and OpenWeatherMap APIs.
- `human_computer_tools.py` & `workflow_tools.py`: UI automation and custom macro workflows.

> [!NOTE]
> The `services/` and `src/` directories contain older historical snapshots and are not imported by `agent.py`. All active development and runtime execution uses the root-level modules.

---

## Technology Stack

* **Core Runtime**: Python 3.11 on Windows 10/11
* **Vocal RTC**: `livekit` & `livekit-agents` (v1.8+)
* **Live Audio Model**: `livekit-plugins-google` (`google.beta.realtime.RealtimeModel`)
* **Vision & Text AI**: `google-genai` (Google's official GenAI SDK)
* **Screen Capture & Imaging**: `Pillow` (PIL)
* **YouTube & Media Controls**: `yt-dlp` (metadata search only, no downloading), `winsdk` (Windows GSMTC background playback control)
* **Desktop Automation**: `pywin32`, `pycaw`, `screen-brightness-control`, `PyAutoGUI`, `PyGetWindow`, `psutil`
* **Translation**: `deep-translator`
* **Search & APIs**: SerpAPI (`requests`), OpenWeatherMap

---

## Folder Structure

```
.
├── .github/                   # GitHub Action workflows and issue templates
├── services/                  # Older reference copies (not imported by agent.py)
├── src/                       # Older reference copies (not imported by agent.py)
├── tests/                     # Automated pytest test suites (vision, YouTube, keys, memory, system)
├── utils/                     # System control helper utilities
├── agent.py                   # Main LiveKit Voice Agent entrypoint
├── gemini_key_manager.py      # Gemini API key and model fallback manager
├── memory_store.py            # Local JSON memory database driver
├── memory.json                # Local memory database file
├── prompts.py                 # Core system prompts & personality profile
├── requirement.txt            # Pinned Python dependencies
├── run_assistant_console.bat  # Windows voice launcher
├── run_assistant_text.bat     # Windows text-only debug launcher
├── vision_tools.py            # Screen capture & image understanding tools
├── youtube_tools.py           # YouTube playback, search, and background media controls
└── .env.local.example         # Environment template
```

---

## Installation Guide

### Prerequisites

* **OS**: Windows 10 or 11 (required for Windows COM/Win32 APIs, sound device control, and desktop automation).
* **Python**: Python 3.11 (ensure `python.exe` is added to your Windows `PATH`).
* **LiveKit**: A free LiveKit Cloud account (or local LiveKit server) providing `LIVEKIT_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`.
* **Google Gemini API Key**: At least one API key from [Google AI Studio](https://aistudio.google.com/).

### Local Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/devsharma26827-svg/AI-Assistant.git
   cd AI-Assistant
   ```

2. **Create and Activate Virtual Environment**:
   ```powershell
   python -m venv venv311
   .\venv311\Scripts\activate
   ```

3. **Install Dependencies**:
   ```powershell
   pip install -r requirement.txt
   ```

4. **Configure Environment Variables**:
   Copy `.env.local.example` to `.env.local`:
   ```powershell
   copy .env.local.example .env.local
   ```
   Open `.env.local` in an editor and configure your credentials.

---

## Environment Variables Configuration

The assistant reads `.env.local` on startup. Key configuration settings include:

| Variable Name | Required | Description | Default / Recommended |
| ------------- | :------: | ----------- | --------------------- |
| `GEMINI_API_KEYS` | **Yes** | Comma-separated Gemini API keys for automatic key rotation on quota limits (429) | `key1,key2` |
| `GEMINI_API_KEY` | Optional | Fallback single key if `GEMINI_API_KEYS` is not set | `your_key_here` |
| `GEMINI_LIVE_MODEL` | Optional | Gemini model used for real-time bidirectional audio streaming via LiveKit | `gemini-3.1-flash-live-preview` |
| `GEMINI_VISION_MODEL` | Optional | Primary model used for screen capture & image understanding | `gemini-3.5-flash-lite` |
| `GEMINI_VISION_FALLBACK_MODEL` | Optional | Fallback model if primary vision model returns 404/unsupported | `gemini-flash-lite-latest` |
| `GEMINI_VISION_TIMEOUT` | Optional | Per-request timeout in seconds for Gemini vision API calls | `15` |
| `TOOL_MODE` | Optional | Tool loading footprint: `core` (30 core tools including YouTube, fast) or `full` (59 tools including Vision & Workflows) | `core` |
| `ASSISTANT_NAME` | Optional | Voice assistant name | `Cynthia` |
| `ASSISTANT_VOICE` | Optional | LiveKit TTS voice profile | `Aoede` |
| `PLAY_STARTUP_SOUND` | Optional | Non-blocking startup sound | `false` |
| `LIVEKIT_URL` | **Yes** | LiveKit WebSocket endpoint | `wss://your-project.livekit.cloud` |
| `LIVEKIT_API_KEY` | **Yes** | LiveKit project API key | `API...` |
| `LIVEKIT_API_SECRET` | **Yes** | LiveKit project API secret | `secret...` |
| `SERPAPI_API_KEY` | Optional | SerpAPI key for Google web search | `your_serpapi_key` |
| `OPENWEATHER_API_KEY` | Optional | OpenWeatherMap API key for weather queries | `your_weather_key` |

> [!IMPORTANT]
> **Independent Voice vs. Vision Models**:
> Changing `GEMINI_VISION_MODEL` (e.g. to `gemini-3.8-flash`) modifies ONLY the screen image analysis engine. It does **not** change or disrupt Cynthia's core LiveKit voice model (`GEMINI_LIVE_MODEL`), and vice versa.

---

## Running Cynthia

### 1. Voice Interaction (Default)
Double-click `run_assistant_console.bat` or run:
```powershell
.\venv311\Scripts\python.exe agent.py console
```
Speak into your microphone. Cynthia will connect to LiveKit and respond vocally in real time. Press `Ctrl+T` to switch between voice and text input in the console.

### 2. Text Debug Mode
Double-click `run_assistant_text.bat` or run:
```powershell
.\venv311\Scripts\python.exe agent.py console --text
```
Type prompts directly into the terminal without microphone streaming.

### 3. Enabling Screen Vision
To use Cynthia's screen vision tools (`analyze_screen`, `detect_ui_element`, `detect_error_popups`, `summarize_screen_state`), ensure `.env.local` contains:
```env
TOOL_MODE=full
```
When enabled, you can say:
- *"What is currently on my screen?"*
- *"Can you see a submit button?"*
- *"Check if there are any error dialogs on screen."*
- *"Summarize what app is open right now."*

### 4. YouTube Voice Commands
YouTube tools are part of `CORE_TOOLS` and work out-of-the-box in both `TOOL_MODE=core` and `TOOL_MODE=full`:
- *"Cynthia, YouTube pe Arijit Singh ka Tum Hi Ho song chalao."* (Resolves & plays top video)
- *"Play the Interstellar theme on YouTube."* (Resolves & plays top video)
- *"YouTube pe Python tutorials search karo."* (Opens video search results)
- *"CarryMinati ka channel search karo."* (Opens channel-filtered results)

---

## YouTube Integration (Voice-Controlled Playback, Search & Background Controls)

Cynthia integrates YouTube playback, search, and headless background media controls directly in Windows without downloading media files, constructing arbitrary shell commands, or stealing keyboard/window focus:

### Tools & Behaviors

#### 1. Launch & Search Tools
1. **`youtube_play_video(query)`**: Uses `yt-dlp` in flat metadata-only mode to find the best match and opens its direct watch page (`https://www.youtube.com/watch?v=...`) in your default browser. Never downloads media to disk. Falls back safely to search results if direct resolution is unavailable.
2. **`youtube_search_videos(query)`**: Opens YouTube search results (`https://www.youtube.com/results?search_query=...`) without automatically selecting or playing a video.
3. **`youtube_search_channels(channel_name)`**: Opens channel-filtered search results (`sp=EgIQAg%253D%253D`) to discover creator channels without confusing them with individual videos or guessing unverified handles.

#### 2. Background Playback Control Tools (Windows GSMTC)
4. **`youtube_pause_playback()`**: Pauses currently playing YouTube video or browser media in the background without switching active windows or interrupting work in VS Code.
5. **`youtube_resume_playback()`**: Resumes/unpauses the existing video without restarting or searching.
6. **`youtube_seek_playback(seconds, direction)`**: Seeks relative position forward (`"forward"`, `"aage"`) or backward (`"backward"`, `"peeche"`) by arbitrary durations (e.g. 10s, 20s, 30s, 45s, 60s/1 min). Clamps safely within video timeline bounds `[min_seek, max_seek]`.
7. **`youtube_next_video()`**: Skips to the next video or track in the queue or playlist.
8. **`youtube_previous_video()`**: Skips to the previous video or track in the queue.
9. **`youtube_get_playback_status()`**: Returns current playback state (Playing / Paused), video title, artist/channel, and position/duration timestamp.

### Voice Command Examples

| Category | Example Voice Commands (Hindi / Hinglish / English) | Tool Invoked |
| -------- | --------------------------------------------------- | ------------ |
| **Play Video / Song** | *"YouTube pe Arijit Singh ka Tum Hi Ho song chalao"*<br>*"Play Interstellar theme on YouTube"* | `youtube_play_video` |
| **Search Videos** | *"YouTube pe React JS tutorials search karo"*<br>*"Lo-fi study music dhoondo YouTube par"* | `youtube_search_videos` |
| **Search Channel** | *"CarryMinati ka channel search karo"*<br>*"Find NASA official channel on YouTube"* | `youtube_search_channels` |
| **Pause Playback** | *"Cynthia, YouTube pause karo"*<br>*"Song pause kar do"*<br>*"YouTube ko band nahi, bas pause karo"* | `youtube_pause_playback` |
| **Resume Playback** | *"Song play karo"*<br>*"Video resume karo"*<br>*"YouTube playback continue karo"* | `youtube_resume_playback` |
| **Seek Forward** | *"10 second aage karo"*<br>*"20 seconds skip karo"*<br>*"Is video ko 45 seconds aage kar do"*<br>*"Ek minute aage skip karo"* | `youtube_seek_playback(seconds, "forward")` |
| **Seek Backward** | *"10 second peeche karo"*<br>*"20 seconds rewind karo"*<br>*"30 second back jao"*<br>*"Ek minute rewind karo"* | `youtube_seek_playback(seconds, "backward")` |
| **Next / Previous** | *"Isko next video par le jao"*<br>*"Previous video chalao"* | `youtube_next_video` / `youtube_previous_video` |
| **Check Status** | *"Kaunsa song chal raha hai?"*<br>*"YouTube par kya chal raha hai?"* | `youtube_get_playback_status` |

### Background Control Architecture (No Focus Stealing)
Background media controls are powered by Windows Runtime **Global System Media Transport Controls (GSMTC)** via `winsdk`.
- **Zero Window Interference**: You can actively type code in VS Code, browse files, or write documents without Cynthia switching focus, minimizing windows, or stealing keyboard input.
- **No Fragile Keystrokes**: Unlike simulators that press Space or arrow keys (which type into active text editors), GSMTC controls media at the OS kernel/transport level.
- **Browser Compatibility**: Works with Microsoft Edge, Google Chrome, Mozilla Firefox, Brave, Opera, and Vivaldi (standard Media Session API enabled by default).

### Dependencies & Setup
- Powered by `yt-dlp` (metadata search) and `winsdk` (Windows GSMTC control), both listed in `requirement.txt`.
- **No Paid API Key Needed**: Operates without a YouTube Data API v3 key or quota limits.
- **Browser Playback**: Videos open in your default browser. Autoplay behavior follows your browser's media permission settings.

### Known Limitations
- Requires an active internet connection.
- Autoplay depends on your browser's autoplay policies.
- Background playback controls require the browser to support and enable media sessions (default in modern browsers).

---

## Automated Testing

Run the full pytest test suite from the activated virtual environment:
```powershell
.\venv311\Scripts\pytest tests
```
The test suite covers:
- YouTube playback resolution, video search, channel search, and fallback handling
- Screen capture, downscaling, and image passing to Gemini models
- Key rotation and cooldown handling across 429 quota limits
- Automatic fallback across unsupported models (404)
- Missing dependencies, missing API keys, and timeouts
- Authentication/permission errors and API key masking (no secrets in logs or responses)
- Memory store persistence and security sanitization checks

---

## Troubleshooting Guide

### 1. Screen Vision Timeouts (`Vision analysis timed out after 35s`)
- **Cause**: Using reasoning/thinking models (such as `gemini-3.8-flash` without thinking limits) or cycling through multiple deprecated models sequentially can cause response times exceeding 30–60 seconds.
- **Fix**: Use the verified fast model `gemini-3.5-flash-lite` (default in `GEMINI_VISION_MODEL`), which typically responds in 1–2 seconds. You can adjust the request timeout with `GEMINI_VISION_TIMEOUT=15` in `.env.local`.

### 2. Unsupported Model Errors (`Model gemini-2.5-flash unsupported`)
- **Cause**: Google AI Studio restricts newly generated API keys from accessing older 2.0 and 2.5 preview models, returning `404 NOT_FOUND: This model is no longer available to new users`.
- **Fix**: Ensure `GEMINI_VISION_MODEL` is set to a current, supported model such as `gemini-3.5-flash-lite` or `gemini-flash-lite-latest`. The assistant automatically falls back to `GEMINI_VISION_FALLBACK_MODEL` if the primary model returns a 404 error.

### 3. Screen Vision Tools Not Triggering
- **Cause**: By default, `TOOL_MODE=core` loads only everyday assistant tools to minimize latency and avoid confusing tool-calling schemas.
- **Fix**: Set `TOOL_MODE=full` in `.env.local` to enable `analyze_screen`, `detect_ui_element`, `detect_error_popups`, and `summarize_screen_state`.

### 4. Ambient Windows `GOOGLE_API_KEY` Conflict
- **Cause**: If your Windows system has `GOOGLE_API_KEY` defined in System Environment Variables (e.g. from gcloud CLI or another project), `python-dotenv` without overrides could pick up the wrong key.
- **Fix**: Cynthia now calls `load_dotenv(".env.local", override=True)` so that `.env.local` always takes precedence. To avoid confusion, check Windows Environment Variables and remove any stale global `GOOGLE_API_KEY`.

### 5. Windows Screen Capture Failure (`screen grab failed`)
- **Cause**: `Pillow`'s `ImageGrab.grab()` requires an active, unlocked Windows desktop GUI session. If Windows is locked (`Win+L`), in a screensaver, or running in a headless SSH/service session, screen capture will fail.
- **Fix**: Ensure your Windows desktop is unlocked and Cynthia is running in an active graphical user session.

### 6. API Key Authentication Failed (401 / 403 / `API_KEY_INVALID`)
- **Cause**: The API key in `.env.local` has expired, was revoked, or contains typos.
- **Fix**: Generate a fresh API key at [Google AI Studio](https://aistudio.google.com/) and paste it into `GEMINI_API_KEYS` in `.env.local`.

### 7. Rate Limits and Quota Exhaustion (429)
- **Cause**: Free tier Gemini API keys have RPM (requests per minute) and RPD (requests per day) limits.
- **Fix**: Provide multiple comma-separated keys in `GEMINI_API_KEYS=key1,key2,key3`. When key 1 hits a rate limit, Cynthia parks it for its cooldown duration and seamlessly rotates to key 2.

### 8. LiveKit WebSocket Policy Violation (`1008 policy violation`)
- **Cause**: The `GEMINI_LIVE_MODEL` configured for the realtime voice session has been retired by Google.
- **Fix**: Update `GEMINI_LIVE_MODEL` in `.env.local` to Google's latest recommended Live model (currently `gemini-3.1-flash-live-preview`).

---

## Contributing

For information on contributing, please read [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
