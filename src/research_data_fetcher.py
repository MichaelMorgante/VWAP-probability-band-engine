
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd


# Original fields returned by the MT5 rates API.
MT5_RATE_COLUMNS = (
    "time",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)


# Research acquisition schema.
RAW_CANDLE_COLUMNS = (
    "datetime",
    "mt5_time_raw",
    "open",
    "high",
    "low",
    "close",
    "tick_volume",
    "spread",
    "real_volume",
)


@dataclass(frozen=True)
class ChunkResult:
    """Record the outcome of an individual MT5 request."""

    requested_start: datetime
    requested_end_exclusive: datetime
    status: str
    rows: int
    first_timestamp_raw: int | None = None
    last_timestamp_raw: int | None = None
    error: tuple | None = None


@dataclass
class AcquisitionResult:
    """Raw observations and their acquisition records."""

    symbol: str
    timeframe: str
    requested_start: datetime
    requested_end_exclusive: datetime
    candles: pd.DataFrame
    chunks: tuple[ChunkResult, ...]


def _as_utc(value: datetime) -> datetime:
    """
    Require an explicitly timezone-aware request boundary.

    This converts request coordinates to UTC. It does not
    establish the correctness of historical broker timestamps.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Request timestamps must be timezone-aware.")

    return value.astimezone(timezone.utc)


def rates_to_raw_dataframe(rates: Any) -> pd.DataFrame:
    """
    Preserve native MT5 candle observations.

    The datetime column uses the documented MT5 Unix timestamp
    interpretation. Historical timezone alignment must be
    verified independently before statistical research.

    No sorting, deduplication, interpolation, volume adjustment
    or broker-offset correction is performed.
    """
    if rates is None or len(rates) == 0:
        return pd.DataFrame(columns=RAW_CANDLE_COLUMNS)

    df = pd.DataFrame(rates)

    missing = set(MT5_RATE_COLUMNS) - set(df.columns)

    if missing:
        raise ValueError(
            f"MT5 response is missing required fields: {sorted(missing)}"
        )

    df = df.loc[:, list(MT5_RATE_COLUMNS)].copy()

    df = df.rename(columns={"time": "mt5_time_raw"})

    df.insert(
        0,
        "datetime",
        pd.to_datetime(
            df["mt5_time_raw"],
            unit="s",
            utc=True,
            errors="raise",
        ),
    )

    return df.loc[:, list(RAW_CANDLE_COLUMNS)]


def fetch_raw_mt5_candles(
    mt5_client: Any,
    symbol: str,
    start_utc: datetime,
    end_utc_exclusive: datetime,
    *,
    chunk_days: int = 31,
) -> AcquisitionResult:
    """
    Retrieve native M1 candles in half-open time intervals.

    The supplied MT5 client must already be connected.

    Raw observations are preserved without normalisation.
    Empty and failed requests are recorded separately.

    A non-empty response does not guarantee complete historical
    coverage. Coverage validation is a separate research step.
    """
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("A valid MT5 symbol is required.")

    if (
        isinstance(chunk_days, bool)
        or not isinstance(chunk_days, int)
        or chunk_days <= 0
    ):
        raise ValueError("chunk_days must be a positive integer.")

    start_utc = _as_utc(start_utc)
    end_utc_exclusive = _as_utc(end_utc_exclusive)

    if start_utc >= end_utc_exclusive:
        raise ValueError("Start must precede the exclusive end.")

    for boundary in (start_utc, end_utc_exclusive):
        if boundary.second != 0 or boundary.microsecond != 0:
            raise ValueError(
                "M1 request boundaries must be minute-aligned."
            )

    frames = []
    chunk_results = []

    chunk_start = start_utc

    while chunk_start < end_utc_exclusive:

        chunk_end = min(
            chunk_start + timedelta(days=chunk_days),
            end_utc_exclusive,
        )

        # MT5 uses an inclusive end boundary.
        # Subtract one second to implement [start, end).
        inclusive_end = chunk_end - timedelta(seconds=1)

        rates = mt5_client.copy_rates_range(
            symbol,
            mt5_client.TIMEFRAME_M1,
            chunk_start,
            inclusive_end,
        )

        if rates is None:
            chunk_results.append(
                ChunkResult(
                    requested_start=chunk_start,
                    requested_end_exclusive=chunk_end,
                    status="failed",
                    rows=0,
                    error=mt5_client.last_error(),
                )
            )

        elif len(rates) == 0:
            chunk_results.append(
                ChunkResult(
                    requested_start=chunk_start,
                    requested_end_exclusive=chunk_end,
                    status="empty",
                    rows=0,
                )
            )

        else:
            raw = rates_to_raw_dataframe(rates)

            frames.append(raw)

            chunk_results.append(
                ChunkResult(
                    requested_start=chunk_start,
                    requested_end_exclusive=chunk_end,
                    status="returned",
                    rows=len(raw),
                    first_timestamp_raw=int(
                        raw["mt5_time_raw"].min()
                    ),
                    last_timestamp_raw=int(
                        raw["mt5_time_raw"].max()
                    ),
                )
            )

        chunk_start = chunk_end

    if frames:
        candles = pd.concat(frames, ignore_index=True)
    else:
        candles = pd.DataFrame(columns=RAW_CANDLE_COLUMNS)

    return AcquisitionResult(
        symbol=symbol,
        timeframe="M1",
        requested_start=start_utc,
        requested_end_exclusive=end_utc_exclusive,
        candles=candles,
        chunks=tuple(chunk_results),
    )
