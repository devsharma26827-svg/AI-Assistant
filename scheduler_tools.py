"""
scheduler_tools.py - Persistent Task & Reminder Scheduler for Cynthia AI Assistant.

Provides:
1. Atomic, persistent JSON store at data/scheduled_tasks.json with 7-day cleanup and corrupt file recovery.
2. Strict time validation (delay_minutes, at_time with 12h/24h, meridiem, roll-to-next-day, past validation).
3. Whitelisted safe action scheduling and arg validation at schedule time.
4. Independent background scheduler loop with GRACE=90s, idle detection, and serialized tool execution.
5. Startup missed-task detection and resolution without duplicate notifications.
"""

import os
import json
import uuid
import time
import shutil
import inspect
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict, field
from typing import Any, Callable, Literal
from livekit.agents import llm
from livekit.agents.llm import function_tool
from tool_serializer import _global_tool_lock, serialized_tool

logger = logging.getLogger("scheduler_tools")
logger.setLevel(logging.INFO)

# Path configuration
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TASKS_FILE = os.path.join(DATA_DIR, "scheduled_tasks.json")

# Grace period: Tasks overdue by more than 90 seconds are marked missed and NOT executed
GRACE_SECONDS = 90.0

# Maximum advance scheduling window: 7 days
MAX_ADVANCE_DAYS = 7

# Whitelist of safe tools allowed to be scheduled
SAFE_SCHEDULE_TOOLS = {
    "whatsapp_message",
    "youtube_play_video",
    "set_system_volume",
    "adjust_system_volume",
    "mute_system_volume",
    "open_app",
    "get_weather",
    "spotify_play",
}

# Injectable clock for deterministic testing
_clock_override: Callable[[], datetime] | None = None


def get_now() -> datetime:
    """Returns the current timezone-aware local datetime, respecting clock override if set."""
    if _clock_override is not None:
        return _clock_override()
    return datetime.now().astimezone()


def set_clock_override(fn: Callable[[], datetime] | None) -> None:
    """Sets or clears a custom clock provider function for unit testing."""
    global _clock_override
    _clock_override = fn


@dataclass
class ScheduledTask:
    id: str
    type: Literal["reminder", "action"]
    description: str
    due_at: str          # ISO-8601 string in local timezone
    created_at: str      # ISO-8601 string
    status: Literal["pending", "running", "done", "failed", "missed", "interrupted", "cancelled"] = "pending"
    tool_name: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    missed_notified: bool = False
    result: str | None = None
    mode: str = "remind"            # "exact" | "remind"
    executed_at: str | None = None  # ISO-8601 string when completed/failed

    def get_due_datetime(self) -> datetime:
        return datetime.fromisoformat(self.due_at)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScheduledTask":
        return cls(
            id=data["id"],
            type=data["type"],
            description=data["description"],
            due_at=data["due_at"],
            created_at=data["created_at"],
            status=data.get("status", "pending"),
            tool_name=data.get("tool_name"),
            args=data.get("args") or {},
            missed_notified=data.get("missed_notified", False),
            result=data.get("result"),
            mode=data.get("mode", "remind"),
            executed_at=data.get("executed_at"),
        )


class TaskStore:
    """
    Manages atomic reading and writing of scheduled tasks to disk.
    Protected by an asyncio.Lock for thread/coroutine safety.
    """
    def __init__(self, filepath: str = TASKS_FILE):
        self.filepath = filepath
        self.lock = asyncio.Lock()
        self.tasks: dict[str, ScheduledTask] = {}
        self._ensure_storage_dir()
        self._load_sync()

    def _ensure_storage_dir(self) -> None:
        directory = os.path.dirname(self.filepath)
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)

    def _load_sync(self) -> None:
        """Synchronously loads tasks from disk on initialization or after corruption backup."""
        self.tasks.clear()
        if not os.path.exists(self.filepath):
            return

        raw_data = None
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("Empty scheduled tasks file")
                data = json.loads(content)
                if not isinstance(data, list):
                    raise ValueError("Scheduled tasks file must contain a JSON list")
                raw_data = data
        except Exception as e:
            logger.warning(f"Corrupt or unreadable tasks file ({e}). Backing up to .bak and starting empty.")
            bak_path = self.filepath + ".bak"
            try:
                shutil.copy2(self.filepath, bak_path)
            except Exception:
                pass
            self.tasks.clear()
            self._save_sync()
            return

        has_interrupted = False
        for item in raw_data:
            task = ScheduledTask.from_dict(item)
            if task.status == "running":
                task.status = "interrupted"
                task.result = "interrupted: assistant shut down while task was running"
                task.missed_notified = False
                has_interrupted = True
                logger.warning(f"[SCHED] Task [{task.id}] '{task.description}' was left in running state; marked as interrupted.")
            self.tasks[task.id] = task

        if has_interrupted:
            try:
                self._save_sync()
            except Exception as e:
                logger.warning(f"[SCHED] Could not save interrupted task state: {e}")

    def _save_sync(self) -> None:
        """Atomic write using temp file and os.replace with Windows/OneDrive retry."""
        self._ensure_storage_dir()
        tmp_path = self.filepath + ".tmp"
        tasks_list = [t.to_dict() for t in self.tasks.values()]
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(tasks_list, f, indent=2, ensure_ascii=False)

        # Windows / OneDrive locking retry
        for attempt in range(5):
            try:
                os.replace(tmp_path, self.filepath)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
            except Exception as e:
                logger.warning(f"[SCHED] os.replace failed ({e}), falling back to direct write")
                break

        # Fallback if os.replace repeatedly failed due to file locks
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(tasks_list, f, indent=2, ensure_ascii=False)
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as e:
            logger.error(f"[SCHED] Error saving scheduled tasks: {e}")

    async def save(self) -> None:
        """Async save wrapper running atomic file write in a background thread."""
        await asyncio.to_thread(self._save_sync)

    async def add_task(self, task: ScheduledTask) -> None:
        async with self.lock:
            self.tasks[task.id] = task
            self._cleanup_old_tasks()
            await self.save()

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        async with self.lock:
            return self.tasks.get(task_id)

    async def update_task(self, task: ScheduledTask) -> None:
        async with self.lock:
            self.tasks[task.id] = task
            await self.save()

    async def list_all_tasks(self) -> list[ScheduledTask]:
        async with self.lock:
            return list(self.tasks.values())

    def _cleanup_old_tasks(self) -> None:
        """Deletes 'done' or 'cancelled' tasks older than 7 days to keep file size bounded."""
        now = get_now()
        cutoff = now - timedelta(days=7)
        to_delete = []
        for tid, t in self.tasks.items():
            if t.status in ("done", "cancelled"):
                try:
                    due = t.get_due_datetime()
                    if due < cutoff:
                        to_delete.append(tid)
                except Exception:
                    pass
        for tid in to_delete:
            del self.tasks[tid]


