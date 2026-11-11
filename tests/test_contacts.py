"""Isolated unit tests for contacts search and SEXP query handling."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from eds_mcp.env import setup_environment

setup_environment()

from gi.repository import GLib  # noqa: E402

from eds_mcp import contacts  # noqa: E402


@pytest.mark.asyncio
async def test_search_contacts_empty_query_returns_validation_error():
    res_raw = await contacts.search_contacts_logic("")
    res = json.loads(res_raw)
    assert "error" in res
    assert res["error"]["code"] == "VALIDATION_ERROR"
    assert "cannot be empty" in res["error"]["message"]

    res_whitespace = json.loads(await contacts.search_contacts_logic("   "))
    assert res_whitespace["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_search_contacts_invalid_bounds_return_validation_error():
    res_zero = json.loads(await contacts.search_contacts_logic("alice", limit=0))
    assert res_zero["error"]["code"] == "VALIDATION_ERROR"

    res_large = json.loads(await contacts.search_contacts_logic("alice", limit=250))
    assert res_large["error"]["code"] == "VALIDATION_ERROR"

    res_offset = json.loads(await contacts.search_contacts_logic("alice", offset=-1))
    assert res_offset["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_search_contacts_escapes_sexp_quotes_and_backslashes(mocker):
    mock_registry = mocker.MagicMock()
    mock_source = mocker.MagicMock()
    mock_source.get_enabled.return_value = True
    mock_source.get_display_name.return_value = "Personal"
    mock_registry.list_sources.return_value = [mock_source]

    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)
    mock_client = mocker.MagicMock()
    mocker.patch("gi.repository.EBook.BookClient.connect_sync", return_value=mock_client)
    mock_client.get_contacts_sync.return_value = (True, [])

    await contacts.search_contacts_logic('user\\"test\\')
    called_sexp = mock_client.get_contacts_sync.call_args[0][0]
    # SEXP should escape backslashes and double quotes
    assert '\\"' in called_sexp
    assert "\\\\" in called_sexp


@pytest.mark.asyncio
async def test_search_contacts_deterministic_sorting_and_pagination(mocker):
    mock_registry = mocker.MagicMock()
    mock_source1 = mocker.MagicMock()
    mock_source1.get_enabled.return_value = True
    mock_source1.get_display_name.return_value = "Book B"

    mock_source2 = mocker.MagicMock()
    mock_source2.get_enabled.return_value = True
    mock_source2.get_display_name.return_value = "Book A"

    mock_registry.list_sources.return_value = [mock_source1, mock_source2]
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    def create_mock_contact(full_name: str, email: str) -> MagicMock:
        c = MagicMock()
        c.get_property.side_effect = lambda prop: (
            full_name if prop == "full-name" else (email if prop == "email-1" else None)
        )
        return c

    contacts_b = [create_mock_contact("Charlie", "charlie@example.com")]
    contacts_a = [
        create_mock_contact("alice", "alice@example.com"),
        create_mock_contact("Bob", "bob@example.com"),
    ]

    def mock_connect(source, timeout, cancellable):
        c = mocker.MagicMock()
        if source.get_display_name() == "Book A":
            c.get_contacts_sync.return_value = (True, contacts_a)
        else:
            c.get_contacts_sync.return_value = (True, contacts_b)
        return c

    mocker.patch("gi.repository.EBook.BookClient.connect_sync", side_effect=mock_connect)

    # First page: limit=2, offset=0
    res_page1 = json.loads(await contacts.search_contacts_logic("test", limit=2, offset=0))
    assert res_page1["meta"]["total"] == 3
    assert res_page1["meta"]["returned"] == 2
    assert res_page1["meta"]["offset"] == 0
    assert res_page1["meta"]["has_more"] is True
    # Alice (Book A), Bob (Book A)
    assert res_page1["items"][0]["name"] == "alice"
    assert res_page1["items"][1]["name"] == "Bob"

    # Second page: limit=2, offset=2
    res_page2 = json.loads(await contacts.search_contacts_logic("test", limit=2, offset=2))
    assert res_page2["meta"]["returned"] == 1
    assert res_page2["meta"]["offset"] == 2
    assert res_page2["meta"]["has_more"] is False
    assert res_page2["items"][0]["name"] == "Charlie"


@pytest.mark.asyncio
async def test_search_contacts_resilient_to_partial_book_glib_error(mocker):
    mock_registry = mocker.MagicMock()
    mock_source1 = mocker.MagicMock()
    mock_source1.get_enabled.return_value = True
    mock_source1.get_display_name.return_value = "Broken Book"

    mock_source2 = mocker.MagicMock()
    mock_source2.get_enabled.return_value = True
    mock_source2.get_display_name.return_value = "Working Book"

    mock_registry.list_sources.return_value = [mock_source1, mock_source2]
    mocker.patch("gi.repository.EDataServer.SourceRegistry.new_sync", return_value=mock_registry)

    good_contact = MagicMock()
    good_contact.get_property.side_effect = lambda prop: "Dana" if prop == "full-name" else None

    def mock_connect(source, timeout, cancellable):
        if source.get_display_name() == "Broken Book":
            raise GLib.Error("Address book connection timeout")
        c = mocker.MagicMock()
        c.get_contacts_sync.return_value = (True, [good_contact])
        return c

    mocker.patch("gi.repository.EBook.BookClient.connect_sync", side_effect=mock_connect)

    res = json.loads(await contacts.search_contacts_logic("Dana"))
    assert res["meta"]["total"] == 1
    assert res["items"][0]["name"] == "Dana"
    assert res["items"][0]["book"] == "Working Book"
