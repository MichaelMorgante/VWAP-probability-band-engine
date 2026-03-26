import pandas as pd

def compute_reference(df: pd.DataFrame, config: dict) -> pd.Series:
    """
    Compute the intraday mean reference line (VWAP, TWAP, or EMA).
    Resets each session_date for VWAP and TWAP.

    Returns
    -------
    pd.Series of reference values, same index as df
    """
    ref_type = config['reference_type']

    if ref_type == 'VWAP':
        # Cumulative sum within each day
        pv = df['typical_price'] * df['tick_volume']
        cum_pv = pv.groupby(df['session_date']).cumsum()
        cum_v  = df['tick_volume'].groupby(df['session_date']).cumsum()
        ref = cum_pv / cum_v

    elif ref_type == 'TWAP':
        # Simple cumulative mean of typical price within each day
        ref = df.groupby('session_date')['typical_price'].transform(
            lambda x: x.expanding().mean()
        )

    elif ref_type == 'EMA':
        # Exponential moving average — does NOT reset daily
        # Use only if VWAP/TWAP are unavailable
        span = config.get('ema_span', 60)
        ref = df['typical_price'].ewm(span=span, adjust=False).mean()
        print(f"⚠️  EMA reference does not reset daily — use VWAP or TWAP for intraday work")

    else:
        raise ValueError(f"Unknown reference_type: {ref_type}. Use 'VWAP', 'TWAP', or 'EMA'")

    print(f"✅ {ref_type} computed — resets per session: {ref_type in ('VWAP','TWAP')}")
    return ref