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

# Global lock ensuring strictly one state-changing / UI / hardware action runs at a time
_global_tool_lock = asyncio.Lock()


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
        self._last_activity_time = 0.0

    def reset(self) -> None:
        """Resets barrier state for a new turn or conversation item."""
        self._step_started_events.clear()
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
    2. Mutual exclusion via global asyncio.Lock.
    3. Safe lock release on normal completion, exceptions, or asyncio.CancelledError.
    4. Uniform logging: `[SEQ] step X/Y start: <tool>` and `[SEQ] step X/Y done: <tool>`.
    """
    def decorator(fn: Callable) -> Callable:
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

            seq_label = f"step {step}/{total_steps}" if total_steps > 1 else f"step {step}"

            # 1. Wait for preceding step to START (only if total_steps > 1)
            await _step_barrier.wait_for_previous_step_to_start(step, total_steps)

            # 2. Acquire global lock ensuring strictly one action runs at a time
            async with _global_tool_lock:
                # Signal that this step has started so subsequent steps can proceed to queue
                _step_barrier.mark_step_started(step)

                logger.info(f"[SEQ] {seq_label} start: {tool_name}")
                try:
                    result = await fn(*args, **kwargs)
                    logger.info(f"[SEQ] {seq_label} done: {tool_name}")
                    return result
                except asyncio.CancelledError:
                    logger.warning(f"[SEQ] {seq_label} cancelled: {tool_name}")
                    raise
                except Exception as e:
                    logger.error(f"[SEQ] {seq_label} failed: {tool_name} with error: {e}")
                    return f"failed: {tool_name} error: {e}"

        return wrapper
    return decorator
