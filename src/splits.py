import pandas as pd

# ── Phase 2 + Phase 3: Date-based train/test split ──────────────────────────

def split_by_date(df: pd.DataFrame, config: dict):
    """
    Split df into calibration, validation, and test sets by session date.
    Returns three DataFrames. Never shuffles rows.
    """
    dates = sorted(df['session_date'].unique())
    n     = len(dates)

    cal_end  = int(n * config['calibration_frac'])
    val_end  = int(n * (config['calibration_frac'] + config['validation_frac']))

    cal_dates = dates[:cal_end]
    val_dates = dates[cal_end:val_end]
    tst_dates = dates[val_end:]

    df_cal = df[df['session_date'].isin(cal_dates)].copy()
    df_val = df[df['session_date'].isin(val_dates)].copy()
    df_tst = df[df['session_date'].isin(tst_dates)].copy()

    print(f"✅ Date-based split complete")
    print(f"   Calibration : {len(df_cal):,} bars  ({len(cal_dates)} days)")
    print(f"   Validation  : {len(df_val):,} bars  ({len(val_dates)} days)")
    print(f"   Test        : {len(df_tst):,} bars  ({len(tst_dates)} days)")
    return df_cal, df_val, df_tst