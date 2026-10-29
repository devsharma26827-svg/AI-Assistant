"""
Unit tests for Cynthia Task & Reminder Scheduler (scheduler_tools.py).
Tests:
1. delay_minutes=5 -> due exactly now+5min; result string contains resolved time.
2. at_time '04:55' with no meridiem at 4:50 PM -> 4:55 PM today; at 5:00 PM -> next occurrence (rolls correctly).
3. Past time with explicit meridiem rolls to tomorrow or fails per rules; > 7 days and negative values rejected.
4. Task fires within GRACE; a task overdue by > GRACE is marked missed and NOT executed (both reminder and action).
5. Restart simulation: tasks stored, new scheduler instance loads them, overdue ones become missed + one startup notice, no auto-execution; run_now=True executes once; False cancels.
6. Exactly-once execution (no double fire after reconnect supervisor creates a new session).
7. Action goes through the serialized lock (assert order with another concurrent tool), and failed tool result -> status failed + honest message.
8. Non-whitelisted tool is rejected; invalid args rejected at schedule time.
9. Cancel by id and by fuzzy text; ambiguous cancel returns candidates.
10. Atomic write: corrupt/empty JSON file doesn't crash startup (back it up as .bak and start empty, log a warning).
"""

import os
import json
import asyncio
import tempfile
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, AsyncMock, patch

import scheduler_tools
from scheduler_tools import (
    ScheduledTask,
    TaskStore,
    TaskScheduler,
    parse_and_validate_time,
    format_due_time_relative,
    validate_action_arguments,
    get_now,
    set_clock_override,
    get_current_time,
    schedule_reminder,
    schedule_action,
    list_scheduled_tasks,
    cancel_scheduled_task,
    resolve_missed_task,
    GRACE_SECONDS,
)
from tool_serializer import _global_tool_lock


@pytest.fixture
def fake_clock():
    """Sets a fixed base time: Tuesday, 27 October 2026, 04:50 PM (16:50) local time."""
    # Use system local timezone
    local_tz = datetime.now().astimezone().tzinfo
    current_time = datetime(2026, 10, 27, 16, 50, 0, tzinfo=local_tz)

    def clock():
        nonlocal current_time
        return current_time

    def advance(minutes: float = 0, seconds: float = 0):
        nonlocal current_time
        current_time += timedelta(minutes=minutes, seconds=seconds)

    clock.advance = advance
    set_clock_override(clock)
    yield clock
    set_clock_override(None)


@pytest.fixture
def temp_store(tmp_path):
    """Provides a fresh isolated TaskStore instance in a temporary directory."""
    test_file = str(tmp_path / "scheduled_tasks.json")
    store = TaskStore(filepath=test_file)
    return store


# -----------------------------------------------------------------------------
# Test 1: delay_minutes=5 -> due exactly now+5min; result contains resolved time
# -----------------------------------------------------------------------------
def test_delay_minutes_calculation(fake_clock):
    now = fake_clock()
    due, err = parse_and_validate_time(delay_minutes=5)
    assert err is None
    assert due == now + timedelta(minutes=5)

    clock_disp, gap_disp = format_due_time_relative(due, now)
    assert clock_disp == "04:55 PM"
    assert "in 5 min" in gap_disp


# -----------------------------------------------------------------------------
# Test 2: at_time "04:55" without meridiem
# - at 4:50 PM -> 4:55 PM today
# - at 5:00 PM -> rolls to next occurrence (4:55 AM tomorrow)
# -----------------------------------------------------------------------------
def test_at_time_no_meridiem_rolling(fake_clock):
    # At 4:50 PM, 4:55 should be 4:55 PM today (in 5 minutes)
    now = fake_clock()
    due, err = parse_and_validate_time(at_time="04:55")
    assert err is None
    assert due.hour == 16
    assert due.minute == 55
    assert due.date() == now.date()

    # Advance clock to 5:00 PM (17:00)
    fake_clock.advance(minutes=10)
    now_5pm = fake_clock()
    due2, err2 = parse_and_validate_time(at_time="04:55")
    assert err2 is None
    # Next upcoming occurrence within 12 hours is tomorrow morning 04:55 AM
    assert due2.hour == 4
    assert due2.minute == 55
    assert due2.date() == now_5pm.date() + timedelta(days=1)


