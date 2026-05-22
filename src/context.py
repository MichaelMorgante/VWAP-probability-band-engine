import numpy as np
import pandas as pd

def compute_context(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    Compute and discretise all context variables.
    Returns a DataFrame with columns:
        trend_bin, volume_bin, time_bin, z_velocity_bin
    """
    ctx = pd.DataFrame(index=df.index)

    # ── 1. VWAP slope (normalised by sigma) ──
    k = config['slope_lookback']
    slope = (df['reference'] - df['reference'].shift(k)) / (k * df['sigma'])
    ctx['trend_raw'] = slope
    
    trend_threshold = config.get('trend_slope_threshold', 0.08)
    ctx['trend_bin'] = pd.cut(
        slope,
        bins=[-np.inf, -trend_threshold, trend_threshold, np.inf],
        labels=['down', 'flat', 'up']
    ).astype(str)

    # ── 1b. Price-location bias relative to VWAP/reference ──
    bias_threshold = config.get('bias_z_threshold', 0.50)

    ctx['bias_display'] = np.select(
        [
            df['z_score'] >= bias_threshold,
            df['z_score'] <= -bias_threshold
        ],
        [
            'BULLISH',
            'BEARISH'
        ],
        default='NEUTRAL'
    )

    # ── 2. Volume regime ──
    vol_ema = df['tick_volume'].ewm(span=config['volume_ema_span'], adjust=False).mean()
    vol_ratio = df['tick_volume'] / vol_ema
    ctx['volume_ratio'] = vol_ratio
    ctx['volume_bin'] = pd.cut(
        vol_ratio,
        bins=[0, 0.6, 1.5, np.inf],
        labels=['low', 'normal', 'high']
    ).astype(str)

    # ── 3. Time of day (UTC hours) ──
    hour = df['datetime'].dt.hour
    def time_bucket(h):
        if 7 <= h < 9:   return 'london_open'
        if 9 <= h < 12:  return 'london_morning'
        if 12 <= h < 16: return 'overlap'
        if 16 <= h < 20: return 'ny_afternoon'
        return 'dead_hours'
    ctx['time_bin'] = hour.apply(time_bucket)

    # ── 4. Z-score velocity (5-bar change in z-score) ──
    z_velocity = df['z_score'] - df['z_score'].shift(5)
    ctx['z_velocity'] = z_velocity
    ctx['z_velocity_bin'] = pd.cut(
        z_velocity,
        bins=[-np.inf, -0.3, 0.3, np.inf],
        labels=['reverting', 'neutral', 'extending']
    ).astype(str)

    print("✅ Context variables computed")
    print(f"   Trend bins   : {ctx['trend_bin'].value_counts().to_dict()}")
    print(f"   Volume bins  : {ctx['volume_bin'].value_counts().to_dict()}")
    print(f"   Time bins    : {ctx['time_bin'].value_counts().to_dict()}")
    return ctx