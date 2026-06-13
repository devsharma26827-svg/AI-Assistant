import os
import requests
import logging
import asyncio
from livekit.agents import function_tool
from dotenv import load_dotenv
from memory_store import memory

# Initialize Logging
logger = logging.getLogger("serp_search")

# Load env vars
load_dotenv(".env") 
load_dotenv(".env.local", override=True)

@function_tool
async def serp_search(query: str) -> str:
    """
    Performs a real-time web search using SerpAPI.
    Use this for:
    - Current news/events
    - Fact-checking
    - Finding documentation or libraries
    - Looking up websites
    
    Arguments:
    - query: The search string.
    """
    try:
        api_key = os.getenv("SERPAPI_API_KEY")

        if not api_key:
             return "❌ Configuration Error: Missing SERPAPI_API_KEY in .env.local."
             
        url = "https://serpapi.com/search"
        params = {
            "engine": "google",
            "q": query,
            "api_key": api_key,
            "num": 5
        }

        logger.info(f"Searching SerpAPI for: {query}")
        
        try:
            # Offload blocking request
            response = await asyncio.to_thread(requests.get, url, params=params, timeout=15)
            
            if response.status_code == 403:
                logger.error("SerpAPI Key Invalid or Quota Exceeded (403).")
                return "❌ SerpAPI Error: Invalid Key or Quota Exceeded."
            
            if response.status_code != 200:
                logger.error(f"SerpAPI Failed with status: {response.status_code}")
                return f"❌ SerpAPI Error: Status {response.status_code}"

            data = response.json()
            
            # Check for errors in response body
            if "error" in data:
                return f"❌ SerpAPI Error: {data['error']}"

            organic_results = data.get("organic_results", [])
            
            if not organic_results:
                return f"⚠️ No results found for '{query}'."

            # Format Results
            result_text = f"🔍 **SerpAPI Search Results for '{query}'**:\n\n"
            for item in organic_results:
                title = item.get("title", "No Title")
                snippet = item.get("snippet", "No Snippet")
                link = item.get("link", "#")
                result_text += f"1. **[{title}]({link})**\n   - {snippet}\n\n"

            # Log Interaction
            memory.log_interaction("serp_search", f"Searched for: {query}")

            return result_text.strip()

        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error during SerpAPI request: {e}")
            return f"❌ Network Error: {e}"
            
    except Exception as e:
        logger.error(f"Critical Error in serp_search: {e}")
        return f"❌ Critical Error: {e}"

@function_tool
async def get_current_datetime() -> str:
    """
    Returns the current date and time in India Standard Time (IST).
    Use this tool when the user asks for the current time, date, or wants to know what day it is.
    Always returns correct IST time regardless of system locale.
    """
    try:
        from datetime import datetime, timezone, timedelta
        # India Standard Time = UTC + 5:30
        IST = timezone(timedelta(hours=5, minutes=30))
        now = datetime.now(IST)
        day_name = now.strftime("%A")         # e.g. Wednesday
        date_str = now.strftime("%d %B %Y")  # e.g. 19 March 2026
        time_str = now.strftime("%I:%M %p")  # e.g. 09:46 AM
        return f"{day_name}, {date_str} — {time_str} IST"
    except Exception as e:
        return f"Error getting time: {e}"
