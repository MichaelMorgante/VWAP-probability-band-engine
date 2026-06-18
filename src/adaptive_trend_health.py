from __future__ import annotations

import math
from statistics import median
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default

        value = float(value)

        if math.isnan(value) or math.isinf(value):
            return default

        return value

    except Exception:
        return default


def _median(values: list[float], default: float = 0.0) -> float:
    clean = []

    for value in values:
        parsed = _as_float(value, math.nan)

        if not math.isnan(parsed):
            clean.append(parsed)

    if not clean:
        return default

    return float(median(clean))


def _count_from_end(history: list[dict], key: str) -> int:
    count = 0

    for row in reversed(history):
        if row.get(key, False):
            count += 1
        else:
            break

    return count


def _last_n_values(
    history: list[dict],
    key: str,
    n: int,
    predicate=None,
) -> list[float]:
    values = []

    for row in reversed(history):
        if predicate is not None and not predicate(row):
            continue

        value = _as_float(row.get(key), math.nan)

        if not math.isnan(value):
            values.append(value)

        if len(values) >= n:
            break

    return list(reversed(values))


def _classify_red_shift(avg_shift: float, config: dict) -> str:
    extreme = float(config.get("adaptive_red_shift_extreme_event", 40.0))
    very_high = float(config.get("adaptive_red_shift_very_high_vol", 20.0))
    very_strong = float(config.get("adaptive_red_shift_very_strong", 12.0))
    strong = float(config.get("adaptive_red_shift_strong", 8.0))
    good = float(config.get("adaptive_red_shift_good", 5.0))
    minimum = float(config.get("adaptive_red_shift_minimum", 3.0))

    if avg_shift >= extreme:
        return "EXTREME_EVENT_SHIFT"

    if avg_shift >= very_high:
        return "VERY_HIGH_VOL_SHIFT"

    if avg_shift >= very_strong:
        return "VERY_STRONG_SHIFT"

    if avg_shift >= strong:
        return "STRONG_SHIFT"

    if avg_shift >= good:
        return "GOOD_SHIFT"

    if avg_shift >= minimum:
        return "MINIMUM_SHIFT"

    return "WEAK_SHIFT"


def _classify_orange_pressure(touches: int) -> str:
    if touches >= 4:
        return "EXTENDED_ORANGE_PRESSURE"

    if touches >= 2:
        return "STRONG_ORANGE_PRESSURE"

    if touches >= 1:
        return "ORANGE_IMPULSE"

    return "NO_ORANGE_PRESSURE"


def _classify_compression(compression_count: int) -> str:
    if compression_count >= 3:
        return "STRONG_COMPRESSION"

    if compression_count >= 1:
        return "MILD_COMPRESSION"

    return "NONE"


def _classify_spread_state(spread_count: int) -> str:
    if spread_count >= 3:
        return "STRONG_EXPANSION"

    if spread_count >= 2:
        return "EXPANDING"

    if spread_count == 1:
        return "MIXED_EXPANSION"

    return "NOT_EXPANDING"


def _classify_trend_state(direction: str, clean_count: int, config: dict) -> str:
    building = int(config.get("adaptive_trend_building_bars", 4))
    confirmed = int(config.get("adaptive_trend_confirm_bars", 7))
    established = int(config.get("adaptive_trend_established_bars", 11))
    extended = int(config.get("adaptive_trend_extended_bars", 16))

    if direction not in {"UP", "DOWN"}:
        return "NO_TREND"

    if clean_count >= extended:
        return f"EXTENDED_{direction}_TREND"

    if clean_count >= established:
        return f"ESTABLISHED_{direction}_TREND"

    if clean_count >= confirmed:
        return f"CONFIRMED_{direction}_TREND"

    if clean_count >= building:
        return f"BUILDING_{direction}_TREND"

    return "NO_TREND"


