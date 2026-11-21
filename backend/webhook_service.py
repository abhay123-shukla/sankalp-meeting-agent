import requests
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("execpulse.webhook")

class WebhookService:
    """
    Dispatches rich notifications to Slack or Discord webhooks.
    """

    @classmethod
    def send_notification(cls, webhook_url: str, webhook_type: str = "auto", title: str = "", message: str = "", fields: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
        if not webhook_url or not webhook_url.startswith("http"):
            return {"sent": False, "reason": "No valid webhook URL provided"}

        is_discord = ("discord.com" in webhook_url) or (webhook_type.lower() == "discord")
        is_slack = ("slack.com" in webhook_url) or (webhook_type.lower() == "slack")

        if not is_discord and not is_slack:
            # Default heuristic
            if "discord" in webhook_url:
                is_discord = True
            else:
                is_slack = True

        try:
            if is_discord:
                # Discord embed format
                embed = {
                    "title": title or "ExecPulse Notification",
                    "description": message,
                    "color": 0x4F46E5,  # Indigo
                    "footer": {"text": "ExecPulse — Meeting-to-Execution Agent"}
                }
                if fields:
                    embed["fields"] = [{"name": f["name"], "value": f["value"], "inline": f.get("inline", True)} for f in fields]
                payload = {"embeds": [embed]}
            else:
                # Slack block format
                slack_blocks = [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": title or "ExecPulse Notification", "emoji": True}
                    },
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": message}
                    }
                ]
                if fields:
                    slack_fields = [{"type": "mrkdwn", "text": f"*{f['name']}*\n{f['value']}"} for f in fields]
                    slack_blocks.append({"type": "section", "fields": slack_fields[:10]})
                payload = {"blocks": slack_blocks, "text": f"{title}: {message}"}

            resp = requests.post(webhook_url, json=payload, timeout=8)
            if resp.status_code in [200, 204]:
                return {"sent": True, "status_code": resp.status_code}
            else:
                logger.warning(f"Webhook post returned {resp.status_code}: {resp.text}")
                return {"sent": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            logger.warning(f"Webhook dispatch error: {e}")
            return {"sent": False, "error": str(e)}

    @classmethod
    def notify_approval(cls, webhook_url: str, webhook_type: str, meeting_title: str, decisions_count: int, superseded_count: int, tasks_count: int) -> Dict[str, Any]:
        title = f"🚀 ExecPulse: Meeting Approved ({meeting_title})"
        message = f"Executive approval confirmed for **{meeting_title}**. Memory ledger and Kanban board updated."
        fields = [
            {"name": "Decisions Locked", "value": f"{decisions_count} active", "inline": True},
            {"name": "Superseded Decisions", "value": f"{superseded_count} updated", "inline": True},
            {"name": "Tasks Created", "value": f"{tasks_count} in Kanban", "inline": True}
        ]
        return cls.send_notification(webhook_url, webhook_type, title, message, fields)

    @classmethod
    def notify_reminders(cls, webhook_url: str, webhook_type: str, reference_time: str, critical_count: int, warning_count: int, overdue_count: int) -> Dict[str, Any]:
        title = "⏰ ExecPulse: Execution Deadline Alert"
        message = f"Deadline radar check triggered for {reference_time}."
        fields = [
            {"name": "🚨 Critical (<= 2h)", "value": str(critical_count), "inline": True},
            {"name": "⚠️ Warning (<= 24h)", "value": str(warning_count), "inline": True},
            {"name": "⛔ Overdue", "value": str(overdue_count), "inline": True}
        ]
        return cls.send_notification(webhook_url, webhook_type, title, message, fields)
