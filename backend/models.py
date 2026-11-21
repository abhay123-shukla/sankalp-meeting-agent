from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# --- Ingestion Models ---

class IngestRequest(BaseModel):
    transcript: str = Field(..., description="Speaker-attributed meeting transcript")
    meeting_title: Optional[str] = Field("Meeting Sync", description="Title or name of the meeting")
    meeting_date: Optional[str] = Field(None, description="ISO or natural date of the meeting (e.g. 2026-11-23)")
    attendees: Optional[List[str]] = Field(default_factory=list, description="Optional list of attendees")

class AgentTraceStep(BaseModel):
    step: int
    name: str
    status: str = "completed"  # pending, in_progress, completed, warning, failed
    duration_ms: int = 0
    details: str
    metrics: Optional[Dict[str, Any]] = None

class ExtractedDecision(BaseModel):
    id: str
    topic: str
    value: str
    category: str = "General"
    speaker: Optional[str] = None
    reason: Optional[str] = None
    confidence: float = 0.95
    status: str = "new"  # new, conflicting
    conflicts_with: Optional[str] = None
    conflict_details: Optional[str] = None

class ExtractedTask(BaseModel):
    id: str
    title: str
    owner: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "medium"  # high, medium, low
    flag_amber: bool = False
    missing_owner: bool = False
    missing_deadline: bool = False
    notes: Optional[str] = None

class DetectedConflict(BaseModel):
    id: str
    conflict_type: str  # decision_override, deadline_shift, owner_conflict
    topic: str
    existing_decision_id: str
    existing_value: str
    existing_meeting: str
    existing_speaker: Optional[str] = None
    proposed_value: str
    proposed_speaker: Optional[str] = None
    proposed_reason: Optional[str] = None
    severity: str = "high"  # high, medium, amber
    suggested_action: str = "supersede"  # supersede, keep_old, discuss

class StagedItems(BaseModel):
    decisions: List[ExtractedDecision] = []
    tasks: List[ExtractedTask] = []
    conflicts: List[DetectedConflict] = []
    discussion_points: List[str] = []
    summary: str = ""

class IngestResponse(BaseModel):
    session_id: str
    meeting_title: str
    meeting_date: str
    trace_steps: List[AgentTraceStep]
    staged_items: StagedItems
    engine_used: str

# --- Approval Models ---

class DecisionApprovalItem(BaseModel):
    id: str
    topic: str
    value: str
    category: Optional[str] = "General"
    speaker: Optional[str] = None
    reason: Optional[str] = None
    conflict_resolution: Optional[str] = "supersede"  # supersede, keep_old, none
    conflicting_decision_id: Optional[str] = None
    approved: bool = True

class TaskApprovalItem(BaseModel):
    id: str
    title: str
    owner: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = "medium"
    flag_amber: bool = False
    approved: bool = True

class ApproveRequest(BaseModel):
    session_id: str
    approved_decisions: List[DecisionApprovalItem] = []
    approved_tasks: List[TaskApprovalItem] = []
    meeting_title: Optional[str] = None
    meeting_date: Optional[str] = None
    push_to_github: Optional[bool] = True
    notify_webhook: Optional[bool] = True

class ApproveResponse(BaseModel):
    success: bool
    message: str
    session_id: str
    decisions_committed: int
    decisions_superseded: int
    tasks_created: int
    github_issues_created: List[Dict[str, Any]] = []
    webhook_notified: bool = False

# --- Task & Decision Ledger Models ---

class TaskResponse(BaseModel):
    id: str
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None
    title: str
    owner: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "medium"
    status: str = "todo"  # todo, in_progress, done
    flag_amber: bool = False
    missing_owner: bool = False
    missing_deadline: bool = False
    github_issue_url: Optional[str] = None
    github_issue_number: Optional[int] = None
    created_at: str
    updated_at: str

class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    owner: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    flag_amber: Optional[bool] = None

class DecisionResponse(BaseModel):
    id: str
    meeting_id: Optional[str] = None
    meeting_title: Optional[str] = None
    topic: str
    value: str
    category: str
    speaker: Optional[str] = None
    reason: Optional[str] = None
    status: str  # active, superseded
    superseded_by_id: Optional[str] = None
    superseded_at: Optional[str] = None
    confidence: float
    created_at: str

# --- Reminders & Simulation Models ---

class ReminderTask(BaseModel):
    task_id: str
    title: str
    owner: Optional[str] = None
    due_date: str
    time_remaining: str
    urgency: str  # critical_2h, warning_24h, overdue, upcoming
    hours_remaining: float

class RemindersResponse(BaseModel):
    reference_time: str
    total_reminders: int
    critical_2h: List[ReminderTask] = []
    warning_24h: List[ReminderTask] = []
    overdue: List[ReminderTask] = []
    upcoming: List[ReminderTask] = []

class SimulateReminderRequest(BaseModel):
    simulated_date: Optional[str] = None  # e.g. "2026-11-25T10:00:00"
    send_webhook: Optional[bool] = True

class SimulateReminderResponse(BaseModel):
    simulated_date: str
    reminders: RemindersResponse
    webhook_sent: bool
    webhook_response: Optional[str] = None

# --- Digest Models ---

class DigestResponse(BaseModel):
    person: str
    generated_at: str
    summary_stats: Dict[str, int]
    active_tasks: List[TaskResponse]
    completed_tasks: List[TaskResponse]
    upcoming_deadlines: List[ReminderTask]
    conflicts_involved: List[Dict[str, Any]]
    decisions_owned: List[DecisionResponse]
    amber_flags: List[TaskResponse]

# --- Settings Models ---

class SettingsModel(BaseModel):
    groq_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    github_token: Optional[str] = None
    github_repo: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_type: Optional[str] = "auto"

class SettingsResponse(BaseModel):
    groq_configured: bool
    gemini_configured: bool
    github_configured: bool
    webhook_configured: bool
    groq_key_preview: str
    gemini_key_preview: str
    github_repo: Optional[str] = None
    github_token_preview: str
    webhook_url_preview: str
    webhook_type: str
    active_ai_provider: str

# --- Samples Models ---

class SampleMeeting(BaseModel):
    id: str
    day: str
    title: str
    date: str
    summary: str
    expected_behavior: str
    transcript: str

class SamplesResponse(BaseModel):
    samples: List[SampleMeeting]