def _classify_trend_health(
    direction: str,
    trend_state: str,
    red_shift_class: str,
    compression_state: str,
    spread_state: str,
    shift_ratio: float,
) -> str:
    if trend_state == "NO_TREND" or direction not in {"UP", "DOWN"}:
        return "NO_TREND"

    if trend_state.startswith("BUILDING"):
        return f"BUILDING_{direction}_TREND"

    if compression_state == "STRONG_COMPRESSION" and red_shift_class in {
        "WEAK_SHIFT",
        "MINIMUM_SHIFT",
    }:
        return f"WEAK_COMPRESSING_{direction}_TREND"

    # Relative decay check:
    # Example: baseline red shift was 12 points, current red shift is 4 points.
    if shift_ratio > 0 and shift_ratio < 0.40:
        return f"DECAYING_{direction}_TREND"

    if shift_ratio >= 0.40 and shift_ratio < 0.60:
        return f"WEAKENING_{direction}_TREND"

    if red_shift_class == "EXTREME_EVENT_SHIFT":
        return f"EXTREME_EVENT_{direction}_TREND"

    if red_shift_class == "VERY_HIGH_VOL_SHIFT":
        return f"VERY_HIGH_VOL_{direction}_TREND"

    if red_shift_class == "VERY_STRONG_SHIFT":
        return f"VERY_STRONG_{direction}_TREND"

    if red_shift_class == "STRONG_SHIFT":
        return f"STRONG_{direction}_TREND"

    if red_shift_class == "GOOD_SHIFT":
        if spread_state in {"EXPANDING", "STRONG_EXPANSION"}:
            return f"HEALTHY_EXPANDING_{direction}_TREND"

        return f"HEALTHY_{direction}_TREND"

    if red_shift_class == "MINIMUM_SHIFT":
        return f"MINIMUM_VALID_{direction}_TREND"

    return f"WEAK_{direction}_TREND"


