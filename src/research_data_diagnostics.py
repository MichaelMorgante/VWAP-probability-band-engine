
from dataclasses import asdict
from pathlib import Path
from typing import Any
import hashlib

import numpy as np
import pandas as pd

from .research_data_fetcher import (
    AcquisitionResult,
    RAW_CANDLE_COLUMNS,
)


OHLC_COLUMNS = ["open", "high", "low", "close"]

VOLUME_SPREAD_COLUMNS = [
    "tick_volume",
    "spread",
    "real_volume",
]

NATIVE_COLUMNS = [
    column
    for column in RAW_CANDLE_COLUMNS
    if column != "datetime"
]


def diagnose_raw_candles(df: pd.DataFrame) -> dict:
    """
    Inspect raw MT5 candles without modifying observations.

    Timestamp conversion follows the provisional MT5 Unix
    timestamp interpretation. This does not independently
    establish historical UTC alignment.
    """
    missing = set(RAW_CANDLE_COLUMNS) - set(df.columns)

    if missing:
        raise ValueError(
            f"Missing required fields: {sorted(missing)}"
        )

    # --------------------------------------------------
    # Timestamp integrity
    # --------------------------------------------------
    raw_seconds = pd.to_numeric(
        df["mt5_time_raw"],
        errors="coerce",
    )

    integer_seconds = (
        np.isfinite(raw_seconds)
        & raw_seconds.mod(1).eq(0)
    )

    decoded = pd.to_datetime(
        raw_seconds.where(integer_seconds),
        unit="s",
        utc=True,
        errors="coerce",
    )

    recorded = pd.to_datetime(
        df["datetime"],
        utc=True,
        errors="coerce",
    )

    invalid_timestamp = decoded.isna()

    non_minute_aligned = (
        decoded.notna()
        & raw_seconds.mod(60).ne(0)
    )

    timestamp_mismatch = (
        decoded.notna()
        & decoded.ne(recorded)
    )

    # --------------------------------------------------
    # Duplicate and conflict diagnostics
    # --------------------------------------------------
    native = df.loc[
        decoded.notna(),
        NATIVE_COLUMNS,
    ]

    distinct_native = native.drop_duplicates()

    exact_duplicate_rows = int(
        native.duplicated().sum()
    )

    conflicting_timestamps = int(
        distinct_native.groupby("mt5_time_raw")
        .size()
        .gt(1)
        .sum()
    )

    conflicting_ohlc_timestamps = int(
        native[["mt5_time_raw"] + OHLC_COLUMNS]
        .drop_duplicates()
        .groupby("mt5_time_raw")
        .size()
        .gt(1)
        .sum()
    )

    # --------------------------------------------------
    # OHLC, volume and spread integrity
    # --------------------------------------------------
    numeric = df[
        OHLC_COLUMNS + VOLUME_SPREAD_COLUMNS
    ].apply(pd.to_numeric, errors="coerce")

    finite = pd.DataFrame(
        np.isfinite(numeric.to_numpy(dtype=float)),
        index=df.index,
        columns=numeric.columns,
    )

    invalid_ohlc = (
        ~finite[OHLC_COLUMNS].all(axis=1)
        | numeric["high"].lt(numeric["open"])
        | numeric["high"].lt(numeric["close"])
        | numeric["low"].gt(numeric["open"])
        | numeric["low"].gt(numeric["close"])
        | numeric["high"].lt(numeric["low"])
    )

    invalid_volume_spread = (
        ~finite[VOLUME_SPREAD_COLUMNS].all(axis=1)
        | numeric[VOLUME_SPREAD_COLUMNS]
        .lt(0)
        .any(axis=1)
    )

    # --------------------------------------------------
    # Observed timestamp intervals
    # --------------------------------------------------
    valid_times = decoded[
        decoded.notna()
        & ~non_minute_aligned
        & ~timestamp_mismatch
    ]

    ordered_unique = pd.Series(
        pd.DatetimeIndex(valid_times)
        .unique()
        .sort_values()
    )

    intervals = (
        ordered_unique.diff()
        .dt.total_seconds()
        .div(60)
        .dropna()
    )

    interval_counts = {
        str(int(minutes)): int(count)
        for minutes, count in
        intervals.value_counts().sort_index().items()
    }

    return {
        "rows": len(df),
        "unique_valid_timestamps": int(
            valid_times.nunique()
        ),
        "invalid_timestamp_rows": int(
            invalid_timestamp.sum()
        ),
        "non_minute_aligned_rows": int(
            non_minute_aligned.sum()
        ),
        "timestamp_mismatch_rows": int(
            timestamp_mismatch.sum()
        ),
        "backward_timestamp_moves": int(
            decoded.diff()
            .lt(pd.Timedelta(0))
            .sum()
        ),
        "exact_duplicate_rows": exact_duplicate_rows,
        "conflicting_timestamps": conflicting_timestamps,
        "conflicting_ohlc_timestamps": (
            conflicting_ohlc_timestamps
        ),
        "invalid_ohlc_rows": int(invalid_ohlc.sum()),
        "invalid_volume_spread_rows": int(
            invalid_volume_spread.sum()
        ),
        "zero_tick_volume_rows": int(
            numeric["tick_volume"].eq(0).sum()
        ),
        "zero_real_volume_rows": int(
            numeric["real_volume"].eq(0).sum()
        ),
        "zero_spread_rows": int(
            numeric["spread"].eq(0).sum()
        ),
        "observed_interval_counts_minutes": (
            interval_counts
        ),
        "intervals_above_one_minute": int(
            intervals.gt(1).sum()
        ),
    }


