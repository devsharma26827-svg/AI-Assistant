# ⚠️ This folder is NOT wired into the running assistant

`agent.py` (the file `run_assistant_console.bat` / `run_assistant_text.bat`
actually launch) imports all its tools from the **root** of this repo
(`system_control_tools.py`, `whatsapp_tools.py`, etc.) — NOT from `src/`.

This `src/` copy has already drifted from the root files (confirmed by diff
during the 2026-09-12 audit). Editing files here will have **no effect** on
the live assistant.

Recommended: either delete this folder, or decide it's the "real" copy and
update `run_assistant_console.bat` / `run_assistant_text.bat` to point at
`src/agent.py` instead — but don't edit both going forward, pick one.
