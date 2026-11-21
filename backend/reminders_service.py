import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

from database import get_all_tasks, get_all_settings
from models import ReminderTask, RemindersResponse
from webhook_service import WebhookService

def parse_date_safely(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    # Try ISO formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y"
    ]:
        try:
            dt = datetime.strptime(date_str, fmt)
            if fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"]:
                dt = dt.replace(hour=18, minute=0, second=0)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
            
    # Try text format e.g. "Nov 25, 2026"
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s*(\d{4}))?", date_str)
    if m:
        mon_str = m.group(1)[:3].lower()
        if mon_str in month_map:
            month = month_map[mon_str]
            day = int(m.group(2))
            year = int(m.group(3)) if m.group(3) else 2026
            # Standardize deadline to 18:00 (end of workday)
            return datetime(year, month, day, 18, 0, 0, tzinfo=timezone.utc)
            
    return None

class RemindersService:
    @classmethod
    def get_reminders(cls, simulated_date_str: Optional[str] = None) -> RemindersResponse:
        """
        Calculates upcoming, 24h warning, 2h critical, and overdue reminders.
        Can use current time or simulated date (useful for verifying Nov 2026 sample flow).
        """
        if simulated_date_str:
            ref_dt = parse_date_safely(simulated_date_str) or datetime.now(timezone.utc)
        else:
            ref_dt = datetime.now(timezone.utc)

        # Get all non-completed tasks
        all_tasks = get_all_tasks()
        active_tasks = [t for t in all_tasks if (t.get("status") or "").lower() != "done"]

        critical_2h: List[ReminderTask] = []
        warning_24h: List[ReminderTask] = []
        overdue: List[ReminderTask] = []
        upcoming: List[ReminderTask] = []

        for task in active_tasks:
            due_str = task.get("due_date")
            if not due_str:
                continue

            due_dt = parse_date_safely(due_str)
            if not due_dt:
                continue

            diff = due_dt - ref_dt
            hours = diff.total_seconds() / 3600.0

            if hours < 0:
                urgency = "overdue"
                hrs_overdue = abs(int(hours))
                time_rem = f"{hrs_overdue}h overdue" if hrs_overdue > 0 else "Just overdue"
                item = ReminderTask(
                    task_id=task["id"],
                    title=task["title"],
                    owner=task.get("owner"),
                    due_date=due_str,
                    time_remaining=time_rem,
                    urgency=urgency,
                    hours_remaining=round(hours, 1)
                )
                overdue.append(item)
            elif 0 <= hours <= 2.0:
                urgency = "critical_2h"
                mins = max(1, int(hours * 60))
                time_rem = f"{mins}m remaining"
                item = ReminderTask(
                    task_id=task["id"],
                    title=task["title"],
                    owner=task.get("owner"),
                    due_date=due_str,
                    time_remaining=time_rem,
                    urgency=urgency,
                    hours_remaining=round(hours, 1)
                )
                critical_2h.append(item)
            elif 2.0 < hours <= 24.0:
                urgency = "warning_24h"
                hrs = int(hours)
                time_rem = f"{hrs}h remaining"
                item = ReminderTask(
                    task_id=task["id"],
                    title=task["title"],
                    owner=task.get("owner"),
                    due_date=due_str,
                    time_remaining=time_rem,
                    urgency=urgency,
                    hours_remaining=round(hours, 1)
                )
                warning_24h.append(item)
            elif 24.0 < hours <= 168.0:  # Within 7 days
                urgency = "upcoming"
                days = int(hours / 24.0)
                time_rem = f"{days}d remaining"
                item = ReminderTask(
                    task_id=task["id"],
                    title=task["title"],
                    owner=task.get("owner"),
                    due_date=due_str,
                    time_remaining=time_rem,
                    urgency=urgency,
                    hours_remaining=round(hours, 1)
                )
                upcoming.append(item)

        total = len(critical_2h) + len(warning_24h) + len(overdue) + len(upcoming)

        return RemindersResponse(
            reference_time=ref_dt.isoformat(),
            total_reminders=total,
            critical_2h=critical_2h,
            warning_24h=warning_24h,
            overdue=overdue,
            upcoming=upcoming
        )

    @classmethod
    def simulate_and_dispatch(cls, simulated_date_str: Optional[str] = None, send_webhook: bool = True) -> Tuple[RemindersResponse, bool, Optional[str]]:
        reminders = cls.get_reminders(simulated_date_str)
        webhook_sent = False
        webhook_msg = None

        if send_webhook:
            settings = get_all_settings()
            webhook_url = settings.get("WEBHOOK_URL")
            webhook_type = settings.get("WEBHOOK_TYPE", "auto")

            if webhook_url:
                res = WebhookService.notify_reminders(
                    webhook_url=webhook_url,
                    webhook_type=webhook_type,
                    reference_time=reminders.reference_time,
                    critical_count=len(reminders.critical_2h),
                    warning_count=len(reminders.warning_24h),
                    overdue_count=len(reminders.overdue)
                )
                webhook_sent = res.get("sent", False)
                webhook_msg = str(res)
            else:
                webhook_msg = "No webhook URL configured in settings."

        return reminders, webhook_sent, webhook_msg
