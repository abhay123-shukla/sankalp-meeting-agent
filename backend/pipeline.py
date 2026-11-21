import time
import uuid
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from models import (
    IngestRequest, IngestResponse, AgentTraceStep, 
    StagedItems, ExtractedDecision, ExtractedTask, DetectedConflict
)
from database import (
    get_active_decisions, save_staged_session, get_all_settings
)
from ai_engine import AIEngine, SmartDeterministicAnalyzer

def normalize_topic_key(topic: str) -> str:
    """Normalizes topic string to canonical comparison key."""
    t = topic.lower().strip()
    if "payment" in t or "stripe" in t or "razorpay" in t or "gateway" in t:
        return "payments_api"
    if "launch" in t or "release" in t or "v1" in t or "date" in t or "deadline" in t:
        return "launch_date"
    if "auth" in t or "login" in t or "authentication" in t:
        return "auth_flow"
    return re.sub(r"[^a-z0-9]", "_", t)

class IngestionPipeline:
    """
    Executes the 4-step autonomous ingest pipeline:
    1. Parse (Speaker attribution & line segmentation)
    2. Extract (Decisions, Action Items, Amber Flags, Summary via AI Engine)
    3. Conflict Audit (Cross-meeting audit against SQLite active memory)
    4. Stage for Approval (Human-in-the-loop preparation & SQLite staged store)
    """

    @classmethod
    def run(cls, request: IngestRequest) -> IngestResponse:
        session_id = f"ingest_{uuid.uuid4().hex[:10]}"
        trace_steps: List[AgentTraceStep] = []
        meeting_title = request.meeting_title or "Meeting Sync"
        meeting_date = request.meeting_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        transcript = request.transcript

        # =========================================================================
        # STEP 1: PARSE (Speaker attribution & structural segmentation)
        # =========================================================================
        t0 = time.time()
        speaker_turns = SmartDeterministicAnalyzer.parse_speaker_lines(transcript)
        speakers = list(dict.fromkeys([turn["speaker"] for turn in speaker_turns if turn["speaker"] != "Unknown"]))
        total_lines = len(speaker_turns)
        duration_step1 = int((time.time() - t0) * 1000)

        trace_steps.append(AgentTraceStep(
            step=1,
            name="Transcript Parsing & Speaker Attribution",
            status="completed",
            duration_ms=duration_step1,
            details=f"Parsed {total_lines} speaker turns across {len(speakers)} participant(s): {', '.join(speakers) if speakers else 'General'}.",
            metrics={
                "turns_count": total_lines,
                "participants": speakers,
                "character_count": len(transcript)
            }
        ))

        # =========================================================================
        # STEP 2: EXTRACT (Decisions, Tasks, Amber Flags, Discussion Points)
        # =========================================================================
        t0 = time.time()
        settings = get_all_settings()
        raw_extraction, engine_used = AIEngine.analyze(
            transcript=transcript,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            settings=settings
        )
        duration_step2 = int((time.time() - t0) * 1000)

        extracted_decisions_raw = raw_extraction.get("decisions", [])
        extracted_tasks_raw = raw_extraction.get("tasks", [])
        discussion_points = raw_extraction.get("discussion_points", [])
        summary = raw_extraction.get("summary", "")

        # Format Extracted Tasks
        staged_tasks: List[ExtractedTask] = []
        for t in extracted_tasks_raw:
            is_amber = bool(t.get("flag_amber"))
            missing_owner = bool(t.get("missing_owner")) or (not t.get("owner")) or (str(t.get("owner")).lower() in ["unassigned", "none", "someone", "tbd"])
            missing_deadline = bool(t.get("missing_deadline")) or (not t.get("due_date")) or (str(t.get("due_date")).lower() in ["tbd", "none", "unknown"])
            
            if missing_owner or missing_deadline:
                is_amber = True

            staged_tasks.append(ExtractedTask(
                id=t.get("id") or f"task_{uuid.uuid4().hex[:8]}",
                title=t.get("title", "Untitled Task"),
                owner=t.get("owner") if not missing_owner else None,
                due_date=t.get("due_date") if not missing_deadline else None,
                priority=t.get("priority", "medium"),
                flag_amber=is_amber,
                missing_owner=missing_owner,
                missing_deadline=missing_deadline,
                notes=t.get("notes") or ("Flagged amber: missing owner/deadline" if is_amber else None)
            ))

        amber_count = sum(1 for t in staged_tasks if t.flag_amber)
        trace_steps.append(AgentTraceStep(
            step=2,
            name="Entity & Intent Extraction",
            status="warning" if amber_count > 0 else "completed",
            duration_ms=duration_step2,
            details=f"Extracted {len(extracted_decisions_raw)} decision(s) and {len(staged_tasks)} action item(s) using {engine_used}." + 
                    (f" {amber_count} item(s) flagged in amber." if amber_count > 0 else ""),
            metrics={
                "engine": engine_used,
                "decisions_count": len(extracted_decisions_raw),
                "tasks_count": len(staged_tasks),
                "amber_flags_count": amber_count
            }
        ))

        # =========================================================================
        # STEP 3: CONFLICT AUDIT (Cross-Meeting Memory Audit against SQLite)
        # =========================================================================
        t0 = time.time()
        active_decisions = get_active_decisions()
        detected_conflicts: List[DetectedConflict] = []
        staged_decisions: List[ExtractedDecision] = []

        for d in extracted_decisions_raw:
            topic = d.get("topic", "")
            val = d.get("value", "")
            speaker = d.get("speaker")
            reason = d.get("reason")
            norm_key = normalize_topic_key(topic)

            conflict_found = None
            for existing in active_decisions:
                existing_norm = normalize_topic_key(existing["topic"])
                if existing_norm == norm_key:
                    # Check if value is different (e.g. Stripe vs Razorpay or 2026-11-28 vs 2026-12-05)
                    exist_val = existing["value"].strip()
                    proposed_val = val.strip()
                    if exist_val.lower() != proposed_val.lower():
                        conflict_found = existing
                        break

            if conflict_found:
                conflict_id = f"conf_{uuid.uuid4().hex[:8]}"
                conf_type = "deadline_shift" if norm_key == "launch_date" else "decision_override"
                conf = DetectedConflict(
                    id=conflict_id,
                    conflict_type=conf_type,
                    topic=conflict_found["topic"],
                    existing_decision_id=conflict_found["id"],
                    existing_value=conflict_found["value"],
                    existing_meeting=conflict_found.get("meeting_title") or "Previous Meeting",
                    existing_speaker=conflict_found.get("speaker"),
                    proposed_value=val,
                    proposed_speaker=speaker,
                    proposed_reason=reason or f"Updated in {meeting_title}",
                    severity="high",
                    suggested_action="supersede"
                )
                detected_conflicts.append(conf)

                staged_decisions.append(ExtractedDecision(
                    id=d.get("id") or f"dec_{uuid.uuid4().hex[:8]}",
                    topic=topic,
                    value=val,
                    category=d.get("category", "General"),
                    speaker=speaker,
                    reason=reason,
                    confidence=float(d.get("confidence", 0.95)),
                    status="conflicting",
                    conflicts_with=conflict_found["id"],
                    conflict_details=f"Conflicts with '{conflict_found['value']}' locked in {conflict_found.get('meeting_title', 'earlier meeting')}"
                ))
            else:
                staged_decisions.append(ExtractedDecision(
                    id=d.get("id") or f"dec_{uuid.uuid4().hex[:8]}",
                    topic=topic,
                    value=val,
                    category=d.get("category", "General"),
                    speaker=speaker,
                    reason=reason,
                    confidence=float(d.get("confidence", 0.95)),
                    status="new",
                    conflicts_with=None,
                    conflict_details=None
                ))

        duration_step3 = int((time.time() - t0) * 1000)
        trace_steps.append(AgentTraceStep(
            step=3,
            name="Memory Conflict Audit",
            status="warning" if len(detected_conflicts) > 0 else "completed",
            duration_ms=duration_step3,
            details=f"Audited against {len(active_decisions)} active decision(s) in SQLite. Detected {len(detected_conflicts)} conflict(s)." if detected_conflicts else f"Audited against {len(active_decisions)} active decision(s) in SQLite. No conflicts detected.",
            metrics={
                "active_memory_records_scanned": len(active_decisions),
                "conflicts_detected": len(detected_conflicts),
                "conflicting_topics": [c.topic for c in detected_conflicts]
            }
        ))

        # =========================================================================
        # STEP 4: STAGE FOR APPROVAL (Human-in-the-Loop Confirmation Gate Prep)
        # =========================================================================
        t0 = time.time()
        staged_items = StagedItems(
            decisions=staged_decisions,
            tasks=staged_tasks,
            conflicts=detected_conflicts,
            discussion_points=discussion_points,
            summary=summary
        )

        duration_step4 = int((time.time() - t0) * 1000)
        trace_steps.append(AgentTraceStep(
            step=4,
            name="Staging for Human-in-the-Loop Gate",
            status="completed",
            duration_ms=duration_step4,
            details=f"Session {session_id} staged successfully. Ready for human review and confirmation.",
            metrics={"session_id": session_id}
        ))

        # Persist staged session into SQLite
        save_staged_session(
            session_id=session_id,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            raw_transcript=transcript,
            trace_steps=[s.model_dump() for s in trace_steps],
            staged_items=staged_items.model_dump()
        )

        return IngestResponse(
            session_id=session_id,
            meeting_title=meeting_title,
            meeting_date=meeting_date,
            trace_steps=trace_steps,
            staged_items=staged_items,
            engine_used=engine_used
        )