def parse_and_validate_time(
    delay_minutes: float | None = None,
    at_time: str | None = None,
    meridiem: str | None = None,
    date_str: str | None = None,
) -> tuple[datetime | None, str | None]:
    """
    Computes absolute timezone-aware due_at datetime from user parameters.
    Returns (due_datetime, error_message).
    """
    now = get_now()

    if delay_minutes is None and not at_time:
        return None, "failed: please provide either delay_minutes or at_time (e.g. 5 min or 04:55)"

    # --- Mode 1: delay_minutes ---
    if delay_minutes is not None:
        try:
            delay = float(delay_minutes)
        except (ValueError, TypeError):
            return None, "failed: invalid delay_minutes value"

        if delay <= 0:
            return None, "failed: delay_minutes must be positive"
        if delay > MAX_ADVANCE_DAYS * 24 * 60:
            return None, f"failed: cannot schedule more than {MAX_ADVANCE_DAYS} days in advance"

        due = now + timedelta(minutes=delay)
        return due, None

    # --- Mode 2: at_time ---
    at_time_clean = at_time.strip().lower()
    # Normalize meridiem if embedded in at_time string (e.g. "4:55pm" or "04:55 pm")
    if at_time_clean.endswith("am"):
        meridiem = "am"
        at_time_clean = at_time_clean[:-2].strip()
    elif at_time_clean.endswith("pm"):
        meridiem = "pm"
        at_time_clean = at_time_clean[:-2].strip()

    parts = at_time_clean.split(":")
    if len(parts) != 2:
        return None, "failed: at_time must be in 'HH:MM' format"

    try:
        raw_h = int(parts[0])
        raw_m = int(parts[1])
    except ValueError:
        return None, "failed: hours and minutes must be numbers"

    if raw_m < 0 or raw_m > 59:
        return None, "failed: minutes must be between 0 and 59"

    # Base target date resolution
    explicit_date = False
    target_date = now.date()

    if date_str:
        d_clean = date_str.strip().lower()
        if d_clean == "tomorrow":
            target_date = now.date() + timedelta(days=1)
            explicit_date = True
        elif d_clean == "today":
            target_date = now.date()
            explicit_date = True
        else:
            try:
                target_date = datetime.strptime(d_clean, "%Y-%m-%d").date()
                explicit_date = True
            except ValueError:
                return None, "failed: date must be 'today', 'tomorrow', or 'YYYY-MM-DD'"

    # Meridiem and Hour Resolution
    if meridiem is not None:
        m_clean = meridiem.strip().lower()
        if m_clean not in ("am", "pm"):
            return None, "failed: meridiem must be 'am' or 'pm'"
        if raw_h < 1 or raw_h > 12:
            return None, "failed: clock hour with am/pm must be between 1 and 12"

        h_24 = (raw_h % 12) + (12 if m_clean == "pm" else 0)
        candidate = datetime(
            year=target_date.year,
            month=target_date.month,
            day=target_date.day,
            hour=h_24,
            minute=raw_m,
            tzinfo=now.tzinfo
        )

        # Past time validation
        if candidate <= now + timedelta(seconds=5):
            if explicit_date and date_str and date_str.strip().lower() != "tomorrow":
                # Explicit date was chosen (e.g. "today") and time is already past
                return None, "failed: that time has already passed today"
            elif not explicit_date:
                # Roll to tomorrow if already past and no explicit date was forced
                candidate += timedelta(days=1)
            else:
                return None, "failed: that time has already passed"

        if candidate > now + timedelta(days=MAX_ADVANCE_DAYS):
            return None, f"failed: cannot schedule more than {MAX_ADVANCE_DAYS} days in advance"

        return candidate, None

    else:
        # No meridiem provided:
        # If hour > 12, user passed 24h format (e.g. "16:55")
        if raw_h > 12:
            if raw_h > 23:
                return None, "failed: hour must be between 0 and 23"
            candidate = datetime(
                year=target_date.year,
                month=target_date.month,
                day=target_date.day,
                hour=raw_h,
                minute=raw_m,
                tzinfo=now.tzinfo
            )
            if candidate <= now + timedelta(seconds=5):
                if explicit_date:
                    return None, "failed: that time has already passed"
                candidate += timedelta(days=1)
            return candidate, None

        # 12h clock time without AM/PM (e.g. user said "4:55"):
        # Select the NEXT upcoming occurrence within the next 12 hours
        # Candidates to evaluate in chronological order
        candidates = []
        for day_offset in (0, 1):
            base_d = target_date + timedelta(days=day_offset) if not explicit_date else (target_date if day_offset == 0 else None)
            if base_d is None:
                continue
            for h_opt in ((raw_h % 12), (raw_h % 12) + 12):
                dt = datetime(
                    year=base_d.year,
                    month=base_d.month,
                    day=base_d.day,
                    hour=h_opt,
                    minute=raw_m,
                    tzinfo=now.tzinfo
                )
                if dt > now + timedelta(seconds=5):
                    candidates.append(dt)

        if not candidates:
            return None, "failed: that time has already passed"

        candidates.sort()
        best_candidate = candidates[0]

        if best_candidate > now + timedelta(days=MAX_ADVANCE_DAYS):
            return None, f"failed: cannot schedule more than {MAX_ADVANCE_DAYS} days in advance"

        return best_candidate, None


