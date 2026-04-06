import os
import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer

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
            accounts.append({
                "uid": source.get_uid(),
                "display_name": source.get_display_name(),
                "enabled": source.get_enabled()
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
            except:
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
