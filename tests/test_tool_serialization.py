"""
Unit tests for Cynthia's Tool Serialization and StepBarrier ordering.
Verifies:
1. Single calls (total_steps <= 1) never wait.
2. Out-of-order arrival (step 3 arrives before step 1) executes strictly in step order (1 -> 2 -> 3).
3. Concurrent tool calls serialize mutually exclusive via global lock.
4. Cancellation (user interrupt) cleanly releases the lock so subsequent tools never hang.
5. Step barrier fallback timeout prevents deadlocks if an earlier step is skipped.
"""
import asyncio
import logging
import pytest
from tool_serializer import serialized_tool, StepBarrier, reset_tool_barrier, _global_tool_lock


@pytest.fixture(autouse=True)
def clean_barrier_and_lock():
    reset_tool_barrier()
    yield
    reset_tool_barrier()


@pytest.mark.asyncio
async def test_single_call_does_not_wait():
    execution_order = []

    @serialized_tool("single_tool")
    async def sample_tool(val: str, step: int = 1, total_steps: int = 1):
        execution_order.append(val)
        return f"done: {val}"

    # Single call (total_steps=1) should run immediately without barrier delay
    start_t = asyncio.get_event_loop().time()
    res = await sample_tool("hello", step=1, total_steps=1)
    duration = asyncio.get_event_loop().time() - start_t

    assert res == "done: hello"
    assert execution_order == ["hello"]
    assert duration < 0.2, f"Single call should not wait, took {duration}s"


@pytest.mark.asyncio
async def test_out_of_order_arrival_executes_in_step_order(caplog):
    execution_order = []
    caplog.set_level(logging.INFO)

    @serialized_tool("step_tool")
    async def step_tool(name: str, step: int = 1, total_steps: int = 3):
        execution_order.append((step, name))
        await asyncio.sleep(0.05)
        return f"done: {name}"

    # Dispatch tasks in reverse order: step 3, then step 2, then step 1
    t3 = asyncio.create_task(step_tool("YouTube", step=3, total_steps=3))
    await asyncio.sleep(0.01)
    t2 = asyncio.create_task(step_tool("Volume", step=2, total_steps=3))
    await asyncio.sleep(0.01)
    t1 = asyncio.create_task(step_tool("WhatsApp", step=1, total_steps=3))

    results = await asyncio.gather(t1, t2, t3)

    assert results == ["done: WhatsApp", "done: Volume", "done: YouTube"]
    # Check execution sequence was strictly 1 -> 2 -> 3
    assert execution_order == [(1, "WhatsApp"), (2, "Volume"), (3, "YouTube")]

    # Check terminal logs contain [SEQ] step X/Y start and done
    logs = caplog.text
    assert "[SEQ] step 1/3 start: step_tool" in logs
    assert "[SEQ] step 1/3 done: step_tool" in logs
    assert "[SEQ] step 2/3 start: step_tool" in logs
    assert "[SEQ] step 2/3 done: step_tool" in logs
    assert "[SEQ] step 3/3 start: step_tool" in logs
    assert "[SEQ] step 3/3 done: step_tool" in logs


@pytest.mark.asyncio
async def test_cancellation_releases_lock():
    execution_order = []

    @serialized_tool("cancellable_tool")
    async def cancellable_tool(val: str, delay: float, step: int = 1, total_steps: int = 2):
        execution_order.append(f"start_{val}")
        await asyncio.sleep(delay)
        execution_order.append(f"done_{val}")
        return f"done: {val}"

    # Step 1 will sleep 1s but get cancelled after 0.05s
    t1 = asyncio.create_task(cancellable_tool("first", delay=1.0, step=1, total_steps=2))
    await asyncio.sleep(0.05)
    t1.cancel()

    with pytest.raises(asyncio.CancelledError):
        await t1

    # Verify lock is NOT stuck: step 2 must be able to acquire lock and finish cleanly
    t2 = asyncio.create_task(cancellable_tool("second", delay=0.01, step=2, total_steps=2))
    res2 = await t2

    assert res2 == "done: second"
    assert "start_first" in execution_order
    assert "done_second" in execution_order
    assert not _global_tool_lock.locked()


@pytest.mark.asyncio
async def test_barrier_timeout_fallback_if_step_skipped():
    # If LLM skips step 1 and directly emits step 2 (total_steps=2), step 2 should time out
    # waiting for step 1 to start and then proceed safely
    custom_barrier = StepBarrier(start_timeout=0.2)

    @serialized_tool("fallback_tool")
    async def fallback_tool(name: str, step: int = 2, total_steps: int = 2):
        return f"done: {name}"

    res = await fallback_tool("Volume", step=2, total_steps=2)
    assert res == "done: Volume"
