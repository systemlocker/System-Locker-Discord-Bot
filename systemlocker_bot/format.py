"""Pure presentation helpers: duration parsing, timestamps, truncation.

Kept free of Discord imports so the parsing rules can be exercised without
the bot runtime installed.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

MAX_DURATION_SECONDS = 10 * 365 * 24 * 3600

_DURATION_TOKEN = re.compile(r"(\d+)\s*(s|m|h|d|w|y)", re.IGNORECASE)
_DURATION_UNITS = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 7 * 86400,
    "y": 365 * 86400,
}

_INPUT_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}(?::\d{2})?))?$")


class DurationError(ValueError):
    """A duration string could not be parsed."""


def parse_duration(text: str) -> int:
    """Parse ``90s``, ``5m``, ``2h``, ``7d``, ``4w``, ``1y``, or combinations
    like ``1d12h`` into seconds. Bare numbers are rejected on purpose so a
    typo can never silently mean seconds."""
    cleaned = text.strip().lower().replace(" ", "")
    if not cleaned:
        raise DurationError("Provide a duration such as 30m, 12h, 7d, or 1d12h.")
    consumed = 0
    total = 0
    for match in _DURATION_TOKEN.finditer(cleaned):
        consumed += len(match.group(0))
        total += int(match.group(1)) * _DURATION_UNITS[match.group(2)]
    if consumed != len(cleaned):
        raise DurationError(
            f"'{text}' is not a valid duration. Combine minutes, hours, days, "
            "weeks, or years, e.g. 90s, 5m, 2h, 7d, 4w, 1y, or 1d12h."
        )
    if total <= 0:
        raise DurationError("The duration must be greater than zero.")
    if total > MAX_DURATION_SECONDS:
        raise DurationError("The duration is unreasonably large (over ten years).")
    return total


def format_duration(seconds: int) -> str:
    """Render seconds as a compact human string such as ``2d 6h 30m``."""
    if seconds <= 0:
        return "0s"
    parts: list[str] = []
    for unit, size in (("y", 365 * 86400), ("w", 7 * 86400), ("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        count, seconds = divmod(seconds, size)
        if count and len(parts) < 3:
            parts.append(f"{count}{unit}")
    return " ".join(parts) or "0s"


def parse_input_datetime(text: str) -> datetime:
    """Parse a user-supplied date into an aware UTC datetime.

    Accepts ``YYYY-MM-DD``, optionally with a time (``HH:MM`` or ``HH:MM:SS``,
    space or ``T`` separator). Naive times are interpreted as UTC.
    """
    match = _INPUT_DATE.match(text.strip())
    if not match:
        raise ValueError(
            f"'{text}' is not a valid date. Use YYYY-MM-DD, or YYYY-MM-DD HH:MM "
            "(UTC), e.g. 2026-09-01 or 2026-09-01 14:30."
        )
    date_part, time_part = match.groups()
    if time_part is None:
        time_part = "00:00:00"
    elif len(time_part) == 5:
        time_part += ":00"
    try:
        return datetime.fromisoformat(f"{date_part}T{time_part}+00:00")
    except ValueError:
        raise ValueError(f"'{text}' is not a real calendar date.") from None


def discord_timestamp(value: datetime | None, style: str = "f") -> str:
    """Render a datetime as a Discord timestamp markup string, or a dash."""
    if value is None:
        return "—"
    return f"<t:{int(value.timestamp())}:{style}>"


def timestamp_line(value: datetime | None) -> str:
    """Absolute Discord timestamp with a relative hint, e.g. for expiry."""
    if value is None:
        return "—"
    return f"{discord_timestamp(value)} ({discord_timestamp(value, 'R')})"


def shorten(text: str | None, limit: int) -> str:
    """Truncate text for Discord embed field limits."""
    if text is None:
        return ""
    text = str(text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
