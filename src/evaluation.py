import numpy as np
import pandas as pd

def evaluate_signals(log: pd.DataFrame, config: dict) -> None:
    """
    Print a full performance report from a walk-forward signal log.
    Covers hit rate, edge gap distribution, fold consistency,
    and signals per session.
    """
    if len(log) == 0:
        print("No signals in log to evaluate.")
        return

    print("=" * 60)
    print("SIGNAL PERFORMANCE REPORT")
    print("=" * 60)

    # ── Overall summary ──
    print(f"\nTotal signals  : {len(log)}")
    print(f"Folds          : {log['fold'].nunique()}")
    n_days = log['fold'].nunique() * config['wf_oos_days']
    print(f"Signals/day    : {len(log)/n_days:.2f}")
    print(f"Overall hit rate : {log['signal_correct'].mean():.1%}")

    # ── By signal type ──
    print(f"\n{'Type':<15} {'n':>5} {'Hit%':>6} {'AvgEdge':>8} {'MedZ':>6}")
    print("-" * 45)
    for stype, grp in log.groupby('signal_type'):
        print(f"{stype:<15} {len(grp):>5} {grp['signal_correct'].mean():>6.1%} "
              f"{grp['edge_gap'].mean():>8.3f} {grp['z_score'].abs().median():>6.2f}")

    # ── By zone ──
    print(f"\n{'Zone':<8} {'n':>5} {'Hit%':>6}")
    print("-" * 22)
    for zone, grp in log.groupby('zone'):
        print(f"{zone:<8} {len(grp):>5} {grp['signal_correct'].mean():>6.1%}")

    # ── Fold consistency — are hit rates stable across folds? ──
    fold_hr = log.groupby('fold')['signal_correct'].mean()
    print(f"\nFold hit rate stability:")
    print(f"  Mean  : {fold_hr.mean():.1%}")
    print(f"  Std   : {fold_hr.std():.1%}")
    print(f"  Min   : {fold_hr.min():.1%}")
    print(f"  Max   : {fold_hr.max():.1%}")

    if fold_hr.std() > 0.15:
        print("  ⚠️  High variance across folds — edge may not be persistent")
    else:
        print("  ✅ Reasonably consistent across folds")

    # ── Edge gap distribution ──
    print(f"\nEdge gap distribution:")
    print(f"  Median : {log['edge_gap'].median():.3f}")
    print(f"  75th % : {log['edge_gap'].quantile(0.75):.3f}")
    print(f"  95th % : {log['edge_gap'].quantile(0.95):.3f}")


def run_backtest(df: pd.DataFrame, config: dict,
                 prob_table: pd.DataFrame,
                 marginal_table: pd.DataFrame = None,
                 EngineState=None,
                 update_engine_state=None,
                 generate_signal=None,
                 regime_gate=None,
                 apply_filters=None) -> pd.DataFrame:
    """
    Run the full historical dataset through the engine bar by bar.
    Now also emits signal output alongside engine state.

    marginal_table: zone-only table for shrinkage. Defaults to prob_table.
    """
    if marginal_table is None:
        marginal_table = prob_table

    state   = EngineState()
    results = []

    for i, row in df.iterrows():
        bar   = row.to_dict()
        state = update_engine_state(state, bar, config, prob_table, marginal_table)

        sig   = generate_signal(state, config)
        sig   = regime_gate(sig, config)
        sig   = apply_filters(sig, state, config)

        probs      = state.probabilities
        mr_prob    = probs.get('MR',   {}).get('prob', np.nan) if isinstance(probs.get('MR'), dict) else np.nan
        cont_prob  = probs.get('CONT', {}).get('prob', np.nan) if isinstance(probs.get('CONT'), dict) else np.nan
        neu_prob   = probs.get('NEU',  {}).get('prob', np.nan) if isinstance(probs.get('NEU'), dict) else np.nan
        confidence = probs.get('MR', {}).get('confidence', 'NONE') if isinstance(probs.get('MR'), dict) else 'NONE'

        results.append({
            'datetime':      state.datetime,
            'close':         state.close,
            'reference':     state.reference,
            'sigma':         state.sigma,
            'band_1p':       state.bands.get('1+', np.nan),
            'band_1n':       state.bands.get('1-', np.nan),
            'band_2p':       state.bands.get('2+', np.nan),
            'band_2n':       state.bands.get('2-', np.nan),
            'band_3p':       state.bands.get('3+', np.nan),
            'band_3n':       state.bands.get('3-', np.nan),
            'z_score':       state.z_score,
            'z_velocity':    state.z_velocity,
            'zone':          state.zone,
            'trend_bin':     state.context.get('trend_bin', ''),
            'volume_bin':    state.context.get('volume_bin', ''),
            'time_bin':      state.context.get('time_bin', ''),
            'p_mr':          mr_prob,
            'p_cont':        cont_prob,
            'p_neu':         neu_prob,
            'edge_gap':      probs.get('edge_gap', 0.0),
            'confidence':    confidence,
            'lookup_tier':   probs.get('lookup_tier', 3),
            'signal_type':   sig.signal_type,
            'suppressed_by': sig.suppressed_by,
            'session_bar':   state.session_bar_count,
        })

    results_df = pd.DataFrame(results)
    print(f"✅ Backtest complete: {len(results_df):,} bars processed")
    live_signals = (results_df['signal_type'] != 'NO_SIGNAL').sum()
    print(f"   Live signals fired : {live_signals:,} ({live_signals/len(results_df):.1%} of bars)")
    return results_df