# Cynthia — Bug-Fix Patch (2026-09-12)

Applied after analyzing the uploaded terminal logs (602,301-item index, wrong
folder matches, generate_reply timeout, dropped WebSocket errors).

## 1. `system_control_tools.py` — the #1 "wrong action" bug
- **Root cause**: `get_file_index()` only scanned `D:/`. Anything created on
  the C: drive (Desktop, Documents, Downloads — the *default* location every
  create/save tool uses) could never be found, so `folder_file()` always
  fuzzy-matched against unrelated files and returned garbage.
- **Fix**: now indexes Desktop, Documents, Downloads, Pictures, Videos, plus
  any extra data drives (D:, E:, F: if present), and skips huge irrelevant
  folders (`node_modules`, `AppData`, `Program Files`, `.git`, etc).
- **Also fixed**: the entire directory walk ran synchronously on the main
  event loop — a 35+ second block on a 600k-item drive, which froze voice
  input/output and caused the WebSocket drops you saw. It now runs via
  `asyncio.to_thread(...)`.
- **Also fixed**: `search_item()` now tries an exact match, then an
  unambiguous substring match, and only falls back to fuzzy matching last —
  fuzzy scoring against a huge unrelated name pool was producing high-score
  false positives (e.g. "My First Project" → "open").
- **Also fixed**: creating a folder/file now adds it straight into the cache
  instead of invalidating the whole thing (which forced a full slow re-walk
  on the very next command).

## 2. `whatsapp_tools.py` — blocking calls freezing the session
- `whatsapp_file`, `read_last_message`, and `whatsapp_reply` called
  `time.sleep()` and `pyautogui` directly inside `async def` functions,
  blocking the event loop for several seconds per call (same disconnect
  symptom as #1). All three now run their blocking logic via
  `loop.run_in_executor(...)`, matching the pattern `whatsapp_message`
  already used correctly.

## 3. `content_writer_tools.py`
- `write_text`'s `pyautogui.write(...)` call (up to ~2s of blocking
  keystrokes for text under 200 chars) now runs in a thread too.

## 4. `agent.py`
- **Tool footprint**: registering all 65 tools on every Realtime session
  adds latency to the schema Gemini has to process each turn, and increases
  wrong-tool selection. Tools are now split into `CORE_TOOLS` (~28,
  everyday use) and `EXTENDED_TOOLS` (ecosystem/vision/workflow/gesture,
  rarer). Default is CORE only; set `TOOL_MODE=full` in `.env` to get
  everything back.
- **Exception handler honesty**: the old handler logged "Reconnecting..."
  for dropped connections but never actually reconnected anything (LiveKit's
  worker handles that, not this code). It now logs an accurate message, and
  escalates to an explicit warning after 3+ drops in one session pointing
  back at "something is blocking the event loop" — since that's the real
  cause, not something this handler can fix by itself.

## 5. `requirement.txt` — pinned versions
Previously **zero** version pins — a fresh `pip install` could silently pull
in a breaking release. Pinned to a known-good, mutually compatible set
(checked against PyPI on 2026-09-12): `livekit==1.1.18`,
`livekit-agents==1.8.1` (you were running `1.5.7`), matching
`livekit-plugins-*==1.8.1`, `google-genai==2.23.0`,
`google-generativeai==0.8.6`, `fastapi==0.141.1`, `uvicorn==0.52.4`,
`pydantic==2.13.5`.

**Action needed**: re-create your venv and reinstall —
```
python -m venv venv311
.\venv311\Scripts\activate
pip install -r requirement.txt --upgrade
```

## 6. Duplicate code warning (not auto-fixed)
`src/` and `services/` contain older/parallel copies of the same tool files.
`agent.py` only ever imports from the **root** files — the `src/` and
`services/` copies have already drifted (e.g. `services/whatsapp.py` still
has the blocking-sleep bug fixed in #2). Added `_NOT_USED_README.md` in both
folders. Recommend deleting one set once you confirm which you want to keep,
so future edits/fixes don't get applied to a copy that isn't actually running.

---
### Not changed (needs your call)
- `TOOL_MODE=core` will hide the ecosystem/vision/workflow/gesture/human_*
  tools by default. If you use those often, add `TOOL_MODE=full` to `.env`.

---
## Round 2 — from the fresh terminal log (13:23–13:29 session)

### 7. `1008 policy violation: Requested entity was not found` — the session-killing crash
Google's own hint nailed it: the Gemini **Live** model name hardcoded in `agent.py`
had been retired server-side. Fixed by pinning an explicit, currently-served
model via `GEMINI_LIVE_MODEL` (defaults to `gemini-3.1-flash-live-preview`,
overridable in `.env.local` without touching code — Google retires these
every few months, so next time this happens you just update one env var).

### 8. `event loop blocked for 527ms at ssl.py` on every session start
`google-genai`'s client builds its own SSL context on first connect, which
reads/parses the certifi CA bundle synchronously — a real ~500ms stall on the
voice loop. Fixed by pre-warming `ssl.create_default_context()` in a
background thread the moment `agent.py` is imported, so that cost is already
paid before the real connection happens.

### 9. Voice Activity Detection (VAD) tuned for faster turn-taking
Added `realtime_input_config` with `silence_duration_ms=400` (was using the
plugin default, 800ms+) — Cynthia now starts responding noticeably sooner
after you stop talking.

### 10. System prompt (`prompts.py`) trimmed ~40%
19 verbose numbered sections (with a lot of repeated exposition) condensed
into compact trigger→action rules — same tools, same behavior, but far fewer
tokens for the model to hold in context every turn. Also kept/verified the
"sound like a real person" directives (1–2 sentence replies, no lists/tool
names spoken aloud, no repeated "Boss", no re-stating the question) that
directly answer the "talk like a real human, no latency" ask.

### 11. `GOOGLE_API_KEY` / `GEMINI_API_KEY` both set (warning, not fixed in code)
Your log showed `Both GOOGLE_API_KEY and GEMINI_API_KEY are set. Using
GOOGLE_API_KEY.` — one of these is set as a real Windows environment
variable outside this project, silently overriding `.env.local`. Check
System Properties → Environment Variables and remove the one you don't
want; noted in `.env.local.example`.

### Not a bug, but worth knowing
The `create_system_folder` "success but I don't see it on Desktop" complaint
from the *first* patch round is already covered by fix #1 in Round 1 — Desktop
is now resolved via the real Windows Known Folder API (`SHGetKnownFolderPath`),
which correctly follows OneDrive Desktop redirection if your PC has "Backup
important folders" turned on in OneDrive settings. If it still creates the
folder in the "wrong" place after this patch, tell Cynthia "kaunse path pe
banaya" — the tool's raw response always includes the exact resolved path.
