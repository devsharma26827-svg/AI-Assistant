import os
import json
import logging
import asyncio
from livekit.agents import function_tool
import google.generativeai as genai
from gemini_key_manager import gemini_key_manager
from dotenv import load_dotenv

logger = logging.getLogger("project_generator")
logger.setLevel(logging.INFO)

load_dotenv(".env")
load_dotenv(".env.local")

@function_tool
async def generate_full_project(project_name: str, project_type: str, description: str, tech_stack: str = "") -> str:
    """
    Generates a complete, multi-file software project (website, webapp, backend, etc.) and saves it to a folder on the Desktop.
    DO NOT use this tool for single-file scripts or small snippets (use write_code instead).
    
    Arguments:
    - project_name: Name of the project (no spaces, e.g., "my_awesome_app").
    - project_type: e.g., "website", "webapp", "backend", "fullstack".
    - description: Detailed instructions on what the application should do.
    - tech_stack: Exact frameworks/languages to use (e.g., "React, Node.js, Tailwind").
    """
    logger.info(f"Generating full project: {project_name} ({project_type})")
    
    if not gemini_key_manager.api_keys or gemini_key_manager.api_keys == [""]:
        return "❌ Error: No GEMINI_API_KEY found in environment variables."

    # Internal blocking function for GenAI and Disk IO
    def _generate_and_write():
        try:
            desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
            base_dir = os.path.join(desktop_path, project_name.replace(" ", "_"))
            
            # Handle duplicates
            counter = 1
            final_dir = base_dir
            while os.path.exists(final_dir):
                final_dir = f"{base_dir}_{counter}"
                counter += 1
                
            prompt = f"""
            You are a senior software architect and developer.
            Task: Create a complete, production-ready, multi-file software project.
            
            Project Name: {project_name}
            Type: {project_type}
            Tech Stack: {tech_stack if tech_stack else 'Use modern, standard choices for this type'}
            Description: {description}
            
            STRICT RULES:
            1. Create a professional, modular project structure.
            2. Write clean, modern, production-ready code. Do NOT provide placeholder or demo-level code.
            3. Ensure responsive UI and proper formatting (if frontend).
            4. MUST include a comprehensive README.md with setup, run, and deployment instructions.
            5. Return the output EXACTLY as a single, valid JSON object where Keys are the relative file paths and Values are the raw file contents (as strings). Do not use markdown wrappers around the JSON.
            
            JSON FORMAT EXAMPLE:
            {{
              "index.html": "<html content>",
              "css/style.css": "<css content>",
              "js/app.js": "<js content>",
              "README.md": "<markdown>"
            }}
            """
            
            def _api_call(active_key, model_name):
                genai.configure(api_key=active_key)
                model = genai.GenerativeModel(model_name)
                return model.generate_content(
                    prompt,
                    generation_config=genai.GenerationConfig(
                        response_mime_type="application/json"
                    )
                )

            response = gemini_key_manager.execute_with_retry(_api_call, max_retries_per_key=1)
            
            files_dict = json.loads(response.text)
            
            # Write to disk
            os.makedirs(final_dir, exist_ok=True)
            files_created = []
            
            for rel_path, content in files_dict.items():
                full_path = os.path.join(final_dir, rel_path)
                
                # Make nested directories if needed
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                files_created.append(rel_path)
                
            return {
                "status": "success",
                "folder": final_dir,
                "file_count": len(files_created),
                "files": files_created
            }
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON Parsing Error: {e}, Response: {response.text[:200]}")
            return {"status": "error", "message": "Failed to parse AI output into files. The project was too complex or malformed."}
        except Exception as e:
            logger.error(f"Project Generation Error: {e}")
            return {"status": "error", "message": str(e)}

    # Offload the entire blocking operation
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _generate_and_write)
        
        if result["status"] == "success":
            summary = (
                f"✅ Project '{project_name}' created successfully!\n"
                f"📂 Saved to: {result['folder']}\n"
                f"📝 Files generated ({result['file_count']}): {', '.join(result['files'][:5])}"
            )
            if result['file_count'] > 5:
                summary += "..."
            return summary
        else:
            return f"❌ Failed to generate project: {result['message']}"
            
    except Exception as e:
        return f"❌ System error during project generation: {e}"
