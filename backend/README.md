# ExecPulse — Meeting-to-Execution Agent (Backend)

Autonomous meeting-to-execution engine built with **Python FastAPI**, **SQLite (Persistent Cross-Meeting Memory)**, and **Pydantic**. Transforms messy speaker-attributed meeting transcripts into structured decisions, cross-meeting conflict audits, Kanban execution tasks, and GitHub issues with a human-in-the-loop confirmation gate.

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Environment Configuration (Optional)
Copy `.env.example` to `.env` if you wish to configure LLM API keys or GitHub / Webhook credentials:
```bash
cp .env.example .env
```
*(Note: ExecPulse includes a **Smart Deterministic Fallback Analyzer** that functions 100% reliably out-of-the-box even without any API key).*

### 3. Start the Backend Server
```bash
uvicorn main:app --reload
```
The server will boot up with zero errors at: `http://127.0.0.1:8000`
- Interactive OpenAPI Docs: `http://127.0.0.1:8000/docs`
- Redoc Documentation: `http://127.0.0.1:8000/redoc`

---

## 🏗️ Architecture & Features

### 1. Dual AI Engine + Smart Deterministic Fallback Analyzer
- Supports `GROQ_API_KEY` (`llama-3.3-70b-versatile`) and `GEMINI_API_KEY` via `.env` or `/api/settings`.
- Enforces strict JSON output schemas.
- Built-in **Smart Deterministic Fallback Analyzer** guarantees that transcript parsing, speaker attribution, entity extraction, amber flagging, and conflict auditing work seamlessly with zero external API dependencies.

### 2. 4-Step Ingestion Pipeline (`POST /api/ingest`)
1. **Parse**: Speaker attribution, structural segmenting, participant discovery, and metrics.
2. **Extract**: Decisions, action items/tasks, key discussion points, and executive summary. Automatically detects missing owners or deadlines and marks tasks in **amber**.
3. **Conflict Audit**: Scans active decisions in SQLite persistent memory. If a new decision contradicts a previous decision (e.g. gateway switch or deadline shift), it triggers a conflict with full provenance and rationale.
4. **Stage for Approval**: Packages the trace steps and detected items into a pending session (`session_id`), awaiting human review.

### 3. Human-in-the-Loop Confirmation Gate (`POST /api/approve`)
- Only approved items enter SQLite persistent memory.
- Conflict resolution strategies:
  - `supersede`: Marks previous decision as `superseded` (`superseded_by_id`, `superseded_at`, `reason`).
  - `keep_old`: Retains old decision and rejects the override.
- Automatically pushes approved tasks to **GitHub Issues** (if `GITHUB_TOKEN` and `GITHUB_REPO` are configured) and populates the local Kanban board.
- Dispatches approval summary to **Discord** or **Slack** webhooks.

### 4. 3 Connected Sample Meetings (`GET /api/samples`)
1. **Meeting 1 (Mon - Product Kickoff)**:
   - Locks Payments API on **Stripe**.
   - Target v1 launch: **Nov 28, 2026** (Owner: Rahul).
   - Priya owns Auth flow (due **Nov 25, 2026**).
2. **Meeting 2 (Wed - Tech Sync)**:
   - Priya switches Payments API to **Razorpay** due to Stripe KYC delays.
   - Rahul moves v1 launch to **Dec 5, 2026** due to gateway rebuild.
   - Ankit assigned API webhook testing (due **Dec 2, 2026**).
   - ⚡ **Triggers 2 HIGH severity memory conflicts** against Meeting 1.
3. **Meeting 3 (Fri - Design & QA Sync)**:
   - Confirms Razorpay sandbox is live and verified.
   - Identifies critical Onboarding UI task with missing owner and deadline -> **Flagged in AMBER**.

---

## 📡 API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server status and active AI provider |
| `GET` | `/api/samples` | Pre-loaded 3 connected sample meetings |
| `POST` | `/api/ingest` | 4-step pipeline: Parse -> Extract -> Conflict Audit -> Stage |
| `GET` | `/api/pending` | List pending staged ingestions awaiting approval |
| `GET` | `/api/pending/{session_id}` | Retrieve details of a staged session |
| `POST` | `/api/approve` | Human-in-the-loop gate: commit decisions & tasks, resolve conflicts, push to GitHub/Kanban |
| `GET` | `/api/memory` | Cross-meeting decision ledger (filter: `active`, `superseded`, `all`) |
| `GET` | `/api/tasks` | Cross-meeting Kanban tasks (filter: `status`, `owner`) |
| `PATCH` | `/api/tasks/{id}` | Update task status (`todo`, `in_progress`, `done`), owner, or deadline |
| `GET` | `/api/reminders` | Pre-deadline radar (`critical_2h`, `warning_24h`, `upcoming`, `overdue`) |
| `POST` | `/api/reminders/simulate` | Simulate deadline check at arbitrary reference time + optional webhook alert |
| `GET` | `/api/digest/{person}` | Weekly personalized digest (active tasks, deadlines, conflicts, decisions) |
| `GET` | `/api/settings` | Read configured credentials (masked) and active engine |
| `POST` | `/api/settings` | Update Groq/Gemini keys, GitHub repo/token, and Webhook URL |
| `POST` | `/api/reset` | Clear database memory for clean test execution |

---

## 🧪 Automated Verification Suite
Run the test suite verifying all 12 backend operations:
```bash
python test_backend.py
```
Outputs:
```text
✓ Health Check Passed: online | AI Provider: Smart Deterministic Fallback Analyzer
✓ Database Reset Passed
✓ GET /api/samples returned 3 connected meetings
✓ Meeting 1 Ingest Trace Steps: 4
✓ Meeting 1 Extracted Decisions: ['Payments API: Stripe', 'v1 Launch Date: 2026-11-28']
✓ Meeting 1 Extracted Tasks: ['Auth flow and user onboarding authentication (Owner: Priya, Due: 2026-11-25)']
✓ Meeting 1 Approved and committed to SQLite memory.
✓ Detected 2 conflict(s) against Meeting 1 in SQLite memory:
  -> Conflict: Payments API | Existing: 'Stripe' vs Proposed: 'Razorpay'
  -> Conflict: v1 Launch Date | Existing: '2026-11-28' vs Proposed: '2026-12-05'
✓ Meeting 2 Approved: 2 decisions committed, 2 superseded.
✓ Meeting 3 Tasks Extracted: AMBER FLAG on 'Finalize onboarding UI before launch' (Owner: None, Due: None)
✓ GET /api/tasks returned 3 Kanban tasks & PATCH task status verified
✓ 2h Critical Pre-deadline alert simulated
✓ Weekly Digests verified for Priya, Rahul, and Ankit
✓ Settings updated and verified
ALL 12 BACKEND TESTS PASSED WITH 100% SUCCESS!
```