def diagnose_acquisition(
    result: AcquisitionResult,
    *,
    expected_minutes=None,
    timestamp_evidence: str | None = None,
    coverage_reference: str | None = None,
) -> dict:
    """
    Assess individual acquisition chunks.

    Without independently verified timestamp alignment and
    an expected trading-minute schedule, historical coverage
    remains unverified.

    An expected schedule must include legitimate market
    closures and shortened sessions.
    """
    if sum(chunk.rows for chunk in result.chunks) != len(
        result.candles
    ):
        raise ValueError(
            "Chunk row counts do not match acquisition data."
        )

    expected = None

    if expected_minutes is not None:
        if not timestamp_evidence or not coverage_reference:
            raise ValueError(
                "Expected coverage requires timestamp "
                "evidence and a schedule reference."
            )

        expected = pd.DatetimeIndex(expected_minutes)

        if expected.tz is None:
            raise ValueError(
                "Expected timestamps must be timezone-aware."
            )

        expected = expected.tz_convert("UTC")

        if (
            expected.hasnans
            or expected.has_duplicates
            or not expected.equals(expected.floor("min"))
        ):
            raise ValueError(
                "Expected timestamps must be unique, valid "
                "and minute-aligned."
            )

        if (
            (expected < result.requested_start).any()
            or (
                expected >= result.requested_end_exclusive
            ).any()
        ):
            raise ValueError(
                "Expected timestamps exceed requested range."
            )

        expected = expected.sort_values()

    chunk_reports = []
    position = 0

    for chunk in result.chunks:
        frame = result.candles.iloc[
            position:position + chunk.rows
        ]

        position += chunk.rows

        seconds = pd.to_numeric(
            frame["mt5_time_raw"],
            errors="coerce",
        )

        timestamps = pd.to_datetime(
            seconds.where(
                np.isfinite(seconds)
                & seconds.mod(1).eq(0)
            ),
            unit="s",
            utc=True,
            errors="coerce",
        )

        recorded = pd.to_datetime(
            frame["datetime"],
            utc=True,
            errors="coerce",
        )

        in_range = (
            timestamps.ge(chunk.requested_start)
            & timestamps.lt(chunk.requested_end_exclusive)
        )

        valid = (
            timestamps.notna()
            & seconds.mod(60).eq(0)
            & timestamps.eq(recorded)
        )

        observed = pd.DatetimeIndex(
            timestamps[valid & in_range]
        ).unique().sort_values()

        outside_rows = int(
            (timestamps.notna() & ~in_range).sum()
        )

        missing_count = None
        expected_count = None
        unexpected_count = None

        if expected is not None:
            expected_chunk = expected[
                (expected >= chunk.requested_start)
                & (
                    expected <
                    chunk.requested_end_exclusive
                )
            ]

            expected_count = len(expected_chunk)

            missing_count = len(
                expected_chunk.difference(observed)
            )

            unexpected_count = len(
                observed.difference(expected_chunk)
            )

        if chunk.status == "failed":
            coverage_status = "failed"

        elif expected is None:
            coverage_status = "unverified"

        elif missing_count and not len(observed):
            coverage_status = "empty"

        elif missing_count:
            coverage_status = "partial"

        elif unexpected_count or outside_rows:
            coverage_status = "unexpected_observations"

        elif expected_count == 0:
            coverage_status = "no_expected_minutes"

        else:
            coverage_status = "complete"

        report = asdict(chunk)

        report["requested_start"] = (
            chunk.requested_start.isoformat()
        )

        report["requested_end_exclusive"] = (
            chunk.requested_end_exclusive.isoformat()
        )

        report.update({
            "observed_first_timestamp": (
                observed.min().isoformat()
                if len(observed) else None
            ),
            "observed_last_timestamp": (
                observed.max().isoformat()
                if len(observed) else None
            ),
            "unique_observed_minutes": len(observed),
            "outside_requested_range_rows": outside_rows,
            "invalid_or_misaligned_rows": int(
                (~valid).sum()
            ),
            "expected_minutes": expected_count,
            "missing_expected_minutes": missing_count,
            "unexpected_minutes": unexpected_count,
            "timestamp_coverage_status": coverage_status,
        })

        chunk_reports.append(report)

    return {
        "timestamp_alignment": (
            "verified_by_caller"
            if timestamp_evidence
            else "unverified"
        ),
        "timestamp_evidence": timestamp_evidence,
        "coverage_reference": coverage_reference,
        "quality": diagnose_raw_candles(result.candles),
        "chunks": chunk_reports,
    }


