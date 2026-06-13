import json
import os
import logging
from datetime import datetime

logger = logging.getLogger("memory_store")
logger.setLevel(logging.INFO)

MEMORY_FILE = "memory.json"

DEFAULT_MEMORY = {
    "user_profile": {
        "name": "Dev Sharma",
        "role": "Creator",
        "location": "India",
        "communication_style": "Hinglish, Direct",
    },
    "life_phases": {
        "current_phase": "Unknown",
        "goals": [],
        "challenges": []
    },
    "preferences": {
        "coding_language": "Python",
        "editor": "VS Code",
        "theme": "Dark"
    },
    "facts": {},  # Categorized facts: {"hobbies": [{"text": "gaming", "confidence": 1.0, "count": 1}], ...}
    "habits": [], # List of habits: [{"trigger": "...", "action": "...", "confidence": 1.0, "count": 1}]
    "schedule": [], # List of tasks: [{"id": "...", "description": "...", "time": "ISO", "status": "pending", "energy": "high"}]
    "emotional_context": {
        "current_state": "Neutral",
        "last_interaction_mood": "Neutral"
    },
    "language_preferences": {
        "primary": "English",
        "secondary": [], # List of other languages user speaks
        "tone": "Neutral", # Formal, Casual, etc.
        "mode": "auto" # auto, strict (always reply in primary)
    },
    "emotional_profile": {
        "communication_style": "adaptable", # adaptable, direct, empathetic
        "stress_triggers": [], # List of observed triggers
        "adaptability_score": 0.5,
        "emotional_history": [] # Long term summaries
    },
    "projects": [], # List of structured projects
    "environment_modes": {
        "active_mode": "normal",
        "last_mode": "normal",
        "preferences": {
            "focus": {"dnd": True, "volume": 0},
            "meeting": {"dnd": True, "volume": 80},
            "relax": {"dnd": False, "volume": 50, "brightness": 40},
            "coding": {"dnd": True, "volume": 20}
        }
    },
    "behavioral_learning": {
        "tool_stats": {}, # { "tool_name": { "success": 0, "failure": 0, "last_failure_reason": "" } }
        "corrections": [], # [ { "trigger": "...", "correction": "...", "timestamp": "..." } ]
        "parameter_preferences": {} # { "category": { "key": "value" } }
    },
    "workflows": {} # { "workflow_name": { "trigger": "...", "steps": ["..."], "conditions": "...", "requires_confirmation": True } }
}