def format_due_time_relative(due_dt: datetime, now_dt: datetime) -> tuple[str, str]:
    """
    Formats due datetime into human-friendly strings:
    (formatted_clock, relative_gap)
    e.g. ("05:35 PM", "in 5 min") or ("tomorrow at 09:00 AM", "in 11h 25m")
    """
    is_today = (due_dt.date() == now_dt.date())
    is_tomorrow = (due_dt.date() == now_dt.date() + timedelta(days=1))

    clock_str = due_dt.strftime("%I:%M %p")
    if is_today:
        formatted_clock = clock_str
    elif is_tomorrow:
        formatted_clock = f"tomorrow at {clock_str}"
    else:
        formatted_clock = f"{due_dt.strftime('%b %d')} at {clock_str}"

    diff_sec = max(0, int((due_dt - now_dt).total_seconds()))
    if diff_sec < 60:
        gap_str = "in a few seconds"
    elif diff_sec < 3600:
        gap_str = f"in {diff_sec // 60} min"
    else:
        hours = diff_sec // 3600
        mins = (diff_sec % 3600) // 60
        gap_str = f"in {hours}h {mins}m" if mins else f"in {hours} hours"

    return formatted_clock, gap_str


# Active tool execution registry for scheduled actions (name -> async callable)
ACTION_REGISTRY: dict[str, Callable[..., Any]] = {}


def register_action_tool(name: str, fn: Callable[..., Any]) -> None:
    """Registers an async tool callable for scheduled actions."""
    ACTION_REGISTRY[name] = fn


def _init_default_action_registry() -> None:
    if not ACTION_REGISTRY:
        try:
            from whatsapp_tools import whatsapp_message
            ACTION_REGISTRY["whatsapp_message"] = whatsapp_message
        except Exception as e:
            logger.debug(f"Could not register whatsapp_message: {e}")
        try:
            from youtube_tools import youtube_play_video, youtube_pause_playback, youtube_resume_playback
            ACTION_REGISTRY["youtube_play_video"] = youtube_play_video
            ACTION_REGISTRY["youtube_pause_playback"] = youtube_pause_playback
            ACTION_REGISTRY["youtube_resume_playback"] = youtube_resume_playback
        except Exception as e:
            logger.debug(f"Could not register youtube tools: {e}")
        try:
            from environment_tools import set_system_volume, adjust_system_volume, mute_system_volume
            ACTION_REGISTRY["set_system_volume"] = set_system_volume
            ACTION_REGISTRY["adjust_system_volume"] = adjust_system_volume
            ACTION_REGISTRY["mute_system_volume"] = mute_system_volume
        except Exception as e:
            logger.debug(f"Could not register environment tools: {e}")
        try:
            from system_control_tools import open_app, set_volume
            ACTION_REGISTRY["open_app"] = open_app
            ACTION_REGISTRY["set_volume"] = set_volume
        except Exception as e:
            logger.debug(f"Could not register system control tools: {e}")
        try:
            from jarvis_get_whether import get_weather
            ACTION_REGISTRY["get_weather"] = get_weather
        except Exception as e:
            logger.debug(f"Could not register get_weather: {e}")
        try:
            from spotify_tools import spotify_play
            ACTION_REGISTRY["spotify_play"] = spotify_play
        except Exception as e:
            logger.debug(f"Could not register spotify_play: {e}")


def get_action_tool_map() -> dict[str, Any]:
    """Compatibility getter for ACTION_REGISTRY."""
    _init_default_action_registry()
    return ACTION_REGISTRY


