import os
import asyncio
import requests
import logging
from dotenv import load_dotenv
from livekit.agents import function_tool  # ✅ Correct decorator
from langchain.tools import tool

load_dotenv()


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_current_city():
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: requests.get("https://ipinfo.io", timeout=5)
        )
        data = response.json()
        return data.get("city", "Unknown")
    except Exception as e:
        logger.warning(f"get_current_city failed: {e}")
        return "Unknown"

@function_tool
async def get_weather(city: str = "") -> str:

    """
    Gives current weather information for a given city.

    Use this tool when the user asks about weather, rain, temperature, humidity, or wind.
    If no city is given, detect city automatically.

    Example prompts:
    - "आज का मौसम कैसा है?"
    - "Weather बताओ Bangalore का"
    - "क्या बारिश होगी मुंबई में?"
    """


    
    api_key = os.getenv("OPENWEATHER_API_KEY")

    if not api_key:
        logger.error("OpenWeather API key missing.")
        return "❌ Environment variables mein OpenWeather API key nahi mili. Kripya .env.local mein OPENWEATHER_API_KEY add karein."

    if not city or city.lower() == "unknown":
        city = await get_current_city()
        if not city or city.lower() == "unknown":
            return "❌ City automatically detect nahi ho saki. Kripya city ka naam bataiye (jaise 'Weather in Delhi')."

    logger.info(f"Fetching weather for city: {city}")
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "q": city,
        "appid": api_key,
        "units": "metric"
    }

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: requests.get(url, params=params, timeout=10)
        )
        if response.status_code != 200:
            logger.error(f"OpenWeather API error: {response.status_code} - {response.text}")
            if response.status_code == 401:
                return "❌ OpenWeather API Key invalid ya unauthorized hai. Kripya .env.local mein OPENWEATHER_API_KEY check karein."
            if response.status_code == 404:
                return f"❌ City '{city}' nahi mili. Kripya city ka sahi naam batayein."
            if response.status_code == 429:
                return "❌ OpenWeather API rate limit ya quota exceed ho gaya hai."
            return f"❌ {city} ke liye weather fetch nahi kar paye (Status {response.status_code})."

        data = response.json()
        weather = data["weather"][0]["description"].title()
        temperature = data["main"]["temp"]
        humidity = data["main"]["humidity"]
        wind_speed = data["wind"]["speed"]

        result = (f"Weather in {city}:\n"
                  f"- Condition: {weather}\n"
                  f"- Temperature: {temperature}°C\n"
                  f"- Humidity: {humidity}%\n"
                  f"- Wind Speed: {wind_speed} m/s")

        logger.info(f"Weather result: \n{result}")
        return result

    except Exception as e:
        logger.exception(f"Weather fetch करते समय exception आया: {e}")
        return "Weather fetch करते समय एक error आया"
    
