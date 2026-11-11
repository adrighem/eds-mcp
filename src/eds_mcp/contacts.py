"""Contact search logic across Evolution Data Server address books."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .env import setup_environment

setup_environment()

from gi.repository import EBook, EDataServer, GLib  # noqa: E402

from . import (  # noqa: E402
    ErrorCode,
    ValidationError,
    error_envelope,
    error_from_exception,
    paginated_envelope,
)

logger = logging.getLogger(__name__)


async def search_contacts_logic(
    query: str,
    limit: int = 25,
    offset: int = 0,
) -> str:
    """Searches for contacts in the Evolution address book by name or email."""
    stripped_query = query.strip() if query else ""
    if not stripped_query:
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            "Search query cannot be empty.",
            hint="Provide a name, email address, or search fragment.",
        )
    if limit < 1 or limit > 200:
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            "Limit must be between 1 and 200.",
            hint="Choose a limit within [1, 200].",
        )
    if offset < 0:
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            "Offset must be >= 0.",
        )

    def _logic() -> str:
        try:
            registry = EDataServer.SourceRegistry.new_sync(None)
            sources = registry.list_sources(EDataServer.SOURCE_EXTENSION_ADDRESS_BOOK)
            all_contacts: list[dict[str, Any]] = []

            safe_query = stripped_query.replace("\\", "\\\\").replace('"', '\\"')
            sexp = f'(or (contains "full_name" "{safe_query}") (contains "email" "{safe_query}"))'

            for source in sources:
                if not source.get_enabled():
                    continue
                book_name = source.get_display_name()
                try:
                    client = EBook.BookClient.connect_sync(source, 30, None)
                    _, contacts = client.get_contacts_sync(sexp, None)

                    for contact in contacts:
                        full_name = contact.get_property("full-name")
                        name = full_name.strip() if full_name else ""
                        emails = [
                            contact.get_property(f"email-{i}").strip()
                            for i in range(1, 5)
                            if contact.get_property(f"email-{i}")
                        ]
                        c_data: dict[str, Any] = {
                            "name": name,
                            "emails": emails,
                            "book": book_name,
                        }
                        phone = contact.get_property("business-phone")
                        if phone and phone.strip():
                            c_data["phone"] = phone.strip()
                        all_contacts.append(c_data)

                except (GLib.Error, RuntimeError) as e:
                    logger.warning("Failed to search address book '%s': %s", book_name, e)
                    continue

            all_contacts.sort(key=lambda c: (c.get("name", "").casefold(), c.get("book", "")))
            total = len(all_contacts)
            sliced = all_contacts[offset : offset + limit]
            return paginated_envelope(sliced, total=total, offset=offset)

        except (GLib.Error, RuntimeError, ValidationError) as e:
            logger.exception("Failed to search contacts")
            return error_from_exception(e)

    return await asyncio.to_thread(_logic)