def _format_action_announcement(tool_name: str, args: dict[str, Any], description: str) -> str:
    """Returns a short, natural, single-sentence Hinglish announcement line."""
    if tool_name == "whatsapp_message":
        contact = args.get("contact", "contact")
        return f"Boss, {contact} ko WhatsApp pe message bhej rahi hoon."
    elif tool_name == "youtube_play_video":
        query = args.get("query", "video")
        return f"Boss, ab {query} play kar rahi hoon."
    elif tool_name in ("set_system_volume", "set_volume"):
        level = args.get("level") if "level" in args else args.get("volume", "")
        return f"Boss, volume {level} percent kar rahi hoon."
    elif tool_name == "adjust_system_volume":
        return "Boss, volume adjust kar rahi hoon."
    elif tool_name == "mute_system_volume":
        return "Boss, system volume mute kar rahi hoon."
    elif tool_name == "open_app":
        app = args.get("app_name", "app")
        return f"Boss, {app} open kar rahi hoon."
    return f"Boss, ab {description} execute kar rahi hoon."


def validate_action_arguments(tool_name: str, args: dict[str, Any]) -> str | None:
    """Validates arguments at schedule time so invalid calls fail immediately, not at firing."""
    if tool_name == "whatsapp_message":
        if not args.get("contact") or not str(args.get("contact")).strip():
            return "whatsapp_message requires non-empty 'contact'"
        if not args.get("message") or not str(args.get("message")).strip():
            return "whatsapp_message requires non-empty 'message'"
    elif tool_name == "youtube_play_video":
        if not args.get("query") or not str(args.get("query")).strip():
            return "youtube_play_video requires non-empty 'query'"
    elif tool_name in ("set_system_volume", "set_volume"):
        val = args.get("level") if "level" in args else args.get("volume")
        if val is None:
            return f"{tool_name} requires 'level' or 'volume' (0-100)"
        try:
            v = int(val)
            if v < 0 or v > 100:
                return "volume level must be between 0 and 100"
            args["level"] = v
        except (ValueError, TypeError):
            return "volume level must be an integer"
    elif tool_name == "open_app":
        if not args.get("app_name") or not str(args.get("app_name")).strip():
            return "open_app requires non-empty 'app_name'"
    return None