# -----------------------------------------------------------------------------
# Test 3: Past time with explicit meridiem rolls to tomorrow or fails per rules;
# > 7 days and negative values rejected.
# -----------------------------------------------------------------------------
def test_meridiem_and_boundary_rejection(fake_clock):
    now = fake_clock()  # 4:50 PM today

    # Explicit "pm" at 4:00 PM (past today) with no date forced -> rolls to tomorrow 4:00 PM
    due_pm, err_pm = parse_and_validate_time(at_time="04:00", meridiem="pm")
    assert err_pm is None
    assert due_pm.hour == 16
    assert due_pm.date() == now.date() + timedelta(days=1)

    # Explicit "today" with past time -> fails with clear message
    due_today_past, err_today_past = parse_and_validate_time(at_time="04:00", meridiem="pm", date_str="today")
    assert due_today_past is None
    assert "already passed" in err_today_past

    # Negative delay rejected
    _, err_neg = parse_and_validate_time(delay_minutes=-10)
    assert "must be positive" in err_neg

    # > 7 days rejected
    _, err_huge = parse_and_validate_time(delay_minutes=8 * 24 * 60)
    assert "cannot schedule more than 7 days" in err_huge


# -----------------------------------------------------------------------------
# Test 4: Task fires within GRACE; overdue by > GRACE is marked missed and NOT executed
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_grace_period_execution_and_missed(fake_clock, temp_store):
    sched = TaskScheduler(store=temp_store)
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    sched.set_active_session(mock_session)

    now = fake_clock()
    # Task 1: due 1 minute ago (within 90s grace)
    t1 = ScheduledTask(
        id="t001",
        type="reminder",
        description="drink water",
        due_at=(now - timedelta(seconds=30)).isoformat(),
        created_at=now.isoformat(),
        status="pending",
    )
    # Task 2: overdue by 300s (exceeds 90s grace)
    t2 = ScheduledTask(
        id="t002",
        type="reminder",
        description="call mom",
        due_at=(now - timedelta(seconds=300)).isoformat(),
        created_at=now.isoformat(),
        status="pending",
    )
    await temp_store.add_task(t1)
    await temp_store.add_task(t2)

    # Run one pass of scheduler loop logic
    # Start scheduler briefly
    sched.start()
    await asyncio.sleep(0.1)
    sched.stop()

    saved1 = await temp_store.get_task("t001")
    saved2 = await temp_store.get_task("t002")

    # t1 was within GRACE -> executed and marked done
    assert saved1.status == "done"
    # t2 was beyond GRACE -> marked missed and never executed
    assert saved2.status == "missed"
    assert "overdue" in saved2.result


# -----------------------------------------------------------------------------
# Test 5: Restart simulation: tasks stored, new scheduler instance loads them,
# overdue ones become missed + one startup notice, run_now=True / False
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_restart_simulation_and_missed_resolution(fake_clock, tmp_path):
    test_file = str(tmp_path / "scheduled_tasks.json")
    store1 = TaskStore(filepath=test_file)

    now = fake_clock()
    # Schedule a task in store1
    task = ScheduledTask(
        id="m001",
        type="action",
        description="test action",
        due_at=(now - timedelta(seconds=200)).isoformat(),  # was due while offline
        created_at=now.isoformat(),
        status="pending",
        tool_name="set_system_volume",
        args={"volume": 50},
    )
    await store1.add_task(task)

    # Simulate restart: new store and scheduler instance loading the same file
    store2 = TaskStore(filepath=test_file)
    sched2 = TaskScheduler(store=store2)

    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()

    # Check startup missed tasks
    await sched2.check_startup_missed_tasks(mock_session)

    loaded = await store2.get_task("m001")
    assert loaded.status == "missed"
    assert loaded.missed_notified is True
    # Startup notice was delivered to user
    mock_session.generate_reply.assert_called_once()

    # Second startup check does not re-notify (missed_notified is True)
    mock_session.generate_reply.reset_mock()
    await sched2.check_startup_missed_tasks(mock_session)
    mock_session.generate_reply.assert_not_called()

    # Resolve missed task: run_now=False cancels
    with patch("scheduler_tools.scheduler", sched2):
        res_cancel = await resolve_missed_task("m001", run_now=False)
        assert "dismissed" in res_cancel
        assert (await store2.get_task("m001")).status == "cancelled"

    # Now create another missed task to test run_now=True
    task2 = ScheduledTask(
        id="m002",
        type="reminder",
        description="say hello",
        due_at=(now - timedelta(seconds=200)).isoformat(),
        created_at=now.isoformat(),
        status="missed",
    )
    await store2.add_task(task2)
    with patch("scheduler_tools.scheduler", sched2):
        sched2.set_active_session(mock_session)
        res_run = await resolve_missed_task("m002", run_now=True)
        assert "delivered missed reminder" in res_run
        assert (await store2.get_task("m002")).status == "done"


