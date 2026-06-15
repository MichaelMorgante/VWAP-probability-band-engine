from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


UK_TZ = ZoneInfo("Europe/London")


@dataclass(frozen=True)
class SessionPreset:
    label: str
    open_time: time
    timezone_name: str


SESSION_PRESETS: dict[str, SessionPreset] = {
    "london_open": SessionPreset(
        label="London open",
        open_time=time(8, 0),
        timezone_name="Europe/London",
    ),
    "ny_open": SessionPreset(
        label="New York open",
        open_time=time(9, 30),
        timezone_name="America/New_York",
    ),
    "asia_open": SessionPreset(
        label="Asia/Tokyo open",
        open_time=time(9, 0),
        timezone_name="Asia/Tokyo",
    ),
}


def _ensure_utc(dt: datetime) -> datetime:
    """
    Return a timezone-aware UTC datetime.

    If a naive datetime is provided, it is treated as UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def _parse_hhmm(value: str) -> tuple[int, int]:
    """
    Parse a string like '16:00' into hour/minute.
    """
    try:
        hour_str, minute_str = value.strip().split(":")
        hour = int(hour_str)
        minute = int(minute_str)
    except Exception as exc:
        raise ValueError(
            f"Invalid time '{value}'. Use HH:MM format, e.g. '16:00'."
        ) from exc

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(
            f"Invalid time '{value}'. Hour must be 0-23 and minute 0-59."
        )

    return hour, minute


def _get_broker_tz(broker_timezone_name: str | None):
    """
    Broker/server timezone is optional and display-only.

    Example for FTMO-style GMT+2/GMT+3 display:
    broker_timezone_name='Europe/Athens'
    """
    if broker_timezone_name is None:
        return None

    return ZoneInfo(broker_timezone_name)


def _add_display_times(session: dict, broker_timezone_name: str | None) -> dict:
    """
    Add UK display times and optional broker/server display times.

    UTC times remain the source of truth for future data loading.
    """
    broker_tz = _get_broker_tz(broker_timezone_name)

    session["start_uk"] = session["start_utc"].astimezone(UK_TZ)
    session["end_uk"] = session["end_utc"].astimezone(UK_TZ)

    if session.get("session_open_utc") is not None:
        session["session_open_uk"] = session["session_open_utc"].astimezone(UK_TZ)
    else:
        session["session_open_uk"] = None

    if broker_tz is not None:
        session["broker_timezone_name"] = broker_timezone_name
        session["start_broker"] = session["start_utc"].astimezone(broker_tz)
        session["end_broker"] = session["end_utc"].astimezone(broker_tz)

        if session.get("session_open_utc") is not None:
            session["session_open_broker"] = session["session_open_utc"].astimezone(
                broker_tz
            )
        else:
            session["session_open_broker"] = None
    else:
        session["broker_timezone_name"] = None
        session["start_broker"] = None
        session["end_broker"] = None
        session["session_open_broker"] = None

    return session


def get_preset_session_start(
    preset: str,
    offset_minutes: int = 0,
    now_utc: datetime | None = None,
    broker_timezone_name: str | None = None,
) -> dict:
    """
    Resolve a named session preset into UTC, UK, and optional broker-display times.

    Example:
    preset='ny_open', offset_minutes=-30

    This means:
    New York open = 09:30 America/New_York
    anchor = 09:00 America/New_York
    converted safely into UTC/UK/broker display time.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_utc = _ensure_utc(now_utc)

    if preset not in SESSION_PRESETS:
        valid = ", ".join(SESSION_PRESETS.keys())
        raise ValueError(f"Unknown session preset '{preset}'. Valid presets: {valid}")

    preset_info = SESSION_PRESETS[preset]
    session_tz = ZoneInfo(preset_info.timezone_name)

    now_session_tz = now_utc.astimezone(session_tz)

    session_open = datetime.combine(
        now_session_tz.date(),
        preset_info.open_time,
        tzinfo=session_tz,
    )

    start_time = session_open + timedelta(minutes=offset_minutes)

    session = {
        "mode": "preset",
        "preset": preset,
        "label": preset_info.label,
        "offset_minutes": offset_minutes,
        "session_open_utc": session_open.astimezone(timezone.utc),
        "start_utc": start_time.astimezone(timezone.utc),
        "end_utc": now_utc,
    }

    return _add_display_times(session, broker_timezone_name)


