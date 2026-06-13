import logging
import os
import matplotlib.pyplot as plt
import pandas as pd
from datetime import datetime
import asyncio
from livekit.agents import function_tool
from memory_store import MemoryStore

logger = logging.getLogger("visualization_tools")
logger.setLevel(logging.INFO)

memory = MemoryStore()

VIS_DIR = "visualizations"
if not os.path.exists(VIS_DIR):
    os.makedirs(VIS_DIR)

def _save_plot(title, export_pdf=False):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_title = title.replace(' ', '_').replace('/', '-')
    
    filename_png = f"{sanitized_title}_{timestamp}.png"
    filepath_png = os.path.join(VIS_DIR, filename_png)
    plt.tight_layout()
    plt.savefig(filepath_png, dpi=300)
    
    returned_path = os.path.abspath(filepath_png)
    
    if export_pdf:
        filename_pdf = f"{sanitized_title}_{timestamp}.pdf"
        filepath_pdf = os.path.join(VIS_DIR, filename_pdf)
        plt.savefig(filepath_pdf, format="pdf", bbox_inches="tight")
        returned_path += f" (and {os.path.abspath(filepath_pdf)})"
        
    plt.close()
    return returned_path

@function_tool
async def generate_visual_report(report_type: str, project_name: str = None, chart_type: str = "bar", data: dict = None, title: str = "Chart", export_pdf: bool = False) -> str:
    """
    Generates visual reports.
    
    Arguments:
    - report_type: "project_status", "habit_strength", "productivity", "weekly_performance", "custom"
    - export_pdf: Set to True to generate a PDF export in addition to the PNG.
    
    For "project_status":
      - project_name: Name of the project
      
    For "custom":
      - chart_type: "bar", "line", "pie", "timeline", "heatmap"
      - data: Dictionary of values. For timeline/heatmap, data format varies.
      - title: Chart title
    """
    
    # Inner sync function to offload
    def _generate_impl():
        try:
            if report_type == "project_status":
                 if not project_name: return "❌ Project name required."
                 # Fetch project
                 projects = memory.memory.get("projects", [])
                 target = next((p for p in projects if p["title"].lower() == project_name.lower()), None)
                 if not target: return f"❌ Project '{project_name}' not found."
                 tasks = target.get("tasks", [])
                 status_counts = {"pending": 0, "completed": 0, "active": 0}
                 for t in tasks:
                    s = t.get("status", "pending")
                    status_counts[s] = status_counts.get(s, 0) + 1
                 plt.figure(figsize=(8, 6))
                 plt.bar(status_counts.keys(), status_counts.values(), color=['orange', 'green', 'blue'])
                 plt.title(f"Project Status: {target['title']}")
                 path = _save_plot(f"Project_{target['title']}")
                 return f"✅ Project Chart generated: {path}"
                 
            elif report_type == "habit_strength":
                 habits = memory.memory.get("habits", [])
                 if not habits: return "❌ No habits."
                 labels = [f"{h['trigger'][:10]}..." for h in habits]
                 confidences = [h.get("confidence", 0) for h in habits]
                 plt.figure(figsize=(10, 6))
                 plt.barh(labels, confidences, color='purple')
                 plt.title("Habit Strength")
                 path = _save_plot("Habit_Strength")
                 return f"✅ Habit Chart generated: {path}"
                 
            elif report_type == "productivity":
                 tasks = memory.memory.get("schedule", [])
                 energy_counts = {"high": 0, "medium": 0, "low": 0}
                 for t in tasks:
                    e = t.get("energy", "medium").lower()
                    energy_counts[e] = energy_counts.get(e, 0) + 1
                 plt.figure(figsize=(8, 6))
                 plt.pie(energy_counts.values(), labels=energy_counts.keys(), autopct='%1.1f%%')
                 plt.title("Task Energy")
                 path = _save_plot("Productivity_Energy", export_pdf)
                 return f"✅ Productivity Chart generated: {path}"
                 
            elif report_type == "weekly_performance":
                 logs = memory.get_recent_interactions(limit=100)
                 if "No recent interactions" in logs:
                     return "❌ Not enough data for weekly performance."
                 
                 # Basic mock logic parsing the string log to get counts per day
                 # In a real scenario, this would read structured data. Wait, let's use schedule instead for a cleaner metric.
                 tasks = memory.memory.get("schedule", [])
                 completed_tasks = [t for t in tasks if t.get("status") == "completed"]
                 
                 # Group by day
                 from collections import defaultdict
                 day_counts = defaultdict(int)
                 for t in completed_tasks:
                     try:
                         # Attempt to parse time to date
                         dt = datetime.fromisoformat(t["time"])
                         day_counts[dt.strftime("%A")] += 1
                     except:
                         pass
                 
                 if not day_counts:
                     return "❌ No completed tasks found to generate weekly performance."
                     
                 plt.figure(figsize=(10, 6))
                 plt.bar(list(day_counts.keys()), list(day_counts.values()), color='teal')
                 plt.title("Weekly Task Performance")
                 plt.ylabel("Tasks Completed")
                 path = _save_plot("Weekly_Performance", export_pdf)
                 return f"✅ Weekly Performance generated: {path}"
                 
            elif report_type == "custom":
                 if not data: return "❌ Data required for custom chart."
                 plt.figure(figsize=(10, 6))
                 
                 if chart_type == "line": 
                     plt.plot(list(data.keys()), list(data.values()), marker='o')
                 elif chart_type == "pie": 
                     plt.pie(list(data.values()), labels=list(data.keys()), autopct='%1.1f%%')
                 elif chart_type == "timeline":
                     # Expects data: {"Task A": {"start": 0, "duration": 5}, ...}
                     import numpy as np
                     labels = list(data.keys())
                     starts = [v.get("start", 0) for v in data.values()]
                     durations = [v.get("duration", 1) for v in data.values()]
                     plt.barh(labels, durations, left=starts, color='skyblue')
                     plt.xlabel("Time units")
                 elif chart_type == "heatmap":
                     # Basic mock heatmap using imshow. data is a list of lists or 2D dict.
                     import numpy as np
                     if isinstance(data, list):
                         matrix = np.array(data)
                         plt.imshow(matrix, cmap='YlOrRd', aspect='auto')
                         plt.colorbar(label='Intensity')
                     else:
                         return "❌ Heatmap requires data to be a 2D list/matrix."
                 else: 
                     plt.bar(list(data.keys()), list(data.values()))
                     
                 plt.title(title)
                 path = _save_plot(title, export_pdf)
                 return f"✅ Custom Chart generated: {path}"
                 
            return f"❌ Unknown report type: {report_type}"
            
        except Exception as e:
            return f"❌ Error generating report: {e}"

    # Offload the entire blocking operation
    return await asyncio.to_thread(_generate_impl)
