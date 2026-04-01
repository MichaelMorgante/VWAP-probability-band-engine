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


# Section 16

import json
import os
from pathlib import Path


def save_artefacts(prob_table,
                   prob_table_trend,
                   results,
                   CONFIG,
                   df_cal=None,
                   df_val=None,
                   df_tst=None,
                   wf_log=None,
                   artefacts_dir: str = 'artifacts') -> None:
    artefacts_path = Path(artefacts_dir)
    artefacts_path.mkdir(exist_ok=True)

    tables_path = artefacts_path / 'tables'
    logs_path = artefacts_path / 'logs'
    metadata_path = artefacts_path / 'metadata'

    tables_path.mkdir(parents=True, exist_ok=True)
    logs_path.mkdir(parents=True, exist_ok=True)
    metadata_path.mkdir(parents=True, exist_ok=True)

    # Probability tables
    prob_table.to_parquet(tables_path / 'prob_table_marginal.parquet', index=False)
    prob_table_trend.to_parquet(tables_path / 'prob_table_trend.parquet', index=False)

    # Backtest results
    results.to_parquet(tables_path / 'backtest_results.parquet', index=False)

    # Walk-forward log
    if wf_log is not None and len(wf_log) > 0:
        wf_log.to_parquet(logs_path / 'wf_signal_log.parquet', index=False)
        print("✅ Walk-forward log saved")

    # Split metadata
    if df_cal is not None and df_val is not None and df_tst is not None:
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
        with open(metadata_path / 'split_meta.json', 'w') as f:
            json.dump(split_meta, f, indent=2)

    # Config
    with open(metadata_path / 'config.json', 'w') as f:
        json.dump({k: str(v) if not isinstance(v, (int, float, str, list, bool)) else v
                   for k, v in CONFIG.items()}, f, indent=2)

    print("✅ Artefacts saved to /artifacts/:")
    for root, _, files in os.walk(artefacts_path):
        for fname in sorted(files):
            full_path = Path(root) / fname
            size = full_path.stat().st_size / 1024
            print(f"   {full_path.as_posix():<65} {size:.1f} KB")


def export_live_artefacts(prob_table,
                          CONFIG,
                          export_dir: str = "live_artifacts") -> None:
    """
    Export minimal live artefacts for MT5 / live notebook use.
    """
    export_path = Path(export_dir)
    export_path.mkdir(parents=True, exist_ok=True)

    exports_path = export_path / "exports"
    exports_path.mkdir(parents=True, exist_ok=True)

    # zone-only probability table
    zone_only = prob_table.reset_index().copy()
    zone_only.to_csv(exports_path / "zone_probabilities.csv", index=False)

    # save config
    with open(exports_path / "config.json", "w") as f:
        json.dump(CONFIG, f, indent=2, default=str)

    print("✅ Exported live artifacts:")
    print(" -", exports_path / "zone_probabilities.csv")
    print(" -", exports_path / "config.json")