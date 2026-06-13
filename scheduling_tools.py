import logging
from datetime import datetime, timedelta
from livekit.agents import function_tool
from memory_store import memory
import dateparser

logger = logging.getLogger("scheduling_tools")
logger.setLevel(logging.INFO)

@function_tool
async def schedule_task(description: str, time: str, energy_level: str = "medium") -> str:
    """
    Schedules a new task for the user. Checks for conflicts before adding.
    
    Arguments:
    - description: What the task is (e.g., "Meeting with team", "Write report").
    - time: Natural language time (e.g., "tomorrow at 10am", "in 2 hours", "tonight 8pm").
    - energy_level: "high" (focus needed), "medium", or "low" (casual task).
    """
    try:
        # 1. Parse Time
        dt = dateparser.parse(time)
        if not dt:
            return f"❌ Could not understand time: '{time}'. Please specify clearly (e.g., '5pm', 'tomorrow morning')."
            
        # Ensure future time
        if dt < datetime.now():
            return f"⚠ That time ({dt.strftime('%I:%M %p')}) is in the past. Did you mean tomorrow?"

        time_iso = dt.isoformat()

        # 2. Check Conflicts
        conflicts = memory.check_conflicts(time_iso)
        if conflicts:
            conflict_msg = "⚠ Scheduling Conflict Detected:\n"
            for c in conflicts:
                conflict_msg += f"- '{c['description']}' at {c['time']}\n"
            conflict_msg += "Do you still want to schedule this? (Reply 'Yes override' or give new time)"
            return conflict_msg

        # 3. Add Task
        result = memory.add_task(description, time_iso, energy_level)
        
        # 4. Contextual Confirmation
        nice_time = dt.strftime("%A, %I:%M %p")
        return f"✅ Scheduled: '{description}' for {nice_time}. (Energy: {energy_level})"
    except Exception as e:
        logger.error(f"Error in schedule_task: {e}")
        return f"❌ Failed to schedule task due to internal error: {e}"

@function_tool
async def get_schedule(time_range: str = "today") -> str:
    """
    Retrieves scheduled tasks.
    
    Arguments:
    - time_range: "today", "tomorrow", "this week", or "all".
    """
    try:
        now = datetime.now()
        start_time = None
        end_time = None
        
        if "today" in time_range:
            start_time = now.strftime("%Y-%m-%d") + "T00:00:00"
            end_time = now.strftime("%Y-%m-%d") + "T23:59:59"
        elif "tomorrow" in time_range:
            tmrw = now + timedelta(days=1)
            start_time = tmrw.strftime("%Y-%m-%d") + "T00:00:00"
            end_time = tmrw.strftime("%Y-%m-%d") + "T23:59:59"
        
        tasks = memory.get_scheduled_tasks(start_time, end_time)
        
        if not tasks:
            return f"📅 No tasks found for {time_range}."
            
        res = f"📅 Schedule for {time_range}:\n"
        for t in tasks:
            dt = datetime.fromisoformat(t["time"])
            nice_time = dt.strftime("%I:%M %p")
            res += f"- {nice_time}: {t['description']} ({t.get('energy')})\n"
            
        return res
    except Exception as e:
        logger.error(f"Error in get_schedule: {e}")
        return f"❌ Failed to retrieve schedule: {e}"

@function_tool
async def complete_task(task_description: str) -> str:
    """
    Marks a task as completed.
    
    Arguments:
    - task_description: Keyword or name of the task to complete.
    """
    try:
        return memory.complete_task(task_description)
    except Exception as e:
        logger.error(f"Error in complete_task: {e}")
        return f"❌ Failed to complete task: {e}"

@function_tool
async def reschedule_task(task_keywords: str, new_time: str) -> str:
    """
    Moves an existing task to a new time.
    
    Arguments:
    - task_keywords: Words to identify the task (e.g., "meeting", "report").
    - new_time: New natural language time (e.g., "tomorrow 10am").
    """
    try:
        dt = dateparser.parse(new_time)
        if not dt:
            return f"❌ Invalid time format: {new_time}"
            
        return memory.reschedule_task(task_keywords, dt.isoformat())
    except Exception as e:
        logger.error(f"Error in reschedule_task: {e}")
        return f"❌ Failed to reschedule task: {e}"

@function_tool
async def defer_task(task_keywords: str) -> str:
    """
    Pushes a task to 'Tomorrow at same time' or 'Later today (+2 hours)'.
    Use this when user says 'do this later' or 'push to tomorrow'.
    """
    try:
        pending = [t for t in memory.memory.get("schedule", []) if t["status"]=="pending"]
        from fuzzywuzzy import process
        choices = [t["description"] for t in pending]
        if not choices: return "No pending tasks."
        
        best_match, score = process.extractOne(task_keywords, choices)
        if score > 70:
            for t in memory.memory["schedule"]:
                if t["description"] == best_match:
                    try:
                        curr_dt = datetime.fromisoformat(t["time"])
                        new_dt = curr_dt + timedelta(days=1)
                        t["time"] = new_dt.isoformat()
                        memory.save_memory()
                        return f"🗓️ Deferred '{best_match}' to tomorrow ({new_dt.strftime('%I:%M %p')})."
                    except:
                        return "❌ Error calculating new time."
                        
        return "❌ Task not found to defer."
    except Exception as e:
        logger.error(f"Error in defer_task: {e}")
        return f"❌ Failed to defer task: {e}"