class TaskScheduler:
    """
    Central background scheduler instance.
    Runs one background worker loop that monitors due tasks, handles GRACE logic,
    and dispatches reminders/actions through Cynthia's active session and tool lock.
    """
    def __init__(self, store: TaskStore | None = None):
        self.store = store or TaskStore()
        self._active_session: Any = None
        self._loop_task: asyncio.Task[None] | None = None
        self._wake_event = asyncio.Event()
        self._running = False
        self._background_tasks: set[asyncio.Task[Any]] = set()
        self._recent_outcomes: list[str] = []
        self._last_heartbeat_time = 0.0

    def set_active_session(self, session: Any) -> None:
        """Updates the reference to the currently active AgentSession (survives supervisor reconnects)."""
        self._active_session = session
        logger.info("[SCHED] Attached active AgentSession to scheduler")
        # Re-inject recent task outcomes into the newly connected session history
        if session and self._recent_outcomes:
            for outcome in self._recent_outcomes[-5:]:
                try:
                    if hasattr(session, "history"):
                        session.history.add_message(role="assistant", content=outcome)
                except Exception as e:
                    logger.debug(f"[SCHED] Error re-injecting outcome on session reconnect: {e}")

    def start(self) -> None:
        """Starts the background scheduler loop if not already running."""
        if self._running and self._loop_task and not self._loop_task.done():
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._scheduler_loop(), name="cynthia-task-scheduler")
        logger.info("[SCHED] TaskScheduler loop started")

    def stop(self) -> None:
        """Stops the scheduler loop and cancels background tasks cleanly."""
        self._running = False
        self._wake_event.set()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        for t in list(self._background_tasks):
            if not t.done():
                t.cancel()
        self._background_tasks.clear()
        logger.info("[SCHED] TaskScheduler stopped")

    def wake(self) -> None:
        """Signals the loop that task list has changed."""
        self._wake_event.set()

    def _on_task_finished(self, task: asyncio.Task[Any], task_id: str) -> None:
        """Done callback ensuring background fire task is cleaned up and errors are logged."""
        self._background_tasks.discard(task)
        if not task.cancelled():
            exc = task.exception()
            if exc:
                logger.error(f"[SCHED] Task {task_id} raised unexpected exception: {exc}", exc_info=exc)

    async def _inject_session_context(self, outcome_line: str) -> None:
        """Injects task outcome into live session history and updates RealtimeSession chat context."""
        self._recent_outcomes.append(outcome_line)
        if len(self._recent_outcomes) > 20:
            self._recent_outcomes = self._recent_outcomes[-20:]

        if not self._active_session:
            return

        try:
            if hasattr(self._active_session, "history"):
                self._active_session.history.add_message(role="assistant", content=outcome_line)
            if hasattr(self._active_session, "_activity") and self._active_session._activity:
                act = self._active_session._activity
                if hasattr(act, "update_chat_ctx") and hasattr(self._active_session, "history"):
                    await act.update_chat_ctx(self._active_session.history)
        except Exception as e:
            logger.warning(f"[SCHED] Could not inject task outcome into session context: {e}")

    async def _wait_for_session_idle(self, max_wait: float = 6.0) -> None:
        """Waits until user and Cynthia are not speaking, up to a safety timeout."""
        start_t = time.monotonic()
        while time.monotonic() - start_t < max_wait:
            if not self._active_session:
                break
            agent_state = getattr(self._active_session, "agent_state", "idle")
            user_state = getattr(self._active_session, "user_state", "listening")
            if agent_state != "speaking" and user_state != "speaking":
                break
            await asyncio.sleep(0.3)

    async def _fire_reminder(self, task: ScheduledTask) -> None:
        """Fires a scheduled reminder via session.generate_reply."""
        logger.info(f"[SCHED] firing id={task.id} (reminder)")
        await self._wait_for_session_idle(max_wait=6.0)

        # Exact vs remind mode
        if task.mode == "exact":
            prompt = (
                f"You are delivering a scheduled voice reminder.\n"
                f"Say strictly and exactly: '{task.description}' and nothing else.\n"
                f"No extra words, no prefixes, no commentary, no quotes."
            )
        else:
            prompt = (
                f"You are delivering a scheduled reminder to the user right now.\n"
                f"Reminder topic: {task.description}\n"
                f"Deliver this reminder in one short, warm Hinglish sentence using ONLY Roman English letters.\n"
                f"Example: 'Boss, aapka reminder: {task.description}.'\n"
                f"Do NOT use Urdu, Arabic, or non-Latin scripts."
            )

        delivered = False
        if self._active_session:
            try:
                handle = self._active_session.generate_reply(instructions=prompt)
                await asyncio.wait_for(handle, timeout=10.0)
                delivered = True
            except Exception as e:
                logger.warning(f"[SCHED] generate_reply reminder failed: {e}")

        task.status = "done"
        task.result = "delivered" if delivered else "delivered (speech timeout)"
        task.executed_at = get_now().isoformat()
        await self.store.update_task(task)

        # Inject outcome into context
        clock_str = get_now().strftime("%I:%M %p")
        outcome_line = f"[scheduler] Task {task.id} (reminder: '{task.description}') result: done at {clock_str}"
        await self._inject_session_context(outcome_line)

        logger.info(f"[SCHED] done id={task.id}")

    async def _fire_action(self, task: ScheduledTask) -> None:
        """Fires a scheduled tool action through the serialized tool lock."""
        logger.info(f"[SCHED] firing id={task.id} (action: {task.tool_name})")
        await self._wait_for_session_idle(max_wait=5.0)

        # 1. Non-blocking short natural spoken announcement
        if self._active_session:
            try:
                announcement_line = _format_action_announcement(task.tool_name or "", task.args, task.description)
                announcement_prompt = f"Speak this line directly to the user in one short Hinglish sentence: '{announcement_line}'"
                handle = self._active_session.generate_reply(instructions=announcement_prompt)
                # Bounded short timeout (4s) so tool execution is never delayed or stuck
                await asyncio.wait_for(handle, timeout=4.0)
            except Exception as e:
                logger.debug(f"[SCHED] Announcement speech omitted/timed out ({e}), proceeding to action.")

        # 2. Resolve tool callable from registry
        tool_map = get_action_tool_map()
        raw_tool = tool_map.get(task.tool_name)

        if not raw_tool:
            task.status = "failed"
            task.result = f"failed: tool {task.tool_name} not available"
            task.executed_at = get_now().isoformat()
            await self.store.update_task(task)
            logger.error(f"[SCHED] failed id={task.id}: tool {task.tool_name} not found")
            return

        # Unwrap if FunctionTool object
        tool_fn = getattr(raw_tool, "__wrapped__", raw_tool)
        if not getattr(tool_fn, "__serialized__", False):
            # Wrap with serialized_tool if missing
            tool_fn = serialized_tool(task.tool_name)(tool_fn)

        # 3. Execute tool through @serialized_tool (which manages _global_tool_lock safely)
        # Note: Do NOT wrap in outer `async with _global_tool_lock:`, as @serialized_tool
        # acquires it reentrantly, coordinates StepBarrier, and enforces execution timeouts.
        tool_res = ""
        try:
            call_args = dict(task.args)
            call_args.setdefault("step", 1)
            call_args.setdefault("total_steps", 1)
            res = tool_fn(**call_args)
            if inspect.isawaitable(res):
                tool_res = await res
            else:
                tool_res = res
        except Exception as e:
            tool_res = f"failed: action execution error: {e}"

        logger.info(f"[SCHED] action id={task.id} executed with result: {tool_res}")
        task.result = str(tool_res)
        task.executed_at = get_now().isoformat()
        success = str(tool_res).strip().startswith("done:")
        task.status = "done" if success else "failed"
        await self.store.update_task(task)

        # 4. Inject outcome into session context
        clock_str = get_now().strftime("%I:%M %p")
        outcome_line = f"[scheduler] Task {task.id} ({task.tool_name}: '{task.description}') result: {task.status} at {clock_str}. Details: {task.result}"
        await self._inject_session_context(outcome_line)

        # 5. Honest spoken confirmation
        if self._active_session:
            try:
                if success:
                    confirm_prompt = (
                        f"The scheduled action '{task.description}' succeeded with result '{tool_res}'. "
                        f"Say in one short, natural Hinglish sentence (under 6 words): 'Bhej diya Boss.' or '{task.description} ho gaya.' "
                        f"Do not use Urdu or foreign words."
                    )
                else:
                    confirm_prompt = (
                        f"The scheduled action '{task.description}' failed with error '{tool_res}'. "
                        f"Inform the user honestly in one short Hinglish sentence: 'Boss, ye nahi ho paya: {tool_res}'"
                    )
                handle = self._active_session.generate_reply(instructions=confirm_prompt)
                await asyncio.wait_for(handle, timeout=6.0)
            except Exception as e:
                logger.debug(f"[SCHED] Confirmation speech omitted ({e})")

        if success:
            logger.info(f"[SCHED] done id={task.id} result={task.result}")
        else:
            logger.warning(f"[SCHED] failed id={task.id} reason={task.result}")

    async def _fire_task_safe(self, task: ScheduledTask) -> None:
        """Safely fires a task in background with try/except/finally guarantees."""
        try:
            if task.type == "reminder":
                await self._fire_reminder(task)
            elif task.type == "action":
                await self._fire_action(task)
        except Exception as e:
            logger.error(f"[SCHED] failed id={task.id} unexpected error: {e}", exc_info=True)
            task.status = "failed"
            task.result = f"failed: unexpected error: {e}"
            task.executed_at = get_now().isoformat()
            await self.store.update_task(task)

    async def _scheduler_loop(self) -> None:
        """Main background loop sleeping until earliest due task, checking GRACE."""
        self._last_heartbeat_time = time.monotonic()
        while self._running:
            self._wake_event.clear()
            now = get_now()

            # Heartbeat log every ~60s
            if time.monotonic() - self._last_heartbeat_time >= 60.0:
                tasks_snapshot = await self.store.list_all_tasks()
                pending_count = sum(1 for t in tasks_snapshot if t.status == "pending")
                logger.info(f"[SCHED] alive, {pending_count} pending")
                self._last_heartbeat_time = time.monotonic()

            tasks = await self.store.list_all_tasks()
            pending = [t for t in tasks if t.status == "pending"]

            # Check for due tasks or find next wake time
            earliest_due: datetime | None = None
            to_fire: list[ScheduledTask] = []
            to_miss: list[ScheduledTask] = []

            for t in pending:
                due_dt = t.get_due_datetime()
                if now >= due_dt:
                    late_by = (now - due_dt).total_seconds()
                    if late_by <= GRACE_SECONDS:
                        to_fire.append(t)
                    else:
                        to_miss.append(t)
                else:
                    if earliest_due is None or due_dt < earliest_due:
                        earliest_due = due_dt

            # Process missed tasks
            for t in to_miss:
                late_by = (now - t.get_due_datetime()).total_seconds()
                t.status = "missed"
                t.result = f"missed: overdue by {int(late_by)}s"
                t.executed_at = get_now().isoformat()
                await self.store.update_task(t)
                logger.warning(f"[SCHED] missed id={t.id} late_by={late_by:.1f}s")

            # Fire due tasks in due_at order via non-blocking asyncio.create_task
            to_fire.sort(key=lambda x: x.get_due_datetime())
            for t in to_fire:
                t.status = "running"
                await self.store.update_task(t)
                fire_coro = self._fire_task_safe(t)
                ft = asyncio.create_task(fire_coro, name=f"sched-fire-{t.id}")
                self._background_tasks.add(ft)
                ft.add_done_callback(lambda fut, tid=t.id: self._on_task_finished(fut, tid))

            # Determine sleep duration until next due task
            if earliest_due:
                now_after = get_now()
                sleep_seconds = max(0.5, min(3600.0, (earliest_due - now_after).total_seconds()))
            else:
                sleep_seconds = 60.0

            try:
                await asyncio.wait_for(self._wake_event.wait(), timeout=sleep_seconds)
            except asyncio.TimeoutError:
                pass

    async def check_startup_missed_tasks(self, session: Any) -> None:
        """
        Runs on session startup:
        1. Identifies tasks that were missed while Cynthia / laptop was offline.
        2. Identifies tasks that were interrupted (were in running state when Cynthia shut down).
        3. Informs the user ONCE asking before re-running.
        """
        now = get_now()
        tasks = await self.store.list_all_tasks()

        unnotified_missed = []
        unnotified_interrupted = []

        for t in tasks:
            if t.status == "pending":
                due_dt = t.get_due_datetime()
                if now - due_dt > timedelta(seconds=GRACE_SECONDS):
                    t.status = "missed"
                    t.result = f"missed: overdue on startup by {(now - due_dt).total_seconds():.0f}s"
                    await self.store.update_task(t)

            if t.status == "missed" and not t.missed_notified:
                unnotified_missed.append(t)
                t.missed_notified = True
                await self.store.update_task(t)
            elif t.status == "interrupted" and not t.missed_notified:
                unnotified_interrupted.append(t)
                t.missed_notified = True
                await self.store.update_task(t)

        if (not unnotified_missed and not unnotified_interrupted) or not session:
            return

        notices = []
        if unnotified_interrupted:
            for t in unnotified_interrupted:
                notices.append(
                    f"Boss, jab assistant pichli baar band hua tha tab '{t.description}' execute ho raha tha aur interrupt ho gaya. "
                    f"Ye task shayad aadha execute ho chuka ho, to kya aap chahte hain ki main ise dobara execute karoon ya dismiss kar doon?"
                )

        if unnotified_missed:
            if len(unnotified_missed) == 1:
                t = unnotified_missed[0]
                clock_str = t.get_due_datetime().strftime("%I:%M %p")
                notices.append(
                    f"Boss, aapne {clock_str} pe '{t.description}' bola tha, par us waqt main band thi. Abhi run kar doon?"
                )
            else:
                descriptions = ", ".join(f"'{t.description}'" for t in unnotified_missed[:2])
                notices.append(
                    f"Boss, jab main offline thi tab aapke {len(unnotified_missed)} scheduled tasks ({descriptions}) miss ho gaye the. Kya unhe abhi run karna hai?"
                )

        notice_text = " ".join(notices)
        try:
            prompt = f"Inform the user once naturally in Hinglish: {notice_text}"
            handle = session.generate_reply(instructions=prompt)
            await asyncio.wait_for(handle, timeout=10.0)
            logger.info(f"[SCHED] Notified user about {len(unnotified_missed)} missed and {len(unnotified_interrupted)} interrupted tasks on startup")
        except Exception as e:
            logger.warning(f"[SCHED] Could not deliver startup notification: {e}")