# -----------------------------------------------------------------------------
# Test 6: Exactly-once execution (no double fire after reconnect supervisor creates session)
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exactly_once_execution(fake_clock, temp_store):
    sched = TaskScheduler(store=temp_store)
    mock_session1 = MagicMock()
    mock_session1.generate_reply = AsyncMock()
    sched.set_active_session(mock_session1)

    now = fake_clock()
    task = ScheduledTask(
        id="x001",
        type="reminder",
        description="check oven",
        due_at=now.isoformat(),
        created_at=now.isoformat(),
        status="pending",
    )
    await temp_store.add_task(task)

    sched.start()
    await asyncio.sleep(0.1)

    # Reconnect supervisor simulates creating a new AgentSession
    mock_session2 = MagicMock()
    mock_session2.generate_reply = AsyncMock()
    sched.set_active_session(mock_session2)
    sched.wake()
    await asyncio.sleep(0.1)
    sched.stop()

    saved = await temp_store.get_task("x001")
    assert saved.status == "done"
    # Fired exactly once on session1, not double fired on session2
    assert mock_session1.generate_reply.call_count == 1
    assert mock_session2.generate_reply.call_count == 0


# -----------------------------------------------------------------------------
# Test 7: Action goes through serialized lock & handles failure honestly
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_action_serialized_lock_and_honest_failure(fake_clock, temp_store):
    sched = TaskScheduler(store=temp_store)
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    sched.set_active_session(mock_session)

    execution_order = []

    async def mock_action(**kwargs):
        # Verify _global_tool_lock is held
        assert _global_tool_lock.locked()
        execution_order.append("scheduled_action")
        return "failed: mock hardware error"

    task = ScheduledTask(
        id="a001",
        type="action",
        description="mock tool action",
        due_at=fake_clock().isoformat(),
        created_at=fake_clock().isoformat(),
        status="pending",
        tool_name="set_system_volume",
        args={"volume": 80},
    )
    await temp_store.add_task(task)

    with patch("scheduler_tools.get_action_tool_map", return_value={"set_system_volume": mock_action}):
        sched.start()
        await asyncio.sleep(0.1)
        sched.stop()

    saved = await temp_store.get_task("a001")
    assert saved.status == "failed"
    assert "failed: mock hardware error" in saved.result
    assert execution_order == ["scheduled_action"]


# -----------------------------------------------------------------------------
# Test 8: Non-whitelisted tool rejected; invalid args rejected at schedule time
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_whitelist_and_arg_validation(fake_clock, temp_store):
    with patch("scheduler_tools.scheduler.store", temp_store):
        # 1. Destructive tool rejected
        res_destr = await schedule_action("power_shutdown", "{}", "shutdown pc", delay_minutes=5)
        assert "failed: not allowed to schedule" in res_destr

        # 2. WhatsApp with missing message rejected at schedule time
        res_wa = await schedule_action("whatsapp_message", json.dumps({"contact": "Kushagar"}), "send msg", delay_minutes=5)
        assert "failed: invalid arguments" in res_wa
        assert "message" in res_wa

        # 3. Invalid volume arg rejected at schedule time
        res_vol = await schedule_action("set_system_volume", json.dumps({"volume": 200}), "set vol", delay_minutes=5)
        assert "failed: invalid arguments" in res_vol
        assert "between 0 and 100" in res_vol