class MemoryStore:
    def __init__(self, filepath=MEMORY_FILE):
        self.filepath = filepath
        self.memory = self.load_memory()

    def load_memory(self):
        if not os.path.exists(self.filepath):
            logger.info("No existing memory found. Creating new memory store.")
            self.save_memory(DEFAULT_MEMORY)
            return DEFAULT_MEMORY
        
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Basic migration if habits key is missing
                if "habits" not in data:
                    data["habits"] = []
                return data
        except Exception as e:
            logger.error(f"Failed to load memory: {e}")
            return DEFAULT_MEMORY

    def save_memory(self, data=None):
        if data is None:
            data = self.memory
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            logger.info("Memory saved successfully.")
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def set_active_file(self, file_path):
        """Updates the context with the last used file path."""
        if "file_context" not in self.memory:
            self.memory["file_context"] = {}
        
        self.memory["file_context"]["last_active_file"] = file_path
        self.memory["file_context"]["last_updated"] = datetime.now().isoformat()
        self.save_memory()
        
    def get_active_file(self):
        """Retrieves the last active file path."""
        return self.memory.get("file_context", {}).get("last_active_file")

    def add_fact(self, category, fact_text):
        if category not in self.memory["facts"]:
            self.memory["facts"][category] = []
        
        # Check if fact already exists
        timestamp = datetime.now().isoformat()
        for item in self.memory["facts"][category]:
            # Backwards compatibility check if item is just a string (old format)
            if isinstance(item, str):
                if item == fact_text:
                    # Upgrade to object
                    self.memory["facts"][category].remove(item)
                    new_item = {"text": fact_text, "confidence": 1.0, "count": 1, "last_used": timestamp}
                    self.memory["facts"][category].append(new_item)
                    self.save_memory()
                    return f"Migrated and remembered: [{category}] {fact_text}"
                continue
            
            # New format check
            if item["text"] == fact_text:
                item["count"] += 1
                item["confidence"] = min(1.0, item["confidence"] + 0.1)
                item["last_used"] = timestamp
                self.save_memory()
                return f"Reinforced: [{category}] {fact_text} (Confidence: {item['confidence']:.1f})"

        # If not found, add new
        new_item = {
            "text": fact_text, 
            "confidence": 0.5, # Start with medium confidence
            "count": 1, 
            "last_used": timestamp
        }
        self.memory["facts"][category].append(new_item)
        self.save_memory()
        return f"Remembered new fact: [{category}] {fact_text}"

    def learn_habit(self, trigger, action):
        timestamp = datetime.now().isoformat()
        for habit in self.memory["habits"]:
            if habit["trigger"] == trigger and habit["action"] == action:
                habit["count"] += 1
                habit["confidence"] = min(1.0, habit["confidence"] + 0.1)
                habit["last_used"] = timestamp
                self.save_memory()
                return f"Reinforced habit: When '{trigger}' -> Do '{action}' (Confidence: {habit['confidence']:.1f})"
        
        # New habit
        new_habit = {
            "trigger": trigger,
            "action": action,
            "confidence": 0.3, # Start low for habits
            "count": 1,
            "last_used": timestamp
        }
        self.memory["habits"].append(new_habit)
        self.save_memory()
        return f"Learned new habit: When '{trigger}' -> Do '{action}'"

    def update_phase(self, phase, description=None):
        self.memory["life_phases"]["current_phase"] = phase
        if description:
             self.memory["life_phases"]["goals"].append(f"Phase Goal: {description}")
        self.save_memory()
        return f"Updated Life Phase to: {phase}"

    def update_emotional_state(self, state, reason=None):
        timestamp = datetime.now().isoformat()
        
        # Initialize history if missing
        if "history" not in self.memory["emotional_context"]:
            self.memory["emotional_context"]["history"] = []
            
        # Add new entry
        entry = {
            "state": state,
            "timestamp": timestamp,
            "reason": reason or "User input"
        }
        self.memory["emotional_context"]["history"].append(entry)
        
        # Keep max 10
        if len(self.memory["emotional_context"]["history"]) > 10:
             self.memory["emotional_context"]["history"] = self.memory["emotional_context"]["history"][-10:]

        self.memory["emotional_context"]["last_interaction_mood"] = self.memory["emotional_context"].get("current_state", "Neutral")
        self.memory["emotional_context"]["current_state"] = state
        self.memory["emotional_context"]["last_updated"] = timestamp
        
        self.save_memory()
        return f"Emotional context updated to: {state} ({reason})"

    def decay_habits(self):
        """
        Reduces confidence of habits that haven't been used in a while.
        """
        if "habits" not in self.memory: return

        now = datetime.now()
        for habit in self.memory["habits"]:
            last_used_str = habit.get("last_used")
            if not last_used_str: continue
            
            try:
                last_used = datetime.fromisoformat(last_used_str)
                delta_days = (now - last_used).days
                
                # Decay logic
                if delta_days > 7:
                    # Reduce confidence by 0.05 per week of inactivity
                    decay_amount = 0.05 * (delta_days // 7)
                    original_conf = habit.get("confidence", 0.0)
                    habit["confidence"] = max(0.0, original_conf - decay_amount)
                    
                    if habit["confidence"] < original_conf:
                         pass # Debug log could go here
            except:
                pass
        self.save_memory()

    def forget_habit(self, trigger, action):
        """
        Explicitly removes or resets a habit based on user correction.
        """
        if "habits" not in self.memory: return "No habits found."
        
        # Normalize for comparison
        trigger = trigger.lower().strip()
        action = action.lower().strip()
        
        for i, habit in enumerate(self.memory["habits"]):
            h_trig = habit.get("trigger", "").lower().strip()
            h_act = habit.get("action", "").lower().strip()
            
            # Fuzzy or exact match? Let's try containment or exact.
            # User might say "Don't open chrome on start", stored might be "start" -> "open chrome"
            
            if (trigger in h_trig or h_trig in trigger) and (action in h_act or h_act in action):
                # Found it.
                # Remove it entirely or set confidence to 0?
                # Removal is cleaner for "Forget this".
                self.memory["habits"].pop(i)
                self.save_memory()
                return f"✅ Habit forgotten: When '{habit['trigger']}' -> '{habit['action']}'."
                
        return f"❌ Habit not found for trigger '{trigger}' and action '{action}'."

    def log_interaction(self, tool_name, description):
        """
        Logs a system interaction for context retention.
        Keeps the last 5 interactions.
        """
        if "recent_interactions" not in self.memory:
            self.memory["recent_interactions"] = []
            
        entry = {
            "timestamp": datetime.now().isoformat(),
            "tool": tool_name,
            "description": description
        }
        
        self.memory["recent_interactions"].append(entry)
        
        # Keep only last 5
        if len(self.memory["recent_interactions"]) > 5:
            self.memory["recent_interactions"] = self.memory["recent_interactions"][-5:]
            
        self.save_memory()

    def get_recent_interactions(self):
        """Returns the formatted list of recent interactions."""
        interactions = self.memory.get("recent_interactions", [])
        if not interactions:
            return "No recent activity."
            
        log_str = ""
        for i in interactions:
            try:
                dt = datetime.fromisoformat(i["timestamp"])
                time_str = dt.strftime("%H:%M")
                log_str += f"- ({time_str}) Used '{i['tool']}': {i['description']}\n"
            except:
                continue
        return log_str.strip()

    def get_predictions(self):
        """
        Analyzes recent interactions and time to predict the next likely action.
        Returns a list of prediction strings.
        """
        predictions = []
        if "habits" not in self.memory: return predictions
        
        # 1. Sequence Prediction (based on last tool used)
        if "recent_interactions" in self.memory and self.memory["recent_interactions"]:
            last_interaction = self.memory["recent_interactions"][-1]
            last_tool = last_interaction["tool"]
            
            # Find habits triggered by this tool/action
            # This is a bit loose, as habits are "trigger" -> "action" strings.
            # We check if the 'trigger' is related to the last tool.
            for habit in self.memory["habits"]:
                if last_tool in habit["trigger"].lower():
                    conf = habit.get("confidence", 0)
                    if conf > 0.5:
                        strength = "High" if conf > 0.75 else "Medium"
                        predictions.append(f"[{strength} Confidence] Since you just used '{last_tool}', you might want to '{habit['action']}'")

        # 2. Time Prediction
        now = datetime.now()
        hour = now.hour
        # Map hour to broad time context for matching
        time_triggers = []
        if 5 <= hour < 10: time_triggers.append("morning")
        if 18 <= hour < 22: time_triggers.append("evening")
        if hour >= 22 or hour < 2: time_triggers.append("night")
        
        for habit in self.memory["habits"]:
            trigger_lower = habit["trigger"].lower()
            for tt in time_triggers:
                if tt in trigger_lower:
                    conf = habit.get("confidence", 0)
                    if conf > 0.5:
                         strength = "High" if conf > 0.75 else "Medium"
                         predictions.append(f"[{strength} Confidence] It is '{tt}', usually you '{habit['action']}'")
                         
        return predictions

    # --- SCHEDULING & TASK MANAGEMENT ---

    def add_task(self, description, time_iso, energy="medium"):
        """Adds a new task to the schedule."""
        if "schedule" not in self.memory:
            self.memory["schedule"] = []
            
        import uuid
        task_id = str(uuid.uuid4())[:8]
        
        new_task = {
            "id": task_id,
            "description": description,
            "time": time_iso,
            "status": "pending",
            "energy": energy,
            "created_at": datetime.now().isoformat()
        }
        
        self.memory["schedule"].append(new_task)
        self.save_memory()
        return f"Scheduled: '{description}' at {time_iso} (ID: {task_id})"

    def get_scheduled_tasks(self, start_time=None, end_time=None):
        """Returns pending tasks within the time range."""
        if "schedule" not in self.memory: return []
        
        tasks = []
        # Simple string comparison works for ISO format if we are careful, 
        # but parsing is safer.
        for task in self.memory["schedule"]:
            if task["status"] != "pending": continue
            
            t_str = task["time"]
            if start_time and t_str < start_time: continue
            if end_time and t_str > end_time: continue
            
            tasks.append(task)
            
        # Sort by time
        tasks.sort(key=lambda x: x["time"])
        return tasks

    def check_conflicts(self, check_time_iso, duration_minutes=60):
        """Checks if a time slot overlaps with existing tasks."""
        if "schedule" not in self.memory: return []
        
        conflicts = []
        check_dt = datetime.fromisoformat(check_time_iso)
        
        # Define check window (assuming simple point check or default duration)
        # For simplicity, we flag if another task is within +/- 30 mins
        import math
        
        for task in self.memory["schedule"]:
            if task["status"] != "pending": continue
            
            try:
                task_dt = datetime.fromisoformat(task["time"])
                delta_minutes = abs((task_dt - check_dt).total_seconds()) / 60
                
                if delta_minutes < 30: # Conflict range
                    conflicts.append(task)
            except: 
                continue
                
        return conflicts

    def complete_task(self, task_description):
        """Marks a task as completed by fuzzy description match."""
        if "schedule" not in self.memory: return "No schedule."
        
        from fuzzywuzzy import process
        pending = [t for t in self.memory["schedule"] if t["status"] == "pending"]
        if not pending: return "No pending tasks."
        
        choices = [t["description"] for t in pending]
        best_match, score = process.extractOne(task_description, choices)
        
        if score > 70:
            for task in self.memory["schedule"]:
                if task["description"] == best_match and task["status"] == "pending":
                    task["status"] = "completed"
                    self.save_memory()
                    return f"✅ Marked as done: {best_match}"
        return "❌ Task not found."

    def reschedule_task(self, task_description, new_time_iso):
        """Reschedules a task by fuzzy description."""
        if "schedule" not in self.memory: return "No schedule."
        
        from fuzzywuzzy import process
        pending = [t for t in self.memory["schedule"] if t["status"] == "pending"]
        
        choices = [t["description"] for t in pending]
        if not choices: return "No pending tasks to reschedule."
        
        best_match, score = process.extractOne(task_description, choices)
        
        if score > 70:
            for task in self.memory["schedule"]:
                if task["description"] == best_match and task["status"] == "pending":
                    old_time = task["time"]
                    task["time"] = new_time_iso
                    self.save_memory()
                    return f"🗓️ Rescheduled '{best_match}': {old_time} -> {new_time_iso}"
        return "❌ Task not found."

    # --- MULTILINGUAL INTELLIGENCE ---
    
    def get_language_preference(self):
        """Returns the current language settings."""
        if "language_preferences" not in self.memory:
            self.memory["language_preferences"] = DEFAULT_MEMORY["language_preferences"]
        return self.memory["language_preferences"]

    def update_language_preference(self, primary=None, tone=None, mode=None):
        """Updates language settings."""
        if "language_preferences" not in self.memory:
            self.memory["language_preferences"] = DEFAULT_MEMORY["language_preferences"]
            
        if primary: self.memory["language_preferences"]["primary"] = primary
        if tone: self.memory["language_preferences"]["tone"] = tone
        if mode: self.memory["language_preferences"]["mode"] = mode
        
        self.save_memory()
        return f"Language settings updated: {self.memory['language_preferences']}"

    def get_formatted_context(self):
        """
        Returns a string representation of the memory for injection into LLM system prompt.
        Prioritizes high-confidence items and ADDS implicit context (Time, etc).
        """
        # Run decay check occasionally
        self.decay_habits()

        user = self.memory.get("user_profile", {})
        phases = self.memory.get("life_phases", {})
        facts = self.memory.get("facts", {})
        habits = self.memory.get("habits", [])
        mood = self.memory.get("emotional_context", {})
        emotional_profile = self.memory.get("emotional_profile", {})
        recent_log = self.get_recent_interactions()
        predictions = self.get_predictions()

        # --- Time Context Logic ---
        now = datetime.now()
        hour = now.hour
        time_str = now.strftime("%H:%M") 
        if 5 <= hour < 12:
            time_context = "Morning (Work/Start of day)"
        elif 12 <= hour < 17:
            time_context = "Afternoon (Deep work focus)"
        elif 17 <= hour < 21:
            time_context = "Evening (Wrap up/Relax)"
        elif 21 <= hour or hour < 5:
            time_context = "Late Night (Quiet/Creative or Sleep time)"
        else:
            time_context = "Unknown"
        
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        context = f"""
[CURRENT CONTEXT]
Time: {timestamp_str} ({time_context})
Emotional State: {mood.get('current_state', 'Neutral')} (Updated: {mood.get('last_updated', 'Unknown')})
Communication Style: {emotional_profile.get('communication_style', 'Adaptable')}
Last Active File: {self.get_active_file() or 'None'}

[RECENT ACTIVITY LOG]
{recent_log}

[UPCOMING SCHEDULE]
"""
        # Get next 3 tasks
        upcoming = self.get_scheduled_tasks()
        if upcoming:
             count = 0
             for task in upcoming:
                 if count >= 3: break
                 # Format properly
                 try:
                     dt = datetime.fromisoformat(task["time"])
                     nice_time = dt.strftime("%I:%M %p")
                     today_str = datetime.now().strftime("%Y-%m-%d")
                     day_str = "Today" if task["time"].startswith(today_str) else dt.strftime("%a")
                     
                     context += f"- [PENDING] {day_str} {nice_time}: {task['description']} (Energy: {task.get('energy','med')})\n"
                     count += 1
                 except: pass
        else:
            context += "(No upcoming tasks)\n"

        context += f"""
[PREDICTIVE INSIGHTS]
"""
        if predictions:
            for p in predictions:
                context += f"- {p}\n"
        else:
            context += "(No strong predictions)\n"

        context += f"""
[USER PROFILE]
Name: {user.get('name', 'User')}
Role: {user.get('role', 'User')}
Current Focus: {phases.get('current_phase', 'Unknown')} - {phases.get('description', '')}

[LONG TERM MEMORY]
"""
        # Add Facts
        for category, items in facts.items():
            if items:
                context += f"\n{category.upper()}:\n"
                for item in items:
                    # Handle both string (legacy) and dict (new)
                    if isinstance(item, str):
                        context += f"- {item}\n"
                    elif isinstance(item, dict):
                        text = item["text"]
                        if item.get("confidence", 0) < 0.5:
                            text += " (Unsure)"
                        context += f"- {text}\n"

        # Add Habits
        context += "\n[OBSERVED HABITS]\n"
        if habits:
            for habit in habits:
                conf = habit.get("confidence", 0)
                if conf > 0.4:
                    trigger_strength = "HIGH" if conf > 0.7 else "MEDIUM"
                    context += f"- [{trigger_strength}] When '{habit['trigger']}' -> Consider '{habit['action']}' (Conf: {conf:.2f})\n"
        else:
            context += "(No habits learned yet)\n"

        # --- Inject Dynamic Refinement Layer ---
        refinements = self.get_refinement_instructions()
        if refinements:
            context += f"\n[SYSTEM REFINEMENTS - DYNAMICALLY APPLIED]\n{refinements}\n"

        return context

    # --- ADVANCED EMOTIONAL INTELLIGENCE ---

    def update_emotional_profile(self, key, value):
        """Updates long-term emotional preference."""
        if "emotional_profile" not in self.memory:
            self.memory["emotional_profile"] = DEFAULT_MEMORY["emotional_profile"]
            
        self.memory["emotional_profile"][key] = value
        self.save_memory()
        return f"Emotional profile updated: {key} -> {value}"

    def get_emotional_profile(self):
        """Returns the emotional profile."""
        if "emotional_profile" not in self.memory:
            self.memory["emotional_profile"] = DEFAULT_MEMORY["emotional_profile"]
        return self.memory["emotional_profile"]
        
    def log_emotional_event(self, event_type, intensity="medium"):
        """Logs significant emotional moments."""
        if "emotional_profile" not in self.memory:
            self.memory["emotional_profile"] = DEFAULT_MEMORY["emotional_profile"]
            
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "intensity": intensity
        }
        self.memory["emotional_profile"]["emotional_history"].append(entry)
        
        # Keep last 20
        if len(self.memory["emotional_profile"]["emotional_history"]) > 20:
             self.memory["emotional_profile"]["emotional_history"] = self.memory["emotional_profile"]["emotional_history"][-20:]
             
        self.save_memory()

    # --- PROJECT MANAGEMENT ---

    def create_project(self, title, description, deadline=None):
        """Creates a new project container."""
        if "projects" not in self.memory:
            self.memory["projects"] = []
            
        import uuid
        project_id = str(uuid.uuid4())[:8]
        
        new_project = {
            "id": project_id,
            "title": title,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "deadline": deadline,
            "status": "active",
            "progress": 0,
            "tasks": []
        }
        
        self.memory["projects"].append(new_project)
        self.save_memory()
        return f"Created Project: '{title}' (ID: {project_id})"

    def add_project_task(self, project_title_or_id, description, dependency_task_id=None):
        """Adds a task to a specific project."""
        if "projects" not in self.memory: return "No projects found."
        
        # Find project
        target_project = None
        for p in self.memory["projects"]:
            if p["id"] == project_title_or_id or p["title"].lower() == project_title_or_id.lower():
                target_project = p
                break
        
        if not target_project:
            return f"❌ Project '{project_title_or_id}' not found."
            
        import uuid
        task_id = str(uuid.uuid4())[:8]
        
        new_task = {
            "id": task_id,
            "description": description,
            "status": "pending",
            "dependencies": [dependency_task_id] if dependency_task_id else [],
            "created_at": datetime.now().isoformat()
        }
        
        target_project["tasks"].append(new_task)
        self.update_project_progress(target_project)
        self.save_memory()
        
        return f"Added task to '{target_project['title']}': {description}"

    def update_project_task_status(self, project_title, task_description, status):
        """Updates a task status within a project."""
        if "projects" not in self.memory: return "No projects found."
        
        from fuzzywuzzy import process
        
        # Find project
        target_project = None
        for p in self.memory["projects"]:
            if project_title.lower() in p["title"].lower():
                target_project = p
                break
        
        if not target_project: return f"❌ Project '{project_title}' not found."
        
        # Find task
        pending_tasks = [t for t in target_project["tasks"]]
        choices = [t["description"] for t in pending_tasks]
        
        best_match, score = process.extractOne(task_description, choices)
        if score > 70:
            for task in target_project["tasks"]:
                if task["description"] == best_match:
                    task["status"] = status
                    self.update_project_progress(target_project)
                    self.save_memory()
                    return f"✅ Updated '{target_project['title']}': '{best_match}' is now {status}."
        
        return f"❌ Task '{task_description}' not found in project '{target_project['title']}'."

    def update_project_progress(self, project):
        """Recalculates progress percentage."""
        total = len(project["tasks"])
        if total == 0:
            project["progress"] = 0
            return
            
        completed = sum(1 for t in project["tasks"] if t["status"] == "completed" or t["status"] == "done")
        project["progress"] = int((completed / total) * 100)
    
    def get_projects_summary(self):
        """Returns a summary of active projects."""
        if "projects" not in self.memory or not self.memory["projects"]:
            return "No active projects."
            
        summary = ""
        for p in self.memory["projects"]:
            if p["status"] != "active": continue
            
            summary += f"📂 {p['title']} ({p['progress']}% Complete)\n"
            # Get next pending task
            pending = [t for t in p["tasks"] if t["status"] == "pending"]
            if pending:
                summary += f"   Next: {pending[0]['description']}\n"
            else:
                summary += "   (All tasks completed)\n"
                
        return summary

    # --- Environment Control Methods ---
    def get_active_mode(self):
        return self.memory.get("environment_modes", {}).get("active_mode", "normal")

    def set_active_mode(self, mode_name):
        modes = self.memory.get("environment_modes", {})
        modes["last_mode"] = modes.get("active_mode", "normal")
        modes["active_mode"] = mode_name
        self.memory["environment_modes"] = modes
        self._save()

    def get_mode_preferences(self, mode_name):
        return self.memory.get("environment_modes", {}).get("preferences", {}).get(mode_name, {})

    def update_mode_preference(self, mode_name, setting, value):
        modes = self.memory.get("environment_modes", {})
        if "preferences" not in modes: modes["preferences"] = {}
        if mode_name not in modes["preferences"]: modes["preferences"][mode_name] = {}
        
        modes["preferences"][mode_name][setting] = value
        self.memory["environment_modes"] = modes
        self._save()

    # --- BEHAVIORAL LEARNING ---

    def log_tool_usage(self, tool_name, success: bool, failure_reason=None):
        """Logs the reliability of a tool."""
        if "behavioral_learning" not in self.memory:
            self.memory["behavioral_learning"] = DEFAULT_MEMORY["behavioral_learning"]
            
        stats = self.memory["behavioral_learning"]["tool_stats"]
        if tool_name not in stats:
            stats[tool_name] = {"success": 0, "failure": 0, "last_failure_reason": None}
            
        if success:
            stats[tool_name]["success"] += 1
        else:
            stats[tool_name]["failure"] += 1
            stats[tool_name]["last_failure_reason"] = failure_reason
            
        self.save_memory()

    def record_correction(self, trigger, correction):
        """Records a user correction."""
        if "behavioral_learning" not in self.memory:
            self.memory["behavioral_learning"] = DEFAULT_MEMORY["behavioral_learning"]
            
        entry = {
            "trigger": trigger,
            "correction": correction,
            "timestamp": datetime.now().isoformat()
        }
        self.memory["behavioral_learning"]["corrections"].append(entry)
        
        # Keep last 20
        if len(self.memory["behavioral_learning"]["corrections"]) > 20:
             self.memory["behavioral_learning"]["corrections"] = self.memory["behavioral_learning"]["corrections"][-20:]
             
        self.save_memory()
        return f"Start learning from mistake: '{trigger}' -> '{correction}'"

    def get_learning_summary(self):
        """Returns a summary of learned behaviors."""
        data = self.memory.get("behavioral_learning", {})
        stats = data.get("tool_stats", {})
        corrections = data.get("corrections", [])
        
        summary = "[LEARNED BEHAVIORS]\n"
        
        # 1. Unreliable Tools
        problematic_tools = []
        for tool, metrics in stats.items():
            total = metrics["success"] + metrics["failure"]
            if total > 0:
                fail_rate = metrics["failure"] / total
                if fail_rate > 0.3: # >30% fail rate
                    problematic_tools.append(f"{tool} (Fail Rate: {int(fail_rate*100)}%)")
        
        if problematic_tools:
            summary += f"⚠ Unreliable Tools (Use Caution): {', '.join(problematic_tools)}\n"
            
        # 2. Recent Corrections
        if corrections:
            summary += "Recent Corrections:\n"
            for c in corrections[-3:]:
                 summary += f"- {c['trigger']} -> {c['correction']}\n"
        else:
            pass
            
        return summary
        
    def get_refinement_instructions(self):
        """
        Calculates dynamic instructions based on learning history.
        This alters execution confidence and retry behavior without touching core prompts.
        """
        refinements = []
        
        # 1. Tool Failures (Retry Buffer)
        data = self.memory.get("behavioral_learning", {})
        stats = data.get("tool_stats", {})
        problematic_tools = []
        for tool, metrics in stats.items():
            total = metrics["success"] + metrics["failure"]
            if total > 0 and (metrics["failure"] / total) > 0.3:
                 problematic_tools.append(tool)
        
        if problematic_tools:
            tools_str = ", ".join(problematic_tools)
            refinements.append(f"- ⚠️ UNSTABLE TOOLS DETECTED: {tools_str}. If these tools fail, apply a +2s backoff delay before retrying.")

        # 2. Frequent Corrections (Verification Strictness)
        corrections = data.get("corrections", [])
        if len(corrections) > 2:
            # Simple check for recent corrections (last 5 items)
            refinements.append("- 🛑 STRICTNESS LEVEL: HIGH. The user has explicitly corrected your behavior recently. You MUST verify intent before executing complex or risky actions.")
        
        # 3. Communication Style (Verbosity)
        style = self.memory.get("user_profile", {}).get("communication_style", "").lower()
        if "direct" in style or "concise" in style:
            refinements.append("- ⚡ OUTPUT VERBOSITY: LOW. Execute directly. Do not over-explain or summarize unless explicitly asked by the user.")
            
        if not refinements:
            return ""
            
        return "\n".join(refinements)
        
    # --- PROACTIVE WORKFLOW AUTOMATION ---
    
    def save_workflow(self, name: str, trigger: str, steps: list, conditions: str = None, requires_confirmation: bool = True):
        """Saves a multi-step workflow into memory."""
        if "workflows" not in self.memory:
            self.memory["workflows"] = {}
            
        self.memory["workflows"][name.lower().strip()] = {
            "name": name,
            "trigger": trigger,
            "steps": steps,
            "conditions": conditions,
            "requires_confirmation": requires_confirmation,
            "created_at": datetime.now().isoformat()
        }
        self.save_memory()
        return f"Workflow '{name}' saved successfully with {len(steps)} steps."
        
    def get_workflow(self, name: str):
        """Retrieves a workflow by name."""
        return self.memory.get("workflows", {}).get(name.lower().strip())
        
    def list_workflows(self):
        """Returns a formatted list of all saved workflows."""
        workflows = self.memory.get("workflows", {})
        if not workflows:
            return "No workflows currently defined."
            
        summary = "Available Workflows:\n"
        for key, wf in workflows.items():
            trigger_text = f" (Trigger: '{wf['trigger']}')" if wf.get('trigger') else ""
            summary += f"- **{wf['name']}**{trigger_text}: {len(wf['steps'])} steps\n"
        return summary

    
# Global instance
memory = MemoryStore()
