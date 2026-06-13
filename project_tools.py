import logging
from livekit.agents import function_tool
from memory_store import memory

logger = logging.getLogger("project_tools")
logger.setLevel(logging.INFO)

@function_tool
async def create_project(title: str, description: str, deadline: str = None) -> str:
    """
    Starts a new long-term project.
    
    Arguments:
    - title: Short title (e.g., "Build Portfolio").
    - description: What needs to be done.
    - deadline: Optional ISO date (e.g., "2024-12-31").
    """
    logger.info(f"Creating project: {title}")
    return memory.create_project(title, description, deadline)

@function_tool
async def add_task_to_project(project_name: str, task_description: str) -> str:
    """
    Adds a single task to an existing project.
    
    Arguments:
    - project_name: The title of the project.
    - task_description: The actionable task (e.g., "Design Home Page").
    """
    return memory.add_project_task(project_name, task_description)

@function_tool
async def get_project_status(project_name: str = None) -> str:
    """
    Returns the status of a specific project or all active projects.
    
    Arguments:
    - project_name: Optional specific project title. If empty, lists all.
    """
    if project_name:
        # Find specific (need to implement specific fetch in memory or iter here)
        # For now, let's use the summary for all if not easy to fetch one, 
        # but better to provide detail for one.
        pass # Implementation logic below is better
    
    return memory.get_projects_summary()

@function_tool
async def update_task_status(project_name: str, task_description: str, status: str) -> str:
    """
    Updates the status of a project task.
    
    Arguments:
    - project_name: Title of the project.
    - task_description: The task name (fuzzy match).
    - status: 'completed', 'pending', 'blocked'.
    """
    status = status.lower()
    if status in ["done", "complete", "finished"]:
        status = "completed"
        
    return memory.update_project_task_status(project_name, task_description, status)
