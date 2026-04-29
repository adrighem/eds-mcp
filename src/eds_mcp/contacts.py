import logging
import json
import asyncio

# Initial setup must happen before imports that might trigger GI loading
from .env import setup_environment
setup_environment()

from gi.repository import EDataServer, EBook  # noqa: E402

logger = logging.getLogger(__name__)

async def search_contacts_logic(query: str) -> str:
    """Searches for contacts in the Evolution address book."""
    def _logic():
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_ADDRESS_BOOK)
            results = {}
            for source in sources:
                if not source.get_enabled():
                    continue
                try:
                    client = EBook.BookClient.connect_sync(source, 30, None)
                    # SEXP search filter
                    safe_query = query.replace('"', '\\"')
                    sexp = f"(or (contains \"full_name\" \"{safe_query}\") (contains \"email\" \"{safe_query}\"))"
                    _, contacts = client.get_contacts_sync(sexp, None)

                    book_contacts = []
                    for contact in contacts:
                        c_data = {
                            "name": contact.get_property("full-name").strip() if contact.get_property("full-name") else ""
                        }
                        emails = [contact.get_property(f"email-{i}").strip() for i in range(1, 5) if contact.get_property(f"email-{i}")]
                        if emails:
                            c_data["emails"] = emails
                        phone = contact.get_property("business-phone")
                        if phone:
                            c_data["phone"] = phone.strip()

                        book_contacts.append(c_data)

                    if book_contacts:
                        results[source.get_display_name()] = book_contacts

                except Exception:
                    logger.exception(f"Failed to search address book '{source.get_display_name()}'")
                    continue
            return json.dumps(results, separators=(',', ':'))
        except Exception as e:
            logger.exception("Failed to search contacts")
            return f"Error: {e}"

    return await asyncio.to_thread(_logic)