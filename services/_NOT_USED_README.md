# ⚠️ This folder is NOT wired into the running assistant

`agent.py` imports its tools from the root of this repo
(`whatsapp_tools.py`, `content_writer_tools.py`, `file_manager_tools.py`,
etc.), not from `services/`. Several files here have already drifted from
their root counterparts (confirmed by diff during the 2026-09-12 audit) —
for example `services/whatsapp.py` still has the blocking `time.sleep()`
bugs that were fixed in the root `whatsapp_tools.py` this session.

Editing files here will have **no effect** on the live assistant. Pick one
copy (root or services/) as the real source of truth and delete the other,
otherwise bugs will keep getting fixed in one place and not the other.
