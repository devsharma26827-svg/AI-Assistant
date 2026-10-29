"""
Tool Serializer for Cynthia AI Assistant.
Provides sequential execution guarantees and step-barrier ordering for multi-step commands,
preventing parallel tool clashes, window focus fighting, and audio/UI race conditions.
"""
import asyncio
import functools
import inspect
import logging
import time
from typing import Any, Callable

logger = logging.getLogger("tool_serializer")
logger.setLevel(logging.INFO)

# Global lock ensuring strictly one state-changing / UI / hardware action runs at a time.
# Reentrant per asyncio.Task to avoid self-deadlocks if a serialized tool calls another.
class ReentrantAsyncLock:
    """
    Task-reentrant asyncio lock.
    Allows the same asyncio.Task to acquire the lock multiple times without deadlocking.
    Automatically binds to the active event loop if the loop changes (e.g. across pytest tests).
    """
    def __init__(self):
        self._lock: asyncio.Lock | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    def _get_lock(self) -> asyncio.Lock:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._lock is None or (loop is not None and self._loop is not None and self._loop is not loop):
            self._lock = asyncio.Lock()
            self._loop = loop
            self._owner = None
            self._depth = 0
        return self._lock

    async def acquire(self, timeout: float | None = None) -> bool:
        lock = self._get_lock()
        current = asyncio.current_task()
        if self._owner is not None and self._owner is current:
            self._depth += 1
            return True

        if timeout is not None:
            async with asyncio.timeout(timeout):
                await lock.acquire()
        else:
            await lock.acquire()

        self._owner = current
        self._depth = 1
        return True

    def release(self) -> None:
        lock = self._get_lock()
        current = asyncio.current_task()
        if self._owner is not current:
            raise RuntimeError(f"Cannot release unowned lock. Owner: {self._owner}, current: {current}")

        self._depth -= 1
        if self._depth == 0:
            self._owner = None
            lock.release()

    def locked(self) -> bool:
        if self._lock is None:
            return False
        return self._lock.locked()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


_global_tool_lock = ReentrantAsyncLock()


LOCK_ACQUIRE_TIMEOUT = 120.0


class StepBarrier:
    """
    Coordinates multi-step tool calls arriving concurrently from a single model turn.
    - If total_steps <= 1 (single command), calls never wait.
    - If total_steps > 1, step N waits only for step N-1 to START (up to start_timeout).
    - Automatically resets on turn inactivity or explicit reset call.
    """
    def __init__(self, start_timeout: float = 3.0, turn_inactivity_timeout: float = 12.0):
        self.start_timeout = start_timeout
        self.turn_inactivity_timeout = turn_inactivity_timeout
        self._step_started_events: dict[int, asyncio.Event] = {}
        self._step_finished_events: dict[int, asyncio.Event] = {}
        self._last_activity_time = 0.0

    def reset(self) -> None:
        """Resets barrier state for a new turn or conversation item."""
        self._step_started_events.clear()
        self._step_finished_events.clear()
        self._last_activity_time = time.monotonic()
        logger.debug("[SEQ] StepBarrier reset")

    async def wait_for_previous_step_to_start(self, step: int, total_steps: int) -> None:
        """
        Wait for step-1 to START if total_steps > 1 and step > 1.
        Never waits for single commands (total_steps <= 1 or step <= 1).
        """
        if total_steps <= 1 or step <= 1:
            return

        now = time.monotonic()
        if self._last_activity_time > 0 and (now - self._last_activity_time > self.turn_inactivity_timeout):
            self.reset()
        self._last_activity_time = now

        prev_step = step - 1
        prev_event = self._step_started_events.setdefault(prev_step, asyncio.Event())
        if not prev_event.is_set():
            logger.debug(f"[SEQ] Step {step}/{total_steps} waiting for step {prev_step} to start (timeout {self.start_timeout}s)...")
            try:
                await asyncio.wait_for(prev_event.wait(), timeout=self.start_timeout)
            except asyncio.TimeoutError:
                logger.warning(f"[SEQ] Step {step}/{total_steps} barrier timed out waiting for step {prev_step} to start. Proceeding.")

    def mark_step_started(self, step: int) -> None:
        """Signals that step has acquired the lock and begun execution."""
        self._last_activity_time = time.monotonic()
        evt = self._step_started_events.setdefault(step, asyncio.Event())
        evt.set()

    def mark_step_finished(self, step: int) -> None:
        """Signals that step has finished execution and released resources."""
        self._last_activity_time = time.monotonic()
        evt = self._step_finished_events.setdefault(step, asyncio.Event())
        evt.set()


