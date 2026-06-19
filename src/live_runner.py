import copy
import os
import json
import time
from pathlib import Path

import pandas as pd

from src.context_overlay import compute_context_vwap


def compute_reference_shift(state, lookback: int = 5) -> float:
    """
    Return cumulative reference/VWAP shift over the last `lookback` bars.
    Uses the engine's internal reference history if available.
    """
    ref_history = getattr(state, "_ref_history", None)

    if ref_history is not None and len(ref_history) >= lookback + 1:
        return float(state.reference - ref_history[-(lookback + 1)])

    return 0.0

# ── Context overlay: export bendy live trail for MT5 / external view ──
def write_live_context(
    symbol: str,
    live_df: pd.DataFrame,
    config: dict,
    output_dir=None,
    n_points: int = 50
) -> None:
    """
    Compute rolling context VWAP bands on recent live bars and write them
    to live_context.json for MT5 or other chart overlays.
    """
    if live_df is None or live_df.empty:
        print("⚠️ write_live_context skipped: live_df is empty")
        return

    live_df = live_df.copy()

    required_price_cols = ['close', 'tick_volume']
    missing = [c for c in required_price_cols if c not in live_df.columns]
    if missing:
        print(f"⚠️ write_live_context skipped: missing columns {missing}")
        return

    if 'datetime' not in live_df.columns:
        print("⚠️ write_live_context skipped: missing 'datetime'")
        return

    live_df['datetime'] = pd.to_datetime(live_df['datetime'])

    if 'typical_price' not in live_df.columns:
        if all(c in live_df.columns for c in ['high', 'low', 'close']):
            live_df['typical_price'] = (
                live_df['high'] + live_df['low'] + live_df['close']
            ) / 3.0
        else:
            print("⚠️ write_live_context skipped: cannot build typical_price")
            return

    if 'session_id' not in live_df.columns:
        live_df['session_id'] = live_df['datetime'].dt.date.astype(str)

    if output_dir is None:
        try:
            import MetaTrader5 as mt5
            output_dir = Path(mt5.terminal_info().data_path) / 'MQL5' / 'Files'
        except Exception:
            output_dir = Path('live_artifacts')

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / 'live_context.json'

    ctx = compute_context_vwap(live_df, config).copy()
    ctx['datetime'] = live_df['datetime'].values
    tail = ctx.tail(n_points)

    points = []
    for _, row in tail.iterrows():
        if pd.isna(row.get('context_reference')):
            continue

        points.append({
            'datetime': str(row['datetime'])[:19],
            'ctx_ref':  round(float(row['context_reference']), 5),
            'ctx_1p':   round(float(row['context_band_1p']), 5),
            'ctx_1n':   round(float(row['context_band_1n']), 5),
            'ctx_2p':   round(float(row['context_band_2p']), 5),
            'ctx_2n':   round(float(row['context_band_2n']), 5),
            'ctx_3p':   round(float(row['context_band_3p']), 5),
            'ctx_3n':   round(float(row['context_band_3n']), 5),
        })

    payload = {
        'symbol': symbol,
        'n_points': len(points),
        'points': points,
    }

    tmp_path = output_path.with_suffix('.tmp')

    for attempt in range(5):
        try:
            with open(tmp_path, 'w') as f:
               json.dump(payload, f, indent=2)

            os.replace(tmp_path, output_path)
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)

    print(f"✅ Context written: {output_path} ({len(points)} points)")

