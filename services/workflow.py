import logging
from livekit.agents import function_tool
from src.memory_store import memory

logger = logging.getLogger("workflow_tools")
logger.setLevel(logging.INFO)

@function_tool
async def create_workflow(name: str, trigger_phrase: str, steps: str, conditions: str = None, requires_confirmation: bool = True) -> str:
    """
    Creates or updates a customized multi-step workflow.
    
    Arguments:
    - name: A short, simple name (e.g., "Morning Setup", "Coding Mode").
    - trigger_phrase: The natural phrase that triggers this (e.g., "good morning", "start working").
    - steps: A comma-separated list of actions (e.g., "open whatsapp, check emails, open vscode").
    - conditions: Time or context conditions (e.g., "morning only").
    - requires_confirmation: True to ask before running, False for full auto.
    """
    try:
        # Parse steps
        step_list = [s.strip() for s in steps.split(',') if s.strip()]
        if not step_list:
            return "❌ At least one step is required to build a workflow."
            
        return memory.save_workflow(name, trigger_phrase, step_list, conditions, requires_confirmation)
    except Exception as e:
        logger.error(f"Error creating workflow: {e}")
        return f"❌ Failed to create workflow: {e}"

@function_tool
async def list_workflows() -> str:
    """
    Lists all available proactive workflows.
    Use this to see what automated routines the user has setup.
    """
    return memory.list_workflows()

@function_tool
async def trigger_workflow(name: str) -> str:
    """
    Loads a specific workflow so the agent can execute its steps.
    Use this when the user says "Run Morning Setup" or triggers a routine.
    
    Arguments:
    - name: The name of the workflow or the trigger phrase.
    """
    try:
        # First try exact name
        wf = memory.get_workflow(name)
        
        # Fallback to trigger phrase matching if name wasn't exact
        if not wf:
             workflows = memory.memory.get("workflows", {})
             for k, v in workflows.items():
                 if name.lower() in v.get("trigger", "").lower() or name.lower() in v.get("name", "").lower():
                     wf = v
                     break
                     
        if not wf:
             return f"❌ Workflow '{name}' not found. Check list_workflows() to see what's available."
             
        # FORMAT THE LLM EXECUTION INSTRUCTION
        steps_text = "\n".join([f"{i+1}. {step}" for i, step in enumerate(wf['steps'])])
        
        confirmation_rule = ""
        if wf.get('requires_confirmation', True):
             confirmation_rule = "🚨 CRITICAL: You MUST ask the user for confirmation ('Are you sure you want to run this?') BEFORE executing these steps! Do not proceed until they say yes."
        else:
             confirmation_rule = "This workflow is set to auto-execute. You may begin the steps using your tools immediately."
             
        instruction = f"""
✅ Workflow '{wf['name']}' Loaded.
STEPS TO EXECUTE:
{steps_text}

{confirmation_rule}

INSTRUCTIONS FOR YOU (THE AI):
If approved, execute EACH step sequentially using the appropriate function tools (e.g., open_app, whatsapp_message). 
- Wait for each tool to finish before running the next.
- If a step fails significantly, abort the workflow and tell the user.
- Provide a final summary only after all steps are complete or the workflow is aborted.
"""
        return instruction
        
    except Exception as e:
        logger.error(f"Error triggering workflow: {e}")
        return f"❌ Failed to load workflow: {e}"
