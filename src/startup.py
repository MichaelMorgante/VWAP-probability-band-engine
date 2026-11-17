from __future__ import annotations

from datetime import timedelta
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
    replay_warmup_bars: int = 90,
    overlay_visual_start: str = "session",
) -> tuple[pd.DataFrame | None, dict]:
    """Load M1 candles to warm up and rebuild the selected session.

    All three modes load replay_warmup_bars minutes before their anchor.
    The live runner uses those candles to warm up the width, then starts
    the trading VWAP at the anchor.

    Return the candles and resolved session times. A failed history load
    returns None for the candles.
    """
    session_start_mode = session_start_mode.lower().strip()

    session_info = resolve_session_start(
        mode=session_start_mode,
        preset=session_preset,
        manual_start_uk=manual_start_uk,
        offset_minutes=anchor_offset_minutes,
        broker_timezone_name=broker_timezone_name,
    )

    print("\n" + format_session_summary(session_info))


    try:
        replay_warmup_bars = max(int(replay_warmup_bars), 0)

        # M1 assumption:
        # 1 bar = 1 minute, so 200 bars = 200 minutes.
        data_start_utc = session_info["start_utc"] - timedelta(
            minutes=replay_warmup_bars
        )

        session_info["replay_warmup_bars"] = replay_warmup_bars
        session_info["data_start_utc"] = data_start_utc
        session_info["data_start_uk"] = data_start_utc.astimezone(
            session_info["start_uk"].tzinfo
        )

        overlay_visual_start = overlay_visual_start.lower().strip()

        if overlay_visual_start not in {"session", "warmup"}:
            raise ValueError(
                "overlay_visual_start must be either 'session' or 'warmup'."
            )

        if overlay_visual_start == "warmup":
            overlay_line_start_utc = data_start_utc
        else:
            overlay_line_start_utc = session_info["start_utc"]

        session_info["overlay_visual_start"] = overlay_visual_start
        session_info["overlay_line_start_utc"] = overlay_line_start_utc
        session_info["overlay_line_start_uk"] = overlay_line_start_utc.astimezone(
            session_info["start_uk"].tzinfo
        )

        start_broker = session_info.get("start_broker")
        if start_broker is not None:
            session_info["overlay_line_start_broker"] = overlay_line_start_utc.astimezone(
                start_broker.tzinfo
            )
        else:
            session_info["overlay_line_start_broker"] = None

        print("\n✅ Loading session rebuild candles from MT5...")
        print(f"✅ Selected launch anchor UK: {session_info['start_uk']:%H:%M}")
        print(f"✅ Data warmup start UK:      {session_info['data_start_uk']:%H:%M}")
        print(
            f"✅ Overlay line start UK:     "
            f"{session_info['overlay_line_start_uk']:%H:%M} "
            f"({overlay_visual_start})"
        )
        print(f"✅ Replay warmup bars:       {replay_warmup_bars}")

        initial_df = load_mt5_range(
            symbol=symbol,
            timeframe_mt5=timeframe_mt5,
            start_time_utc=data_start_utc,
            end_time_utc=session_info["end_utc"],
        )

        session_info["startup_rebuild_used"] = True

        print(f"✅ Loaded {len(initial_df):,} candles including replay warmup")

        if "datetime" in initial_df.columns and len(initial_df) > 0:
            print(f"✅ First loaded candle: {initial_df['datetime'].min()}")
            print(f"✅ Last loaded candle:  {initial_df['datetime'].max()}")

        return initial_df, session_info

    except Exception as exc:
        session_info["startup_rebuild_used"] = False

        print("\n⚠️ Could not load history for the selected VWAP anchor.")
        print(f"Reason: {exc}")
        return None, session_info