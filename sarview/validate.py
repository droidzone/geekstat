"""Reject anything that must not reach an SSH command line."""

from __future__ import annotations

import re
from datetime import date

from sarview.errors import SarviewError

_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FILE = re.compile(r"^sa(?:\d{2}|\d{8})(?:\.(?:xz|gz|bz2))?$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SA_DIR = re.compile(r"^/[A-Za-z0-9._/-]+$")
_OFFSET = re.compile(r"^[+-]\d{4}$")

BIND_HOST = "127.0.0.1"


def validate_host(host: str) -> str:
    if not _HOST.fullmatch(host or ""):
        raise SarviewError("invalid SSH host alias")
    return host


def validate_filename(name: str) -> str:
    if not _FILE.fullmatch(name or ""):
        raise SarviewError(f"invalid sysstat filename {name!r}")
    return name


def validate_date(text: str) -> str:
    if not _DATE.fullmatch(text or ""):
        raise SarviewError("invalid date")
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise SarviewError("invalid date") from exc
    return text


def validate_sa_dir(path: str) -> str:
    cleaned = (path or "").rstrip("/")
    if not cleaned or not _SA_DIR.fullmatch(cleaned) or ".." in cleaned.split("/"):
        raise SarviewError("invalid sysstat directory")
    return cleaned


def validate_offset(offset: str) -> str:
    if not _OFFSET.fullmatch(offset or ""):
        raise SarviewError(f"unusable UTC offset {offset!r}")
    return offset


def validate_port(port: int, *, allow_ephemeral: bool = False) -> int:
    if allow_ephemeral and port == 0:
        return 0
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise SarviewError("port must be between 1 and 65535")
    return port


def validate_bind(host: str) -> str:
    if host != BIND_HOST:
        raise SarviewError("sarview only binds to 127.0.0.1")
    return host
