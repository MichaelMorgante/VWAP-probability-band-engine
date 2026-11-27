import pandas as pd

from .research_config import RESEARCH_CONFIG


def validate_timestamp_index(timestamps):
    """
    Validate the structural requirements for historical
    minute-level timestamp analysis.
    """
    index = pd.DatetimeIndex(timestamps)

    if index.tz is None or index.hasnans:
        raise ValueError(
            "Valid timezone-aware timestamps required."
        )

    index = index.tz_convert("UTC")

    if index.has_duplicates:
        raise ValueError("Duplicate timestamps detected.")

    if not index.is_monotonic_increasing:
        raise ValueError("Unordered timestamps detected.")

    if not index.equals(index.floor("min")):
        raise ValueError(
            "Minute-aligned timestamps required."
        )

    return index


def classify_research_split(session_date):
    """
    Assign a chronological partition independently
    of model assumptions and market outcomes.
    """
    date = pd.Timestamp(session_date).date()

    for name, start, end in RESEARCH_CONFIG[
        "research_splits"
    ]:

        if (
            pd.Timestamp(start).date()
            <= date
            < pd.Timestamp(end).date()
        ):
            return name

    return "unassigned"


def summarise_daily_coverage(
    timestamps,
    start_date,
    end_date,
    *,
    timezone="America/New_York",
):
    """
    Describe observed daily coverage without imposing
    an anchor, warmup or research window.

    Internal gaps are descriptive and may include
    legitimate market closures.
    """
    index = validate_timestamp_index(timestamps)

    local = index.tz_convert(timezone)

    observations = pd.DataFrame({
        "date": local.strftime("%Y-%m-%d"),
        "timestamp": local,
    })

    daily = observations.groupby(
        "date"
    )["timestamp"].agg(
        first_observed="min",
        last_observed="max",
        observed_minutes="size",
    )

    dates = pd.date_range(
        start_date,
        end_date,
        freq="D",
    ).strftime("%Y-%m-%d")

    daily = daily.reindex(dates)

    daily.index.name = "date"

    daily["observed_minutes"] = (
        daily["observed_minutes"]
        .fillna(0)
        .astype(int)
    )

    daily["span_minutes"] = (
        (
            daily["last_observed"]
            - daily["first_observed"]
        ).dt.total_seconds() / 60 + 1
    ).astype("Int64")

    daily["internal_unobserved_minutes"] = (
        daily["span_minutes"]
        - daily["observed_minutes"]
    )

    daily["has_observations"] = (
        daily["observed_minutes"] > 0
    )

    daily = daily.reset_index()

    daily["split"] = daily["date"].map(
        classify_research_split
    )

    return daily


def assess_windows(timestamps, windows):
    """
    Assess completeness for arbitrary half-open
    time windows [start, end).

    Windows must contain timezone-aware start and
    end columns. No model parameters are assumed.
    """
    index = validate_timestamp_index(timestamps)

    result = windows.copy()

    starts = pd.DatetimeIndex(result["start"])
    ends = pd.DatetimeIndex(result["end"])

    if (
        starts.tz is None
        or ends.tz is None
        or starts.hasnans
        or ends.hasnans
    ):
        raise ValueError(
            "Timezone-aware window boundaries required."
        )

    starts = starts.tz_convert("UTC")
    ends = ends.tz_convert("UTC")

    if (
        not starts.equals(starts.floor("min"))
        or not ends.equals(ends.floor("min"))
    ):
        raise ValueError(
            "Window boundaries must be minute-aligned."
        )

    if (ends <= starts).any():
        raise ValueError(
            "Window end must follow its start."
        )

    expected = (
        (ends - starts) / pd.Timedelta(minutes=1)
    ).astype(int)

    observed = (
        index.searchsorted(ends, side="left")
        - index.searchsorted(starts, side="left")
    )

    result["expected_minutes"] = expected
    result["observed_minutes"] = observed

    result["missing_minutes"] = (
        expected - observed
    )

    result["complete"] = (
        result["missing_minutes"] == 0
    )

    return result