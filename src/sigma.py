import pandas as pd

def compute_sigma(df: pd.DataFrame, config: dict) -> pd.Series:
    """
    Compute sigma around the reference line, not close-to-close return volatility.
    This is more appropriate for a VWAP probability band engine.

    Changes:
    - shorter-memory EWMA sigma
    - minimum warmup period
    - adaptive floor to stop tiny early-session sigma exploding z-scores
    """
    method = config['vol_method']

    # Deviation from mean reference
    deviation = df['close'] - df['reference']

    if method == 'ewma':
        sigma = deviation.ewm(
            halflife=config['ewma_halflife'],
            adjust=False,
            min_periods=config.get('sigma_min_periods', 15)
        ).std()

    elif method == 'rolling':
        sigma = deviation.rolling(
            window=config['rolling_window'],
            min_periods=config.get('sigma_min_periods', 15)
        ).std()

    else:
        raise ValueError(f"Unknown vol_method: {method}. Use 'ewma' or 'rolling'")

    # Build an adaptive sigma floor from non-null values
    valid_sigma = sigma.dropna()
    if len(valid_sigma) > 0:
        sigma_floor = valid_sigma.quantile(config.get('sigma_floor_quantile', 0.10))
        sigma_floor = max(float(sigma_floor), 1e-6)
    else:
        sigma_floor = 1e-6

    # Clean up sigma
    sigma = sigma.bfill().clip(lower=sigma_floor)

    print(f"✅ Sigma computed ({method})")
    print(f"   Mean sigma : {sigma.mean():.6f}")
    print(f"   Min sigma  : {sigma.min():.6f}")
    print(f"   Max sigma  : {sigma.max():.6f}")
    print(f"   Floor used : {sigma_floor:.6f}")

    return sigma


def compute_bands(df: pd.DataFrame, sigma: pd.Series) -> pd.DataFrame:
    """
    Compute ±1σ, ±2σ, ±3σ bands around reference.
    """
    bands = pd.DataFrame(index=df.index)
    for k in [1, 2, 3]:
        bands[f'band_{k}p'] = df['reference'] + k * sigma
        bands[f'band_{k}n'] = df['reference'] - k * sigma
    return bands