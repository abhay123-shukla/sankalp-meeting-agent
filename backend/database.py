import sqlite3
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

DB_FILE = Path(__file__).resolve().parent / "execpulse.db"

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_FILE), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Settings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Meetings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS meetings (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        date TEXT NOT NULL,
        raw_transcript TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)

    # Decisions ledger (Cross-meeting persistent memory)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS decisions (
        id TEXT PRIMARY KEY,
        meeting_id TEXT,
        meeting_title TEXT,
        topic TEXT NOT NULL,
        value TEXT NOT NULL,
        category TEXT DEFAULT 'General',
        speaker TEXT,
        reason TEXT,
        status TEXT DEFAULT 'active', -- active, superseded, revoked
        superseded_by_id TEXT,
        superseded_at TEXT,
        confidence REAL DEFAULT 0.95,
        created_at TEXT NOT NULL
    );
    """)

    # Tasks / Action items / Kanban board
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        meeting_id TEXT,
        meeting_title TEXT,
        title TEXT NOT NULL,
        owner TEXT,
        due_date TEXT,
        priority TEXT DEFAULT 'medium', -- high, medium, low
        status TEXT DEFAULT 'todo', -- todo, in_progress, done
        flag_amber INTEGER DEFAULT 0,
        missing_owner INTEGER DEFAULT 0,
        missing_deadline INTEGER DEFAULT 0,
        github_issue_url TEXT,
        github_issue_number INTEGER,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)

    # Conflicts log
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS conflicts_log (
        id TEXT PRIMARY KEY,
        meeting_id TEXT,
        existing_decision_id TEXT,
        topic TEXT NOT NULL,
        old_value TEXT NOT NULL,
        new_value TEXT NOT NULL,
        proposed_by TEXT,
        resolution TEXT DEFAULT 'pending', -- superseded, kept_old, modified
        detected_at TEXT NOT NULL,
        resolved_at TEXT
    );
    """)

    # Staged ingest sessions
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS staged_sessions (
        id TEXT PRIMARY KEY,
        meeting_title TEXT NOT NULL,
        meeting_date TEXT NOT NULL,
        raw_transcript TEXT NOT NULL,
        trace_steps_json TEXT NOT NULL,
        staged_items_json TEXT NOT NULL,
        status TEXT DEFAULT 'pending', -- pending, approved, rejected
        created_at TEXT NOT NULL
    );
    """)

    # Create helpful indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_topic ON decisions(topic);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_owner ON tasks(owner);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_staged_status ON staged_sessions(status);")

    conn.commit()
    conn.close()

# Auto-initialize database tables on module import
init_db()

# --- Settings Helpers ---

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    if row:
        return row["value"]
    return os.environ.get(key, default)

def set_setting(key: str, value: str):
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO settings (key, value, updated_at) 
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
    """, (key, value, now_iso))
    conn.commit()
    conn.close()

def get_all_settings() -> Dict[str, str]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings")
    rows = cur.fetchall()
    conn.close()
    settings = {r["key"]: r["value"] for r in rows}
    # Fallback to env
    for env_k in ["GROQ_API_KEY", "GEMINI_API_KEY", "GITHUB_TOKEN", "GITHUB_REPO", "WEBHOOK_URL", "WEBHOOK_TYPE"]:
        if env_k not in settings and os.environ.get(env_k):
            settings[env_k] = os.environ.get(env_k, "")
    return settings

# --- Decisions Helpers ---

