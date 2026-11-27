
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
import json
import re
import shutil

import pandas as pd

from .research_data_fetcher import (
    AcquisitionResult,
    fetch_raw_mt5_candles,
)

from .research_data_diagnostics import (
    build_acquisition_metadata,
    sha256_file,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def calendar_year_bounds(
    year: int,
    *,
    as_of_utc: datetime | None = None,
) -> tuple[datetime, datetime]:
    """
    Construct half-open calendar-year request boundaries.

    Current-year requests end at the opening timestamp
    of the current minute, under the provisional UTC
    timestamp interpretation.
    """
    if (
        isinstance(year, bool)
        or not isinstance(year, int)
        or not 1 <= year <= 9998
    ):
        raise ValueError("Invalid calendar year.")

    if as_of_utc is None:
        as_of_utc = datetime.now(timezone.utc)

    if (
        as_of_utc.tzinfo is None
        or as_of_utc.utcoffset() is None
    ):
        raise ValueError(
            "as_of_utc must be timezone-aware."
        )

    as_of_utc = as_of_utc.astimezone(timezone.utc)

    completed_minute_cutoff = as_of_utc.replace(
        second=0,
        microsecond=0,
    )

    start = datetime(
        year, 1, 1, tzinfo=timezone.utc
    )

    calendar_end = datetime(
        year + 1, 1, 1, tzinfo=timezone.utc
    )

    end_exclusive = min(
        calendar_end,
        completed_minute_cutoff,
    )

    if end_exclusive <= start:
        raise ValueError(
            "Requested year contains no completed "
            "historical minutes."
        )

    return start, end_exclusive


def fetch_calendar_year(
    mt5_client: Any,
    symbol: str,
    year: int,
    *,
    chunk_days: int = 31,
) -> AcquisitionResult:
    """
    Request native M1 observations for a calendar year.

    MT5 must already be connected. This function does not
    save files or certify historical timestamp alignment.
    """
    start, end = calendar_year_bounds(year)

    return fetch_raw_mt5_candles(
        mt5_client,
        symbol,
        start,
        end,
        chunk_days=chunk_days,
    )


def select_closed_research_candles(
    result: AcquisitionResult,
    verified_open_times: pd.Series,
    *,
    timestamp_evidence: str,
) -> pd.DataFrame:
    """
    Return a separate research copy containing only candles
    whose verified opening timestamps establish that they
    had closed before acquisition began.

    Historical timestamp verification must be performed
    independently by the caller.

    This function does not certify overall dataset quality.
    """
    if not timestamp_evidence.strip():
        raise ValueError(
            "Independent timestamp evidence is required."
        )

    if not isinstance(verified_open_times, pd.Series):
        raise TypeError(
            "Verified opening times must be a Series."
        )

    if not verified_open_times.index.equals(
        result.candles.index
    ):
        raise ValueError(
            "Verified timestamps must align with raw rows."
        )

    if not isinstance(
        verified_open_times.dtype,
        pd.DatetimeTZDtype,
    ):
        raise ValueError(
            "Verified timestamps must be timezone-aware."
        )

    verified = verified_open_times.dt.tz_convert("UTC")

    if verified.isna().any():
        raise ValueError(
            "Verified timestamps contain missing values."
        )

    if not verified.eq(
        verified.dt.floor("min")
    ).all():
        raise ValueError(
            "Verified M1 timestamps must be minute-aligned."
        )

    candle_close = verified + pd.Timedelta(minutes=1)

    closed = candle_close.le(
        pd.Timestamp(result.started_at_utc)
    )

    research = result.candles.loc[closed].copy()

    research["verified_datetime_utc"] = verified.loc[
        closed
    ]

    return research


def export_raw_acquisition(
    result: AcquisitionResult,
    source: dict,
    output_dir: str | Path,
    *,
    code_version: str,
    working_tree_dirty: bool,
    label: str | None = None,
) -> dict:
    """
    Save raw observations and companion provenance metadata.

    Exports must be outside this repository.

    Each export receives a new directory. Existing datasets
    cannot be silently overwritten.

    Raw observations remain unchanged, including duplicates,
    invalid values and potentially incomplete observations.
    """
    root = Path(output_dir).expanduser().resolve()

    if root == PROJECT_ROOT or PROJECT_ROOT in root.parents:
        raise ValueError(
            "Raw datasets must be stored outside "
            "the Git repository."
        )

    if label is None:
        symbol = re.sub(
            r"[^a-zA-Z0-9]+",
            "_",
            result.symbol,
        ).strip("_").lower()

        start = result.requested_start.strftime(
            "%Y%m%dT%H%MZ"
        )

        end = result.requested_end_exclusive.strftime(
            "%Y%m%dT%H%MZ"
        )

        label = f"{symbol}_m1_raw_{start}_{end}"

    if not re.fullmatch(
        r"[a-zA-Z0-9_-]+",
        label,
    ):
        raise ValueError("Invalid dataset label.")

    root.mkdir(parents=True, exist_ok=True)

    dataset_dir = root / label

    # Exclusive creation prevents accidental overwriting.
    dataset_dir.mkdir(exist_ok=False)

    csv_path = dataset_dir / f"{label}.csv"
    metadata_path = dataset_dir / f"{label}.json"

    try:
        result.candles.to_csv(
            csv_path,
            index=False,
            mode="x",
            lineterminator="\n",
        )

        metadata = build_acquisition_metadata(
            result,
            source,
            csv_path,
            code_version=code_version,
            working_tree_dirty=working_tree_dirty,
        )

        metadata["dataset_label"] = label

        metadata["exported_at_utc"] = (
            datetime.now(timezone.utc).isoformat()
        )

        metadata["research_eligibility"] = (
            "pending_validation"
        )

        metadata["incomplete_candle_filter_applied"] = False

        # Record the actual acquisition source-file hashes,
        # including when exporting from a dirty working tree.
        metadata["acquisition_source_sha256"] = {
            filename: sha256_file(
                PROJECT_ROOT / "src" / filename
            )
            for filename in (
                "research_data_fetcher.py",
                "research_data_diagnostics.py",
                "research_data_exports.py",
            )
        }

        with metadata_path.open(
            "x",
            encoding="utf-8",
        ) as file:
            json.dump(
                metadata,
                file,
                indent=2,
                allow_nan=False,
            )

    except Exception:
        # Remove only the new directory created by this call.
        shutil.rmtree(dataset_dir, ignore_errors=True)
        raise

    return {
        "dataset_dir": dataset_dir,
        "csv_path": csv_path,
        "metadata_path": metadata_path,
        "metadata": metadata,
    }