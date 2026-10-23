"""
Empathy Voice Conversation Tools for Cynthia AI Assistant.
Provides dynamic conversational tone evaluation, emotional warmth adaptation,
and pacing guidance without persisting transient emotions as permanent facts.
"""
import logging
from livekit.agents import function_tool

logger = logging.getLogger("empathy_tools")
logger.setLevel(logging.INFO)

# Tone adaptation profiles (guiding prompts and pacing)
_TONE_PROFILES = {
    "stressed": {
        "pacing": "rapid and concise",
        "style": "Ultra-brief, direct action. Skip small talk and fillers. Immediate confirmations.",
        "example_phrase": "Done, Boss."
    },
    "frustrated": {
        "pacing": "calm and attentive",
        "style": "Acknowledge frustration respectfully, apologize once briefly, fix immediately without making technical excuses.",
        "example_phrase": "Maaf kijiyega Boss, main ise abhi theek kar deti hoon."
    },
    "uncertain": {
        "pacing": "gentle and reassuring",
        "style": "Soft, clear explanations. Offer simple next steps and confirm choices gently.",
        "example_phrase": "Fikar mat kijiye, main help kar sakti hoon."
    },
    "sad": {
        "pacing": "warm and supportive",
        "style": "Warm, dependable tone. Gentle listening with supportive, empathetic Hinglish phrasing.",
        "example_phrase": "Main yahin hoon aapke saath, batayein main kya sambhal sakti hoon?"
    },
    "excited": {
        "pacing": "energetic and engaged",
        "style": "Mirror user excitement and celebratory energy, while staying helpful and productive.",
        "example_phrase": "Wah Boss! Ye to bohot badhiya hai!"
    },
    "calm": {
        "pacing": "steady and relaxed",
        "style": "Balanced, polite, friendly conversational tone with standard Hinglish rhythm.",
        "example_phrase": "Ji Boss, main dekh leti hoon."
    }
}


@function_tool
async def adapt_conversational_tone(detected_mood: str, user_sentiment: str = "") -> str:
    """
    Evaluates and adapts Cynthia's conversational tone, empathy, pacing, and verbosity based on the user's conversational mood.
    
    Parameters:
    - detected_mood: One of 'stressed', 'frustrated', 'uncertain', 'sad', 'excited', 'calm'.
    - user_sentiment: Optional brief description of conversational context (e.g., 'User is in a rush', 'User is struggling with code bug').
    
    IMPORTANT: This tone adaptation is transient for the current conversation turn.
    It does NOT permanently alter memory facts.
    """
    mood = (detected_mood or "calm").strip().lower()
    profile = _TONE_PROFILES.get(mood, _TONE_PROFILES["calm"])
    
    logger.info(f"Adapted conversational tone to: {mood} (sentiment: {user_sentiment})")
    
    return (
        f"✅ Tone adapted to '{mood.capitalize()}':\n"
        f"- Pacing: {profile['pacing']}\n"
        f"- Speaking style: {profile['style']}\n"
        f"- Suggested tone feel: \"{profile['example_phrase']}\""
    )
