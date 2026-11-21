import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("execpulse.github")

class GitHubService:
    """
    Handles automatic creation of GitHub Issues for approved action items.
    """

    @classmethod
    def create_issue(cls, repo: str, token: str, task: Dict[str, Any], meeting_title: Optional[str] = None) -> Dict[str, Any]:
        """
        Creates a GitHub Issue in the specified repository (e.g. 'owner/repo').
        Returns dict with success status, issue_url, and issue_number.
        """
        if not repo or "/" not in repo or not token:
            return {"success": False, "error": "Missing or invalid GITHUB_REPO or GITHUB_TOKEN"}

        url = f"https://api.github.com/repos/{repo.strip()}/issues"
        headers = {
            "Authorization": f"Bearer {token.strip()}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ExecPulse-Agent"
        }

        owner_str = task.get("owner") or "Unassigned"
        due_str = task.get("due_date") or "TBD"
        priority_str = (task.get("priority") or "medium").upper()
        
        body_content = f"""### 🎯 ExecPulse Action Item
**Task**: {task.get('title')}
**Assignee**: {owner_str}
**Due Date**: {due_str}
**Priority**: `{priority_str}`
**Origin**: {meeting_title or 'Meeting Sync'}

---
*Created automatically by [ExecPulse](https://github.com) Meeting-to-Execution Agent.*
"""
        labels = ["execpulse", f"priority:{priority_str.lower()}"]
        if task.get("flag_amber"):
            labels.append("needs-triage")

        payload = {
            "title": f"[{priority_str}] {task.get('title')}",
            "body": body_content,
            "labels": labels
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=8)
            if resp.status_code in [200, 201]:
                data = resp.json()
                return {
                    "success": True,
                    "issue_url": data.get("html_url"),
                    "issue_number": data.get("number")
                }
            else:
                logger.warning(f"GitHub API returned {resp.status_code}: {resp.text}")
                return {"success": False, "error": f"GitHub returned {resp.status_code}: {resp.text}"}
        except Exception as e:
            logger.warning(f"Failed to post to GitHub: {e}")
            return {"success": False, "error": str(e)}
