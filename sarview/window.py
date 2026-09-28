"""Select raw samples inside a clock-time window. Never resample them."""

from __future__ import annotations

from datetime import datetime, tzinfo

from sarview.errors import SarviewError


def parse_clock(text: str) -> tuple[int, int, int]:
    parts = (text or "").strip().split(":")
    if len(parts) not in (2, 3):
        raise SarviewError("invalid time")
    try:
        numbers = [int(part) for part in parts]
    except ValueError as exc:
        raise SarviewError("invalid time") from exc
    if len(numbers) == 2:
        numbers.append(0)
    hour, minute, second = numbers
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise SarviewError("invalid time")
    return hour, minute, second


def window_bounds(start: str, end: str) -> tuple[int, int]:
    """Return inclusive seconds-from-midnight bounds.

    An end time that lands on a whole minute includes the rest of that
    minute. sar stamps each sample a few seconds after the interval, so
    08:15 has to keep the 08:15:07 sample.
    """
    start_h, start_m, start_s = parse_clock(start)
    end_h, end_m, end_s = parse_clock(end)
    if end_s == 0:
        end_s = 59
    start_sec = start_h * 3600 + start_m * 60 + start_s
    end_sec = end_h * 3600 + end_m * 60 + end_s
    if end_sec < start_sec:
        raise SarviewError("end time is before start time")
    return start_sec, end_sec


def filter_samples(samples: list[dict], zone: tzinfo, start: str, end: str) -> list[dict]:
    start_sec, end_sec = window_bounds(start, end)
    chosen: list[dict] = []
    for sample in samples:
        local = datetime.fromtimestamp(sample["epoch"], zone)
        tod = local.hour * 3600 + local.minute * 60 + local.second
        if start_sec <= tod <= end_sec:
            chosen.append(sample)
    return chosen