# -----------------------------------------------------------------------------
# Test 9: Cancel by id and by fuzzy text; ambiguous cancel returns candidates
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cancel_scheduled_task(fake_clock, temp_store):
    now = fake_clock()
    t1 = ScheduledTask(id="c001", type="reminder", description="buy milk", due_at=(now + timedelta(minutes=10)).isoformat(), created_at=now.isoformat())
    t2 = ScheduledTask(id="c002", type="reminder", description="buy eggs", due_at=(now + timedelta(minutes=20)).isoformat(), created_at=now.isoformat())
    t3 = ScheduledTask(id="c003", type="reminder", description="water plants", due_at=(now + timedelta(minutes=30)).isoformat(), created_at=now.isoformat())
    await temp_store.add_task(t1)
    await temp_store.add_task(t2)
    await temp_store.add_task(t3)

    with patch("scheduler_tools.scheduler.store", temp_store):
        # Cancel by exact ID
        res_id = await cancel_scheduled_task("c003")
        assert "done: cancelled task [c003]" in res_id
        assert (await temp_store.get_task("c003")).status == "cancelled"

        # Cancel by ambiguous text ("buy") matches c001 and c002
        res_ambig = await cancel_scheduled_task("buy")
        assert "failed: ambiguous match" in res_ambig
        assert "[c001]" in res_ambig and "[c002]" in res_ambig

        # Cancel by specific fuzzy text
        res_milk = await cancel_scheduled_task("milk")
        assert "done: cancelled task [c001]" in res_milk
        assert (await temp_store.get_task("c001")).status == "cancelled"


# -----------------------------------------------------------------------------
# Test 10: Atomic write: corrupt/empty JSON file doesn't crash startup (backs up as .bak)
# -----------------------------------------------------------------------------
def test_corrupt_file_recovery(tmp_path):
    test_file = str(tmp_path / "scheduled_tasks.json")
    bak_file = test_file + ".bak"

    # Write corrupt JSON
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("{corrupt bad json content !!!")

    # TaskStore initialization must not raise, and should create .bak backup
    store = TaskStore(filepath=test_file)
    assert os.path.exists(bak_file)
    assert len(store.tasks) == 0

    # Ensure empty file recovery also works
    with open(test_file, "w", encoding="utf-8") as f:
        f.write("")
    store_empty = TaskStore(filepath=test_file)
    assert len(store_empty.tasks) == 0


# -----------------------------------------------------------------------------
# Test 11: Real @serialized_tool action execution (whatsapp_message) without deadlock
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_real_serialized_tool_action_no_deadlock(fake_clock, temp_store, caplog):
    import logging
    from whatsapp_tools import whatsapp_message

    sched = TaskScheduler(store=temp_store)
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    sched.set_active_session(mock_session)

    now = fake_clock()
    task = ScheduledTask(
        id="w001",
        type="action",
        description="WhatsApp hello to Dev Sharma",
        due_at=now.isoformat(),
        created_at=now.isoformat(),
        status="pending",
        tool_name="whatsapp_message",
        args={"contact": "Dev Sharma", "message": "hello"},
    )
    await temp_store.add_task(task)

    with caplog.at_level(logging.INFO):
        with patch("whatsapp_tools._whatsapp_message_sync", return_value="done: WhatsApp message sent to Dev Sharma."):
            sched.start()
            for _ in range(40):
                saved_check = await temp_store.get_task("w001")
                if saved_check and saved_check.status in ("done", "failed"):
                    break
                await asyncio.sleep(0.05)
            sched.stop()

    saved = await temp_store.get_task("w001")
    assert saved.status == "done"
    assert "done: WhatsApp message sent" in saved.result
    # Verify [SEQ] step 1/1 start and done appeared in logs
    log_text = caplog.text
    assert "[SEQ] step 1/1 start: whatsapp_message" in log_text
    assert "[SEQ] step 1/1 done: whatsapp_message" in log_text
    assert "[SCHED] done id=w001" in log_text


# -----------------------------------------------------------------------------
# Test 12: Scheduled action waits while another tool holds the lock, then runs
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_scheduled_action_waits_for_held_lock(fake_clock, temp_store):
    sched = TaskScheduler(store=temp_store)
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    sched.set_active_session(mock_session)

    execution_order = []

    async def blocking_holder():
        async with _global_tool_lock:
            execution_order.append("holder_acquired")
            await asyncio.sleep(0.15)
            execution_order.append("holder_released")

    async def mock_action(**kwargs):
        execution_order.append("scheduled_tool_ran")
        return "done: mock action finished"

    task = ScheduledTask(
        id="h001",
        type="action",
        description="action waiting for lock",
        due_at=fake_clock().isoformat(),
        created_at=fake_clock().isoformat(),
        status="pending",
        tool_name="set_system_volume",
        args={"volume": 50},
    )
    await temp_store.add_task(task)

    with patch("scheduler_tools.get_action_tool_map", return_value={"set_system_volume": mock_action}):
        # Start holder task holding the lock
        holder_task = asyncio.create_task(blocking_holder())
        await asyncio.sleep(0.02)  # ensure holder acquires lock first
        assert _global_tool_lock.locked()

        sched.start()
        await asyncio.sleep(0.25)
        sched.stop()
        await holder_task

    saved = await temp_store.get_task("h001")
    assert saved.status == "done"
    assert execution_order == ["holder_acquired", "holder_released", "scheduled_tool_ran"]


