# Sankalp — Meeting-to-Execution Agent

> *Meetings end. Decisions don't.*  
> **Sankalp** turns messy, speaker-attributed meeting transcripts into confirmed cross-meeting decisions, assigned tasks, and deadlines while catching the exact moment a new meeting contradicts an earlier one.

---

## 🌟 Overview

Decisions made in meetings get lost the moment the call ends. Notes get buried, chats scroll away, and changed decisions silently contradict old ones.

**Sankalp** bridges the gap between conversation and execution with an autonomous agentic pipeline and a strict **human-in-the-loop confirmation gate**:
1. **Reads conversation transcripts** with speaker attribution.
2. **Extracts decisions, action items, owners, and deadlines** using an intelligent dual-engine LLM system (Groq `llama-3.3-70b-versatile` or Gemini 1.5 Flash) with an autonomous **Smart Deterministic Fallback Analyzer** (100% functional without API keys).
3. **Audits cross-meeting memory** in SQLite to detect clashes (e.g. gateway switches like Stripe vs. Razorpay or deadline shifts).
4. **Human-in-the-Loop Confirmation Gate**: No AI-generated task or decision touches the tracker until a human reviews and approves it via a tactile hold-to-approve gesture.
5. **Execution & Tracker Push**: Commits decisions to persistent memory, supersedes outdated records, logs tasks to Kanban, and optionally creates GitHub Issues.
6. **Pre-deadline Reminders**: Alerts owners ahead of deadlines (24h warning, 2h critical) with webhook support.
7. **Personalized Weekly Digest**: Compiles individual recaps for teammates every week.

---

## 🏗️ Architecture

```
                                  +-----------------------------------------------+
                                  |            Sankalp Web UI (/ui)              |
                                  |    (Single-page reactive app with 3D scene,   |
                                  |   memory graph, hold-to-approve gate, digest) |
                                  +-----------------------+-----------------------+
                                                          | HTTP REST / JSON
                                                          v
+-------------------------------------------------------------------------------------------------------------------+
|                                            FastAPI Backend (Port 8000)                                            |
|                                                                                                                   |
|  POST /api/ingest                  POST /api/approve                   GET /api/tasks      GET /api/digest/{name} |
|  - Step 1: Parse Speakers          - Commit Decisions                  - Kanban List       - Personalized Weekly  |
|  - Step 2: AI / Heuristic Extract  - Resolve Conflicts (Supersede)     - Status Updates      Digest               |
|  - Step 3: Conflict Memory Audit   - Commit Kanban Tasks               PATCH /api/tasks/{id}                      |
|  - Step 4: Staged Confirmation     - Optional GitHub & Webhooks        GET /api/reminders  GET /api/memory        |
+--------------------------------------------+-----------------------------------+----------------------------------+
                                             |                                   |
                                             v                                   v
                      +------------------------------+       +------------------------------------+
                      |    AI & Fallback Engine      |       |  SQLite Persistent Memory Ledger   |
                      | - Groq (llama-3.3-70b)       |       | - Decisions (Active & Superseded)  |
                      | - Gemini 1.5 Flash           |       | - Kanban Tasks & Amber Flags       |
                      | - Smart Deterministic Engine |       | - Conflict Audit Logs              |
                      +------------------------------+       | - Staged Confirmation Sessions     |
                                                             +------------------------------------+
```

### Component Details
- **Backend**: Python FastAPI with SQLite persistent cross-meeting memory, Pydantic data validation, and CORS enabled for all origins.
- **Frontend**: `frontend/sankalp.html` served directly at `http://127.0.0.1:8000/ui`, featuring a Three.js 3D scene, themes (Nightfall, Aurora, Ember), live SVG cross-meeting memory graph, tactile Hold-to-Approve button, and weekly digest.

---

## ⚡ Core Capabilities

### 1. Cross-Meeting Conflict Detection
When a decision is proposed in a new meeting (e.g. switching payment gateway to Razorpay or moving launch to Dec 10), Sankalp automatically audits SQLite memory against earlier decisions:
- Identifies contradicting topics (e.g. `Payments API: Stripe` vs `Razorpay`, `Launch Date: Dec 5` vs `Dec 10`).
- Flags the contradiction with full provenance: meeting origin, speaker, date, and rationale.
- Prompts the human reviewer to choose which decision stands (`Supersede` or `Keep`).

### 2. Human-in-the-Loop Confirmation Gate
AI recommendations remain in a staged state (`POST /api/ingest`) until explicitly approved (`POST /api/approve`).
- The reviewer selects how conflicts should be resolved.
- Pressing and holding the confirmation button commits decisions to memory, marks old decisions as `superseded`, and publishes tasks to the tracker.

