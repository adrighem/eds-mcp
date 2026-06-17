"""Daily summary composition helpers.

This module intentionally has no GI imports. Keeping orchestration logic here
lets contributors test the daily-summary behavior without a running Evolution
session or PyGObject system packages.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Optional

AsyncLogic = Callable[..., Awaitable[str]]


def format_daily_summary(
    calendar_summary: str,
    task_summary: str,
    mail_summary: str,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Format already-collected summary sections as markdown."""
    current_time = now or datetime.now()
    return "\n".join([
        "# Daily Summary",
        f"Date: {current_time.strftime('%A, %d %B %Y')}",
        "",
        "## \N{CALENDAR} Calendar",
        calendar_summary,
        "",
        "## \N{WHITE HEAVY CHECK MARK} Tasks",
        task_summary,
        "",
        mail_summary,
    ])


async def resolve_primary_mail_account_uid(
    list_mail_accounts: AsyncLogic,
) -> Optional[str]:
    """Return the first available mail account UID from the mail resource."""
    try:
        accounts = json.loads(await list_mail_accounts())
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(accounts, list) or not accounts:
        return None

    first_account = accounts[0]
    if not isinstance(first_account, dict):
        return None

    uid = first_account.get("uid")
    return uid if isinstance(uid, str) and uid else None


async def get_daily_summary_logic(
    get_calendar_events: AsyncLogic,
    get_tasks: AsyncLogic,
    list_mail_accounts: AsyncLogic,
    get_emails: AsyncLogic,
    *,
    account_uid: Optional[str] = None,
    now: Optional[datetime] = None,
) -> str:
    """Build the daily summary from calendar, task, and mail logic functions."""
    calendar_summary = await get_calendar_events(date="today", summary_only=True)
    task_summary = await get_tasks(date="today", summary_only=True)

    resolved_account_uid = account_uid
    if not resolved_account_uid:
        resolved_account_uid = await resolve_primary_mail_account_uid(list_mail_accounts)

    if resolved_account_uid:
        mail_summary = await get_emails(
            resolved_account_uid,
            limit=10,
            format="summary",
        )
    else:
        mail_summary = "_No mail account identified for summary._"

    return format_daily_summary(
        calendar_summary,
        task_summary,
        mail_summary,
        now=now,
    )
