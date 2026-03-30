import numpy as np
import pandas as pd

def walk_forward_eval(df: pd.DataFrame, config: dict,
                      calibrate_probability_table,
                      EngineState,
                      update_engine_state,
                      generate_signal,
                      regime_gate,
                      apply_filters) -> pd.DataFrame:
    """
    Rolling walk-forward evaluation.

    For each fold:
      - Calibrate prob_table on the preceding wf_calibration_days
      - Generate signals on the next wf_oos_days (out-of-sample)
      - Label those signals with the actual N-bar outcome
      - Collect all signal rows into a single log DataFrame

    Returns
    -------
    DataFrame with one row per fired signal, including outcome label.
    """
    cal_days = config['wf_calibration_days']
    oos_days = config['wf_oos_days']
    N        = config['outcome_horizon_bars']

    all_dates    = sorted(df['session_date'].unique())
    signal_rows  = []
    fold_count   = 0

    i = cal_days
    while i + oos_days <= len(all_dates):
        cal_date_window = all_dates[i - cal_days : i]
        oos_date_window = all_dates[i : i + oos_days]

        df_fold_cal = df[df['session_date'].isin(cal_date_window)].copy()
        df_fold_oos = df[df['session_date'].isin(oos_date_window)].copy().reset_index(drop=True)

        if len(df_fold_cal) < 200:
            i += oos_days
            continue

        # Calibrate on this fold's calibration window
        fold_table = calibrate_probability_table(df_fold_cal, config)

        # Run signal generation on OOS window
        state = EngineState()
        for idx, row in df_fold_oos.iterrows():
            state = update_engine_state(state, row.to_dict(), config,
                                        fold_table, fold_table)
            sig = generate_signal(state, config)
            sig = regime_gate(sig, config)
            sig = apply_filters(sig, state, config)

            if sig.signal_type == 'NO_SIGNAL':
                continue

            # Look forward N bars to get the actual outcome
            z_entry    = state.z_score
            future_end = min(idx + N, len(df_fold_oos) - 1)
            z_future   = df_fold_oos['z_score'].iloc[future_end] if 'z_score' in df_fold_oos.columns else np.nan
            actual_outcome = 'NEU'
            if not np.isnan(z_future):
                if (abs(z_future) < config['mr_threshold'] or
                        np.sign(z_future) != np.sign(z_entry)):
                    actual_outcome = 'MR'
                elif abs(z_future) > abs(z_entry) + config['cont_threshold']:
                    actual_outcome = 'CONT'

            signal_rows.append({
                'fold':           fold_count,
                'datetime':       sig.datetime,
                'signal_type':    sig.signal_type,
                'zone':           sig.zone,
                'z_score':        sig.z_score,
                'edge_gap':       sig.edge_gap,
                'p_mr':           sig.p_mr,
                'p_cont':         sig.p_cont,
                'trend_bin':      sig.trend_bin,
                'session_bar':    sig.session_bar,
                'actual_outcome': actual_outcome,
                'signal_correct': (
                    (sig.dominant == 'MR'   and actual_outcome == 'MR') or
                    (sig.dominant == 'CONT' and actual_outcome == 'CONT')
                ),
            })

        fold_count += 1
        i += oos_days

    log = pd.DataFrame(signal_rows)
    print(f"✅ Walk-forward complete: {fold_count} folds, {len(log)} signals fired")
    if len(log) > 0:
        print(f"   Overall hit rate : {log['signal_correct'].mean():.1%}")
        print(f"   Signals per day  : {len(log) / (fold_count * oos_days):.1f}")
        print(f"\n   By signal type:")
        for stype, grp in log.groupby('signal_type'):
            hr = grp['signal_correct'].mean()
            print(f"     {stype:15s}  n={len(grp):4d}  hit_rate={hr:.1%}")
    return log