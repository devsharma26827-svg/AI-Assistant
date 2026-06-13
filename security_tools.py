import re
import os
import logging
from livekit.agents import function_tool

logger = logging.getLogger("security_tools")
logger.setLevel(logging.INFO)

# --- CONFIG ---
DANGEROUS_EXTENSIONS = [
    ".exe", ".bat", ".cmd", ".ps1", ".vbs", ".scr", ".pif", ".jar", ".js", ".reg"
]

SECRET_PATTERNS = [
    (r"sk-[a-zA-Z0-9]{20,}", "OpenAI API Key"),
    (r"ghp_[a-zA-Z0-9]{20,}", "GitHub Personal Access Token"),
    (r"(?i)password\s*=\s*['\"][^'\"]+['\"]", "Hardcoded Password"),
    (r"(?i)api[-_]?key\s*[:=]\s*['\"][a-zA-Z0-9\-_]{20,}['\"]", "Generic API Key"),
    (r"xox[baprs]-([0-9a-zA-Z]{10,48})?", "Slack Token"),
    (r"([0-9]{16})", "Prossible Credit Card"), # Simple check, might have lots of false positives, use with care
]

def scan_text_for_secrets(text: str):
    """
    Scans text for sensitive patterns.
    Returns: (is_safe: bool, masked_text: str, warning: str)
    """
    if not text:
        return True, text, None
        
    warning_msgs = []
    masked_text = text
    found_secrets = False
    
    for pattern, label in SECRET_PATTERNS:
        matches = re.finditer(pattern, text)
        for match in matches:
            found_secrets = True
            secret = match.group(0)
            
            # Masking: first 2 chars visible, rest stars
            if len(secret) > 4:
                masked = secret[:2] + "*" * (len(secret)-4) + secret[-2:]
            else:
                masked = "*" * len(secret)
                
            masked_text = masked_text.replace(secret, masked)
            warning_msgs.append(f"Detected {label}")
            
    if found_secrets:
        return False, masked_text, " | ".join(set(warning_msgs))
        
    return True, text, None

def scan_file_safety(file_path: str):
    """
    Checks if a file is potentially dangerous.
    Returns: (is_safe: bool, warning: str)
    """
    if not os.path.exists(file_path):
        return False, "File does not exist."
        
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext in DANGEROUS_EXTENSIONS:
        return False, f"⚠ Use of dangerous file extension '{ext}' is restricted."
        
    return True, None

@function_tool
async def validate_action_safety(action_type: str, details: str) -> str:
    """
    Validates if an action is safe to proceed.
    Use this before running risky commands.
    
    Arguments:
    - action_type: "send_message", "share_file", "execute_command"
    - details: The content or command to be executed.
    """
    if action_type == "send_message":
        is_safe, masked, warn = scan_text_for_secrets(details)
        if not is_safe:
            return f"⛔ SECURITY BLOCK: {warn}. Content masked: {masked}. Require explicit confirmation."
            
    if action_type == "share_file":
        is_safe, warn = scan_file_safety(details)
        if not is_safe:
             return f"⛔ SECURITY BLOCK: {warn}. Require explicit confirmation to send."
             
    if action_type == "execute_command":
        dangerous_keywords = ["rm -rf", "format", "del /s", "shutdown", "mkfs"]
        if any(k in details.lower() for k in dangerous_keywords):
             return f"⛔ SECURITY BLOCK: Destructive command detected. Require explicit confirmation."

    return "✅ Scan Safe."
