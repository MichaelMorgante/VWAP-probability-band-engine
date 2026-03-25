import pandas as pd

def _normalise(df: pd.DataFrame) -> pd.DataFrame:
    """
    Shared post-processing applied by every loader.
    Sorts by datetime, resets index, adds derived columns.
    This function is internal — call loaders, not this directly.
    """
    df = df.sort_values('datetime').reset_index(drop=True)
    df['datetime'] = pd.to_datetime(df['datetime'], utc=True)
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
    df['session_date'] = df['datetime'].dt.date
    df['tick_volume'] = df['tick_volume'].fillna(1.0).clip(lower=1.0)  # no zero volumes
    df = df[['datetime', 'open', 'high', 'low', 'close', 'tick_volume',
             'typical_price', 'session_date']]
    return df


# ──────────────────────────────────────────────────────────────
# LOADER 1 — MT5 Export CSV
# Handles both angle-bracket format <DATE>,<TIME>,<OPEN>,...
# and clean format DATE,TIME,OPEN,...
# ──────────────────────────────────────────────────────────────
def load_mt5_csv(path: str) -> pd.DataFrame:
    """
    Load an MT5-exported OHLCV CSV file.
    Handles angle-bracket headers: <DATE>, <TIME>, <OPEN>, etc.
    Also handles flat format without angle brackets.
    Spread column is preserved but not required.
    """
    raw = pd.read_csv(path)

    # Strip angle brackets from column names if present
    raw.columns = [c.strip().strip('<>').upper() for c in raw.columns]

    # Build datetime — support DATE+TIME, DATETIME, or unix TIME
    if 'DATE' in raw.columns and 'TIME' in raw.columns:
        raw['datetime'] = pd.to_datetime(
            raw['DATE'].astype(str) + ' ' + raw['TIME'].astype(str),
            utc=True
        )
    elif 'DATETIME' in raw.columns:
        raw['datetime'] = pd.to_datetime(raw['DATETIME'], utc=True)
    elif 'TIME' in raw.columns:  # unix datetime
        raw['datetime'] = pd.to_datetime(raw['TIME'], unit='s', utc=True)
    else:
        raise ValueError("Cannot find DATE/TIME, DATETIME, or TIME column in MT5 CSV")

    # Map to internal column names
    col_map = {
        'OPEN':        'open',
        'HIGH':        'high',
        'LOW':         'low',
        'CLOSE':       'close',
        'TICKVOL':     'tick_volume',
        'TICK_VOLUME': 'tick_volume',
        'VOL':         'tick_volume',
        'VOLUME':      'tick_volume',
    }

    raw = raw.rename(columns=col_map)

    # Use TICKVOL preferentially; fall back to real VOL; fall back to 1
    if 'tick_volume' not in raw.columns:
        raw['tick_volume'] = 1.0
        print("⚠️  No volume column found — using constant 1.0 (TWAP mode recommended)")

    print(f"✅ MT5 CSV loaded: {len(raw):,} bars from {path}")
    return _normalise(raw)


# ──────────────────────────────────────────────────────────────
# LOADER 2 — MT5 Live API
# Called from run_live.py — returns the same schema as load_mt5_csv
# ──────────────────────────────────────────────────────────────
def load_mt5_live(symbol: str, timeframe_mt5, n_bars: int = 500) -> pd.DataFrame:
    """
    Pull recent bars from MT5 via the MetaTrader5 Python package.
    Returns the same normalised DataFrame as all other loaders.

    Parameters
    ----------
    symbol       : MT5 symbol string e.g. 'EURUSD'
    timeframe_mt5: MT5 timeframe constant e.g. mt5.TIMEFRAME_M1
    n_bars       : how many historical bars to pull for context

    Note: MT5 must be initialised before calling this function.
          Call mt5.initialize() in run_live.py before using this loader.
    """
    try:
        import MetaTrader5 as mt5
    except ImportError:
        raise ImportError("MetaTrader5 package not installed. Run: pip install MetaTrader5")

    rates = mt5.copy_rates_from_pos(symbol, timeframe_mt5, 0, n_bars)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"MT5 returned no data for {symbol}. Is terminal connected?")

    df = pd.DataFrame(rates)
    df = df.rename(columns={
        'time':         'datetime',
        'open':         'open',
        'high':         'high',
        'low':          'low',
        'close':        'close',
        'tick_volume':  'tick_volume',
        'real_volume':  'real_volume',
    })
    df['datetime'] = pd.to_datetime(df['datetime'], unit='s', utc=True)
    print(f"✅ MT5 Live loaded: {len(df):,} bars for {symbol}")
    return _normalise(df)


