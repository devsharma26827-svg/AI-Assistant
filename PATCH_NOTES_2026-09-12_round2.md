# Cynthia — Patch Round 2 (2026-09-12, based on new terminal log)

Good news first: round 1 fixes are working — you're now on `livekit-agents 1.8.1`,
`venv311` runs fine, and the assistant correctly reported "29 explicit tools"
(the new CORE_TOOLS split). This round fixes what showed up in your new log.

## 1. THE CRASH — Gemini Live model was outdated/retired
```
ERROR livekit.plugins.google error in receive task: 1008 None.
Requested entity was not found.
Hint: A 1008 policy violation error often indicates that the model name
doesn't match the API being used.
```
- **Root cause**: `agent.py` never set an explicit `model=` on
  `RealtimeModel(...)`, so it fell back to the plugin's built-in default:
  `gemini-2.5-flash-native-audio-preview-12-2025`. Google retires these
  dated preview Live models on a regular cycle (their changelog shows this
  happening every 1–3 months), and this one is no longer being served —
  hence "Requested entity was not found" a couple minutes into the session.
- **Fix**: `agent.py` now explicitly pins
  `model="gemini-3.1-flash-live-preview"` — Google's currently documented
  "recommended model for all Live API use cases." It's also overridable via
  `.env.local` → `GEMINI_LIVE_MODEL=...` so the next time Google renames or
  retires a model, you just change one line instead of editing code.

## 2. "Folder banaya but Desktop pe dikha hi nahi" — OneDrive redirect
- **Root cause**: `resolve_location("desktop")` built the path as
  `%USERPROFILE%\Desktop`. On most Windows 11 setups with OneDrive Backup
  turned on, the REAL Desktop your File Explorer shows is actually
  `%USERPROFILE%\OneDrive\Desktop` — Windows silently redirects it.
  `%USERPROFILE%\Desktop` can still exist as an empty leftover folder, so the
  tool truthfully created the folder there and reported success — just not
  where you were looking.
- **Fix**: added `_get_known_folder()` in `system_control_tools.py`, which
  calls the real Windows Shell API (`SHGetKnownFolderPath`) to resolve
  Desktop/Documents/Downloads/Pictures/Videos/Music the same way File
  Explorer does — redirect-aware. `resolve_location()` and the file indexer
  (`_index_base_dirs()`) both now use this, so a folder you ask for gets
  created AND found in the same, correct place.

## 3. Startup stall: "event loop blocked for 527ms ... ssl.py"
- Building the SSL context for the first Gemini connection reads/parses the
  certifi CA bundle — a one-time synchronous cost inside the Google library
  itself. `agent.py` now fires this off in a background thread the moment
  the module loads (well before any session starts), so that cost is usually
  already paid by the time you actually connect. Small win (~500ms), but
  free.

## 4. Conversation felt robotic / not "insaan jaisa"
- Added a dedicated section to `prompts.py`: keep replies to 1–2 short
  spoken-style sentences, never read out numbered lists/headings, never
  narrate tool/function names, don't repeat "Boss" every single line, don't
  over-explain success or over-apologize on failure. This sits right after
  the personality core so it takes priority.
- This won't fix latency by itself, but a shorter, more natural reply is
  also a **faster** one for the Realtime API to generate and speak — long,
  structured, report-style replies take longer to synthesize as audio.

## Still true from Round 1 (recap)
- File index now covers Desktop/Documents/Downloads/Pictures/Videos + extra
  drives, off the main thread.
- WhatsApp/content-writer blocking calls moved to `run_in_executor`.
- Tool list defaults to ~28 "core" tools (`TOOL_MODE=full` for everything).
- `requirement.txt` fully version-pinned.

## If it still feels slow after this
The remaining latency you'll see (a few hundred ms to ~1s per turn) is
largely inherent to the Gemini Live API's own round-trip + audio synthesis
time — that part isn't something this codebase can eliminate, only avoid
adding *extra* delay on top of. If a specific command is still consistently
slow after this patch, send me that exact terminal snippet and I'll dig into
that one.
