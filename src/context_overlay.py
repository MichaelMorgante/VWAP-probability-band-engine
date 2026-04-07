import pandas as pd

# ── Context overlay: rolling / bendy VWAP bands ─────────────────────
def compute_context_vwap(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Compute a rolling ('bendy') VWAP and its rolling sigma bands.

    This does NOT replace the execution VWAP.
    It is a second overlay for visual context.
    """
    out = pd.DataFrame(index=df.index)

    window = int(config.get('context_vwap_window', 60))
    sigma_window = int(config.get('context_sigma_window', 30))

    tp = df['typical_price']
    vol = df['tick_volume'].fillna(1.0)

    pv = tp * vol

    # Rolling VWAP within each session so it stays intraday-aware
    if 'session_id' in df.columns:
        rolling_pv = pv.groupby(df['session_id']).transform(
            lambda x: x.rolling(window=window, min_periods=5).sum()
        )
        rolling_v = vol.groupby(df['session_id']).transform(
            lambda x: x.rolling(window=window, min_periods=5).sum()
        )
    else:
        rolling_pv = pv.rolling(window=window, min_periods=5).sum()
        rolling_v = vol.rolling(window=window, min_periods=5).sum()

    out['context_reference'] = rolling_pv / rolling_v.replace(0, np.nan)

    # Deviation from rolling VWAP
    context_dev = df['close'] - out['context_reference']

    if 'session_id' in df.columns:
        out['context_sigma'] = context_dev.groupby(df['session_id']).transform(
            lambda x: x.rolling(window=sigma_window, min_periods=10).std()
        )
    else:
        out['context_sigma'] = context_dev.rolling(window=sigma_window, min_periods=10).std()

    # Safe floor
    valid_sigma = out['context_sigma'].dropna()
    sigma_floor = max(float(valid_sigma.quantile(0.10)), 1e-6) if len(valid_sigma) else 1e-6
    out['context_sigma'] = out['context_sigma'].fillna(sigma_floor).clip(lower=sigma_floor)

    for k in [1, 2, 3]:
        out[f'context_band_{k}p'] = out['context_reference'] + k * out['context_sigma']
        out[f'context_band_{k}n'] = out['context_reference'] - k * out['context_sigma']

    return out