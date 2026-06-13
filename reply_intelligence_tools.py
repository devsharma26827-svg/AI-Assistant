import logging
import os
import json
from livekit.agents import function_tool
import google.generativeai as genai
from gemini_key_manager import gemini_key_manager

# Configure logging
logger = logging.getLogger("reply_intelligence_tools")
logger.setLevel(logging.INFO)

@function_tool
async def smart_auto_reply(sender_name: str, message_text: str, context: dict) -> str:
    """
    Generates 3 context-aware, short, human-like WhatsApp replies (Hinglish).
    
    Arguments:
    - sender_name: Name of sender.
    - message_text: The incoming message.
    - context: Dict containing location, activity, status, time_of_day, relationship.
    """
    import asyncio
    try:
        if not gemini_key_manager.api_keys or gemini_key_manager.api_keys == [""]:
            return json.dumps({
                "intent": "error",
                "reply_options": ["Error: API Key missing.", "Cannot generate reply.", "System Check Required."]
            })

        # Inner sync function
        def _generate():
            try:
                # Construct Prompt
                prompt = f"""
                You are a Smart Reply Engine for a user named Dev.
                Generate 3 short, human-like, Hinglish WhatsApp replies based on the incoming message context.
                
                INPUT:
                Sender: {sender_name} (Relationship: {context.get('relationship', 'Unknown')})
                Message: "{message_text}"
                Context:
                - Location: {context.get('location', 'Unknown')}
                - Activity: {context.get('activity', 'Unknown')}
                - Status: {context.get('status', 'Unknown')}
                - Time: {context.get('time_of_day', 'Unknown')}
                
                RULES:
                1. Analyize Intent (Greeting, Urgent, Casual, etc.).
                2. Tone: {context.get('relationship', 'Unknown')}. (Friend=Casual, Boss=Polite).
                3. Length: 3-8 words max per reply.
                4. Style: Natural Hinglish (e.g. "Haan main aata hu", "Busy hu yaar").
                5. Output JSON format ONLY: {{ "intent": "...", "reply_options": ["...", "...", "..."] }}
                """
                
                def _api_call(active_key, model_name):
                    genai.configure(api_key=active_key)
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(prompt)
                    
                    # Clean response logic
                    text = response.text.strip()
                    if text.startswith("```json"):
                        text = text.replace("```json", "").replace("```", "")
                    return text
                    
                return gemini_key_manager.execute_with_retry(_api_call, max_retries_per_key=1)
            except Exception as e:
                logger.error(f"GenAI call failed: {e}")
                raise e

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _generate)

    except Exception as e:
        logger.error(f"Smart Reply Generation Failed: {e}")
        return json.dumps({
            "intent": "error",
            "reply_options": ["Error generating reply.", "Try again later.", "System busy."]
        })

@function_tool
async def auto_reply_decision(
    sender_name: str, 
    message_text: str, 
    intent: str, 
    relationship: str, 
    average_confidence: float = 0.5
) -> str:
    """
    Decides the safety/permission level for an auto-reply.
    
    Returns: "AUTO_SEND", "ASK_USER", or "DO_NOT_REPLY"
    """
    try:
        # Normalize inputs
        intent = intent.lower()
        relationship = relationship.lower()
        msg_lower = message_text.lower()
        
        # --- DO NOT REPLY CONDITIONS ---
        if any(x in msg_lower for x in ["otp", "code", "bank", "money", "pay", "amount", "credit", "debit"]):
            return json.dumps({"decision": "DO_NOT_REPLY", "reason": "Sensitive/Financial content."})
            
        if any(x in intent for x in ["urgent", "conflict", "work_discussion", "serious"]):
            return json.dumps({"decision": "DO_NOT_REPLY", "reason": "Serious or Urgent intent."})
            
        if average_confidence < 0.4:
            return json.dumps({"decision": "DO_NOT_REPLY", "reason": "Low confidence score."})

        # --- ASK USER CONDITIONS ---
        if any(x in intent for x in ["call", "plan", "invitation", "emotional"]):
             return json.dumps({"decision": "ASK_USER", "reason": "Requires user confirmation (Plan/Call/Emotion)."})
             
        if len(message_text.split()) > 30:
             return json.dumps({"decision": "ASK_USER", "reason": "Long message detected."})
             
        if relationship == "unknown" or "unknown" in relationship:
             return json.dumps({"decision": "ASK_USER", "reason": "Unknown sender."})

        if 0.4 <= average_confidence <= 0.75:
             return json.dumps({"decision": "ASK_USER", "reason": "Medium confidence score."})

        # --- AUTO SEND CONDITIONS ---
        if relationship == "friend" and average_confidence > 0.75:
            return json.dumps({"decision": "AUTO_SEND", "reason": "High confidence friend."})
            
        if any(x in intent for x in ["greeting", "location_question", "casual", "availability"]):
             return json.dumps({"decision": "AUTO_SEND", "reason": "Safe/Casual intent."})
             
        # Default Fallback
        return json.dumps({"decision": "ASK_USER", "reason": "Default safety fallback."})

    except Exception as e:
        return json.dumps({"decision": "ASK_USER", "reason": f"Error in decision logic: {e}"})

