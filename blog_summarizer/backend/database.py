"""
SQLite database operations for Savify.
"""

import sqlite3
import json
import os
from typing import List, Dict, Any

DB_PATH = os.path.join(os.path.dirname(__file__), "summaries.db")


def get_connection() -> sqlite3.Connection:
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the summaries table if it doesn't exist."""
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                summary TEXT NOT NULL,
                key_points TEXT NOT NULL,
                takeaway TEXT NOT NULL,
                original_url TEXT NOT NULL UNIQUE,
                source_type TEXT NOT NULL DEFAULT 'blog',
                tools_mentioned TEXT DEFAULT '[]',
                category TEXT DEFAULT 'General',
                is_favorite INTEGER NOT NULL DEFAULT 0,
                summary_edited TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migration: add source_type column if missing (for existing DBs)
        cursor = conn.execute("PRAGMA table_info(summaries)")
        columns = [row[1] for row in cursor.fetchall()]
        if "source_type" not in columns:
            conn.execute("ALTER TABLE summaries ADD COLUMN source_type TEXT NOT NULL DEFAULT 'blog'")
        if "tools_mentioned" not in columns:
            conn.execute("ALTER TABLE summaries ADD COLUMN tools_mentioned TEXT DEFAULT '[]'")
        if "category" not in columns:
            conn.execute("ALTER TABLE summaries ADD COLUMN category TEXT DEFAULT 'General'")
        if "is_favorite" not in columns:
            conn.execute("ALTER TABLE summaries ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")
        if "summary_edited" not in columns:
            conn.execute("ALTER TABLE summaries ADD COLUMN summary_edited TEXT")

        conn.commit()
    finally:
        conn.close()


def save_summary(data: Dict[str, Any]) -> int:
    """
    Save a summary to the database.
    Returns the row ID of the inserted record.
    """
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO summaries (title, domain, difficulty, summary, key_points, takeaway, original_url, source_type, tools_mentioned, category)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["title"],
                data["domain"],
                data["difficulty"],
                data["summary"],
                json.dumps(data["key_points"]),
                data["takeaway"],
                data["original_url"],
                data.get("source_type", "blog"),
                json.dumps(data.get("tools_mentioned", [])),
                data.get("category", "General"),
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_all_summaries() -> List[Dict[str, Any]]:
    """Retrieve all summaries, newest first."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM summaries ORDER BY created_at DESC"
        ).fetchall()

        results = []
        for row in rows:
            item = dict(row)
            item["key_points"] = json.loads(item["key_points"])
            item["tools_mentioned"] = json.loads(item.get("tools_mentioned", "[]") or "[]")
            # Ensure defaults for migratable columns
            if not item.get("source_type"):
                item["source_type"] = "blog"
            if not item.get("category"):
                item["category"] = "General"
            item["is_favorite"] = bool(item.get("is_favorite", 0))
            item["summary_edited"] = item.get("summary_edited")
            results.append(item)
        return results
    finally:
        conn.close()


def delete_summary(summary_id: int) -> bool:
    """Delete a summary by ID. Returns True if deleted."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM summaries WHERE id = ?", (summary_id,)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_favorite(summary_id: int, is_favorite: bool) -> bool:
    """Update favorite status of a summary."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE summaries SET is_favorite = ? WHERE id = ?",
            (1 if is_favorite else 0, summary_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_summary_text(summary_id: int, new_text: str) -> bool:
    """Update the summary text (manual refinement)."""
    conn = get_connection()
    try:
        cursor = conn.execute(
            "UPDATE summaries SET summary_edited = ? WHERE id = ?",
            (new_text, summary_id)
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()