# -----------------------------------------------------------------------------
# Test 13: Lock-acquire timeout returns 'failed: busy' and releases cleanly
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_lock_acquire_timeout_busy():
    from tool_serializer import serialized_tool

    @serialized_tool("busy_test_tool")
    async def my_tool():
        return "done: tool executed"

    # Patch LOCK_ACQUIRE_TIMEOUT to a tiny duration (0.05s)
    with patch("tool_serializer.LOCK_ACQUIRE_TIMEOUT", 0.05):
        # Hold lock with another task for 0.2s
        async def holder():
            async with _global_tool_lock:
                await asyncio.sleep(0.2)

        holder_task = asyncio.create_task(holder())
        await asyncio.sleep(0.02)

        # Call tool while lock is busy
        res = await my_tool()
        assert "failed: busy" in res
        assert "could not acquire tool lock" in res

        await holder_task
        assert not _global_tool_lock.locked()


# -----------------------------------------------------------------------------
# Test 14: Nested serialized call regression runs without deadlock
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_nested_serialized_call_no_deadlock():
    from tool_serializer import serialized_tool

    @serialized_tool("inner_tool")
    async def inner_tool():
        return "done: inner"

    @serialized_tool("outer_tool")
    async def outer_tool():
        inner_res = await inner_tool()
        return f"done: outer -> {inner_res}"

    # Must execute smoothly without self-deadlock
    res = await asyncio.wait_for(outer_tool(), timeout=1.0)
    assert res == "done: outer -> done: inner"
    assert not _global_tool_lock.locked()


# -----------------------------------------------------------------------------
# Test 15: Tool execution hang/timeout returns failed: timeout and releases lock
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_execution_timeout_releases_lock():
    from tool_serializer import serialized_tool

    @serialized_tool("hanging_tool")
    async def hanging_tool():
        await asyncio.sleep(10.0)
        return "done: finished"

    res = await hanging_tool(execution_timeout=0.1)
    assert "failed: hanging_tool execution timed out" in res
    assert not _global_tool_lock.locked()


# -----------------------------------------------------------------------------
# Test 16: Task left 'running' at startup becomes 'interrupted', warns, not auto-run
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_running_task_becomes_interrupted_on_startup(fake_clock, tmp_path):
    test_file = str(tmp_path / "scheduled_tasks.json")

    now = fake_clock()
    # Write a task with status="running" as if assistant crashed mid-execution
    running_task = {
        "id": "i001",
        "type": "action",
        "description": "WhatsApp msg to Rahul",
        "due_at": now.isoformat(),
        "created_at": now.isoformat(),
        "status": "running",
        "tool_name": "whatsapp_message",
        "args": {"contact": "Rahul", "message": "hey"},
        "missed_notified": False,
        "result": None,
    }
    with open(test_file, "w", encoding="utf-8") as f:
        json.dump([running_task], f)

    # Initialize store
    store = TaskStore(filepath=test_file)
    task = await store.get_task("i001")
    assert task.status == "interrupted"
    assert "interrupted" in task.result

    sched = TaskScheduler(store=store)
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()

    # Startup check
    await sched.check_startup_missed_tasks(mock_session)
    mock_session.generate_reply.assert_called_once()
    spoken_inst = mock_session.generate_reply.call_args[1]["instructions"]
    assert "interrupt" in spoken_inst
    assert "aadha" in spoken_inst or "partially" in spoken_inst

    # Resolve interrupted task with dismiss
    with patch("scheduler_tools.scheduler", sched):
        res_dismiss = await resolve_missed_task("i001", run_now=False)
        assert "dismissed" in res_dismiss
        assert (await store.get_task("i001")).status == "cancelled"


