import logging
import json
from typing import Optional, List, Dict, Any

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer, EBook, EBookContacts

logger = logging.getLogger(__name__)

def search_contacts_logic(query: str) -> str:
    """Searches for contacts in the Evolution address book."""
    try:
        registry = EDataServer.SourceRegistry.new_sync(None)
        sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_ADDRESS_BOOK)
        all_contacts = []
        for source in sources:
            if not source.get_enabled(): continue
            try:
                client = EBook.BookClient.connect_sync(source, 30, None)
                # SEXP search filter
                sexp = f"(or (contains \"full_name\" \"{query}\") (contains \"email\" \"{query}\"))"
                _, contacts = client.get_contacts_sync(sexp, None)
                for contact in contacts:
                    all_contacts.append({
                        "full_name": contact.get_property("full-name"),
                        "emails": [contact.get_property(f"email-{i}") for i in range(1, 5) if contact.get_property(f"email-{i}")],
                        "phone": contact.get_property("business-phone"),
                        "source": source.get_display_name()
                    })
            except Exception as e:
                logger.exception(f"Failed to search address book '{source.get_display_name()}'")
                continue
        return json.dumps(all_contacts, indent=2)
    except Exception as e:
        logger.exception("Failed to search contacts")
        return f"Error: {e}"