def run_live(symbol: str, timeframe_mt5, config: dict,
             prob_table: pd.DataFrame,
             marginal_table: pd.DataFrame = None,
             load_mt5_live=None,
             EngineState=None,
             update_engine_state=None,
             generate_signal=None,
             regime_gate=None,
             apply_filters=None,
             on_state_update=None,
             initial_df: pd.DataFrame | None = None,
             session_info: dict | None = None,) -> None:
    """
    Live mode runner with:
    - Session warmup guard (no signals for first N bars after VWAP reset)
    - Signal state machine (alerts only on state transitions)
    - Reconnection loop with backoff
    - JSON state output to live_artifacts/live_state.json each bar

    Signal states: NO_SIGNAL → SIGNAL_ACTIVE → SIGNAL_RESOLVED
    Alert fires only on: NO_SIGNAL→ACTIVE, ACTIVE→RESOLVED transitions.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise ImportError("pip install MetaTrader5")

    if load_mt5_live is None:
        raise ValueError("run_live() requires load_mt5_live")
    if EngineState is None:
        raise ValueError("run_live() requires EngineState")
    if update_engine_state is None:
        raise ValueError("run_live() requires update_engine_state")
    if generate_signal is None:
        raise ValueError("run_live() requires generate_signal")
    if regime_gate is None:
        raise ValueError("run_live() requires regime_gate")
    if apply_filters is None:
        raise ValueError("run_live() requires apply_filters")

    if marginal_table is None:
        marginal_table = prob_table

    mt5_files_dir = Path(mt5.terminal_info().data_path) / "MQL5" / "Files"
    mt5_files_dir.mkdir(parents=True, exist_ok=True)
    output_path = mt5_files_dir / "live_state.json"

    # ── Warm up engine ──
    if initial_df is not None:
        warmup_df = initial_df.copy()
        print(f"✅ Using preloaded startup dataframe: {len(warmup_df):,} bars")

        if session_info is not None:
            print(
                "✅ Startup session: "
                f"{session_info.get('label', 'unknown')} "
                f"| mode={session_info.get('mode', 'unknown')}"
            )
    else:
        warmup_df = load_mt5_live(symbol, timeframe_mt5, n_bars=200)
        print(f"✅ Using normal MT5 live warmup: {len(warmup_df):,} bars")

    if warmup_df is None or len(warmup_df) == 0:
        raise RuntimeError("Warmup dataframe is empty. Cannot start live engine.")

    if "datetime" in warmup_df.columns:
        warmup_df = warmup_df.sort_values("datetime").reset_index(drop=True)

    state = EngineState()

    for _, row in warmup_df.iterrows():
        state = update_engine_state(
            state,
            row.to_dict(),
            config,
            prob_table,
            marginal_table,
        )

    print(f"✅ Live engine warmed up on {len(warmup_df):,} bars")
    # If preset/manual startup replay was used, the warmup dataframe already
    # contains candles up to the current/latest available bar.
    #
    # Set last_bar_time to the final replayed candle so the live loop continues
    # AFTER the replay, instead of processing the same latest candle again.
    #
    # In normal "now" mode, keep last_bar_time=None to preserve existing behaviour.
    startup_replay_active = (
        initial_df is not None
        and session_info is not None
        and bool(session_info.get("startup_rebuild_used", False))
    )

    if startup_replay_active and "datetime" in warmup_df.columns:
        last_bar_time = pd.to_datetime(warmup_df["datetime"].max(), utc=True)
        print(f"✅ Startup replay complete. Live loop will continue after: {last_bar_time}")
    else:
        last_bar_time = None

    # last_bar_time is set after warmup.
    # In normal "now" mode it remains None, preserving old behaviour.
    signal_state = 'NO_SIGNAL'   # state machine
    active_signal = None         # the SignalResult currently active
    reconnect_wait = 1

    print(f"🟢 Live mode active — {symbol} | Ctrl+C to stop")
    try:
        while True:
            try:
                rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 1, 1)
            except Exception as e:
                print(f"⚠️  MT5 read error: {e} — retrying in {reconnect_wait}s")
                time.sleep(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 60)
                continue

            reconnect_wait = 1  # reset on success

            if rates is None or len(rates) == 0:
                time.sleep(1)
                continue

            bar_time = rates[0]['time']
            if bar_time == last_bar_time:
                time.sleep(1)
                continue

            last_bar_time = bar_time
            bar = {
                'datetime':    pd.Timestamp(bar_time, unit='s', tz='UTC'),
                'open':        float(rates[0]['open']),
                'high':        float(rates[0]['high']),
                'low':         float(rates[0]['low']),
                'close':       float(rates[0]['close']),
                'tick_volume': float(rates[0]['tick_volume']),
            }

            state = update_engine_state(state, bar, config, prob_table, marginal_table)
            sig = generate_signal(state, config)
            sig = regime_gate(sig, config)
            sig = apply_filters(sig, state, config)

            # ── Alert state machine ──
            alert = None
            new_sig_state = 'SIGNAL_ACTIVE' if sig.signal_type != 'NO_SIGNAL' else 'NO_SIGNAL'

            if signal_state == 'NO_SIGNAL' and new_sig_state == 'SIGNAL_ACTIVE':
                alert = f"🔔 NEW SIGNAL: {sig.signal_type} | Zone {sig.zone} | EdgeGap {sig.edge_gap:.2f}"
                active_signal = sig

            elif signal_state == 'SIGNAL_ACTIVE' and new_sig_state == 'NO_SIGNAL':
                alert = f"✅ SIGNAL RESOLVED: {active_signal.signal_type} | Z now={state.z_score:.2f}"
                active_signal = None
                new_sig_state = 'NO_SIGNAL'

            signal_state = new_sig_state

            # ── Live state JSON output (read by MQL5 overlay) ──
            probs = state.probabilities

            reference_shift_5 = compute_reference_shift(
                state,
                lookback=int(config.get("vwap_shift_lookback", 5))
            )

            raw_trend = state.context.get('trend_bin', 'flat')

            trend_display = {
                'up': 'BULLISH',
                'down': 'BEARISH',
                'flat': 'FLAT'
            }.get(raw_trend, 'FLAT')

            setup_display = getattr(sig, 'setup_type', None)
            if setup_display is None:
                setup_display = probs.get('dominant', 'NEU')

            setup_display = {
                'MR': 'MR',
                'CONT': 'CONT',
                'NEU': 'NEUTRAL',
                'NEUTRAL': 'NEUTRAL'
            }.get(setup_display, 'NEUTRAL')

            signal_display = getattr(sig, 'signal_display', None)
            if signal_display is None:
                signal_display = sig.signal_type

            if signal_display == 'NO_SIGNAL':
                signal_display = 'WAIT'

            ath = getattr(state, "adaptive_trend_health", {}) or {}

            live_state_dict = {
                'datetime':      str(state.datetime),
                'symbol':        symbol,
                'close':         round(state.close, 5),
                'reference':     round(state.reference, 5),
                'reference_shift_5': round(reference_shift_5, 5),
                'sigma':         round(state.sigma, 5),
                'z_score':       round(state.z_score, 4),
                'z_velocity':    round(state.z_velocity, 4),
                'zone':          state.zone,
                'trend_bin':     state.context.get('trend_bin', ''),
                'trend_display': trend_display,
                'bias_display': state.context.get('bias_display', 'NEUTRAL'),
                'setup_type': setup_display,
                'signal_display': signal_display,
                'suppressed_by': sig.suppressed_by,
                'volume_bin':    state.context.get('volume_bin', ''),
                'time_bin':      state.context.get('time_bin', ''),
                'p_mr':          round(probs.get('MR', {}).get('prob', 0), 4) if isinstance(probs.get('MR'), dict) else 0,
                'p_cont':        round(probs.get('CONT', {}).get('prob', 0), 4) if isinstance(probs.get('CONT'), dict) else 0,
                'edge_gap':      round(probs.get('edge_gap', 0), 4),
                'signal_type': sig.signal_type,
                'signal_state': signal_state,
                'session_bar': state.session_bar_count,

                'adaptive_trend_direction': ath.get('trend_direction', 'NONE'),
                'adaptive_trend_state': ath.get('trend_state', 'NO_TREND'),
                'adaptive_lane_count': int(ath.get('lane_count', 0)),
                'adaptive_red_shift': round(float(ath.get('avg_trend_shift', 0.0)), 2),
                'adaptive_current_red_shift': round(float(ath.get('current_shift', 0.0)), 2),
                'adaptive_shift_ratio': round(float(ath.get('shift_ratio', 0.0)), 4),
                'adaptive_shift_class': ath.get('shift_class', 'WEAK_SHIFT'),
                'adaptive_spread_state': ath.get('spread_state', 'NOT_EXPANDING'),
                'adaptive_orange_pressure': ath.get('orange_pressure', 'NO_ORANGE_PRESSURE'),
                'adaptive_compression': ath.get('compression_state', 'NONE'),
                'adaptive_trend_health': ath.get('trend_health', 'NO_TREND'),
                
                'band_1p':       round(state.bands.get('1+', 0), 5),
                'band_1n':       round(state.bands.get('1-', 0), 5),
                'band_2p':       round(state.bands.get('2+', 0), 5),
                'band_2n':       round(state.bands.get('2-', 0), 5),
                'band_3p':       round(state.bands.get('3+', 0), 5),
                'band_3n':       round(state.bands.get('3-', 0), 5),
            }
            if session_info is not None:
                start_uk = session_info.get("start_uk")
                start_broker = session_info.get("start_broker")
                line_start_uk = session_info.get("overlay_line_start_uk")
                line_start_broker = session_info.get("overlay_line_start_broker")
                rebuild_used = bool(session_info.get("startup_rebuild_used", False))

                live_state_dict.update(
                    {
                        "startup_mode": str(session_info.get("mode", "")),
                        "startup_label": str(session_info.get("label", "")),
                        "startup_overlay_visual_start": str(
                            session_info.get("overlay_visual_start", "")
                        ),
                        "startup_start_uk": (
                            start_uk.strftime("%H:%M") if start_uk is not None else ""
                        ),
                        "startup_start_server": (
                            start_broker.strftime("%Y.%m.%d %H:%M")
                            if start_broker is not None
                            else ""
                        ),
                        "startup_line_start_uk": (
                            line_start_uk.strftime("%H:%M") if line_start_uk is not None else ""
                        ),
                        "startup_line_start_server": (
                            line_start_broker.strftime("%Y.%m.%d %H:%M")
                            if line_start_broker is not None
                            else ""
                        ),
                        "startup_anchor_active": (
                            "YES" if rebuild_used and line_start_broker is not None else "NO"
                        ),
                    }
                )
            else:
                live_state_dict.update(
                    {
                        "startup_mode": "",
                        "startup_label": "",
                        "startup_overlay_visual_start": "",
                        "startup_start_uk": "",
                        "startup_start_server": "",
                        "startup_line_start_uk": "",
                        "startup_line_start_server": "",
                        "startup_anchor_active": "NO",
                    }
                )
            with open(output_path, 'w') as f:
                json.dump(live_state_dict, f, indent=2)

            if alert:
                print(alert)

            if on_state_update:
                on_state_update(copy.copy(state), sig)

    except KeyboardInterrupt:
        print("\n🔴 Live mode stopped")


# ── Context overlay: separate live runner with bendy export ──────────
def run_live_with_context(symbol: str, timeframe_mt5, config: dict,
                          prob_table: pd.DataFrame,
                          marginal_table: pd.DataFrame = None,
                          load_mt5_live=None,
                          EngineState=None,
                          update_engine_state=None,
                          generate_signal=None,
                          regime_gate=None,
                          apply_filters=None,
                          on_state_update=None) -> None:
    """
    Live mode runner with:
    - Session warmup guard
    - Signal state machine
    - Reconnection loop with backoff
    - JSON state output to live_artifacts/live_state.json each bar
    - Context VWAP trail output to live_artifacts/live_context.json each bar

    This preserves the original run_live() and adds a separate version for
    context-overlay export testing.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise ImportError("pip install MetaTrader5")

    if load_mt5_live is None:
        raise ValueError("run_live_with_context() requires load_mt5_live")
    if EngineState is None:
        raise ValueError("run_live_with_context() requires EngineState")
    if update_engine_state is None:
        raise ValueError("run_live_with_context() requires update_engine_state")
    if generate_signal is None:
        raise ValueError("run_live_with_context() requires generate_signal")
    if regime_gate is None:
        raise ValueError("run_live_with_context() requires regime_gate")
    if apply_filters is None:
        raise ValueError("run_live_with_context() requires apply_filters")

    if marginal_table is None:
        marginal_table = prob_table

    mt5_files_dir = Path(mt5.terminal_info().data_path) / "MQL5" / "Files"
    mt5_files_dir.mkdir(parents=True, exist_ok=True)
    output_path = mt5_files_dir / "live_state.json"

    # ── Warm up engine ──
    warmup_df = load_mt5_live(symbol, timeframe_mt5, n_bars=200)

    if 'sessions' in config:
        try:
            from src.loaders import assign_sessions
            warmup_df = assign_sessions(warmup_df, config['sessions'])
        except Exception:
            pass

    if 'typical_price' not in warmup_df.columns and all(c in warmup_df.columns for c in ['high', 'low', 'close']):
        warmup_df['typical_price'] = (
            warmup_df['high'] + warmup_df['low'] + warmup_df['close']
        ) / 3.0

    state = EngineState()
    for _, row in warmup_df.iterrows():
        state = update_engine_state(state, row.to_dict(), config,
                                    prob_table, marginal_table)
    print(f"✅ Live engine warmed up on {len(warmup_df)} bars")

    last_bar_time = None
    signal_state = 'NO_SIGNAL'
    active_signal = None
    reconnect_wait = 1

    print(f"🟢 Live mode with context overlay active — {symbol} | Ctrl+C to stop")

    try:
        while True:
            try:
                rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 1, 1)
            except Exception as e:
                print(f"⚠️  MT5 read error: {e} — retrying in {reconnect_wait}s")
                time.sleep(reconnect_wait)
                reconnect_wait = min(reconnect_wait * 2, 60)
                continue

            reconnect_wait = 1

            if rates is None or len(rates) == 0:
                time.sleep(1)
                continue

            bar_time = rates[0]['time']
            if bar_time == last_bar_time:
                time.sleep(1)
                continue

            last_bar_time = bar_time
            bar = {
                'datetime':    pd.Timestamp(bar_time, unit='s', tz='UTC'),
                'open':        float(rates[0]['open']),
                'high':        float(rates[0]['high']),
                'low':         float(rates[0]['low']),
                'close':       float(rates[0]['close']),
                'tick_volume': float(rates[0]['tick_volume']),
            }

            if 'sessions' in config:
                try:
                    from src.loaders import assign_session_id
                    bar['session_id'] = assign_session_id(
                        bar['datetime'], config['sessions']
                    )[0]
                except Exception:
                    bar['session_id'] = str(bar['datetime'].date())

            bar['typical_price'] = (bar['high'] + bar['low'] + bar['close']) / 3.0

            state = update_engine_state(state, bar, config, prob_table, marginal_table)
            sig = generate_signal(state, config)
            sig = regime_gate(sig, config)
            sig = apply_filters(sig, state, config)

            alert = None
            new_sig_state = 'SIGNAL_ACTIVE' if sig.signal_type != 'NO_SIGNAL' else 'NO_SIGNAL'

            if signal_state == 'NO_SIGNAL' and new_sig_state == 'SIGNAL_ACTIVE':
                alert = f"🔔 NEW SIGNAL: {sig.signal_type} | Zone {sig.zone} | EdgeGap {sig.edge_gap:.2f}"
                active_signal = sig

            elif signal_state == 'SIGNAL_ACTIVE' and new_sig_state == 'NO_SIGNAL':
                if active_signal is not None:
                    alert = f"✅ SIGNAL RESOLVED: {active_signal.signal_type} | Z now={state.z_score:.2f}"
                else:
                    alert = f"✅ SIGNAL RESOLVED | Z now={state.z_score:.2f}"
                active_signal = None
                new_sig_state = 'NO_SIGNAL'

            signal_state = new_sig_state

            # ── Append new bar to rolling live buffer ──
            warmup_df = pd.concat([warmup_df, pd.DataFrame([bar])], ignore_index=True)

            # ── Context overlay: keep a longer rolling buffer for smoother bendy trail ──
            context_export_points = 120

            keep_bars = max(
                config.get('context_vwap_window', 60),
                config.get('context_sigma_window', 30)
            ) + context_export_points + 20

            warmup_df = warmup_df.tail(keep_bars).copy()

            # ── Live state JSON output (read by MQL5 overlay) ──
            probs = state.probabilities

            reference_shift_5 = compute_reference_shift(
                state,
                lookback=int(config.get("vwap_shift_lookback", 5))
            )

            raw_trend = state.context.get('trend_bin', 'flat')

            trend_display = {
                'up': 'BULLISH',
                'down': 'BEARISH',
                'flat': 'FLAT'
            }.get(raw_trend, 'FLAT')

            setup_display = getattr(sig, 'setup_type', None)
            if setup_display is None:
                setup_display = probs.get('dominant', 'NEU')

            setup_display = {
                'MR': 'MR',
                'CONT': 'CONT',
                'NEU': 'NEUTRAL',
                'NEUTRAL': 'NEUTRAL'
            }.get(setup_display, 'NEUTRAL')

            signal_display = getattr(sig, 'signal_display', None)
            if signal_display is None:
                signal_display = sig.signal_type

            if signal_display == 'NO_SIGNAL':
                signal_display = 'WAIT'

            live_state_dict = {
                'datetime':      str(state.datetime),
                'symbol':        symbol,
                'close':         round(state.close, 5),
                'reference':     round(state.reference, 5),
                'reference_shift_5': round(reference_shift_5, 5),
                'sigma':         round(state.sigma, 5),
                'z_score':       round(state.z_score, 4),
                'z_velocity':    round(state.z_velocity, 4),
                'zone':          state.zone,
                'trend_bin':     state.context.get('trend_bin', ''),
                'trend_display': trend_display,
                'setup_type': setup_display,
                'signal_display': signal_display,
                'volume_bin':    state.context.get('volume_bin', ''),
                'time_bin':      state.context.get('time_bin', ''),
                'p_mr':          round(probs.get('MR', {}).get('prob', 0), 4) if isinstance(probs.get('MR'), dict) else 0,
                'p_cont':        round(probs.get('CONT', {}).get('prob', 0), 4) if isinstance(probs.get('CONT'), dict) else 0,
                'edge_gap':      round(probs.get('edge_gap', 0), 4),
                'signal_type':   sig.signal_type,
                'signal_state':  signal_state,
                'session_bar':   state.session_bar_count,
                'band_1p':       round(state.bands.get('1+', 0), 5),
                'band_1n':       round(state.bands.get('1-', 0), 5),
                'band_2p':       round(state.bands.get('2+', 0), 5),
                'band_2n':       round(state.bands.get('2-', 0), 5),
                'band_3p':       round(state.bands.get('3+', 0), 5),
                'band_3n':       round(state.bands.get('3-', 0), 5),
            }

            tmp_state_path = output_path.with_suffix('.tmp')

            for attempt in range(5):
                try:
                    with open(tmp_state_path, 'w') as f:
                        json.dump(live_state_dict, f, indent=2)

                    os.replace(tmp_state_path, output_path)
                    break
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.2)

            # ── Context VWAP trail output (bendy overlay) ──
            write_live_context(
                symbol,
                warmup_df,
                config,
                output_dir=output_path.parent,
                n_points=context_export_points
            )

            if alert:
                print(alert)

            if on_state_update:
                on_state_update(copy.copy(state), sig)

    except KeyboardInterrupt:
        print("\n🔴 Live mode stopped")