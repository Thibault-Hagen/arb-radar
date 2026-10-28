"""Time helpers. Every timestamp inside the app is UTC; game dates use US Eastern."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo

    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - only when the system has no tz database
    ZoneInfo = None
    _ET = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def parse_iso(value) -> datetime | None:
    """Parse ISO-8601 (with Z, offsets or no seconds) or a unix timestamp into UTC."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(float(value), timezone.utc)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _eastern_offset(dt_utc: datetime) -> timedelta:
    """US Eastern offset using the post-2007 DST rules (fallback only)."""
    year = dt_utc.year
    march8 = datetime(year, 3, 8, 7, tzinfo=timezone.utc)
    dst_start = march8 + timedelta(days=(6 - march8.weekday()) % 7)
    nov1 = datetime(year, 11, 1, 6, tzinfo=timezone.utc)
    dst_end = nov1 + timedelta(days=(6 - nov1.weekday()) % 7)
    return timedelta(hours=-4) if dst_start <= dt_utc < dst_end else timedelta(hours=-5)


def to_eastern(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    if _ET is not None:
        return dt.astimezone(_ET)
    return dt + _eastern_offset(dt)


def et_date(dt: datetime | None) -> date | None:
    """The calendar date of a moment in US Eastern time (how leagues date games)."""
    if dt is None:
        return None
    return to_eastern(dt).date()


def local_label(dt: datetime | None, tz_name: str) -> str:
    """Short human label such as 'Wed 6:30 PM CDT' in the given time zone."""
    if dt is None:
        return "time TBD"
    try:
        local = dt.astimezone(ZoneInfo(tz_name)) if ZoneInfo else to_eastern(dt)
    except Exception:
        local = to_eastern(dt)
    hour = local.strftime("%I").lstrip("0") or "12"
    zone = local.strftime("%Z") or ("ET" if ZoneInfo is None else "")
    return f"{local.strftime('%a')} {hour}:{local.strftime('%M %p')} {zone}".strip()