def update_adaptive_trend_health(
    history: list[dict] | None,
    bar: dict,
    reference: float,
    bands: dict,
    config: dict,
) -> tuple[list[dict], dict]:
    """
    Stateful adaptive trend-health calculation.

    This does NOT detect entries.

    Trend exists from:
    - price holding the trend lane
    - VWAP/green/orange shifting in trend direction

    Trend strength comes from:
    - red band moving in the trend direction

    Spread confirmation comes from:
    - opposite red band moving away
    - total band width expanding

    Band interpretation:
    1+ / 1- = green bands
    2+ / 2- = orange bands
    3+ / 3- = red bands
    """

    history = list(history or [])

    max_history = int(config.get("adaptive_trend_history_bars", 80))
    break_bars = int(config.get("adaptive_trend_break_bars", 3))
    baseline_window = int(config.get("adaptive_shift_baseline_window", 7))
    current_window = int(config.get("adaptive_shift_current_window", 3))
    orange_window = int(config.get("adaptive_orange_pressure_window", 10))
    compression_tolerance = float(config.get("adaptive_compression_tolerance", 0.0))

    close = _as_float(bar.get("close"))
    open_ = _as_float(bar.get("open"), close)
    high = _as_float(bar.get("high"), max(open_, close))
    low = _as_float(bar.get("low"), min(open_, close))

    row = {
        "datetime": bar.get("datetime"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "reference": _as_float(reference),
        "band_1p": _as_float(bands.get("1+")),
        "band_1n": _as_float(bands.get("1-")),
        "band_2p": _as_float(bands.get("2+")),
        "band_2n": _as_float(bands.get("2-")),
        "band_3p": _as_float(bands.get("3+")),
        "band_3n": _as_float(bands.get("3-")),
    }

    previous = history[-1] if history else None

    if previous is None:
        row["reference_shift"] = 0.0
        row["band_1p_shift"] = 0.0
        row["band_1n_shift"] = 0.0
        row["band_2p_shift"] = 0.0
        row["band_2n_shift"] = 0.0
        row["band_3p_shift"] = 0.0
        row["band_3n_shift"] = 0.0
        row["band_width_shift"] = 0.0

    else:
        row["reference_shift"] = row["reference"] - _as_float(previous.get("reference"))
        row["band_1p_shift"] = row["band_1p"] - _as_float(previous.get("band_1p"))
        row["band_1n_shift"] = row["band_1n"] - _as_float(previous.get("band_1n"))
        row["band_2p_shift"] = row["band_2p"] - _as_float(previous.get("band_2p"))
        row["band_2n_shift"] = row["band_2n"] - _as_float(previous.get("band_2n"))
        row["band_3p_shift"] = row["band_3p"] - _as_float(previous.get("band_3p"))
        row["band_3n_shift"] = row["band_3n"] - _as_float(previous.get("band_3n"))

        current_width = row["band_3p"] - row["band_3n"]
        previous_width = _as_float(previous.get("band_3p")) - _as_float(previous.get("band_3n"))

        row["band_width_shift"] = current_width - previous_width

    # Orange touch is impulse/extension, not a trend-ending signal.
    row["up_orange_touch"] = row["high"] >= row["band_2p"]
    row["down_orange_touch"] = row["low"] <= row["band_2n"]

    row["compressing"] = row["band_width_shift"] < -abs(compression_tolerance)

    # Trend-lane logic.
    # UP = price holds above upper green while VWAP/green/orange shift up.
    # DOWN = price holds below lower green while VWAP/green/orange shift down.
    # Orange touch is allowed.
    row["up_lane"] = (
        row["close"] > row["band_1p"]
        and row["reference_shift"] > 0
        and row["band_1p_shift"] > 0
        and row["band_2p_shift"] > 0
    )

    row["down_lane"] = (
        row["close"] < row["band_1n"]
        and row["reference_shift"] < 0
        and row["band_1n_shift"] < 0
        and row["band_2n_shift"] < 0
    )

    # Directional red-band shift.
    # This is the main trend-power measurement.
    bullish_directional_red_shift = max(row["band_3p_shift"], 0.0)
    bearish_directional_red_shift = max(-row["band_3n_shift"], 0.0)

    # Opposite-side red-band movement.
    # This confirms bands are spreading away from price/value.
    bullish_opposite_red_shift = max(-row["band_3n_shift"], 0.0)
    bearish_opposite_red_shift = max(row["band_3p_shift"], 0.0)

    row["instant_up_shift"] = bullish_directional_red_shift
    row["instant_down_shift"] = bearish_directional_red_shift

    row["up_spreading"] = (
        bullish_directional_red_shift > 0
        and bullish_opposite_red_shift > 0
        and row["band_width_shift"] > 0
    )

    row["down_spreading"] = (
        bearish_directional_red_shift > 0
        and bearish_opposite_red_shift > 0
        and row["band_width_shift"] > 0
    )

    history.append(row)
    history = history[-max_history:]

    up_clean_count = _count_from_end(history, "up_lane")
    down_clean_count = _count_from_end(history, "down_lane")

    prev = history[-2] if len(history) >= 2 else {}
    prev_direction = prev.get("active_direction", "NONE")
    prev_break_count = int(prev.get("trend_break_count", 0))
    prev_active_clean_count = int(prev.get("active_clean_count", 0))

    building_bars = int(config.get("adaptive_trend_building_bars", 4))

    active_direction = "NONE"
    active_clean_count = 0
    trend_break_count = 0

    if up_clean_count >= building_bars:
        active_direction = "UP"
        active_clean_count = up_clean_count
        trend_break_count = 0

    elif down_clean_count >= building_bars:
        active_direction = "DOWN"
        active_clean_count = down_clean_count
        trend_break_count = 0

    elif prev_direction == "UP":
        latest = history[-1]

        lost_green = latest["close"] < latest["band_1p"]
        lost_shift = (
            latest["reference_shift"] <= 0
            or latest["band_1p_shift"] <= 0
            or latest["band_2p_shift"] <= 0
        )
        hard_vwap_break = latest["close"] < latest["reference"]

        if lost_green or lost_shift or latest["compressing"]:
            trend_break_count = prev_break_count + 1
        else:
            trend_break_count = 0

        if hard_vwap_break or trend_break_count >= break_bars:
            active_direction = "NONE"
            active_clean_count = 0
        else:
            active_direction = "UP"
            active_clean_count = prev_active_clean_count

    elif prev_direction == "DOWN":
        latest = history[-1]

        lost_green = latest["close"] > latest["band_1n"]
        lost_shift = (
            latest["reference_shift"] >= 0
            or latest["band_1n_shift"] >= 0
            or latest["band_2n_shift"] >= 0
        )
        hard_vwap_break = latest["close"] > latest["reference"]

        if lost_green or lost_shift or latest["compressing"]:
            trend_break_count = prev_break_count + 1
        else:
            trend_break_count = 0

        if hard_vwap_break or trend_break_count >= break_bars:
            active_direction = "NONE"
            active_clean_count = 0
        else:
            active_direction = "DOWN"
            active_clean_count = prev_active_clean_count

    latest = history[-1]
    latest["active_direction"] = active_direction
    latest["active_clean_count"] = active_clean_count
    latest["trend_break_count"] = trend_break_count

    trend_state = _classify_trend_state(active_direction, active_clean_count, config)

    if active_direction == "UP":
        shift_key = "instant_up_shift"
        lane_key = "up_lane"
        orange_key = "up_orange_touch"
        spread_key = "up_spreading"

    elif active_direction == "DOWN":
        shift_key = "instant_down_shift"
        lane_key = "down_lane"
        orange_key = "down_orange_touch"
        spread_key = "down_spreading"

    else:
        shift_key = None
        lane_key = None
        orange_key = None
        spread_key = None

    if shift_key is None:
        baseline_shift = 0.0
        current_shift = 0.0
        orange_touches = 0
        spread_count = 0

    else:
        baseline_values = _last_n_values(
            history,
            shift_key,
            baseline_window,
            predicate=lambda r: bool(r.get(lane_key, False)),
        )

        current_values = _last_n_values(
            history,
            shift_key,
            current_window,
        )

        baseline_shift = _median(baseline_values, default=0.0)
        current_shift = _median(current_values, default=0.0)

        recent_orange = history[-orange_window:]
        orange_touches = int(sum(1 for r in recent_orange if r.get(orange_key, False)))

        recent_spread = history[-current_window:]
        spread_count = int(sum(1 for r in recent_spread if r.get(spread_key, False)))

    compression_count = int(sum(1 for r in history[-3:] if r.get("compressing", False)))

    compression_state = _classify_compression(compression_count)
    spread_state = _classify_spread_state(spread_count)

    shift_ratio = current_shift / baseline_shift if baseline_shift > 0 else 0.0
    red_shift_class = _classify_red_shift(baseline_shift, config)
    orange_pressure = _classify_orange_pressure(orange_touches)

    trend_health = _classify_trend_health(
        direction=active_direction,
        trend_state=trend_state,
        red_shift_class=red_shift_class,
        compression_state=compression_state,
        spread_state=spread_state,
        shift_ratio=shift_ratio,
    )

    health = {
        "trend_direction": active_direction,
        "trend_state": trend_state,
        "lane_count": active_clean_count,

        # Red-band shift values.
        "avg_trend_shift": baseline_shift,
        "current_shift": current_shift,
        "shift_ratio": shift_ratio,
        "shift_class": red_shift_class,

        # Expansion/spread values.
        "spread_state": spread_state,
        "spread_count": spread_count,

        # Other context.
        "orange_touches": orange_touches,
        "orange_pressure": orange_pressure,
        "compression_state": compression_state,
        "trend_health": trend_health,
        "trend_break_count": trend_break_count,
    }

    return history, health