# ──────────────────────────────────────────────────────────────
# LOADER 3 — TradingView CSV Export
# File → Export chart data in TradingView
# ──────────────────────────────────────────────────────────────
def load_tradingview_csv(path: str) -> pd.DataFrame:
    """
    Load a TradingView exported CSV.
    TradingView uses: time, open, high, low, close, Volume
    'time' is a Unix datetime (seconds).
    Volume is often 0 for forex pairs on TradingView — flagged automatically.
    """
    raw = pd.read_csv(path)
    raw.columns = [c.strip().lower() for c in raw.columns]

    raw = raw.rename(columns={
        'time':   'datetime',
        'volume': 'tick_volume',
    })
    raw['datetime'] = pd.to_datetime(raw['datetime'], unit='s', utc=True)

    if 'tick_volume' not in raw.columns or raw['tick_volume'].sum() == 0:
        raw['tick_volume'] = 1.0
        print("⚠️  TradingView volume is zero (common for forex) — using TWAP reference")
        print("   Set CONFIG['reference_type'] = 'TWAP' for accurate results")

    print(f"✅ TradingView CSV loaded: {len(raw):,} bars from {path}")
    return _normalise(raw)


# ──────────────────────────────────────────────────────────────
# LOADER 4 — Generic OHLCV CSV (any broker / custom format)
# You specify the column mapping explicitly
# ──────────────────────────────────────────────────────────────
def load_generic_csv(path: str, column_map: dict,
                     datetime_format: str = None,
                     date_col: str = None, time_col: str = None) -> pd.DataFrame:
    """
    Load any OHLCV CSV by providing an explicit column mapping.

    Parameters
    ----------
    path         : path to CSV file
    column_map   : dict mapping your column names to internal names
                   e.g. {'Date': 'datetime', 'Open': 'open', ...}
    datetime_format : optional strptime format string for datetime parsing
    date_col     : if datetime is split across two columns, name of date col
    time_col     : if datetime is split across two columns, name of time col

    Example
    -------
    load_generic_csv('my_data.csv', {
        'Datetime': 'datetime',
        'Open':     'open',
        'High':     'high',
        'Low':      'low',
        'Close':    'close',
        'Vol':      'tick_volume'
    })
    """
    raw = pd.read_csv(path)

    # Combine date + time columns if needed
    if date_col and time_col:
        raw['datetime'] = raw[date_col].astype(str) + ' ' + raw[time_col].astype(str)
        column_map = {k: v for k, v in column_map.items()
                      if k not in (date_col, time_col)}

    raw = raw.rename(columns=column_map)

    if datetime_format:
        raw['datetime'] = pd.to_datetime(raw['datetime'], format=datetime_format, utc=True)
    else:
        raw['datetime'] = pd.to_datetime(raw['datetime'], utc=True, infer_datetime_format=True)

    if 'tick_volume' not in raw.columns:
        raw['tick_volume'] = 1.0

    print(f"✅ Generic CSV loaded: {len(raw):,} bars from {path}")
    return _normalise(raw)


# ──────────────────────────────────────────────────────────────
# SESSION HELPERS — for all-session mode
# Adds named session blocks like Sydney / Asian / London / NewYork
# ──────────────────────────────────────────────────────────────
def assign_session_id(ts: pd.Timestamp, sessions: dict) -> str:
    """
    Assign a unique session id of the form:
    YYYY-MM-DD_SessionName
    """
    ts = pd.Timestamp(ts)
    hour = ts.hour + ts.minute / 60.0

    for session_name, spec in sessions.items():
        open_utc = spec['open_utc']
        close_utc = spec['close_utc']

        # Standard same-day session
        if open_utc < close_utc:
            if open_utc <= hour < close_utc:
                return f"{ts.date()}_{session_name}"

        # Cross-midnight session
        else:
            if hour >= open_utc:
                return f"{ts.date()}_{session_name}"
            elif hour < close_utc:
                prev_date = (ts - pd.Timedelta(days=1)).date()
                return f"{prev_date}_{session_name}"

    # Fallback if no session matched
    return f"{ts.date()}_Unassigned"


def assign_sessions(df: pd.DataFrame, sessions: dict) -> pd.DataFrame:
    """
    Add session_id, session_name, and session_date columns
    for use in all-session mode.
    """
    df = df.copy()
    df['session_id'] = df['datetime'].apply(lambda x: assign_session_id(x, sessions))
    df['session_name'] = df['session_id'].str.split('_', n=1).str[1]
    df['session_date'] = pd.to_datetime(
        df['session_id'].str.split('_', n=1).str[0],
        errors='coerce'
    ).dt.date
    return df