def capture_mt5_source(
    mt5_client: Any,
    symbol: str,
) -> dict:
    """
    Capture non-sensitive source metadata while connected
    to MT5. Never retain account IDs or credentials.
    """
    account = mt5_client.account_info()
    terminal = mt5_client.terminal_info()
    instrument = mt5_client.symbol_info(symbol)

    if any(
        item is None
        for item in (account, terminal, instrument)
    ):
        raise RuntimeError(
            "Unable to establish MT5 source metadata."
        )

    return {
        "provider": "MetaTrader5",
        "broker_company": account.company,
        "broker_server": account.server,
        "symbol": symbol,
        "symbol_digits": int(instrument.digits),
        "symbol_point": float(instrument.point),
        "terminal_maxbars": int(terminal.maxbars),
        "terminal_build": int(terminal.build),
        "mt5_package_version": getattr(
            mt5_client, "__version__", None
        ),
    }


def sha256_file(path: str | Path) -> str:
    """Calculate a SHA-256 hash without loading the entire file."""
    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        for block in iter(
            lambda: file.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def build_acquisition_metadata(
    result: AcquisitionResult,
    source: dict,
    csv_path: str | Path,
    *,
    code_version: str,
    working_tree_dirty: bool,
    expected_minutes=None,
    timestamp_evidence: str | None = None,
    coverage_reference: str | None = None,
) -> dict:
    """
    Construct metadata for a previously written raw CSV.

    The caller must ensure that csv_path contains the exact
    raw acquisition represented by result.
    """
    if source.get("symbol") != result.symbol:
        raise ValueError(
            "Source symbol does not match acquisition."
        )

    if not code_version.strip():
        raise ValueError("Code version must be recorded.")

    path = Path(csv_path)
    checksum = sha256_file(path)

    # Explicit whitelist prevents private account metadata
    # from accidentally entering the exported manifest.
    source_fields = (
        "provider",
        "broker_company",
        "broker_server",
        "symbol",
        "symbol_digits",
        "symbol_point",
        "terminal_maxbars",
        "terminal_build",
        "mt5_package_version",
    )

    timestamps = pd.to_datetime(
        result.candles["datetime"],
        utc=True,
        errors="coerce",
    ).dropna()

    return {
        "metadata_schema_version": 1,
        "dataset_id": f"sha256:{checksum}",
        "filename": path.name,
        "sha256": checksum,
        "file_size_bytes": path.stat().st_size,
        "source": {
            field: source.get(field)
            for field in source_fields
        },
        "symbol": result.symbol,
        "timeframe": result.timeframe,
        "requested_start": (
            result.requested_start.isoformat()
        ),
        "requested_end_exclusive": (
            result.requested_end_exclusive.isoformat()
        ),
        "observed_first_timestamp": (
            timestamps.min().isoformat()
            if len(timestamps) else None
        ),
        "observed_last_timestamp": (
            timestamps.max().isoformat()
            if len(timestamps) else None
        ),
        "acquisition_started_utc": (
            result.started_at_utc.isoformat()
        ),
        "acquisition_finished_utc": (
            result.finished_at_utc.isoformat()
        ),
        "chunk_days": result.chunk_days,
        "rows": len(result.candles),
        "code_version": code_version,
        "working_tree_dirty": working_tree_dirty,
        "timestamp_interpretation": (
            "MT5 integer seconds interpreted as UTC"
        ),
        "broker_offset_correction_applied": False,
        "session_filter_applied": False,
        "normalisation_applied": False,
        "diagnostics": diagnose_acquisition(
            result,
            expected_minutes=expected_minutes,
            timestamp_evidence=timestamp_evidence,
            coverage_reference=coverage_reference,
        ),
    }
