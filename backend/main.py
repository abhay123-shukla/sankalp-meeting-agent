import os
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load .env if present
load_dotenv()

# Resolve path to frontend/sankalp.html robustly
FRONTEND_HTML = (Path(__file__).resolve().parent.parent / "frontend" / "sankalp.html").resolve()
if not FRONTEND_HTML.exists():
    FRONTEND_HTML = Path("frontend/sankalp.html").resolve()

from database import (
    init_db, get_setting, set_setting, get_all_settings,
    get_all_decisions, get_active_decisions, insert_decision, supersede_decision,
    get_all_tasks, get_task_by_id, insert_task, update_task,
    get_staged_session, get_pending_staged_sessions, set_staged_session_status,
    log_conflict, get_conflicts_for_person, reset_database
)
from models import (
    IngestRequest, IngestResponse,
    ApproveRequest, ApproveResponse,
    TaskResponse, TaskUpdateRequest,
    DecisionResponse,
    RemindersResponse, SimulateReminderRequest, SimulateReminderResponse,
    DigestResponse,
    SettingsModel, SettingsResponse,
    SamplesResponse
)
from pipeline import IngestionPipeline
from samples import get_sample_meetings
from github_service import GitHubService
from webhook_service import WebhookService
from reminders_service import RemindersService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("execpulse")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize SQLite tables and memory indexes
    logger.info("Initializing ExecPulse SQLite database and schema...")
    init_db()
    logger.info("ExecPulse Backend is ready to process transcripts.")
    yield
    logger.info("Shutting down ExecPulse Backend.")

