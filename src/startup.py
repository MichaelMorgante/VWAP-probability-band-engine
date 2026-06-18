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
    replay_warmup_bars: int = 200,
    overlay_visual_start: str = "session",
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

    replay_warmup_bars:
        Used only for preset/manual mode.

        Because this project runs on M1, 200 bars = 200 minutes.
        The loader pulls this much data before the selected anchor so the
        engine recreates the state as if it had really been launched then.

        Example:
        selected anchor = 14:00
        replay_warmup_bars = 200
        data load starts = 10:40
        overlay anchor remains = 14:00

    Returns
    -------
    initial_df:
        DataFrame if session rebuild succeeded.
        None if mode='now' or if rebuild fails and fallback should be used.

    session_info:
        Dictionary containing resolved UTC/UK/broker display times.
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

    if session_start_mode == "now":
        session_info["startup_rebuild_used"] = False
        session_info["replay_warmup_bars"] = 0
        session_info["data_start_utc"] = None
        session_info["data_start_uk"] = None
        session_info["overlay_visual_start"] = "none"
        session_info["overlay_line_start_utc"] = None
        session_info["overlay_line_start_uk"] = None
        session_info["overlay_line_start_broker"] = None

        print("\n✅ SESSION_START_MODE='now' selected.")
        print("✅ Using normal recent MT5 warmup, same as before.")
        return None, session_info

    if session_start_mode not in {"preset", "manual"}:
        raise ValueError(
            "session_start_mode must be one of: 'now', 'preset', or 'manual'."
        )

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

        print("\n⚠️ Session rebuild failed. Falling back to normal live startup.")
        print(f"Reason: {exc}")
        return None, session_info