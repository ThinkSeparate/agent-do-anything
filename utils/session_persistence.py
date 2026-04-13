"""Session persistence module for SQLite-based state management."""

import json
import sqlite3
from typing import Any, Dict, List, Optional


class SessionPersistence:
    """Manages session state persistence using SQLite.

    This class provides methods to create, save, load, and manage session states
    for long-running tasks that need to be persisted across interruptions.
    """

    def __init__(self, project_directory: str):
        """Initialize the SessionPersistence instance.

        Args:
            project_directory: The directory where the SQLite database will be stored.
        """
        self.project_directory = project_directory
        self.db_path = f"{project_directory}/.session_states.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the database tables if they don't exist."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_states (
                    session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_task TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    task_mode TEXT DEFAULT 'short',
                    state_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def create_session(self, original_task: str, task_mode: str = 'short') -> int:
        """Create a new session and return its session_id.

        Args:
            original_task: The original task description for this session.
            task_mode: 'short' for short task, 'long' for long task mode.

        Returns:
            The session_id of the newly created session.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO session_states (original_task, status, task_mode) VALUES (?, 'run', ?)",
                (original_task, task_mode)
            )
            conn.commit()
            return cursor.lastrowid

    def save_state(self, session_id: int, state: Dict[str, Any]) -> None:
        """Save the session state (JSON serialized).

        Args:
            session_id: The ID of the session to save state for.
            state: The state dictionary to serialize and save.
        """
        state_json = json.dumps(state)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE session_states
                   SET state_json = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE session_id = ?""",
                (state_json, session_id)
            )
            conn.commit()

    def load_state(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Load the session state.

        Args:
            session_id: The ID of the session to load state for.

        Returns:
            The deserialized state dictionary, or None if not found.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT state_json FROM session_states WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])
            return None

    def get_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Get complete session information.

        Args:
            session_id: The ID of the session to retrieve.

        Returns:
            A dictionary containing all session fields, or None if not found.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM session_states WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def list_sessions(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """List sessions with pagination.

        Args:
            limit: Maximum number of sessions to return (default 20).
            offset: Number of sessions to skip (default 0).

        Returns:
            A list of session dictionaries, ordered by session_id ASC.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM session_states
                   ORDER BY session_id ASC
                   LIMIT ? OFFSET ?""",
                (limit, offset)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def get_total_session_count(self) -> int:
        """Get total number of sessions.

        Returns:
            Total count of all sessions.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM session_states")
            return cursor.fetchone()[0]

    def mark_completed(self, session_id: int) -> None:
        """Mark a session as completed.

        Args:
            session_id: The ID of the session to mark as completed.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE session_states
                   SET status = 'done', updated_at = CURRENT_TIMESTAMP
                   WHERE session_id = ?""",
                (session_id,)
            )
            conn.commit()

    def mark_failed(self, session_id: int) -> None:
        """Mark a session as failed.

        Args:
            session_id: The ID of the session to mark as failed.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE session_states
                   SET status = 'fail', updated_at = CURRENT_TIMESTAMP
                   WHERE session_id = ?""",
                (session_id,)
            )
            conn.commit()

    def mark_corrupted(self, session_id: int) -> None:
        """Mark a session as corrupted (unrecoverable).

        Args:
            session_id: The ID of the session to mark.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """UPDATE session_states
                   SET status = 'corrupted', updated_at = CURRENT_TIMESTAMP
                   WHERE session_id = ?""",
                (session_id,)
            )
            conn.commit()

    def get_last_session(self) -> Optional[Dict[str, Any]]:
        """Get the most recent session (by session_id).

        Returns:
            The most recent session dictionary, or None if no sessions exist.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM session_states
                   ORDER BY session_id DESC
                   LIMIT 1"""
            )
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None