app = FastAPI(
    title="ExecPulse — Meeting-to-Execution Agent API",
    description="Autonomous engine that parses speaker-attributed transcripts, extracts decisions/tasks, performs cross-meeting memory audits, and executes approvals into persistent memory, Kanban, and GitHub.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS Configuration allowing all origins for sankalp.html and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- UI Endpoint ---

BANNER_PNG = (Path(__file__).resolve().parent.parent / "frontend" / "sankalp-banner.png").resolve()
if not BANNER_PNG.exists():
    BANNER_PNG = Path("frontend/sankalp-banner.png").resolve()

@app.get("/ui", tags=["UI"], response_class=FileResponse)
@app.get("/ui/", tags=["UI"], response_class=FileResponse)
def serve_ui():
    """Serves the frontend interactive interface (frontend/sankalp.html)."""
    if not FRONTEND_HTML.exists():
        raise HTTPException(status_code=404, detail=f"Frontend file not found at {FRONTEND_HTML}.")
    return FileResponse(str(FRONTEND_HTML), media_type="text/html")

@app.get("/sankalp-banner.png", tags=["UI"], response_class=FileResponse)
@app.get("/ui/sankalp-banner.png", tags=["UI"], response_class=FileResponse)
@app.get("/static/sankalp-banner.png", tags=["UI"], response_class=FileResponse)
def serve_banner():
    """Serves the hero brand banner (frontend/sankalp-banner.png)."""
    if not BANNER_PNG.exists():
        raise HTTPException(status_code=404, detail=f"Banner image not found at {BANNER_PNG}.")
    return FileResponse(str(BANNER_PNG), media_type="image/png")

def mask_secret(secret: Optional[str]) -> str:
    if not secret:
        return ""
    s = secret.strip()
    if len(s) <= 8:
        return "***"
    return f"{s[:4]}...{s[-4:]}"

# --- Health Check ---

@app.get("/", tags=["Health"])
@app.get("/health", tags=["Health"])
def health_check():
    settings = get_all_settings()
    has_groq = bool(settings.get("GROQ_API_KEY"))
    has_gemini = bool(settings.get("GEMINI_API_KEY"))
    provider = "Groq (llama-3.3-70b-versatile)" if has_groq else ("Gemini 1.5 Flash" if has_gemini else "Smart Deterministic Fallback Analyzer")
    return {
        "status": "online",
        "agent": "ExecPulse — Meeting-to-Execution Agent",
        "ai_engine": provider,
        "database": "SQLite (Persistent Cross-Meeting Memory)",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# --- 1. Samples Endpoint ---

@app.get("/api/samples", response_model=SamplesResponse, tags=["Samples"])
def get_samples():
    """Returns the 3 pre-loaded connected sample meetings to test cross-meeting conflict detection."""
    return get_sample_meetings()

# --- 2. Ingestion Pipeline Endpoint ---

@app.post("/api/ingest", response_model=IngestResponse, tags=["Pipeline"])
def ingest_transcript(request: IngestRequest):
    """
    Accepts speaker-attributed transcript, executes 4-step pipeline:
    1. Parse (Speaker attribution & line segmentation)
    2. Extract (Decisions, Action Items, Amber Flags)
    3. Conflict Audit (Cross-meeting audit against SQLite active memory)
    4. Stage for Approval (Prepares staged items and saves pending session)
    """
    if not request.transcript or not request.transcript.strip():
        raise HTTPException(status_code=400, detail="Transcript cannot be empty.")
    try:
        response = IngestionPipeline.run(request)
        return response
    except Exception as e:
        logger.error(f"Ingestion error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process transcript: {str(e)}")

# --- 3. Staged / Pending Approvals ---

@app.get("/api/pending", tags=["Approval"])
def get_pending_ingestions():
    """Returns currently staged sessions awaiting human-in-the-loop confirmation."""
    pending_sessions = get_pending_staged_sessions()
    return {
        "count": len(pending_sessions),
        "pending_sessions": pending_sessions
    }

@app.get("/api/pending/{session_id}", tags=["Approval"])
def get_pending_by_id(session_id: str):
    session = get_staged_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Staged session '{session_id}' not found.")
    return session

# --- 4. Human-in-the-Loop Confirmation Gate ---

@app.post("/api/approve", response_model=ApproveResponse, tags=["Approval"])
def approve_session(request: ApproveRequest):
    """
    Human-in-the-loop gate:
    1. Commits approved decisions to SQLite memory.
    2. Resolves conflicts (e.g. supersedes previous decisions).
    3. Commits approved action items to local Kanban board.
    4. Pushes tasks to GitHub Issues if configured.
    5. Dispatches approval notification to Slack/Discord webhook if configured.
    """
    session = get_staged_session(request.session_id)
    meeting_title = request.meeting_title or (session.get("meeting_title") if session else "Meeting Sync")
    meeting_date = request.meeting_date or (session.get("meeting_date") if session else datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    decisions_committed = 0
    decisions_superseded = 0
    tasks_created = 0
    github_issues = []

    settings = get_all_settings()
    gh_token = settings.get("GITHUB_TOKEN")
    gh_repo = settings.get("GITHUB_REPO")
    webhook_url = settings.get("WEBHOOK_URL")
    webhook_type = settings.get("WEBHOOK_TYPE", "auto")

    # 1. Process Approved Decisions
    for dec_item in request.approved_decisions:
        if not dec_item.approved:
            continue

        # Check for conflict resolution
        if dec_item.conflicting_decision_id and dec_item.conflict_resolution == "supersede":
            supersede_decision(
                old_decision_id=dec_item.conflicting_decision_id,
                new_decision_id=dec_item.id,
                reason=dec_item.reason
            )
            log_conflict(
                conflict_id=f"conf_res_{uuid.uuid4().hex[:8]}",
                meeting_id=request.session_id,
                existing_decision_id=dec_item.conflicting_decision_id,
                topic=dec_item.topic,
                old_val="",
                new_val=dec_item.value,
                proposed_by=dec_item.speaker,
                resolution="superseded"
            )
            decisions_superseded += 1

        insert_decision({
            "id": dec_item.id or f"dec_{uuid.uuid4().hex[:8]}",
            "meeting_id": request.session_id,
            "meeting_title": meeting_title,
            "topic": dec_item.topic,
            "value": dec_item.value,
            "category": dec_item.category or "General",
            "speaker": dec_item.speaker,
            "reason": dec_item.reason,
            "status": "active"
        })
        decisions_committed += 1

    # 2. Process Approved Tasks
    for task_item in request.approved_tasks:
        if not task_item.approved:
            continue

        task_id = task_item.id or f"task_{uuid.uuid4().hex[:8]}"
        is_missing_owner = not task_item.owner or task_item.owner.lower() in ["unassigned", "none", "someone", "tbd"]
        is_missing_deadline = not task_item.due_date or task_item.due_date.lower() in ["tbd", "none", "unknown"]
        is_amber = task_item.flag_amber or is_missing_owner or is_missing_deadline

        task_record = {
            "id": task_id,
            "meeting_id": request.session_id,
            "meeting_title": meeting_title,
            "title": task_item.title,
            "owner": task_item.owner if not is_missing_owner else None,
            "due_date": task_item.due_date if not is_missing_deadline else None,
            "priority": task_item.priority or "medium",
            "status": "todo",
            "flag_amber": is_amber,
            "missing_owner": is_missing_owner,
            "missing_deadline": is_missing_deadline,
            "github_issue_url": None,
            "github_issue_number": None
        }

        # Optional GitHub Issue creation
        if request.push_to_github and gh_token and gh_repo:
            gh_res = GitHubService.create_issue(
                repo=gh_repo,
                token=gh_token,
                task=task_record,
                meeting_title=meeting_title
            )
            if gh_res.get("success"):
                task_record["github_issue_url"] = gh_res.get("issue_url")
                task_record["github_issue_number"] = gh_res.get("issue_number")
                github_issues.append(gh_res)

        insert_task(task_record)
        tasks_created += 1

    # 3. Mark staged session status
    set_staged_session_status(request.session_id, "approved")

    # 4. Webhook Notification
    webhook_notified = False
    if request.notify_webhook and webhook_url:
        wh_res = WebhookService.notify_approval(
            webhook_url=webhook_url,
            webhook_type=webhook_type,
            meeting_title=meeting_title,
            decisions_count=decisions_committed,
            superseded_count=decisions_superseded,
            tasks_count=tasks_created
        )
        webhook_notified = wh_res.get("sent", False)

    return ApproveResponse(
        success=True,
        message=f"Meeting approval executed successfully. {decisions_committed} decision(s) saved ({decisions_superseded} superseded), {tasks_created} task(s) added to Kanban.",
        session_id=request.session_id,
        decisions_committed=decisions_committed,
        decisions_superseded=decisions_superseded,
        tasks_created=tasks_created,
        github_issues_created=github_issues,
        webhook_notified=webhook_notified
    )

# --- 5. Memory Ledger Endpoint ---

@app.get("/api/memory", response_model=List[DecisionResponse], tags=["Memory Ledger"])
def get_memory(
    status: Optional[str] = Query("all", description="Filter by status: 'active', 'superseded', or 'all'"),
    category: Optional[str] = Query(None, description="Filter by category")
):
    """Returns cross-meeting persistent decision ledger with full provenance and superseded tracking."""
    decisions = get_all_decisions(status=status, category=category)
    return [DecisionResponse(**d) for d in decisions]

# --- 6. Tasks / Kanban Endpoints ---

@app.get("/api/tasks", response_model=List[TaskResponse], tags=["Kanban"])
def get_tasks(
    status: Optional[str] = Query("all", description="Filter by status: 'todo', 'in_progress', 'done', or 'all'"),
    owner: Optional[str] = Query(None, description="Filter by owner name")
):
    """Returns cross-meeting Kanban action items."""
    tasks = get_all_tasks(status=status, owner=owner)
    return [
        TaskResponse(
            **{
                **t,
                "flag_amber": bool(t.get("flag_amber")),
                "missing_owner": bool(t.get("missing_owner")),
                "missing_deadline": bool(t.get("missing_deadline"))
            }
        )
        for t in tasks
    ]

@app.patch("/api/tasks/{task_id}", response_model=TaskResponse, tags=["Kanban"])
def update_task_endpoint(task_id: str, updates: TaskUpdateRequest):
    """Updates task status (todo -> in_progress -> done), owner, due date, priority, or amber flag."""
    existing = get_task_by_id(task_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found.")

    payload = updates.model_dump(exclude_unset=True)
    updated = update_task(task_id, payload)
    return TaskResponse(
        **{
            **updated,
            "flag_amber": bool(updated.get("flag_amber")),
            "missing_owner": bool(updated.get("missing_owner")),
            "missing_deadline": bool(updated.get("missing_deadline"))
        }
    )

# --- 7. Reminders & Simulation Endpoints ---

@app.get("/api/reminders", response_model=RemindersResponse, tags=["Reminders"])
def get_reminders(simulated_date: Optional[str] = Query(None, description="Optional simulated reference date e.g. '2026-11-25T10:00:00'")):
    """Returns pre-deadline reminders categorized into 2h critical, 24h warning, overdue, and upcoming."""
    return RemindersService.get_reminders(simulated_date)

@app.post("/api/reminders/simulate", response_model=SimulateReminderResponse, tags=["Reminders"])
def simulate_reminders_trigger(request: SimulateReminderRequest):
    """Triggers deadline simulation check and dispatches real-time webhook alert if configured."""
    reminders, webhook_sent, webhook_response = RemindersService.simulate_and_dispatch(
        simulated_date_str=request.simulated_date,
        send_webhook=bool(request.send_webhook)
    )
    return SimulateReminderResponse(
        simulated_date=reminders.reference_time,
        reminders=reminders,
        webhook_sent=webhook_sent,
        webhook_response=webhook_response
    )

# --- 8. Person Weekly Digest Endpoint ---

@app.get("/api/digest/{person}", response_model=DigestResponse, tags=["Digest"])
def get_person_digest(person: str):
    """Returns comprehensive weekly digest for an individual: active tasks, deadlines, conflicts, and decisions."""
    person_clean = person.strip()
    all_tasks = get_all_tasks()
    
    # Filter tasks owned by person
    person_tasks = [t for t in all_tasks if t.get("owner") and person_clean.lower() in t.get("owner", "").lower()]
    active_tasks = [
        TaskResponse(
            **{
                **t,
                "flag_amber": bool(t.get("flag_amber")),
                "missing_owner": bool(t.get("missing_owner")),
                "missing_deadline": bool(t.get("missing_deadline"))
            }
        )
        for t in person_tasks if (t.get("status") or "").lower() != "done"
    ]
    completed_tasks = [
        TaskResponse(
            **{
                **t,
                "flag_amber": bool(t.get("flag_amber")),
                "missing_owner": bool(t.get("missing_owner")),
                "missing_deadline": bool(t.get("missing_deadline"))
            }
        )
        for t in person_tasks if (t.get("status") or "").lower() == "done"
    ]

    # Amber flagged tasks (assigned to person, or all amber unassigned tasks for team visibility)
    amber_tasks = [
        TaskResponse(
            **{
                **t,
                "flag_amber": bool(t.get("flag_amber")),
                "missing_owner": bool(t.get("missing_owner")),
                "missing_deadline": bool(t.get("missing_deadline"))
            }
        )
        for t in all_tasks if bool(t.get("flag_amber")) and (not t.get("owner") or person_clean.lower() in t.get("owner", "").lower())
    ]

    # Reminders for this person
    reminders = RemindersService.get_reminders()
    person_upcoming = [r for r in (reminders.critical_2h + reminders.warning_24h + reminders.upcoming) if r.owner and person_clean.lower() in r.owner.lower()]

    # Decisions owned / proposed by person
    all_decisions = get_all_decisions(status="all")
    person_decisions = [
        DecisionResponse(**d) for d in all_decisions 
        if d.get("speaker") and person_clean.lower() in d.get("speaker", "").lower()
    ]

    # Conflicts involving person
    conflicts = get_conflicts_for_person(person_clean)

    summary_stats = {
        "active_tasks_count": len(active_tasks),
        "completed_tasks_count": len(completed_tasks),
        "upcoming_deadlines_count": len(person_upcoming),
        "decisions_owned_count": len(person_decisions),
        "conflicts_involved_count": len(conflicts),
        "amber_flags_count": len(amber_tasks)
    }

    return DigestResponse(
        person=person_clean,
        generated_at=datetime.now(timezone.utc).isoformat(),
        summary_stats=summary_stats,
        active_tasks=active_tasks,
        completed_tasks=completed_tasks,
        upcoming_deadlines=person_upcoming,
        conflicts_involved=conflicts,
        decisions_owned=person_decisions,
        amber_flags=amber_tasks
    )

# --- 9. Settings Endpoints ---

@app.get("/api/settings", response_model=SettingsResponse, tags=["Settings"])
def get_settings():
    """Returns current integration configurations and active AI provider with masked secrets."""
    settings = get_all_settings()
    groq_k = settings.get("GROQ_API_KEY", "")
    gemini_k = settings.get("GEMINI_API_KEY", "")
    gh_token = settings.get("GITHUB_TOKEN", "")
    gh_repo = settings.get("GITHUB_REPO", "")
    wh_url = settings.get("WEBHOOK_URL", "")
    wh_type = settings.get("WEBHOOK_TYPE", "auto")

    active_provider = "Groq (llama-3.3-70b-versatile)" if groq_k else ("Gemini 1.5 Flash" if gemini_k else "Smart Deterministic Fallback Analyzer")

    return SettingsResponse(
        groq_configured=bool(groq_k),
        gemini_configured=bool(gemini_k),
        github_configured=bool(gh_token and gh_repo),
        webhook_configured=bool(wh_url),
        groq_key_preview=mask_secret(groq_k),
        gemini_key_preview=mask_secret(gemini_k),
        github_repo=gh_repo or None,
        github_token_preview=mask_secret(gh_token),
        webhook_url_preview=mask_secret(wh_url),
        webhook_type=wh_type,
        active_ai_provider=active_provider
    )

@app.post("/api/settings", tags=["Settings"])
def update_settings(new_settings: SettingsModel):
    """Saves API keys, GitHub credentials, and Webhooks persistently into SQLite."""
    fields = new_settings.model_dump(exclude_unset=True)
    key_mapping = {
        "groq_api_key": "GROQ_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "github_token": "GITHUB_TOKEN",
        "github_repo": "GITHUB_REPO",
        "webhook_url": "WEBHOOK_URL",
        "webhook_type": "WEBHOOK_TYPE"
    }
    for model_key, env_key in key_mapping.items():
        if model_key in fields and fields[model_key] is not None:
            set_setting(env_key, fields[model_key])

    return {"success": True, "message": "Settings updated successfully in SQLite storage."}

# --- 10. Database Reset Endpoint (for clean state testing) ---

@app.post("/api/reset", tags=["Utilities"])
def reset_db(preserve_settings: bool = Query(True, description="Keep configured API keys and settings")):
    """Resets meetings, decisions, tasks, conflicts, and staged sessions."""
    reset_database(preserve_settings=preserve_settings)
    return {"success": True, "message": "Database memory cleared for testing clean execution."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
