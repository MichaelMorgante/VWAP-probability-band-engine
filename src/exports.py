import json
import os
from pathlib import Path


def save_artefacts(prob_table,
                   prob_table_trend,
                   results,
                   CONFIG,
                   df_cal,
                   df_val,
                   df_tst,
                   wf_log=None,
                   artefacts_dir: str = 'artefacts') -> None:
    artefacts_path = Path(artefacts_dir)
    artefacts_path.mkdir(exist_ok=True)

    # Probability tables (calibration set only)
    prob_table.to_parquet(artefacts_path / 'prob_table_marginal.parquet', index=False)
    prob_table_trend.to_parquet(artefacts_path / 'prob_table_trend.parquet', index=False)

    # Backtest results
    results.to_parquet(artefacts_path / 'backtest_results.parquet', index=False)

    # Walk-forward log
    if wf_log is not None and len(wf_log) > 0:
        wf_log.to_parquet(artefacts_path / 'wf_signal_log.parquet', index=False)
        print("✅ Walk-forward log saved")

    # Split metadata
    split_meta = {
        'calibration_days': int(df_cal['session_date'].nunique()),
        'validation_days':  int(df_val['session_date'].nunique()),
        'test_days':        int(df_tst['session_date'].nunique()),
        'cal_start':        str(df_cal['session_date'].min()),
        'cal_end':          str(df_cal['session_date'].max()),
        'val_start':        str(df_val['session_date'].min()),
        'val_end':          str(df_val['session_date'].max()),
        'tst_start':        str(df_tst['session_date'].min()),
        'tst_end':          str(df_tst['session_date'].max()),
    }
    with open(artefacts_path / 'split_meta.json', 'w') as f:
        json.dump(split_meta, f, indent=2)

    # Config
    with open(artefacts_path / 'config.json', 'w') as f:
        json.dump({k: str(v) if not isinstance(v, (int, float, str, list, bool)) else v
                   for k, v in CONFIG.items()}, f, indent=2)

    print("✅ Artefacts saved to /artefacts/:")
    for fname in sorted(os.listdir(artefacts_path)):
        size = os.path.getsize(artefacts_path / fname) / 1024
        print(f"   {fname:<50} {size:.1f} KB")