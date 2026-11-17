"""Conversations per assistant (Fosholi / Dr. Krishi). Messages use the existing ai_messages table.
Needs migrations 010 (assistant column) and 012 (hidden_at, payload). Every query checks the owner AND the
assistant, so a farmer can never open, rename or delete someone else's chat, and the two assistants never mix."""
from __future__ import annotations

from chashibondhu.web.db import execute, fetch_all, fetch_one

ASSISTANTS = ("fosholi", "drkrishi")
TITLE_MAX = 80


def new_conversation(user_id: int, assistant: str) -> int:
    return int(fetch_one("INSERT INTO ai_conversations (user_id, assistant) VALUES (%s, %s) RETURNING id",
                         (user_id, assistant))["id"])


def owns(conv_id: int, user_id: int, assistant: str) -> bool:
    return fetch_one("SELECT 1 AS x FROM ai_conversations WHERE id = %s AND user_id = %s AND assistant = %s "
                     "AND hidden_at IS NULL", (conv_id, user_id, assistant)) is not None


def messages(conv_id: int, user_id: int, assistant: str, limit: int = 40) -> list[dict]:
    """Messages of the user's own conversation of THIS assistant (oldest first)."""
    return fetch_all("SELECT m.id, m.role, m.kind, m.content, m.sources, m.status, m.payload, m.created_at "
                     "FROM ai_messages m JOIN ai_conversations c ON c.id = m.conversation_id "
                     "WHERE c.id = %s AND c.user_id = %s AND c.assistant = %s AND c.hidden_at IS NULL "
                     "ORDER BY m.id DESC LIMIT %s", (conv_id, user_id, assistant, limit))[::-1]


def conversations(user_id: int, assistant: str, q: str = "", limit: int = 80) -> list[dict]:
    """Sidebar list: newest first; only chats that have a first question (title). q searches titles."""
    q = " ".join((q or "").split())[:80]
    sql = ("SELECT id, title, updated_at FROM ai_conversations WHERE user_id = %s AND assistant = %s "
           "AND hidden_at IS NULL AND title IS NOT NULL")
    args: list = [user_id, assistant]
    if q:
        sql += " AND title ILIKE %s"
        args.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    return fetch_all(sql + " ORDER BY updated_at DESC, id DESC LIMIT %s", (*args, limit))


def rename(conv_id: int, user_id: int, assistant: str, title: str) -> bool:
    title = " ".join((title or "").split())[:TITLE_MAX]
    if not title:
        return False
    r = fetch_one("UPDATE ai_conversations SET title = %s WHERE id = %s AND user_id = %s AND assistant = %s "
                  "AND hidden_at IS NULL RETURNING id", (title, conv_id, user_id, assistant))
    return r is not None


def hide(conv_id: int, user_id: int, assistant: str) -> bool:
    r = fetch_one("UPDATE ai_conversations SET hidden_at = now() WHERE id = %s AND user_id = %s AND assistant = %s "
                  "AND hidden_at IS NULL RETURNING id", (conv_id, user_id, assistant))
    return r is not None


def set_payload(message_id: int, payload: dict) -> None:
    from psycopg.types.json import Jsonb
    execute("UPDATE ai_messages SET payload = %s WHERE id = %s", (Jsonb(payload), message_id))


def user_area(user_id: int) -> str | None:
    """The user's registered upazila (or district) code, for weather."""
    r = fetch_one("SELECT upazila_code, district_code FROM users WHERE id = %s", (user_id,))
    return (r or {}).get("upazila_code") or (r or {}).get("district_code") if r else None


def retitle(conv_id: int, old: str, new: str) -> None:
    """A photo-only chat gets a clearer title (crop - problem) once, only if nobody renamed it."""
    execute("UPDATE ai_conversations SET title = %s WHERE id = %s AND title = %s", (new[:TITLE_MAX], conv_id, old))