# Singleton instance
scheduler = TaskScheduler()


# ==============================================================================
# TOOLS EXPOSED TO THE LLM
# ==============================================================================

@function_tool
def get_current_time() -> str:
    """
    Returns the current local date, weekday, and time in both 12-hour and 24-hour formats.
    Always call this tool when the user asks what time it is, or what today's date is.
    Do not guess the time.
    """
    now = get_now()
    weekday = now.strftime("%A")
    date_str = now.strftime("%d %B %Y")
    time_12 = now.strftime("%I:%M %p")
    time_24 = now.strftime("%H:%M")
    return f"Current time: {weekday}, {date_str}, {time_12} ({time_24} hrs)"


@function_tool
async def schedule_reminder(
    text: str,
    delay_minutes: float | None = None,
    at_time: str | None = None,
    meridiem: str | None = None,
    date: str | None = None,
    mode: Literal["exact", "remind"] = "remind",
) -> str:
    """
    Schedules Cynthia to speak a voice reminder to the user at a future time.
    Provide EITHER delay_minutes (e.g. 5, 2.5, 120) OR at_time ('HH:MM' clock format).
    Args:
        text: What to remind the user about (e.g. 'hello bolna' or 'drink water').
        delay_minutes: Relative minutes from now (e.g. 5 for '5 min baad', 120 for '2 ghante baad').
        at_time: Specific clock time in 'HH:MM' (e.g. '04:55' or '09:30').
        meridiem: Optional 'am' or 'pm' if user specified. If None, schedules next upcoming occurrence.
        date: Optional 'today', 'tomorrow', or 'YYYY-MM-DD'. Defaults to today (rolls to tomorrow if past).
        mode: 'exact' to speak strictly the text with no commentary (e.g. for 'mujhe hello bolna');
              'remind' for natural reminder phrasing (e.g. for 'dawai lene ka yaad dilana').
    """
    if not text or not text.strip():
        return "failed: reminder text cannot be empty"

    due_dt, err = parse_and_validate_time(delay_minutes, at_time, meridiem, date)
    if err:
        return err

    now = get_now()
    task_id = uuid.uuid4().hex[:4]
    clock_disp, gap_disp = format_due_time_relative(due_dt, now)

    mode_clean = "exact" if str(mode).strip().lower() == "exact" else "remind"

    task = ScheduledTask(
        id=task_id,
        type="reminder",
        description=text.strip(),
        due_at=due_dt.isoformat(),
        created_at=now.isoformat(),
        status="pending",
        mode=mode_clean,
    )

    await scheduler.store.add_task(task)
    scheduler.wake()
    logger.info(f"[SCHED] scheduled id={task_id} type=reminder mode={mode_clean} due={due_dt.isoformat()} desc='{text}'")

    return f"done: reminder '{text.strip()}' set for {clock_disp} ({gap_disp}) [id: {task_id}]"