# Shared instance of the step barrier
_step_barrier = StepBarrier()


def reset_tool_barrier() -> None:
    """Public helper to reset the barrier state at each new speech/turn."""
    _step_barrier.reset()


def serialized_tool(name: str | None = None) -> Callable:
    """
    Decorator for state-changing / UI / hardware action tools.
    Enforces:
    1. Step-order coordination when total_steps > 1.
    2. Mutual exclusion via ReentrantAsyncLock with lock-acquire timeout.
    3. Safe lock release and StepBarrier completion in finally block.
    4. Per-tool execution timeout prevention.
    5. No double-wrapping via __serialized__ attribute.
    6. Uniform logging: `[SEQ] step X/Y start: <tool>` and `[SEQ] step X/Y done: <tool>`.
    """
    def decorator(fn: Callable) -> Callable:
        # Prevent double-wrapping
        if getattr(fn, "__serialized__", False):
            return fn
        inner = getattr(fn, "__wrapped__", None)
        if inner is not None and getattr(inner, "__serialized__", False):
            return fn

        tool_name = name or fn.__name__
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract step and total_steps if passed in kwargs or args
            bound = None
            try:
                bound = sig.bind_partial(*args, **kwargs)
                bound.apply_defaults()
                step = int(bound.arguments.get("step", 1))
                total_steps = int(bound.arguments.get("total_steps", 1))
            except Exception:
                step = int(kwargs.get("step", 1))
                total_steps = int(kwargs.get("total_steps", 1))

            seq_label = f"step {step}/{total_steps}"

            # 1. Wait for preceding step to START (only if total_steps > 1)
            await _step_barrier.wait_for_previous_step_to_start(step, total_steps)

            # 2. Acquire global lock with timeout (protects against deadlocks/busy states)
            try:
                await _global_tool_lock.acquire(timeout=LOCK_ACQUIRE_TIMEOUT)
            except TimeoutError:
                logger.warning(f"[SEQ] {seq_label} failed to acquire lock within {LOCK_ACQUIRE_TIMEOUT}s: {tool_name}")
                return f"failed: busy - could not acquire tool lock for {tool_name}"

            # 3. Execute inside try...finally ensuring lock release and barrier signaling
            try:
                _step_barrier.mark_step_started(step)
                logger.info(f"[SEQ] {seq_label} start: {tool_name}")

                # Default timeouts: 90s for WhatsApp desktop UI, 30s for other tools
                default_timeout = 90.0 if "whatsapp" in tool_name.lower() else 30.0
                exec_timeout = float(kwargs.pop("execution_timeout", default_timeout))

                try:
                    if exec_timeout and exec_timeout > 0:
                        async with asyncio.timeout(exec_timeout):
                            res = fn(*args, **kwargs)
                            if inspect.isawaitable(res):
                                result = await res
                            else:
                                result = res
                    else:
                        res = fn(*args, **kwargs)
                        if inspect.isawaitable(res):
                            result = await res
                        else:
                            result = res
                    logger.info(f"[SEQ] {seq_label} done: {tool_name}")
                    return result
                except TimeoutError:
                    logger.warning(f"[SEQ] {seq_label} execution timed out ({exec_timeout}s): {tool_name}")
                    return f"failed: {tool_name} execution timed out"
                except asyncio.CancelledError:
                    logger.warning(f"[SEQ] {seq_label} cancelled: {tool_name}")
                    raise
                except Exception as e:
                    logger.error(f"[SEQ] {seq_label} failed: {tool_name} with error: {e}")
                    return f"failed: {tool_name} error: {e}"
            finally:
                _step_barrier.mark_step_finished(step)
                _global_tool_lock.release()

        wrapper.__serialized__ = True
        return wrapper
    return decorator