### 3. Execution & Task Tracking
- Local SQLite-backed Kanban board with statuses (`todo`, `in_progress`, `done`).
- Automatically flags tasks in **Amber** if missing an assigned owner or deadline before launch.
- Optional automated issue creation in GitHub via GitHub REST API if `GITHUB_TOKEN` and `GITHUB_REPO` are configured.

### 4. Pre-Deadline Radar & Notifications
- Categorizes tasks into `critical_2h` (<= 2 hours), `warning_24h` (<= 24 hours), `overdue`, and `upcoming`.
- Supports simulation checks at arbitrary reference times (`POST /api/reminders/simulate`).
- Real-time notification dispatch to Discord or Slack webhooks.

### 5. Personalized Weekly Digest (`GET /api/digest/{person}`)
Provides individual team members with their duties, active tasks, upcoming deadlines, decisions owned, and conflicts involved.

---

## 🚀 Getting Started

### 1. Clone & Setup
```bash
git clone https://github.com/abhay123-shukla/sankalp-meeting-agent.git
cd sankalp-meeting-agent
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment (Optional)
Copy `.env.example` to `.env` to provide optional API keys or GitHub/Webhook tokens:
```bash
cp .env.example .env
```
*(If no API keys are provided, Sankalp automatically uses its built-in **Smart Deterministic Fallback Analyzer**, running 100% offline with zero external dependencies).*

### 4. Run the Application
You can run the server directly from the repository root:
```bash
uvicorn backend.main:app --reload
```
Or from within the `backend/` directory:
```bash
cd backend
uvicorn main:app --reload
```

- **Interactive UI**: Open [http://127.0.0.1:8000/ui](http://127.0.0.1:8000/ui)
- **API Documentation**: Open [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health Check**: Open [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 🧪 Running Automated Tests
Run the comprehensive verification test suite covering all 12 backend operations:
```bash
cd backend
python test_backend.py
```

Expected output:
```text
✓ Health Check Passed: online | AI Provider: Smart Deterministic Fallback Analyzer
✓ GET /ui successfully serving frontend/sankalp.html
✓ Database Reset Passed
✓ GET /api/samples returned 3 connected meetings
✓ Meeting 1 Ingestion: Extracted Stripe & Nov 28 decisions, Auth flow task
✓ Meeting 1 Approved: Committed to SQLite memory
✓ Meeting 2 Ingestion: Detected 2 conflicts against Meeting 1 (Stripe -> Razorpay, Nov 28 -> Dec 5)
✓ Meeting 2 Approved: Superseded Meeting 1 decisions, updated active memory
✓ Meeting 3 Ingestion: Detected Amber Flag on unassigned onboarding UI task
✓ Kanban Tasks API & Status Patching verified
✓ Reminders & 2h Pre-Deadline Alerts verified
✓ Weekly Digests verified for Priya, Rahul, and Ankit
✓ Settings Persistence verified
ALL 12 BACKEND TESTS PASSED WITH 100% SUCCESS!
```

---

## 📡 API Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/ui` | Serves the Sankalp single-page web app |
| `GET` | `/health` | System health and active AI engine |
| `GET` | `/api/samples` | 3 connected sample meetings demonstrating conflict detection |
| `POST` | `/api/ingest` | 4-step pipeline: Parse -> Extract -> Conflict Audit -> Stage |
| `GET` | `/api/pending` | List pending staged sessions awaiting confirmation |
| `POST` | `/api/approve` | Human-in-the-loop gate: commit decisions & tasks to memory |
| `GET` | `/api/memory` | Cross-meeting decision ledger (`active`, `superseded`, `all`) |
| `GET` | `/api/tasks` | Cross-meeting Kanban tasks |
| `PATCH` | `/api/tasks/{id}` | Update task status (`todo`, `in_progress`, `done`) or assignee |
| `GET` | `/api/reminders` | Pre-deadline radar (2h critical, 24h warning, overdue) |
| `POST` | `/api/reminders/simulate` | Trigger deadline simulation and webhook alert |
| `GET` | `/api/digest/{person}` | Personalized weekly digest for a teammate |
| `GET` | `/api/settings` | Read configured integration settings (masked) |
| `POST` | `/api/settings` | Update API keys, GitHub credentials, or webhooks |
| `POST` | `/api/reset` | Clear database memory for clean test runs |

---

## 📜 License
MIT License. Built for seamless meeting-to-execution workflows.
