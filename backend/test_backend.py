import sys
from fastapi.testclient import TestClient
from main import app
from database import init_db, reset_database

def run_tests():
    with TestClient(app) as client:
        print("=" * 60)
        print("Starting ExecPulse Backend Integration & Verification Tests")
        print("=" * 60)

        # 1. Health check & UI Route
        res = client.get("/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        health_data = res.json()
        print("✓ Health Check Passed:", health_data["status"], "| AI Provider:", health_data["ai_engine"])

        res_ui = client.get("/ui")
        assert res_ui.status_code == 200, f"UI route failed: {res_ui.status_code}"
        assert "Sankalp" in res_ui.text, "Expected 'Sankalp' in UI response"
        assert "<!DOCTYPE html>" in res_ui.text, "Expected HTML doctype in UI response"
        print("✓ GET /ui successfully serving frontend/sankalp.html")

        # Verify banner asset serving
        res_banner = client.get("/sankalp-banner.png")
        assert res_banner.status_code == 200, f"Banner route failed: {res_banner.status_code}"
        assert res_banner.headers["content-type"] == "image/png"
        res_ui_banner = client.get("/ui/sankalp-banner.png")
        assert res_ui_banner.status_code == 200
        res_static_banner = client.get("/static/sankalp-banner.png")
        assert res_static_banner.status_code == 200
        print("✓ GET /sankalp-banner.png, /ui/sankalp-banner.png & /static/sankalp-banner.png successfully serving banner")

        # 2. Reset database for clean testing run
        res = client.post("/api/reset?preserve_settings=false")
        assert res.status_code == 200
        print("✓ Database Reset Passed")

        # 3. GET /api/samples
        res = client.get("/api/samples")
        assert res.status_code == 200
        samples = res.json()["samples"]
        assert len(samples) == 3, f"Expected 3 sample meetings, got {len(samples)}"
        print(f"✓ GET /api/samples returned {len(samples)} connected meetings")

        meet1 = samples[0]
        meet2 = samples[1]
        meet3 = samples[2]

        # 4. Ingest Meeting 1 (Product Kickoff - Mon)
        print("\n--- Testing Meeting 1 Ingestion (Kickoff) ---")
        res = client.post("/api/ingest", json={
            "transcript": meet1["transcript"],
            "meeting_title": meet1["title"],
            "meeting_date": meet1["date"]
        })
        assert res.status_code == 200, f"Meeting 1 ingest failed: {res.text}"
        m1_data = res.json()
        assert len(m1_data["trace_steps"]) == 4, "Expected 4 trace steps"
        assert len(m1_data["staged_items"]["conflicts"]) == 0, "Meeting 1 should have 0 conflicts"
        assert len(m1_data["staged_items"]["decisions"]) >= 2, "Expected Payments API & Launch Date decisions"
        assert any("Stripe" in d["value"] for d in m1_data["staged_items"]["decisions"]), "Stripe should be extracted"
        assert any("2026-11-28" in d["value"] or "Nov 28" in d["value"] for d in m1_data["staged_items"]["decisions"]), "Nov 28 launch date should be extracted"
        assert any("Auth flow" in t["title"] for t in m1_data["staged_items"]["tasks"]), "Priya Auth flow task should be extracted"
        print("✓ Meeting 1 Ingest Trace Steps:", len(m1_data["trace_steps"]))
        print("✓ Meeting 1 Extracted Decisions:", [d["topic"] + ": " + d["value"] for d in m1_data["staged_items"]["decisions"]])
        print("✓ Meeting 1 Extracted Tasks:", [t["title"] + " (Owner: " + str(t["owner"]) + ", Due: " + str(t["due_date"]) + ")" for t in m1_data["staged_items"]["tasks"]])

        # 5. Approve Meeting 1
        m1_session_id = m1_data["session_id"]
        approve_m1_payload = {
            "session_id": m1_session_id,
            "meeting_title": meet1["title"],
            "meeting_date": meet1["date"],
            "approved_decisions": [
                {
                    "id": d["id"],
                    "topic": d["topic"],
                    "value": d["value"],
                    "category": d["category"],
                    "speaker": d["speaker"],
                    "reason": d["reason"],
                    "conflict_resolution": "none",
                    "approved": True
                } for d in m1_data["staged_items"]["decisions"]
            ],
            "approved_tasks": [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "owner": t["owner"],
                    "due_date": t["due_date"],
                    "priority": t["priority"],
                    "flag_amber": t["flag_amber"],
                    "approved": True
                } for t in m1_data["staged_items"]["tasks"]
            ],
            "push_to_github": False,
            "notify_webhook": False
        }
        res = client.post("/api/approve", json=approve_m1_payload)
        assert res.status_code == 200, f"Approve Meeting 1 failed: {res.text}"
        print("✓ Meeting 1 Approved and committed to SQLite memory.")

        # Verify SQLite memory after Meeting 1
        res = client.get("/api/memory?status=active")
        active_mems = res.json()
        assert len(active_mems) >= 2, "Expected at least 2 active decisions in SQLite memory"
        print("✓ Active memory records in SQLite:", [m["topic"] + " = " + m["value"] for m in active_mems])

        # 6. Ingest Meeting 2 (Tech Sync - Wed) -> MUST TRIGGER 2 CONFLICTS
        print("\n--- Testing Meeting 2 Ingestion (Tech Sync) ---")
        res = client.post("/api/ingest", json={
            "transcript": meet2["transcript"],
            "meeting_title": meet2["title"],
            "meeting_date": meet2["date"]
        })
        assert res.status_code == 200, f"Meeting 2 ingest failed: {res.text}"
        m2_data = res.json()
        conflicts = m2_data["staged_items"]["conflicts"]
        print(f"✓ Detected {len(conflicts)} conflict(s) against Meeting 1 in SQLite memory:")
        for c in conflicts:
            print(f"  -> Conflict: {c['topic']} | Existing: '{c['existing_value']}' vs Proposed: '{c['proposed_value']}' | Reason: {c['proposed_reason']}")
        
        assert len(conflicts) == 2, f"CRITICAL: Expected exactly 2 conflicts against Meeting 1, got {len(conflicts)}"
        
        # Verify conflict 1 is Payments API (Stripe -> Razorpay)
        payment_conflict = next((c for c in conflicts if "payment" in c["topic"].lower()), None)
        assert payment_conflict is not None, "Payments API conflict not found"
        assert "Stripe" in payment_conflict["existing_value"]
        assert "Razorpay" in payment_conflict["proposed_value"]

        # Verify conflict 2 is Launch Date (Nov 28 -> Dec 5)
        launch_conflict = next((c for c in conflicts if "launch" in c["topic"].lower() or "date" in c["topic"].lower()), None)
        assert launch_conflict is not None, "Launch date conflict not found"
        assert "2026-11-28" in launch_conflict["existing_value"] or "Nov 28" in launch_conflict["existing_value"]
        assert "2026-12-05" in launch_conflict["proposed_value"] or "Dec 5" in launch_conflict["proposed_value"]

        # 7. Approve Meeting 2 with "supersede" resolution
        m2_session_id = m2_data["session_id"]
        approve_m2_payload = {
            "session_id": m2_session_id,
            "meeting_title": meet2["title"],
            "meeting_date": meet2["date"],
            "approved_decisions": [
                {
                    "id": d["id"],
                    "topic": d["topic"],
                    "value": d["value"],
                    "category": d["category"],
                    "speaker": d["speaker"],
                    "reason": d["reason"],
                    "conflict_resolution": "supersede",
                    "conflicting_decision_id": d.get("conflicts_with"),
                    "approved": True
                } for d in m2_data["staged_items"]["decisions"]
            ],
            "approved_tasks": [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "owner": t["owner"],
                    "due_date": t["due_date"],
                    "priority": t["priority"],
                    "flag_amber": t["flag_amber"],
                    "approved": True
                } for t in m2_data["staged_items"]["tasks"]
            ],
            "push_to_github": False,
            "notify_webhook": False
        }
        res = client.post("/api/approve", json=approve_m2_payload)
        assert res.status_code == 200, f"Approve Meeting 2 failed: {res.text}"
        appr_res = res.json()
        assert appr_res["decisions_superseded"] == 2, f"Expected 2 superseded decisions, got {appr_res['decisions_superseded']}"
        print(f"✓ Meeting 2 Approved: {appr_res['decisions_committed']} decisions committed, {appr_res['decisions_superseded']} superseded.")

        # Verify memory after Meeting 2
        res = client.get("/api/memory?status=active")
        active_mems_2 = res.json()
        res_superseded = client.get("/api/memory?status=superseded")
        superseded_mems = res_superseded.json()
        assert len(superseded_mems) == 2, f"Expected 2 superseded records, got {len(superseded_mems)}"
        print("✓ Current Active Decisions in SQLite:", [m["topic"] + " = " + m["value"] for m in active_mems_2])
        print("✓ Superseded Decisions in SQLite:", [m["topic"] + " = " + m["value"] + " (Superseded by " + str(m["superseded_by_id"]) + ")" for m in superseded_mems])

        # 8. Ingest Meeting 3 (Design & QA Sync - Fri) -> MUST FLAG AMBER ON MISSING OWNER/DEADLINE
        print("\n--- Testing Meeting 3 Ingestion (Design & QA Sync) ---")
        res = client.post("/api/ingest", json={
            "transcript": meet3["transcript"],
            "meeting_title": meet3["title"],
            "meeting_date": meet3["date"]
        })
        assert res.status_code == 200, f"Meeting 3 ingest failed: {res.text}"
        m3_data = res.json()
        m3_tasks = m3_data["staged_items"]["tasks"]
        amber_tasks = [t for t in m3_tasks if t["flag_amber"]]
        print(f"✓ Meeting 3 Tasks Extracted: {len(m3_tasks)} total, {len(amber_tasks)} flagged in amber:")
        for at in amber_tasks:
            print(f"  -> AMBER FLAG: '{at['title']}' | Owner: {at['owner']} | Due: {at['due_date']} | Amber: {at['flag_amber']}")

        assert len(amber_tasks) >= 1, "Expected at least 1 amber flagged task in Meeting 3"
        onboarding_task = next((t for t in amber_tasks if "onboarding ui" in t["title"].lower()), None)
        assert onboarding_task is not None, "Onboarding UI task must be flagged in amber"
        assert onboarding_task["flag_amber"] is True
        assert onboarding_task["owner"] is None or onboarding_task["missing_owner"] is True

        # Approve Meeting 3
        res = client.post("/api/approve", json={
            "session_id": m3_data["session_id"],
            "meeting_title": meet3["title"],
            "meeting_date": meet3["date"],
            "approved_decisions": [
                {
                    "id": d["id"],
                    "topic": d["topic"],
                    "value": d["value"],
                    "category": d["category"],
                    "speaker": d["speaker"],
                    "reason": d["reason"],
                    "conflict_resolution": "none",
                    "approved": True
                } for d in m3_data["staged_items"]["decisions"]
            ],
            "approved_tasks": [
                {
                    "id": t["id"],
                    "title": t["title"],
                    "owner": t["owner"],
                    "due_date": t["due_date"],
                    "priority": t["priority"],
                    "flag_amber": t["flag_amber"],
                    "approved": True
                } for t in m3_data["staged_items"]["tasks"]
            ],
            "push_to_github": False,
            "notify_webhook": False
        })
        assert res.status_code == 200
        print("✓ Meeting 3 Approved and committed.")

        # 9. Test Kanban Tasks Endpoints
        print("\n--- Testing Kanban Tasks API ---")
        res = client.get("/api/tasks")
        assert res.status_code == 200
        all_tasks = res.json()
        assert len(all_tasks) >= 3, f"Expected at least 3 tasks, got {len(all_tasks)}"
        print(f"✓ GET /api/tasks returned {len(all_tasks)} Kanban tasks")

        # Test PATCH task status
        task_to_update = all_tasks[0]
        res = client.patch(f"/api/tasks/{task_to_update['id']}", json={"status": "in_progress"})
        assert res.status_code == 200
        updated_t = res.json()
        assert updated_t["status"] == "in_progress"
        print(f"✓ PATCH /api/tasks/{task_to_update['id']} moved status to 'in_progress'")

        # 10. Test Reminders & Pre-Deadline simulation
        print("\n--- Testing Reminders API & Simulation ---")
        # Simulate at 2026-11-25 10:00:00 (Auth flow due 2026-11-25 18:00:00 -> 8h remaining -> warning_24h)
        res = client.post("/api/reminders/simulate", json={
            "simulated_date": "2026-11-25T10:00:00",
            "send_webhook": False
        })
        assert res.status_code == 200
        remind_data = res.json()
        assert "reminders" in remind_data
        print("✓ Reminders Simulation at 2026-11-25T10:00:00:", {
            "critical_2h": len(remind_data["reminders"]["critical_2h"]),
            "warning_24h": len(remind_data["reminders"]["warning_24h"]),
            "upcoming": len(remind_data["reminders"]["upcoming"]),
            "overdue": len(remind_data["reminders"]["overdue"])
        })

        # Simulate at 2026-11-25 17:00:00 (1h before 18:00:00 -> critical_2h!)
        res = client.post("/api/reminders/simulate", json={
            "simulated_date": "2026-11-25T17:00:00",
            "send_webhook": False
        })
        assert res.status_code == 200
        remind_data_critical = res.json()
        assert len(remind_data_critical["reminders"]["critical_2h"]) >= 1, "Expected critical 2h reminder"
        print("✓ 2h Critical Pre-deadline alert triggered:", remind_data_critical["reminders"]["critical_2h"][0]["title"], "-", remind_data_critical["reminders"]["critical_2h"][0]["time_remaining"])

        # 11. Test Weekly Digest per Person
        print("\n--- Testing Weekly Digest API ---")
        for person in ["Priya", "Rahul", "Ankit"]:
            res = client.get(f"/api/digest/{person}")
            assert res.status_code == 200, f"Digest for {person} failed: {res.text}"
            digest = res.json()
            assert digest["person"] == person
            print(f"✓ Digest for {person}: {digest['summary_stats']}")

        # 12. Test Settings API
        print("\n--- Testing Settings API ---")
        res = client.get("/api/settings")
        assert res.status_code == 200
        settings = res.json()
        print("✓ Settings check: active_ai_provider =", settings["active_ai_provider"])

        res = client.post("/api/settings", json={
            "github_repo": "testorg/testrepo",
            "webhook_type": "discord"
        })
        assert res.status_code == 200
        res = client.get("/api/settings")
        assert res.json()["github_repo"] == "testorg/testrepo"
        print("✓ Settings updated and verified.")

        print("\n" + "=" * 60)
        print("ALL 12 BACKEND TESTS PASSED WITH 100% SUCCESS!")
        print("=" * 60)

if __name__ == "__main__":
    run_tests()