def get_active_decisions() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM decisions WHERE status = 'active' ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_all_decisions(status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT * FROM decisions WHERE 1=1"
    params = []
    if status and status.lower() != "all":
        query += " AND status = ?"
        params.append(status.lower())
    if category and category.lower() != "all":
        query += " AND LOWER(category) = LOWER(?)"
        params.append(category)
    query += " ORDER BY created_at DESC"
    cur.execute(query, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def insert_decision(decision_data: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO decisions (
            id, meeting_id, meeting_title, topic, value, category, speaker, 
            reason, status, superseded_by_id, superseded_at, confidence, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        decision_data.get("id"),
        decision_data.get("meeting_id"),
        decision_data.get("meeting_title"),
        decision_data.get("topic"),
        decision_data.get("value"),
        decision_data.get("category", "General"),
        decision_data.get("speaker"),
        decision_data.get("reason"),
        decision_data.get("status", "active"),
        decision_data.get("superseded_by_id"),
        decision_data.get("superseded_at"),
        decision_data.get("confidence", 0.95),
        decision_data.get("created_at", datetime.now(timezone.utc).isoformat())
    ))
    conn.commit()
    conn.close()

def supersede_decision(old_decision_id: str, new_decision_id: str, reason: Optional[str] = None):
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        UPDATE decisions 
        SET status = 'superseded', superseded_by_id = ?, superseded_at = ?
        WHERE id = ?
    """, (new_decision_id, now_iso, old_decision_id))
    conn.commit()
    conn.close()

# --- Tasks Helpers ---

def get_all_tasks(status: Optional[str] = None, owner: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    query = "SELECT * FROM tasks WHERE 1=1"
    params = []
    if status and status.lower() != "all":
        query += " AND LOWER(status) = LOWER(?)"
        params.append(status)
    if owner and owner.lower() != "all":
        query += " AND LOWER(owner) = LOWER(?)"
        params.append(owner)
    query += " ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, created_at DESC"
    cur.execute(query, tuple(params))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def insert_task(task_data: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO tasks (
            id, meeting_id, meeting_title, title, owner, due_date, priority, 
            status, flag_amber, missing_owner, missing_deadline, github_issue_url, 
            github_issue_number, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_data.get("id"),
        task_data.get("meeting_id"),
        task_data.get("meeting_title"),
        task_data.get("title"),
        task_data.get("owner"),
        task_data.get("due_date"),
        task_data.get("priority", "medium"),
        task_data.get("status", "todo"),
        1 if task_data.get("flag_amber") else 0,
        1 if task_data.get("missing_owner") else 0,
        1 if task_data.get("missing_deadline") else 0,
        task_data.get("github_issue_url"),
        task_data.get("github_issue_number"),
        task_data.get("created_at", now_iso),
        task_data.get("updated_at", now_iso)
    ))
    conn.commit()
    conn.close()

def update_task(task_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    
    fields = []
    params = []
    now_iso = datetime.now(timezone.utc).isoformat()
    
    for key, val in updates.items():
        if key in ["title", "owner", "due_date", "priority", "status", "github_issue_url", "github_issue_number"]:
            fields.append(f"{key} = ?")
            params.append(val)
        elif key == "flag_amber":
            fields.append("flag_amber = ?")
            params.append(1 if val else 0)

    if not fields:
        conn.close()
        return get_task_by_id(task_id)

    fields.append("updated_at = ?")
    params.append(now_iso)
    params.append(task_id)

    query = f"UPDATE tasks SET {', '.join(fields)} WHERE id = ?"
    cur.execute(query, tuple(params))
    conn.commit()
    conn.close()
    return get_task_by_id(task_id)

# --- Staged Sessions Helpers ---

def save_staged_session(session_id: str, meeting_title: str, meeting_date: str, raw_transcript: str, trace_steps: List[Dict[str, Any]], staged_items: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO staged_sessions (
            id, meeting_title, meeting_date, raw_transcript, trace_steps_json, 
            staged_items_json, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
        ON CONFLICT(id) DO UPDATE SET
            meeting_title = excluded.meeting_title,
            meeting_date = excluded.meeting_date,
            raw_transcript = excluded.raw_transcript,
            trace_steps_json = excluded.trace_steps_json,
            staged_items_json = excluded.staged_items_json,
            status = 'pending',
            created_at = excluded.created_at
    """, (
        session_id,
        meeting_title,
        meeting_date,
        raw_transcript,
        json.dumps(trace_steps),
        json.dumps(staged_items),
        now_iso
    ))
    conn.commit()
    conn.close()

def get_staged_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM staged_sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    data["trace_steps"] = json.loads(data["trace_steps_json"])
    data["staged_items"] = json.loads(data["staged_items_json"])
    return data

def get_pending_staged_sessions() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM staged_sessions WHERE status = 'pending' ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["trace_steps"] = json.loads(d["trace_steps_json"])
        d["staged_items"] = json.loads(d["staged_items_json"])
        result.append(d)
    return result

def set_staged_session_status(session_id: str, status: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE staged_sessions SET status = ? WHERE id = ?", (status, session_id))
    conn.commit()
    conn.close()

# --- Conflicts Log Helpers ---

def log_conflict(conflict_id: str, meeting_id: Optional[str], existing_decision_id: str, topic: str, old_val: str, new_val: str, proposed_by: Optional[str], resolution: str = "pending"):
    conn = get_db_connection()
    cur = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT OR REPLACE INTO conflicts_log (
            id, meeting_id, existing_decision_id, topic, old_value, new_value, 
            proposed_by, resolution, detected_at, resolved_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        conflict_id,
        meeting_id,
        existing_decision_id,
        topic,
        old_val,
        new_val,
        proposed_by,
        resolution,
        now_iso,
        now_iso if resolution != "pending" else None
    ))
    conn.commit()
    conn.close()

def get_conflicts_for_person(name: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    # Check decisions proposed by or superseded by this person
    cur.execute("""
        SELECT cl.*, d.meeting_title, d.speaker as original_speaker
        FROM conflicts_log cl
        LEFT JOIN decisions d ON cl.existing_decision_id = d.id
        WHERE LOWER(cl.proposed_by) = LOWER(?) OR LOWER(d.speaker) = LOWER(?)
        ORDER BY cl.detected_at DESC
    """, (name, name))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows

# --- DB Reset Helper ---

def reset_database(preserve_settings: bool = True):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM staged_sessions;")
    cur.execute("DELETE FROM conflicts_log;")
    cur.execute("DELETE FROM tasks;")
    cur.execute("DELETE FROM decisions;")
    cur.execute("DELETE FROM meetings;")
    if not preserve_settings:
        cur.execute("DELETE FROM settings;")
    conn.commit()
    conn.close()
