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