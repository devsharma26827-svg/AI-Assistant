"""
SMTP Email Automation Tools for Cynthia AI Assistant.
Provides secure email drafting, recipient review, and confirmed dispatch via SMTP (TLS/STARTTLS).
"""
import os
import re
import smtplib
import logging
from email.message import EmailMessage
from livekit.agents import function_tool

logger = logging.getLogger("email_tools")
logger.setLevel(logging.INFO)

# In-memory storage for current pending email draft
_CURRENT_DRAFT = {
    "recipient": "",
    "subject": "",
    "body": "",
    "cc": "",
    "bcc": "",
}

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _is_valid_email(address: str) -> bool:
    """Validates an email address format."""
    if not address:
        return False
    return bool(EMAIL_REGEX.match(address.strip()))


@function_tool
async def draft_email(recipient: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
    """
    Creates or updates an email draft for user review WITHOUT sending it.
    
    Parameters:
    - recipient: Primary recipient email address (e.g. 'dev@example.com').
    - subject: Email subject line.
    - body: Content/message of the email.
    - cc: Optional comma-separated CC recipients.
    - bcc: Optional comma-separated BCC recipients.
    """
    to_addr = (recipient or "").strip()
    sub = (subject or "").strip()
    msg_body = (body or "").strip()

    if not to_addr or not _is_valid_email(to_addr):
        return f"❌ Validation Error: '{to_addr}' ek valid recipient email address nahi hai."

    if not sub:
        return "❌ Error: Email subject khaali nahi ho sakta."

    _CURRENT_DRAFT["recipient"] = to_addr
    _CURRENT_DRAFT["subject"] = sub
    _CURRENT_DRAFT["body"] = msg_body
    _CURRENT_DRAFT["cc"] = cc.strip()
    _CURRENT_DRAFT["bcc"] = bcc.strip()

    cc_part = f"\n- CC: {cc.strip()}" if cc.strip() else ""
    return (
        f"📝 Boss, Email draft prepare kar diya hai:\n"
        f"- To: {to_addr}{cc_part}\n"
        f"- Subject: '{sub}'\n"
        f"- Body Preview: {msg_body[:100]}...\n\n"
        f"Kripya review karein. Send karne ke liye 'Send email' ya 'Confirmed' bolein."
    )


@function_tool
async def get_email_draft() -> str:
    """
    Retrieves and displays the currently active email draft.
    """
    if not _CURRENT_DRAFT["recipient"]:
        return "ℹ Abhi koi pending email draft nahi hai. 'draft_email' use karke naya email compose karein."

    cc_part = f"\n- CC: {_CURRENT_DRAFT['cc']}" if _CURRENT_DRAFT['cc'] else ""
    return (
        f"📝 Current Email Draft:\n"
        f"- To: {_CURRENT_DRAFT['recipient']}{cc_part}\n"
        f"- Subject: {_CURRENT_DRAFT['subject']}\n"
        f"- Body:\n{_CURRENT_DRAFT['body']}"
    )


@function_tool
async def send_email(
    recipient: str = "",
    subject: str = "",
    body: str = "",
    cc: str = "",
    bcc: str = "",
    confirmed: bool = False
) -> str:
    """
    Sends an email using configured SMTP settings after explicit user confirmation.
    
    Parameters:
    - recipient: Target email address (uses draft recipient if empty).
    - subject: Subject line (uses draft subject if empty).
    - body: Email message body (uses draft body if empty).
    - cc: Optional CC address.
    - bcc: Optional BCC address.
    - confirmed: Must be True to dispatch the email.
    """
    # Fallback to current draft if arguments are not provided
    to_addr = (recipient or _CURRENT_DRAFT["recipient"]).strip()
    sub = (subject or _CURRENT_DRAFT["subject"]).strip()
    msg_body = (body or _CURRENT_DRAFT["body"]).strip()
    cc_addr = (cc or _CURRENT_DRAFT["cc"]).strip()
    bcc_addr = (bcc or _CURRENT_DRAFT["bcc"]).strip()

    if not to_addr or not _is_valid_email(to_addr):
        return f"❌ Validation Error: '{to_addr}' ek valid email address nahi hai."

    if not confirmed:
        return (
            f"⚠ Confirmation Required: Kya aap sach mein ye email bhejna chahte hain?\n"
            f"- To: {to_addr}\n"
            f"- Subject: '{sub}'\n"
            f"Kripya 'Confirm send' bolein agar bhej doon."
        )

    # Read SMTP Configuration from environment
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()

    if not host or not user or not password:
        return (
            f"❌ SMTP configuration missing:\n"
            f"`.env.local` mein `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, aur `SMTP_PASSWORD` "
            f"configure karein taaki Cynthia emails send kar sake."
        )

    try:
        msg = EmailMessage()
        msg["From"] = user
        msg["To"] = to_addr
        msg["Subject"] = sub
        if cc_addr:
            msg["Cc"] = cc_addr
        if bcc_addr:
            msg["Bcc"] = bcc_addr

        msg.set_content(msg_body)

        # Connect and send
        import asyncio
        def _send():
            if port == 465:
                with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                    server.login(user, password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(host, port, timeout=15) as server:
                    server.starttls()
                    server.login(user, password)
                    server.send_message(msg)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send)

        # Clear draft after successful delivery
        _CURRENT_DRAFT["recipient"] = ""
        _CURRENT_DRAFT["subject"] = ""
        _CURRENT_DRAFT["body"] = ""

        return f"✅ Boss, email successfully send kar diya gaya hai to '{to_addr}'!"
    except smtplib.SMTPAuthenticationError:
        return "❌ SMTP Authentication Error: Username ya password galat hai (App password require ho sakta hai)."
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return f"❌ Email send karne mein error aaya: {e}"