@function_tool
async def schedule_action(
    tool_name: str,
    args_json: str,
    description: str,
    delay_minutes: float | None = None,
    at_time: str | None = None,
    meridiem: str | None = None,
    date: str | None = None,
) -> str:
    """
    Schedules an existing safe tool action to execute automatically at a future time.
    Only whitelisted safe tools can be scheduled: whatsapp_message, youtube_play_video,
    set_system_volume, adjust_system_volume, mute_system_volume, open_app, spotify_play.
    Args:
        tool_name: Name of the tool to schedule (e.g. 'whatsapp_message').
        args_json: JSON string of arguments for the tool (e.g. '{\"contact\": \"Kushagar\", \"message\": \"hi\"}').
        description: Readable Hinglish description (e.g. 'WhatsApp msg to Kushagar').
        delay_minutes: Relative minutes from now (e.g. 5 for '5 min baad').
        at_time: Specific clock time in 'HH:MM' (e.g. '04:55').
        meridiem: Optional 'am' or 'pm'.
        date: Optional 'today', 'tomorrow', or 'YYYY-MM-DD'.
    """
    tool_name_clean = tool_name.strip()
    if tool_name_clean not in SAFE_SCHEDULE_TOOLS:
        return f"failed: not allowed to schedule this tool '{tool_name_clean}'. Allowed: {', '.join(sorted(SAFE_SCHEDULE_TOOLS))}"

    # Parse and validate args
    try:
        if isinstance(args_json, dict):
            args_dict = args_json
        else:
            args_dict = json.loads(args_json)
    except Exception as e:
        return f"failed: args_json must be valid JSON ({e})"

    arg_err = validate_action_arguments(tool_name_clean, args_dict)
    if arg_err:
        return f"failed: invalid arguments for {tool_name_clean}: {arg_err}"

    due_dt, err = parse_and_validate_time(delay_minutes, at_time, meridiem, date)
    if err:
        return err

    now = get_now()
    task_id = uuid.uuid4().hex[:4]
    clock_disp, gap_disp = format_due_time_relative(due_dt, now)

    desc = description.strip() if description else f"{tool_name_clean} action"

    task = ScheduledTask(
        id=task_id,
        type="action",
        description=desc,
        due_at=due_dt.isoformat(),
        created_at=now.isoformat(),
        status="pending",
        tool_name=tool_name_clean,
        args=args_dict,
    )

    await scheduler.store.add_task(task)
    scheduler.wake()
    logger.info(f"[SCHED] scheduled id={task_id} type=action tool={tool_name_clean} due={due_dt.isoformat()}")

    return f"done: action '{desc}' set for {clock_disp} ({gap_disp}) [id: {task_id}]"


