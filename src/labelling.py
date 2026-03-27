import numpy as np
import pandas as pd

def label_outcomes(df: pd.DataFrame, config: dict, mode: str = 'backtest') -> pd.Series:
    """
    Label each bar with its cost-adjusted outcome N bars forward.
    ONLY call this in backtest mode.

    New vs original:
    - MR label requires the trade to survive its stop (mae_stop_zscore)
    - MR label requires net profit after spread cost (min_profit_zscore)
    - CONT label is unchanged (directional continuation, no cost check)
    - NEU catches everything that doesn't meet either threshold
    """
    if mode != 'backtest':
        raise RuntimeError(
            "label_outcomes() called outside backtest mode. "
            "This function uses future data and must never run in replay or live mode."
        )

    N            = config['outcome_horizon_bars']
    mr_thresh    = config['mr_threshold']
    cont_thresh  = config['cont_threshold']
    spread_z     = config['spread_cost'] / df['sigma'].replace(0, np.nan)
    stop_z       = config['mae_stop_zscore']
    min_profit_z = config['min_profit_zscore']

    z_now     = df['z_score']
    z_forward = df['z_score'].shift(-N)

    # Build a rolling maximum adverse excursion over the N-bar window
    # For a long MR entry (z_now negative), worst case is z going more negative
    # For a short MR entry (z_now positive), worst case is z going more positive
    mae_series = pd.Series(np.nan, index=df.index)
    for i in range(len(df) - N):
        window_z = df['z_score'].iloc[i+1 : i+N+1]
        z_entry  = df['z_score'].iloc[i]
        if z_entry > 0:
            mae_series.iloc[i] = window_z.max()   # worst for short MR
        else:
            mae_series.iloc[i] = window_z.min()   # worst for long MR

    outcomes = pd.Series('NEU', index=df.index, dtype=str)

    # Mean reversion conditions
    z_returned     = (z_forward.abs() < mr_thresh) | (np.sign(z_forward) != np.sign(z_now))
    stop_not_hit   = (
        ((z_now > 0) & (mae_series < z_now + stop_z)) |
        ((z_now < 0) & (mae_series > z_now - stop_z)) |
        (z_now == 0)
    )
    net_profit_ok  = (z_now.abs() - z_forward.abs() - spread_z) > min_profit_z
    mr_mask        = z_returned & stop_not_hit & net_profit_ok

    # Continuation condition (unchanged)
    cont_mask = (z_forward.abs() > z_now.abs() + cont_thresh)

    outcomes[mr_mask]              = 'MR'
    outcomes[cont_mask]            = 'CONT'
    outcomes[mr_mask & cont_mask]  = 'MR'   # MR takes priority
    outcomes.iloc[-N:]             = np.nan  # no valid forward data

    print(f"✅ Cost-adjusted outcomes labelled (N={N} bars forward)")
    vc = outcomes.value_counts()
    for outcome in ['MR', 'CONT', 'NEU']:
        n = vc.get(outcome, 0)
        print(f"   {outcome:4s}: {n:6,} ({n/len(df):.1%})")
    print(f"   NaN : {outcomes.isna().sum():6,} (last {N} bars)")
    return outcomes