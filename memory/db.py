"""
memory/db.py — SQLite persistence layer for J.A.R.V.I.S.

Tables:
    conversations  — every user/jarvis exchange
    summaries      — daily nightly summaries
    reminders      — user-created reminders
"""

import sqlite3
import logging
from datetime import datetime, date
from typing import Optional
from config import DB_PATH

logger = logging.getLogger(__name__)


def _get_connection() -> sqlite3.Connection:
    """Return a connection with row-factory set to Row."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def initialize_db() -> None:
    """Create all tables if they don't already exist."""
    conn = _get_connection()
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                date        TEXT NOT NULL,
                timestamp   TEXT NOT NULL,
                user_input  TEXT NOT NULL,
                jarvis_response TEXT NOT NULL,
                summary     TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS summaries (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                date    TEXT NOT NULL UNIQUE,
                summary TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                datetime    TEXT NOT NULL,
                repeat      TEXT DEFAULT 'none',
                triggered   INTEGER DEFAULT 0
            );
            """
        )
        conn.commit()
        logger.info("Database initialised at %s", DB_PATH)
    except Exception as exc:
        logger.error("DB init error: %s", exc)
    finally:
        conn.close()


# ── Conversations ─────────────────────────────────────────────────────────────

def save_conversation(user_input: str, jarvis_response: str) -> None:
    """Persist one exchange to the conversations table."""
    now = datetime.now()
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO conversations (date, timestamp, user_input, jarvis_response) "
            "VALUES (?, ?, ?, ?)",
            (now.strftime("%Y-%m-%d"), now.isoformat(timespec="seconds"),
             user_input, jarvis_response),
        )
        conn.commit()
    except Exception as exc:
        logger.error("Failed to save conversation: %s", exc)
    finally:
        conn.close()


def get_today_conversations(limit: int = 10) -> list[dict]:
    """Return up to *limit* most-recent conversations from today."""
    today = date.today().isoformat()
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT user_input, jarvis_response, timestamp "
            "FROM conversations WHERE date = ? "
            "ORDER BY id DESC LIMIT ?",
            (today, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]
    except Exception as exc:
        logger.error("get_today_conversations error: %s", exc)
        return []
    finally:
        conn.close()


def get_conversations_for_date(target_date: str) -> list[dict]:
    """Return all conversations for a specific date string (YYYY-MM-DD)."""
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT user_input, jarvis_response, timestamp "
            "FROM conversations WHERE date = ? ORDER BY id",
            (target_date,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("get_conversations_for_date error: %s", exc)
        return []
    finally:
        conn.close()


# ── Summaries ─────────────────────────────────────────────────────────────────

def save_summary(target_date: str, summary_text: str) -> None:
    """Upsert a daily summary."""
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO summaries (date, summary) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET summary=excluded.summary",
            (target_date, summary_text),
        )
        conn.commit()
    except Exception as exc:
        logger.error("save_summary error: %s", exc)
    finally:
        conn.close()


def get_recent_summaries(limit: int = 3) -> list[dict]:
    """Return the *limit* most recent daily summaries (excluding today)."""
    today = date.today().isoformat()
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT date, summary FROM summaries WHERE date < ? "
            "ORDER BY date DESC LIMIT ?",
            (today, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("get_recent_summaries error: %s", exc)
        return []
    finally:
        conn.close()


# ── Reminders ─────────────────────────────────────────────────────────────────

def add_reminder(title: str, dt: datetime, repeat: str = "none") -> int:
    """Insert a reminder and return its id."""
    conn = _get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO reminders (title, datetime, repeat) VALUES (?, ?, ?)",
            (title, dt.isoformat(timespec="seconds"), repeat),
        )
        conn.commit()
        return cur.lastrowid
    except Exception as exc:
        logger.error("add_reminder error: %s", exc)
        return -1
    finally:
        conn.close()


def get_due_reminders() -> list[dict]:
    """Return untriggered reminders whose datetime <= now."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, datetime, repeat FROM reminders "
            "WHERE triggered = 0 AND datetime <= ?",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("get_due_reminders error: %s", exc)
        return []
    finally:
        conn.close()


def mark_reminder_triggered(reminder_id: int) -> None:
    """Mark a reminder as triggered (or delete if non-repeating)."""
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE reminders SET triggered = 1 WHERE id = ?",
            (reminder_id,),
        )
        conn.commit()
    except Exception as exc:
        logger.error("mark_reminder_triggered error: %s", exc)
    finally:
        conn.close()


def list_upcoming_reminders(limit: int = 5) -> list[dict]:
    """Return the next *limit* untriggered reminders."""
    now = datetime.now().isoformat(timespec="seconds")
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, datetime, repeat FROM reminders "
            "WHERE triggered = 0 AND datetime > ? ORDER BY datetime LIMIT ?",
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        logger.error("list_upcoming_reminders error: %s", exc)
        return []
    finally:
        conn.close()