# -----------------------------------------------------------------------------
# Test 17: list_scheduled_tasks shows 24h history with all statuses and results
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_list_scheduled_tasks_24h_history(fake_clock, temp_store):
    now = fake_clock()
    t_pending = ScheduledTask(id="lp01", type="reminder", description="buy tea", due_at=(now + timedelta(minutes=10)).isoformat(), created_at=now.isoformat(), status="pending")
    t_done = ScheduledTask(id="ld01", type="action", description="play music", due_at=(now - timedelta(minutes=30)).isoformat(), created_at=now.isoformat(), status="done", result="done: playing lo-fi")
    t_failed = ScheduledTask(id="lf01", type="action", description="set vol", due_at=(now - timedelta(minutes=45)).isoformat(), created_at=now.isoformat(), status="failed", result="failed: hardware error")
    t_interrupted = ScheduledTask(id="li01", type="action", description="send email", due_at=(now - timedelta(hours=2)).isoformat(), created_at=now.isoformat(), status="interrupted", result="interrupted: shut down")

    await temp_store.add_task(t_pending)
    await temp_store.add_task(t_done)
    await temp_store.add_task(t_failed)
    await temp_store.add_task(t_interrupted)

    with patch("scheduler_tools.scheduler.store", temp_store):
        output = await list_scheduled_tasks()
        assert "[lp01] (pending)" in output
        assert "[ld01] (done)" in output and "result: done: playing lo-fi" in output
        assert "[lf01] (failed)" in output and "error: failed: hardware error" in output
        assert "[li01] (interrupted)" in output


# -----------------------------------------------------------------------------
# Test 18: Exact mode reminder vs Remind mode reminder
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_exact_vs_remind_mode(fake_clock, temp_store):
    sched = TaskScheduler(store=temp_store)
    mock_session = MagicMock()
    mock_session.generate_reply = AsyncMock()
    sched.set_active_session(mock_session)

    now = fake_clock()
    # 1. Exact mode
    t_exact = ScheduledTask(id="e001", type="reminder", description="Hello", due_at=now.isoformat(), created_at=now.isoformat(), status="pending", mode="exact")
    await sched._fire_reminder(t_exact)
    exact_prompt = mock_session.generate_reply.call_args[1]["instructions"]
    assert "Say strictly and exactly: 'Hello' and nothing else" in exact_prompt

    mock_session.generate_reply.reset_mock()
    # 2. Remind mode
    t_remind = ScheduledTask(id="r001", type="reminder", description="take medicine", due_at=now.isoformat(), created_at=now.isoformat(), status="pending", mode="remind")
    await sched._fire_reminder(t_remind)
    remind_prompt = mock_session.generate_reply.call_args[1]["instructions"]
    assert "Deliver this reminder in one short, warm Hinglish sentence" in remind_prompt
    assert "Do NOT use Urdu, Arabic, or non-Latin scripts" in remind_prompt


# -----------------------------------------------------------------------------
# Test 19: Session context injection after task completion and reconnect
# -----------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_session_context_injection(fake_clock, temp_store):
    from livekit.agents import llm
    sched = TaskScheduler(store=temp_store)
    mock_session = MagicMock()
    mock_session.history = llm.ChatContext()
    mock_session.generate_reply = AsyncMock()
    sched.set_active_session(mock_session)

    now = fake_clock()
    task = ScheduledTask(
        id="c001",
        type="action",
        description="WhatsApp msg to Dev Sharma",
        due_at=now.isoformat(),
        created_at=now.isoformat(),
        status="pending",
        tool_name="set_system_volume",
        args={"volume": 70},
    )
    await temp_store.add_task(task)

    async def mock_tool(**kwargs):
        return "done: Volume set to 70%."

    with patch("scheduler_tools.get_action_tool_map", return_value={"set_system_volume": mock_tool}):
        await sched._fire_action(task)

    # Context was injected into mock_session.history
    assert len(mock_session.history.items) >= 1
    last_msg = mock_session.history.items[-1]
    assert "[scheduler] Task c001" in str(last_msg.content)
    assert "result: done" in str(last_msg.content)

    # Simulate supervisor reconnect: new session attached
    mock_session2 = MagicMock()
    mock_session2.history = llm.ChatContext()
    sched.set_active_session(mock_session2)
    # The outcome line was re-injected into the new session history!
    assert len(mock_session2.history.items) >= 1
    assert "[scheduler] Task c001" in str(mock_session2.history.items[-1].content)
