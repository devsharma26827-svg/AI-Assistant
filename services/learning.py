import logging
from livekit.agents import function_tool
from src.memory_store import MemoryStore

logger = logging.getLogger("learning_tools")
logger.setLevel(logging.INFO)

memory = MemoryStore()

@function_tool
async def manage_self_learning(action: str, tool_name: str = None, outcome: str = None, details: str = None, category: str = None, key: str = None, value: str = None) -> str:
    """
    Manages self-learning capabilities.
    
    Arguments:
    - action: "log_outcome", "get_summary", "save_preference"
    
    For "log_outcome":
      - tool_name: Name of tool used.
      - outcome: "success", "failure", "correction"
      - details: Reason for failure/correction
      
    For "save_preference":
      - category: Preference category (e.g. "contacts")
      - key: Item key
      - value: Preference value
    """
    try:
        if action == "log_outcome":
            if not tool_name or not outcome:
                return "❌ Tool name and outcome required for log_outcome."
            
            outcome = outcome.lower().strip()
            if outcome == "correction":
                 memory.log_tool_usage(tool_name, False, "User Corrected")
                 memory.record_correction(f"Used {tool_name}", details or "Correction")
                 return f"✅ Recorded correction for {tool_name}."
            elif outcome == "failure":
                 memory.log_tool_usage(tool_name, False, details)
                 return f"✅ Logged failure for {tool_name}."
            elif outcome == "success":
                 memory.log_tool_usage(tool_name, True)
                 return f"✅ Logged success for {tool_name}."
                 
        elif action == "get_summary":
            return memory.get_learning_summary()
            
        elif action == "save_preference":
            if not category or not key or not value:
                return "❌ Category, key, and value required for save_preference."
            
            # Direct memory access for now
            mem_data = memory.memory
            if "behavioral_learning" not in mem_data:
                return "❌ Memory not initialized."
            if "parameter_preferences" not in mem_data["behavioral_learning"]:
                mem_data["behavioral_learning"]["parameter_preferences"] = {}
            if category not in mem_data["behavioral_learning"]["parameter_preferences"]:
                mem_data["behavioral_learning"]["parameter_preferences"][category] = {}
                
            mem_data["behavioral_learning"]["parameter_preferences"][category][key] = value
            memory.save_memory()
            return f"✅ Learned preference: [{category}] {key} = {value}"
            
        return f"❌ Unknown action: {action}"
        
    except Exception as e:
        return f"❌ Error in self-learning: {e}"