@function_tool
async def list_scheduled_tasks() -> str:
    """
    Lists all scheduled tasks: pending tasks and recent tasks from the last 24 hours
    with their status (pending, running, done, failed, missed, interrupted, cancelled),
    due time, execution time, and result.
    Call this tool whenever the user asks about scheduled tasks, pending reminders,
    or whether a task was completed/sent.
    """
    now = get_now()
    cutoff_24h = now - timedelta(hours=24)
    tasks = await scheduler.store.list_all_tasks()

    # Filter: all pending/running/missed/interrupted, plus completed/failed/cancelled within 24 hours
    relevant = []
    for t in tasks:
        if t.status in ("pending", "running", "missed", "interrupted"):
            relevant.append(t)
        else:
            try:
                due_dt = t.get_due_datetime()
                if due_dt >= cutoff_24h:
                    relevant.append(t)
            except Exception:
                relevant.append(t)

    if not relevant:
        return "No scheduled tasks in the last 24 hours."

    lines = ["Scheduled tasks:"]
    # Sort pending first, then by due_at
    for t in sorted(relevant, key=lambda x: (0 if x.status in ("pending", "running") else 1, x.due_at)):
        due_dt = t.get_due_datetime()
        clock_disp, gap_disp = format_due_time_relative(due_dt, now)
        if t.status == "pending":
            lines.append(f"- [{t.id}] (pending) {t.type} '{t.description}' due at {clock_disp} ({gap_disp})")
        elif t.status == "running":
            lines.append(f"- [{t.id}] (running) {t.type} '{t.description}' currently executing")
        elif t.status == "done":
            lines.append(f"- [{t.id}] (done) {t.type} '{t.description}' at {clock_disp} -> result: {t.result}")
        elif t.status == "failed":
            lines.append(f"- [{t.id}] (failed) {t.type} '{t.description}' at {clock_disp} -> error: {t.result}")
        elif t.status == "interrupted":
            lines.append(f"- [{t.id}] (interrupted) {t.type} '{t.description}' shut down while running")
        elif t.status == "cancelled":
            lines.append(f"- [{t.id}] (cancelled) {t.type} '{t.description}'")
        else:
            lines.append(f"- [{t.id}] ({t.status}) {t.type} '{t.description}' was due at {clock_disp}")

    return "\n".join(lines)


@function_tool
async def cancel_scheduled_task(task_id_or_text: str) -> str:
    """
    Cancels a pending scheduled task by its 4-character ID or by matching text in its description.
    """
    query = task_id_or_text.strip().lower()
    tasks = await scheduler.store.list_all_tasks()
    pending = [t for t in tasks if t.status == "pending"]

    # 1. Exact ID match
    for t in pending:
        if t.id.lower() == query:
            t.status = "cancelled"
            await scheduler.store.update_task(t)
            scheduler.wake()
            return f"done: cancelled task [{t.id}] '{t.description}'"

    # 2. Fuzzy description match
    matches = [t for t in pending if query in t.description.lower()]
    if len(matches) == 1:
        t = matches[0]
        t.status = "cancelled"
        await scheduler.store.update_task(t)
        scheduler.wake()
        return f"done: cancelled task [{t.id}] '{t.description}'"
    elif len(matches) > 1:
        candidates = ", ".join(f"[{m.id}] '{m.description}'" for m in matches)
        return f"failed: ambiguous match. Did you mean: {candidates}?"

    return f"failed: no pending scheduled task matching '{task_id_or_text}'"


@function_tool
async def resolve_missed_task(task_id: str, run_now: bool) -> str:
    """
    Resolves an unresolved missed or interrupted task (from a previous session or when laptop was off).
    Args:
        task_id: The ID of the task.
        run_now: True to execute the task immediately, False to dismiss/cancel it.
    """
    t = await scheduler.store.get_task(task_id.strip())
    if not t or t.status not in ("missed", "interrupted"):
        return f"failed: no missed or interrupted task found with id '{task_id}'"

    if not run_now:
        t.status = "cancelled"
        await scheduler.store.update_task(t)
        return f"done: dismissed task [{t.id}] '{t.description}'"

    # Execute immediately
    logger.info(f"[SCHED] User requested immediate execution of task [{t.id}] (status={t.status})")
    if t.type == "reminder":
        await scheduler._fire_reminder(t)
        return f"done: delivered missed reminder [{t.id}] '{t.description}'"
    else:
        await scheduler._fire_action(t)
        return f"done: executed action [{t.id}] '{t.description}' (result: {t.result})"
