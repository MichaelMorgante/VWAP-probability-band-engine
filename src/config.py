from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG = {
    # Data source
    'data_dir': PROJECT_ROOT / 'data' / 'historical',
    'csv_filename': 'US100_cash_M1_NY_session_30d.csv',
    'instrument': 'US100.cash',
    'timeframe': 'M1',

    # Trading sessions (UTC hours) - all 4 major sessions
    'sessions': {
        'Sydney':  {'open_utc': 21, 'close_utc': 24},
        'Asian':   {'open_utc':  0, 'close_utc':  8},
        'London':  {'open_utc':  8, 'close_utc': 13},
        'NewYork': {'open_utc': 13, 'close_utc': 21},
    },
    'session_open_hour': 0,
    'session_close_hour': 24,

    # VWAP / mean reference
    'reference_type': 'VWAP',
    'ema_span': 60,

    # Volatility
    'ewma_halflife': 15,
    'rolling_window': 30,
    'vol_method': 'ewma',

    # Zone thresholds
    'zone_thresholds': [0.5, 1.0, 2.0],

    # Outcome labelling
    'outcome_horizon_bars': 12,
    'mr_threshold': 0.3,
    'cont_threshold': 0.5,

    # Context
    'slope_lookback': 20,
    'volume_ema_span': 20,

    # Minimum observations to trust a probability estimate
    'min_sample_count': 100,

    # Replay speed
    'replay_speed': 50.0,

    # Plot
    'plot_last_n_bars': 180,

    # ── PHASE 1: Execution cost parameters ──────────────────────────
    # Spread in price units (e.g. 0.5 index points for US100 on M1)
    # Used to adjust outcome labels so MR only fires if edge survives cost
    'spread_cost': 0.8,
    # Max adverse excursion allowed before a trade would have been stopped
    # Expressed as a z-score distance (e.g. 1.5 sigma stop)
    'mae_stop_zscore': 1.5,
    # Minimum net profit in z-score units for a label to count as MR
    'min_profit_zscore': 0.2,

    # ── PHASE 2: Probability table upgrade ──────────────────────────
    # Shrinkage constant k: lower = more shrinkage toward marginal prior
    # A cell with N observations gets weight N/(N+k) on its own estimate
    'shrinkage_k': 30,
    # Minimum observations before a conditioned cell is trusted at all
    'min_conditioned_n': 10,
    # Edge gap threshold: best outcome must beat second-best by this much
    # to produce an actionable signal
    'edge_gap_threshold': 0.10,

    # ── PHASE 3: Train/test split ───────────────────────────────────
    # Fraction of data used for calibration (must be by date, not random)
    'calibration_frac': 0.60,
    'validation_frac': 0.20,
    # test_frac is implicitly 1 - calibration_frac - validation_frac = 0.20

    # Walk-forward settings
    'wf_calibration_days': 60,   # rolling calibration window in days
    'wf_oos_days': 10,           # out-of-sample window per fold

    # Session warmup: suppress signals for this many bars after VWAP reset
    'session_warmup_bars': 20,
    # Minimum z-score absolute value to consider a signal (ignore Z0 entries)
    'min_signal_zscore': 0.8,
}