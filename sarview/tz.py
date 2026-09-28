"""Map sysstat file dates onto the server's current timezone."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sarview.errors import SarviewError
from sarview.validate import validate_offset

_UTC_NAMES = {"UTC", "GMT", "UCT", "ZULU", "ETC/UTC", "ETC/GMT"}


def resolve_zone(name: str, offset: str) -> tuple[str, tzinfo]:
    offset = validate_offset(offset)
    cleaned = (name or "").strip()
    if cleaned and not any(ch.isspace() for ch in cleaned):
        try:
            return cleaned, ZoneInfo(cleaned)
        except ZoneInfoNotFoundError:
            pass
    return cleaned or "UTC", _fixed_zone(offset)


def _fixed_zone(offset: str) -> timezone:
    sign = 1 if offset[0] == "+" else -1
    minutes = sign * (int(offset[1:3]) * 60 + int(offset[3:5]))
    try:
        return timezone(timedelta(minutes=minutes))
    except ValueError as exc:
        raise SarviewError(f"unusable UTC offset {offset!r}") from exc


def offset_minutes(zone: tzinfo, day: str) -> int:
    current = date.fromisoformat(day)
    aware = datetime(current.year, current.month, current.day, 12, 0, tzinfo=zone)
    delta = aware.utcoffset() or timedelta(0)
    return int(delta.total_seconds() // 60)


def covered_local_dates(
    file_date: str,
    file_timezone: str,
    mtime: int,
    name: str,
    server_zone: tzinfo,
) -> set[str]:
    """Local calendar dates a daily sa file can contain.

    sadf -T prints timestamps in the server's current zone. Files recorded
    while the host was still on UTC therefore spill into the next Kolkata
    morning, and the previous day's file holds the early hours of today.
    """
    origin = date.fromisoformat(file_date)
    if (file_timezone or "").upper() in _UTC_NAMES:
        start = datetime(origin.year, origin.month, origin.day, tzinfo=timezone.utc)
        if name.endswith((".xz", ".gz", ".bz2")):
            end = start + timedelta(days=1, seconds=-1)
        else:
            end = datetime.fromtimestamp(int(mtime), timezone.utc)
            if end < start:
                end = start
            cap = start + timedelta(days=2)
            if end > cap:
                end = cap
        first = start.astimezone(server_zone).date()
        last = end.astimezone(server_zone).date()
    else:
        first = origin - timedelta(days=1)
        last = origin + timedelta(days=1)
    if last < first:
        last = first
    days: set[str] = set()
    cursor = first
    while cursor <= last:
        days.add(cursor.isoformat())
        cursor += timedelta(days=1)
    return days