def get_manual_session_start(
    manual_start_uk: str,
    now_utc: datetime | None = None,
    broker_timezone_name: str | None = None,
) -> dict:
    """
    Resolve a manual UK start time into UTC and optional broker-display time.

    Example:
    manual_start_uk='16:00'

    This means:
    start from 16:00 Europe/London today.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_utc = _ensure_utc(now_utc)
    now_uk = now_utc.astimezone(UK_TZ)

    hour, minute = _parse_hhmm(manual_start_uk)

    start_uk = now_uk.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )

    if start_uk > now_uk:
        raise ValueError(
            f"Manual start time {manual_start_uk} UK is in the future today."
        )

    session = {
        "mode": "manual",
        "preset": None,
        "label": f"Manual UK start {manual_start_uk}",
        "offset_minutes": None,
        "session_open_utc": None,
        "start_utc": start_uk.astimezone(timezone.utc),
        "end_utc": now_utc,
    }

    return _add_display_times(session, broker_timezone_name)


def get_now_session_start(
    now_utc: datetime | None = None,
    broker_timezone_name: str | None = None,
) -> dict:
    """
    Resolve start-now mode.

    This means no session rebuild.
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)

    now_utc = _ensure_utc(now_utc)

    session = {
        "mode": "now",
        "preset": None,
        "label": "Start now",
        "offset_minutes": None,
        "session_open_utc": None,
        "start_utc": now_utc,
        "end_utc": now_utc,
    }

    return _add_display_times(session, broker_timezone_name)


def resolve_session_start(
    mode: str,
    preset: str = "ny_open",
    manual_start_uk: str = "16:00",
    offset_minutes: int = 0,
    now_utc: datetime | None = None,
    broker_timezone_name: str | None = None,
) -> dict:
    """
    Main public function used by notebooks/runners.

    Parameters
    ----------
    mode:
        'preset', 'manual', or 'now'

    preset:
        Used only when mode='preset'.
        Options: 'london_open', 'ny_open', 'asia_open'

    manual_start_uk:
        Used only when mode='manual'.
        Example: '16:00'

    offset_minutes:
        Used only when mode='preset'.
        -30 = start 30 minutes before selected session open
          0 = start exactly at selected session open
         30 = start 30 minutes after selected session open

    broker_timezone_name:
        Optional display-only broker/server timezone.
        For FTMO-style GMT+2/GMT+3 display, use 'Europe/Athens'.
        For no broker display, leave as None.
    """
    mode = mode.lower().strip()

    if mode == "preset":
        return get_preset_session_start(
            preset=preset,
            offset_minutes=offset_minutes,
            now_utc=now_utc,
            broker_timezone_name=broker_timezone_name,
        )

    if mode == "manual":
        return get_manual_session_start(
            manual_start_uk=manual_start_uk,
            now_utc=now_utc,
            broker_timezone_name=broker_timezone_name,
        )

    if mode == "now":
        return get_now_session_start(
            now_utc=now_utc,
            broker_timezone_name=broker_timezone_name,
        )

    raise ValueError("mode must be one of: 'preset', 'manual', or 'now'.")


def format_session_summary(session: dict) -> str:
    """
    Human-readable summary for notebook output.
    """
    lines = [
        f"✅ Session mode: {session['mode']}",
        f"✅ Session label: {session['label']}",
    ]

    if session.get("session_open_uk") is not None:
        lines.append(f"✅ Session open UK time: {session['session_open_uk']:%H:%M}")

    lines.extend(
        [
            f"✅ Start UK time: {session['start_uk']:%H:%M}",
            f"✅ Start UTC: {session['start_utc']:%Y-%m-%d %H:%M:%S %Z}",
            f"✅ End UTC: {session['end_utc']:%Y-%m-%d %H:%M:%S %Z}",
        ]
    )

    if session.get("start_broker") is not None:
        lines.append(
            f"✅ Start broker/server time: {session['start_broker']:%H:%M} "
            f"({session['broker_timezone_name']})"
        )

    return "\n".join(lines)