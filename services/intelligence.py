from livekit.agents import function_tool
from src.memory_store import memory
import logging
import asyncio
import threading

logger = logging.getLogger(__name__)

# Global lock to prevent race conditions during file writes
_memory_lock = threading.Lock()

@function_tool
async def remember_fact(category: str, fact: str) -> str:
    """
    Stores a new fact or reinforces an existing one.
    Use this when the user explicitly states a preference, goal, or life event.
    Repeated calls for the same fact will increase its confidence score.
    
    Args:
        category: The category of the fact (e.g., 'hobbies', 'work', 'health', 'goals').
        fact: The specific detail to remember (e.g., 'User likes dark mode', 'User is learning Rust').
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _remember_fact_impl, category, fact)
    except Exception as e:
        return f"Failed to store memory: {e}"

def _remember_fact_impl(category: str, fact: str) -> str:
    with _memory_lock:
        logger.info(f"Remembering/Reinforcing: [{category}] {fact}")
        return memory.add_fact(category, fact)

@function_tool
async def learn_habit(trigger: str, action: str) -> str:
    """
    Records a detected habit or pattern.
    Use this when you observe the user doing the same thing repeatedly in response to a situation.
    
    Args:
        trigger: The situation or command that triggers the habit (e.g., 'User says "Build"').
        action: The action the user expects or takes (e.g., 'Run build.bat').
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _learn_habit_impl, trigger, action)
    except Exception as e:
        return f"Failed to learn habit: {e}"

def _learn_habit_impl(trigger: str, action: str) -> str:
    with _memory_lock:
        logger.info(f"Learning habit: {trigger} -> {action}")
        return memory.learn_habit(trigger, action)

@function_tool
async def update_emotional_state(state: str, reason: str = "") -> str:
    """
    Updates the assistant's understanding of the user's current emotional state.
    Use this when the user's tone or words indicate a specific mood (e.g., 'stressed', 'happy', 'excited').
    
    Args:
        state: The detected emotional state (e.g., 'Stressed', 'Focused', 'Relaxed').
        reason: Optional context or specific words that indicated this state.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _update_emotional_state_impl, state, reason)
    except Exception as e:
        return f"Failed to update emotional state: {e}"

def _update_emotional_state_impl(state: str, reason: str) -> str:
    with _memory_lock:
        logger.info(f"Updating emotional state to: {state} ({reason})")
        return memory.update_emotional_state(state, reason)

@function_tool
async def update_life_phase(phase: str, description: str = "") -> str:
    """
    Updates the current life phase or major focus area of the user.
    Use this when the user mentions a new job, project, or major life change.
    
    Args:
        phase: The name of the new phase (e.g., 'Job Hunting', 'Building Startup').
        description: Optional details about this phase.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _update_life_phase_impl, phase, description)
    except Exception as e:
        return f"Failed to update life phase: {e}"

def _update_life_phase_impl(phase: str, description: str) -> str:
    with _memory_lock:
        logger.info(f"Updating life phase: {phase}")
        return memory.update_phase(phase, description)

@function_tool
async def get_user_context() -> str:
    """
    Retrieves the current user context and memory summary.
    Useful if the assistant needs to refresh its understanding of the user.
    """
    # Reads usually don't need strict locking if just reading a dict loaded in memory,
    # but memory_store might access file. To be safe/consistent:
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _get_user_context_impl)
    except Exception as e:
        return f"Failed to retrieve context: {e}"

def _get_user_context_impl() -> str:
    return memory.get_formatted_context()

@function_tool
async def forget_habit(trigger: str, action: str) -> str:
    """
    Removes a habit from memory. Use this when the user says "Ye meri aadat nahi hai" or "Stop doing this".
    
    Arguments:
    - trigger: The situation/command (e.g., "start", "morning").
    - action: The action the assistant incorrectly learned (e.g., "open chrome", "play music").
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _forget_habit_impl, trigger, action)
    except Exception as e:
        return f"Failed to forget habit: {e}"

def _forget_habit_impl(trigger: str, action: str) -> str:
    with _memory_lock:
        return memory.forget_habit(trigger, action)

@function_tool
async def set_communication_style(style: str) -> str:
    """
    Sets the assistant's communication style / emotional mode.
    Use this when user says "Be direct", "Be supportive", "Normal mode", etc.
    
    Arguments:
    - style: 'direct' (short, no fluff), 'supportive' (encouraging), 'neutral' (default), 'formal'.
    """
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _set_communication_style_impl, style)
    except Exception as e:
        return f"Failed to set style: {e}"

def _set_communication_style_impl(style: str) -> str:
    with _memory_lock:
        style = style.lower()
        valid_styles = ["direct", "supportive", "neutral", "formal", "adaptable"]
        if style not in valid_styles:
            style = "adaptable"
            
        memory.update_emotional_profile("communication_style", style)
        return f"✅ Communication style set to: {style}"
