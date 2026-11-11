"""Shared error contracts and compact JSON envelope serializers for eds-mcp."""

from __future__ import annotations

import json
import sqlite3
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Deterministic machine-readable error codes returned by MCP tools."""

    BRIDGE_UNAVAILABLE = "BRIDGE_UNAVAILABLE"
    BRIDGE_CALL_FAILED = "BRIDGE_CALL_FAILED"
    CACHE_MISS = "CACHE_MISS"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EDS_ERROR = "EDS_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    DEPENDENCY_MISSING = "DEPENDENCY_MISSING"


class EdsMcpError(Exception):
    """Base domain error carrying structured MCP error metadata."""

    def __init__(
        self,
        message: str,
        *,
        code: str = ErrorCode.EDS_ERROR,
        retryable: bool = False,
        hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = message
        self.retryable = retryable
        self.hint = hint


class BridgeUnavailableError(EdsMcpError, ConnectionError):
    """Raised when Evolution or its D-Bus automation bridge is unreachable."""

    def __init__(
        self,
        message: str = "Evolution GUI process is not running on session D-Bus.",
        *,
        hint: str
        | None = "Start Evolution with the MCP automation bridge plugin installed, or read cached items only.",
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.BRIDGE_UNAVAILABLE,
            retryable=False,
            hint=hint,
        )


class BridgeCallError(EdsMcpError):
    """Raised when a D-Bus bridge method returns a failure or times out."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        hint: str | None = None,
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.BRIDGE_CALL_FAILED,
            retryable=retryable,
            hint=hint,
        )


class CacheMissError(EdsMcpError):
    """Raised when a message body/attachment is absent from local Camel cache."""

    def __init__(
        self,
        message: str,
        *,
        hint: str
        | None = "Open or sync the message in Evolution, or start Evolution so bridge fallback can fetch it.",
    ) -> None:
        super().__init__(
            message,
            code=ErrorCode.CACHE_MISS,
            retryable=True,
            hint=hint,
        )


class ResourceNotFoundError(EdsMcpError):
    """Raised when a requested account, folder, calendar, or item does not exist."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.NOT_FOUND,
            retryable=False,
            hint=hint,
        )


class ValidationError(EdsMcpError, ValueError):
    """Raised when tool input parameters fail validation."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.VALIDATION_ERROR,
            retryable=False,
            hint=hint,
        )


class DatabaseError(EdsMcpError):
    """Raised when reading Evolution's SQLite index fails."""

    def __init__(self, message: str, *, retryable: bool = True, hint: str | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.DATABASE_ERROR,
            retryable=retryable,
            hint=hint,
        )


class EdsClientError(EdsMcpError):
    """Raised when an Evolution Data Server client call fails."""

    def __init__(self, message: str, *, retryable: bool = False, hint: str | None = None) -> None:
        super().__init__(
            message,
            code=ErrorCode.EDS_ERROR,
            retryable=retryable,
            hint=hint,
        )


def strip_empty(value: Any) -> Any:
    """Recursively remove None, empty strings, empty lists, and empty dicts."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            cleaned_v = strip_empty(v)
            if cleaned_v is None or cleaned_v == "" or cleaned_v == [] or cleaned_v == {}:
                continue
            cleaned[k] = cleaned_v
        return cleaned
    if isinstance(value, list):
        cleaned_list = [strip_empty(item) for item in value]
        return [
            item
            for item in cleaned_list
            if item is not None and item != "" and item != [] and item != {}
        ]
    return value


def compact_json(payload: Any) -> str:
    """Serialize payload as minimal UTF-8 JSON without whitespace bloat."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False)


def ok_envelope(payload: dict[str, Any]) -> str:
    """Strip empty fields from an object response and serialize compactly."""
    return compact_json(strip_empty(payload))


def paginated_envelope(
    items: list[Any],
    *,
    total: int,
    offset: int = 0,
    extra_meta: dict[str, Any] | None = None,
    extra_top: dict[str, Any] | None = None,
) -> str:
    """Serialize standardized list response with pagination metadata."""
    cleaned_items = [strip_empty(item) for item in items]
    returned = len(cleaned_items)
    meta: dict[str, Any] = {
        "returned": returned,
        "total": total,
        "offset": offset,
        "has_more": (offset + returned) < total,
    }
    if extra_meta:
        cleaned_meta = strip_empty(extra_meta)
        if isinstance(cleaned_meta, dict):
            meta.update(cleaned_meta)

    envelope: dict[str, Any] = {}
    if extra_top:
        cleaned_top = strip_empty(extra_top)
        if isinstance(cleaned_top, dict):
            envelope.update(cleaned_top)
    envelope["items"] = cleaned_items
    envelope["meta"] = meta
    return compact_json(envelope)


def error_envelope(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    hint: str | None = None,
) -> str:
    """Serialize standardized structured error contract."""
    err: dict[str, Any] = {
        "code": str(code),
        "message": message,
        "retryable": retryable,
    }
    if hint:
        err["hint"] = hint
    return compact_json({"error": err})


def error_from_exception(
    exc: BaseException,
    *,
    default_code: str = ErrorCode.EDS_ERROR,
    default_hint: str | None = None,
) -> str:
    """Convert domain or stdlib exceptions into structured error envelopes."""
    if isinstance(exc, EdsMcpError):
        return error_envelope(
            exc.code,
            exc.message,
            retryable=exc.retryable,
            hint=exc.hint or default_hint,
        )
    if isinstance(exc, ValueError):
        return error_envelope(
            ErrorCode.VALIDATION_ERROR,
            str(exc),
            retryable=False,
            hint=default_hint,
        )
    if isinstance(exc, sqlite3.Error):
        return error_envelope(
            ErrorCode.DATABASE_ERROR,
            str(exc),
            retryable=True,
            hint=default_hint,
        )
    if isinstance(exc, ConnectionError):
        return error_envelope(
            ErrorCode.BRIDGE_UNAVAILABLE,
            str(exc),
            retryable=False,
            hint=default_hint or "Start Evolution or read cached items only.",
        )
    if isinstance(exc, TimeoutError):
        return error_envelope(
            ErrorCode.BRIDGE_CALL_FAILED,
            str(exc),
            retryable=True,
            hint=default_hint,
        )
    return error_envelope(
        default_code,
        str(exc),
        retryable=False,
        hint=default_hint,
    )
