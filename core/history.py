"""
SQLite state and history manager for the Aegis autonomous browser agent.
"""

import aiosqlite
import json
import uuid
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import settings


class HistoryManager:
    """
    Manages the session and action history for the Aegis agent using SQLite.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize the HistoryManager.
        
        Args:
            db_path: Path to the SQLite database. Defaults to settings.DB_PATH.
        """
        self.db_path = db_path or settings.DB_PATH
        
    async def init_db(self) -> None:
        """
        Initialize the database, creating necessary directories and tables if they do not exist.
        """
        db_file = Path(self.db_path)
        
        # Create data directory if it doesn't exist
        os.makedirs(db_file.parent, exist_ok=True)
        
        async with aiosqlite.connect(self.db_path) as db:
            # Create sessions table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    task TEXT,
                    status TEXT DEFAULT 'running',
                    created_at TEXT,
                    completed_at TEXT
                )
            ''')
            
            # Create actions table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    step_number INTEGER,
                    action_type TEXT,
                    action_json TEXT,
                    reasoning TEXT,
                    result TEXT,
                    data TEXT,
                    timestamp TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                )
            ''')
            
            await db.commit()

    async def create_session(self, task: str) -> str:
        """
        Create a new session for a task.
        
        Args:
            task: The main task description for this session.
            
        Returns:
            The generated session ID (UUID) as a string.
        """
        session_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO sessions (id, task, created_at) VALUES (?, ?, ?)",
                (session_id, task, created_at)
            )
            await db.commit()
            
        return session_id

    async def log_action(
        self, 
        session_id: str, 
        step_number: int, 
        action: Any, 
        result: str, 
        data: Optional[str] = None
    ) -> None:
        """
        Log an agent action to the database.
        
        Args:
            session_id: The ID of the session.
            step_number: The current step number.
            action: The AgentAction object performed.
            result: The result or output of the action.
            data: Additional data or artifacts from the action (optional).
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Serialize the AgentAction using model_dump()
        action_dict = action.model_dump()
        action_json = json.dumps(action_dict)
        
        # Extract metadata from the action dictionary for quick queries
        action_type = action_dict.get('action', 'unknown')
        reasoning = action_dict.get('reasoning', '')
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                '''
                INSERT INTO actions 
                (session_id, step_number, action_type, action_json, reasoning, result, data, timestamp) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (session_id, step_number, action_type, action_json, reasoning, result, data, timestamp)
            )
            await db.commit()

    async def get_recent_actions(self, session_id: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieve the most recent actions for a given session.
        
        Args:
            session_id: The ID of the session.
            limit: The maximum number of actions to return (default 5).
            
        Returns:
            A list of action dictionaries, ordered by step_number ascending (chronological).
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                '''
                SELECT * FROM actions 
                WHERE session_id = ? 
                ORDER BY step_number DESC 
                LIMIT ?
                ''',
                (session_id, limit)
            )
            rows = await cursor.fetchall()
            
            # Reverse the results to return them in chronological order
            actions = [dict(row) for row in rows]
            actions.reverse()
            return actions

    async def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """
        Get a summary of a session including its status, task, and total steps.
        
        Args:
            session_id: The ID of the session.
            
        Returns:
            A dictionary containing the session summary information.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Get session details
            cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            session_row = await cursor.fetchone()
            
            if not session_row:
                return {}
                
            summary = dict(session_row)
            
            # Get step count
            cursor = await db.execute("SELECT COUNT(*) as step_count FROM actions WHERE session_id = ?", (session_id,))
            count_row = await cursor.fetchone()
            summary['step_count'] = count_row['step_count'] if count_row else 0
            
            return summary

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """
        List all sessions, ordered by creation time descending.
        
        Returns:
            A list of session dictionaries.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM sessions ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def get_session_actions(self, session_id: str) -> List[Dict[str, Any]]:
        """
        Retrieve all actions for a given session.
        
        Args:
            session_id: The ID of the session.
            
        Returns:
            A list of action dictionaries, ordered by step_number ascending.
        """
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM actions WHERE session_id = ? ORDER BY step_number ASC", 
                (session_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_session_status(self, session_id: str, status: str) -> None:
        """
        Update the status of a session and set completed_at if appropriate.
        
        Args:
            session_id: The ID of the session.
            status: The new status string.
        """
        # If the status implies the session is finished, record completion time
        if status.lower() in ('completed', 'failed', 'error', 'finished', 'stopped'):
            completed_at = datetime.now(timezone.utc).isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE sessions SET status = ?, completed_at = ? WHERE id = ?",
                    (status, completed_at, session_id)
                )
                await db.commit()
        else:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE sessions SET status = ? WHERE id = ?",
                    (status, session_id)
                )
                await db.commit()
