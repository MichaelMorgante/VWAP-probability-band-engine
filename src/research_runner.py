from copy import deepcopy

import numpy as np
import pandas as pd

from .engine import EngineState, update_engine_state
from .research_sessions import validate_timestamp_index


def run_historical_session(
    candles: pd.DataFrame,
    config: dict,
    *,
    anchor_utc,
) -> pd.DataFrame:
    """
    Reconstruct the existing engine over one historical
    candle sequence without replay delays or live execution.

    All candles must be completed, chronological and
    continuous at M1 frequency.

    The caller supplies the experimental anchor and
    observation window. No warmup duration is assumed.

    Unprefixed values describe the updated state after
    each candle closes.

    Columns prefixed with prior_ describe the preceding
    completed candle's mathematical state.

    Snapshots contain independent scalar values rather
    than references to mutable engine state.
    """
    required = [
        "datetime",
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
    ]

    missing = set(required) - set(candles.columns)

    if missing:
        raise ValueError(
            f"Missing candle columns: {sorted(missing)}"
        )

    if candles.empty:
        raise ValueError("Empty historical session.")

    timestamps = validate_timestamp_index(
        candles["datetime"]
    )

    # Do not silently treat missing minutes as consecutive
    # observations in a time-dependent estimator.
    if len(timestamps) > 1:

        if not (
            timestamps[1:] - timestamps[:-1]
            == pd.Timedelta(minutes=1)
        ).all():
            raise ValueError(
                "Historical session contains missing minutes."
            )

    anchor = pd.Timestamp(anchor_utc)

    if anchor.tzinfo is None:
        raise ValueError(
            "Anchor must be timezone-aware."
        )

    anchor = anchor.tz_convert("UTC")

    if anchor not in timestamps:
        raise ValueError(
            "Anchor candle is absent from the session."
        )

    values = candles[required[1:]].apply(
        pd.to_numeric,
        errors="raise",
    )

    if not np.isfinite(
        values.to_numpy(dtype=float)
    ).all():
        raise ValueError(
            "Non-finite candle values detected."
        )

    if (
        values["high"].lt(values["open"]).any()
        or values["high"].lt(values["close"]).any()
        or values["low"].gt(values["open"]).any()
        or values["low"].gt(values["close"]).any()
        or values["high"].lt(values["low"]).any()
        or values["tick_volume"].le(0).any()
    ):
        raise ValueError(
            "Invalid OHLC or tick-volume observations."
        )

    # Isolate experimental settings from the live CONFIG.
    effective_config = deepcopy(config)

    effective_config["vwap_anchor_utc"] = anchor

    # This runner studies the mathematical bands, not
    # historical MR/CONT/NEU trading probability tables.
    # An empty table activates the engine's existing
    # unconditioned fallback without using future outcomes.
    empty_prob_table = pd.DataFrame(
        columns=["zone"]
    )

    state = EngineState()
    observations = []
    previous_snapshot = None

    for timestamp, row in zip(
        timestamps,
        values.itertuples(index=False, name=None),
    ):

        bar = {
            "datetime": timestamp,
            **dict(zip(required[1:], row)),
        }

        # Same mathematical update used in live mode.
        state = update_engine_state(
            state,
            bar,
            effective_config,
            empty_prob_table,
            empty_prob_table,
        )

        # Capture the updated mathematical state using
        # scalar values rather than mutable state references.
        snapshot = {
            "datetime": timestamp,
            "available_at_utc": (
                timestamp + pd.Timedelta(minutes=1)
            ),
            "is_post_anchor": timestamp >= anchor,
            "close": state.close,
            "reference": state.reference,
            "sigma": state.sigma,
            "z_score": state.z_score,
            "session_bar_count": state.session_bar_count,
            "ghost_ready": (
                state.ghost_distribution is not None
            ),
            "ghost_sigma": (
                state.ghost_distribution.stdev
                if state.ghost_distribution is not None
                else np.nan
            ),
        }

        snapshot.update({
            f"solid_{key}": value
            for key, value in state.bands.items()
        })

        # Preserve a consistent schema even when the
        # Gaussian distribution is not yet available.
        snapshot.update({
            f"ghost_{key}": state.ghost_bands.get(
                key, np.nan
            )
            for key in state.bands
        })

        observation = {
            "anchor_utc": anchor,
            **snapshot,
            "prior_exists": previous_snapshot is not None,
        }

        # The prior snapshot contains only the values
        # captured after processing the preceding candle.
        for key in snapshot:

            if previous_snapshot is not None:

                prior_value = previous_snapshot[key]

            elif key in [
                "datetime",
                "available_at_utc",
            ]:

                prior_value = pd.NaT

            elif key in [
                "ghost_ready",
                "is_post_anchor",
            ]:

                prior_value = False

            else:

                prior_value = np.nan

            observation[f"prior_{key}"] = prior_value

        observations.append(observation)

        # Store only the independent scalar snapshot.
        previous_snapshot = snapshot.copy()

    return pd.DataFrame(observations)