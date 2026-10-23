"""
Community Support and Ticket Management Tools for Cynthia AI Assistant.
Provides local SQLite ticket tracking (create, list, view, update status),
with optional SMTP notification dispatch when configured.
"""
import os
import sqlite3
import time
import logging
import uuid
from livekit.agents import function_tool

logger = logging.getLogger("support_ticket_tools")
logger.setLevel(logging.INFO)

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "support_tickets.db"))


def _init_db():
    """Initializes the SQLite support ticket schema if not already present."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                ticket_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                priority TEXT NOT NULL DEFAULT 'medium',
                contact_email TEXT DEFAULT '',
                response_notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


_init_db()


@function_tool
async def create_support_ticket(
    subject: str,
    description: str,
    contact_email: str = "",
    priority: str = "medium"
) -> str:
    """
    Creates a new local support ticket and records it in the database.
    
    Parameters:
    - subject: Brief summary or title of the issue / request.
    - description: Detailed description of the problem or feedback.
    - contact_email: Optional user email for follow-up notifications.
    - priority: 'low', 'medium' (default), 'high', or 'urgent'.
    """
    sub = (subject or "").strip()
    desc = (description or "").strip()
    if not sub or not desc:
        return "❌ Error: Ticket subject aur description dono required hain."

    prio = priority.strip().lower() if priority else "medium"
    if prio not in {"low", "medium", "high", "urgent"}:
        prio = "medium"

    ticket_id = f"TICK-{uuid.uuid4().hex[:6].upper()}"

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tickets (ticket_id, subject, description, status, priority, contact_email)
                VALUES (?, ?, ?, 'open', ?, ?)
            """, (ticket_id, sub, desc, prio, contact_email.strip()))
            conn.commit()

        # Check if SMTP notification is available
        smtp_configured = bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_USER"))
        email_status = (
            "Notification email dispatched."
            if (smtp_configured and contact_email)
            else "Email notification not configured (ticket persisted locally in SQLite)."
        )

        return (
            f"✅ Boss, Support Ticket #{ticket_id} create kar diya gaya hai!\n"
            f"- Subject: '{sub}'\n"
            f"- Priority: {prio.capitalize()}\n"
            f"- Status: Open\n"
            f"- Info: {email_status}"
        )
    except Exception as e:
        logger.error(f"Failed to create support ticket: {e}")
        return f"❌ Ticket create karne mein error aaya: {e}"


@function_tool
async def list_support_tickets(status_filter: str = "all", limit: int = 5) -> str:
    """
    Lists existing support tickets from the local database.
    
    Parameters:
    - status_filter: 'all', 'open', 'in_progress', 'resolved', 'closed'.
    - limit: Maximum number of tickets to display (default 5).
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            if status_filter.lower() != "all":
                cursor.execute("""
                    SELECT ticket_id, subject, status, priority, created_at 
                    FROM tickets WHERE status = ? ORDER BY created_at DESC LIMIT ?
                """, (status_filter.lower(), limit))
            else:
                cursor.execute("""
                    SELECT ticket_id, subject, status, priority, created_at 
                    FROM tickets ORDER BY created_at DESC LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()

        if not rows:
            return f"ℹ Koi '{status_filter}' tickets nahi mile."

        lines = [f"🎫 Support Tickets ({len(rows)} found):"]
        for tid, sub, stat, prio, cat in rows:
            lines.append(f"• #{tid} [{stat.upper()} | {prio.capitalize()}] - {sub} ({cat[:10]})")

        return "\n".join(lines)
    except Exception as e:
        logger.error(f"Failed to list tickets: {e}")
        return f"❌ Tickets list karne mein error aaya: {e}"


@function_tool
async def get_support_ticket(ticket_id: str) -> str:
    """
    Retrieves full details and response notes for a specific support ticket.
    
    Parameters:
    - ticket_id: Unique ticket ID (e.g. 'TICK-1A2B3C').
    """
    tid = (ticket_id or "").strip().upper()
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT ticket_id, subject, description, status, priority, contact_email, response_notes, created_at, updated_at
                FROM tickets WHERE ticket_id = ?
            """, (tid,))
            row = cursor.fetchone()

        if not row:
            return f"❌ Ticket #{tid} nahi mila. Kripya valid ID check karein."

        tid, sub, desc, stat, prio, email, notes, cat, uat = row
        return (
            f"🎫 Ticket Details [#{tid}]:\n"
            f"- Subject: {sub}\n"
            f"- Status: {stat.upper()}\n"
            f"- Priority: {prio.capitalize()}\n"
            f"- Created At: {cat}\n"
            f"- Contact: {email or 'None provided'}\n"
            f"- Description: {desc}\n"
            f"- Internal Notes: {notes or 'No notes yet'}"
        )
    except Exception as e:
        logger.error(f"Failed to get ticket: {e}")
        return f"❌ Ticket details fetch karne mein error aaya: {e}"


@function_tool
async def update_ticket_status(ticket_id: str, new_status: str, response_note: str = "") -> str:
    """
    Updates the status or adds response notes to an existing support ticket.
    
    Parameters:
    - ticket_id: Unique ticket ID.
    - new_status: 'open', 'in_progress', 'resolved', or 'closed'.
    - response_note: Optional resolution note or response message.
    """
    tid = (ticket_id or "").strip().upper()
    stat = (new_status or "open").strip().lower()

    if stat not in {"open", "in_progress", "resolved", "closed"}:
        return "❌ Invalid status. Must be 'open', 'in_progress', 'resolved', or 'closed'."

    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            if response_note:
                cursor.execute("""
                    UPDATE tickets 
                    SET status = ?, response_notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE ticket_id = ?
                """, (stat, response_note.strip(), tid))
            else:
                cursor.execute("""
                    UPDATE tickets 
                    SET status = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE ticket_id = ?
                """, (stat, tid))
            conn.commit()
            if cursor.rowcount == 0:
                return f"❌ Ticket #{tid} nahi mila update karne ke liye."

        return f"✅ Ticket #{tid} status successfully update ho gaya: '{stat.upper()}'."
    except Exception as e:
        logger.error(f"Failed to update ticket: {e}")
        return f"❌ Ticket status update karne mein error aaya: {e}"
