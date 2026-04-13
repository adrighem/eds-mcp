import os
import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer  # noqa: E402

logger = logging.getLogger(__name__)

def get_mail_db_path(account_uid: str) -> Optional[str]:
    """Resolves the SQLite database path for a given Evolution mail account."""
    potential_paths = [
        os.path.expanduser(f"~/.cache/evolution/mail/{account_uid}/folders.db"),
        os.path.expanduser(f"~/.local/share/evolution/mail/{account_uid}/folders.db")
    ]
    for path in potential_paths:
        if os.path.exists(path):
            return path
    return None

def list_mail_accounts_logic() -> str:
    """Lists all configured email accounts."""
    try:
        registry = EDataServer.SourceRegistry.new_sync(None)
        sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_MAIL_ACCOUNT)
        accounts = []
        for source in sources:
            if source.get_enabled():
                accounts.append({
                    "uid": source.get_uid(),
                    "name": source.get_display_name()
                })
        return json.dumps(accounts, indent=2)
    except Exception as e:
        logger.exception("Failed to list mail accounts")
        return f"Error: {e}"

def list_mail_folders_logic(account_uid: str) -> str:
    """Lists folders for a specific mail account."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT folder_name, unread_count, visible_count FROM folders")
        folders = []
        for row in cursor.fetchall():
            folders.append({
                "name": row[0],
                "unread": row[1],
                "total": row[2]
            })
        conn.close()
        return json.dumps(folders, indent=2)
    except Exception as e:
        logger.exception(f"Database error for account {account_uid}")
        return f"Error: {e}"

def get_emails_logic(account_uid: str, folder_name: str = "Inbox", limit: int = 10) -> str:
    """Gets recent emails from a specific folder with validation."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Security: Validate folder name exists in the database before using it in a query
        cursor.execute("SELECT folder_name FROM folders WHERE folder_name = ?", (folder_name,))
        if not cursor.fetchone():
            conn.close()
            return f"Error: Folder '{folder_name}' not found in account {account_uid}"

        # Safe to use folder_name as table name now as we've verified it exists in the 'folders' metadata table
        query = f"SELECT uid, subject, mail_from, dreceived, preview FROM '{folder_name}' ORDER BY dreceived DESC LIMIT ?"
        cursor.execute(query, (limit,))

        emails = []
        for row in cursor.fetchall():
            try:
                date_str = datetime.fromtimestamp(row[3]).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                date_str = str(row[3])

            emails.append({
                "uid": row[0],
                "subject": row[1],
                "from": row[2],
                "date": date_str,
                "preview": row[4]
            })
        conn.close()
        return json.dumps(emails, indent=2)
    except Exception as e:
        logger.exception(f"Failed to fetch emails from {folder_name}")
        return f"Error: {e}"

def search_emails_logic(account_uid: str, query: str, folder_name: Optional[str] = None, limit: int = 10) -> str:
    """Searches emails for a specific query across all folders or a specific folder."""
    db_path = get_mail_db_path(account_uid)
    if not db_path:
        return f"Error: Could not find mail database for account {account_uid}"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        folders_to_search = []
        if folder_name:
            cursor.execute("SELECT folder_name FROM folders WHERE folder_name = ?", (folder_name,))
            if not cursor.fetchone():
                conn.close()
                return f"Error: Folder '{folder_name}' not found in account {account_uid}"
            folders_to_search.append(folder_name)
        else:
            cursor.execute("SELECT folder_name FROM folders")
            folders_to_search = [row[0] for row in cursor.fetchall()]

        emails = []
        search_pattern = f"%{query}%"

        for folder in folders_to_search:
            # Verify table exists to prevent SQL injection or missing tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (folder,))
            if not cursor.fetchone():
                continue

            sql = f"""
                SELECT uid, subject, mail_from, dreceived, preview, '{folder}' as folder
                FROM '{folder}'
                WHERE subject LIKE ? OR preview LIKE ? OR mail_from LIKE ?
                ORDER BY dreceived DESC
                LIMIT ?
            """
            cursor.execute(sql, (search_pattern, search_pattern, search_pattern, limit))

            for row in cursor.fetchall():
                try:
                    date_str = datetime.fromtimestamp(row[3]).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    date_str = str(row[3])

                emails.append({
                    "uid": row[0],
                    "subject": row[1],
                    "from": row[2],
                    "date": date_str,
                    "preview": row[4],
                    "folder": row[5]
                })

        # Sort combined results by date descending and take top 'limit'
        emails.sort(key=lambda x: x['date'], reverse=True)
        emails = emails[:limit]

        conn.close()
        return json.dumps(emails, indent=2)
    except Exception as e:
        logger.exception(f"Failed to search emails for query '{query}'")
        return f"Error: {e}"
