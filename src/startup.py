from __future__ import annotations

from typing import Any

import pandas as pd

from src.loaders import load_mt5_range
from src.session_times import format_session_summary, resolve_session_start


def prepare_live_startup(
    symbol: str,
    timeframe_mt5: Any,
    session_start_mode: str = "now",
    session_preset: str = "ny_open",
    anchor_offset_minutes: int = -30,
    manual_start_uk: str = "16:00",
    broker_timezone_name: str | None = None,
) -> tuple[pd.DataFrame | None, dict]:
    """
    Prepare optional startup data for the live engine.

    Modes
    -----
    now:
        Current/old behaviour. Do not preload session data.
        The live runner will use its normal recent MT5 warmup.

    preset:
        Load candles from a named session anchor, e.g.
        London open, New York open, or Asia/Tokyo open.

    manual:
        Load candles from a manually selected UK time, e.g. 16:00.

    Returns
    -------
    initial_df:
        DataFrame if session rebuild succeeded.
        None if mode='now' or if rebuild fails and fallback should be used.

    session_info:
        Dictionary containing resolved UTC/UK/broker display times.
    """
    session_info = resolve_session_start(
        mode=session_start_mode,
        preset=session_preset,
        manual_start_uk=manual_start_uk,
        offset_minutes=anchor_offset_minutes,
        broker_timezone_name=broker_timezone_name,
    )

    print("\n" + format_session_summary(session_info))

    if session_start_mode == "now":
        print("\n✅ SESSION_START_MODE='now' selected.")
        print("✅ Using normal recent MT5 warmup, same as before.")
        return None, session_info

    if session_start_mode not in {"preset", "manual"}:
        raise ValueError(
            "session_start_mode must be one of: 'now', 'preset', or 'manual'."
        )

    try:
        print("\n✅ Loading session rebuild candles from MT5...")

        initial_df = load_mt5_range(
            symbol=symbol,
            timeframe_mt5=timeframe_mt5,
            start_time_utc=session_info["start_utc"],
            end_time_utc=session_info["end_utc"],
        )

        print(f"✅ Loaded {len(initial_df):,} candles from selected startup anchor")
        return initial_df, session_info

    except Exception as exc:
        print("\n⚠️ Session rebuild failed. Falling back to normal live startup.")
        print(f"Reason: {exc}")
        return None, session_info