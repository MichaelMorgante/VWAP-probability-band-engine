"""
VWAP Sigma Live Execution Engine

Configurable live/demo execution engine for VWAP sigma-based trading logic.

This script is designed to:
- load live market context
- evaluate VWAP sigma setup logic
- apply configurable strategy and risk controls
- support signal-only or automated execution modes
- log signals, blocks, order attempts, fills, and position-management events
"""

from __future__ import annotations

import csv
import time as time_module
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


# ============================================================
# LIVE / DEMO EXECUTION CONFIG
# ============================================================

SYMBOL = "US100.cash"
TIMEFRAME = "M1"

EXECUTION_MODE = "signal_only"
# options:
# "signal_only"  = compute and log signals only
# "place_orders" = full auto execution once MT5 execution is added

LOT_SIZE = 60.0

MAGIC_NUMBER = 260710
# MT5 identifier for this bot's trades.
# Set once and do not change while trades are open.

ORDER_COMMENT = "VWAP_SIGMA_CONT"

POLL_SECONDS = 1
CANDLE_CONFIRMATION_DELAY_SECONDS = 2

RUN_LIVE_LOOP_ON_STARTUP = False
# False = connect, fetch candles, process one latest closed candle, then exit.
# True  = continuously poll MT5 and process each new closed candle once.

ALLOW_LIVE_TRADING = False
# False should prevent accidental live-account trading if account type can be detected.
# Demo trading will be allowed once MT5 account checks are added.

# ============================================================
# MT5 CONNECTION CONFIG
# ============================================================

CONNECT_MT5_ON_STARTUP = False
# False = do not connect when the script starts.
# True  = test MT5 terminal connection and candle loading at startup.

MT5_TERMINAL_PATH = None
# Optional path to terminal64.exe.
# Leave as None to use the default installed/logged-in terminal.

MT5_LOGIN = None
MT5_PASSWORD = None
MT5_SERVER = None
# Optional login details.
# Prefer leaving these as None and logging in through the MT5 terminal.

MT5_TIMEOUT_MS = 60_000
MT5_PORTABLE_MODE = False


# ============================================================
# SESSION / TIME CONFIG
# ============================================================

TRADING_TIMEZONE = "Europe/London"

NO_NEW_TRADES_AFTER = "19:00"

USE_SESSION_FILTER = False
SESSION_START = "14:30"
SESSION_END = "21:00"

# ============================================================
# STARTUP / HISTORY CONFIG
# ============================================================

HISTORY_LOOKBACK_MINUTES = 200
MIN_WARMUP_CANDLES = 120
REQUIRE_FULL_LOOKBACK_BEFORE_TRADING = False


# ============================================================
# MARKET OPEN BLACKOUT CONFIG
# ============================================================

BLOCK_MARKET_OPEN_WINDOW = False
MARKET_OPEN_TIME = "14:30"
MARKET_OPEN_TIMEZONE = "Europe/London"
MARKET_OPEN_BLOCK_MINUTES = 15

# ============================================================
# TIMEFRAME HELPERS
# ============================================================

TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 5 * 60,
    "M15": 15 * 60,
    "M30": 30 * 60,
    "H1": 60 * 60,
    "H4": 4 * 60 * 60,
    "D1": 24 * 60 * 60,
}

# ============================================================
# CORE STRATEGY CONFIG
# ============================================================

ENGINE_MODE = "intelligent"
# options:
# "manual"
# "intelligent"

ENABLE_CONTINUATION = True
ENABLE_MEAN_REVERSION = False

USE_STRATEGY_FILTER = True
STRATEGY_FILTER_MODE = "v4_dynamic_regime_selector"

ENABLE_REGIME_ROUTER = True

ENABLE_S_TIER = True
ENABLE_DYNAMIC_S_TIER = True
ENABLE_A_TIER = True
ENABLE_DELAYED_PULLBACK = True


# ============================================================
# SETUP-SPECIFIC QUALITY FILTER CONFIG
# ============================================================

USE_S_TIER_CLEAN_STATE_FILTER = True

USE_RED_SHIFT_FLOOR = False
USE_TREND_HEALTH_FILTER = True
USE_CANDLE_QUALITY_FILTER = True
USE_GREEN_EXTENSION_FILTER = True

DEFAULT_MAX_GREEN_EXTENSION_POINTS = 20.0

DEFAULT_S_TIER_RED_SHIFT_POINTS = 2.0
DEFAULT_DYNAMIC_S_TIER_RED_SHIFT_POINTS = 2.0
DEFAULT_A_TIER_RED_SHIFT_POINTS = 3.0
DEFAULT_DELAYED_PULLBACK_RED_SHIFT_POINTS = 3.0
DEFAULT_MEAN_REVERSION_RED_SHIFT_POINTS = 0.0


# ============================================================
# RISK / EXIT CONFIG
# ============================================================

SL_POINTS = 36.0
TP_POINTS = 72.0
BE_TRIGGER_POINTS = 36.0

RUNNER_MODE = "always"
# options should match notebook logic as it is ported

RUNNER_TARGET_R = 7.0
# Global fallback only.
# Setup-specific targets in SETUP_PROFILES override this.

ENABLE_LEGACY_EARLY_RUNNER_LOCK = False

RUNNER_TRAIL_RULES_R = [
    {"trigger_r": 1.0, "lock_r": 0.0, "label": "BE"},
    {"trigger_r": 2.7, "lock_r": 2.0, "label": "TRAIL_LOCK_2R"},
    {"trigger_r": 3.7, "lock_r": 3.0, "label": "TRAIL_LOCK_3R"},
    {"trigger_r": 4.7, "lock_r": 4.0, "label": "TRAIL_LOCK_4R"},
    {"trigger_r": 5.7, "lock_r": 5.0, "label": "TRAIL_LOCK_5R"},
    {"trigger_r": 6.7, "lock_r": 6.0, "label": "TRAIL_LOCK_6R"},
    {"trigger_r": 7.7, "lock_r": 7.0, "label": "TRAIL_LOCK_7R"},
    {"trigger_r": 8.7, "lock_r": 8.0, "label": "TRAIL_LOCK_8R"},
    {"trigger_r": 9.7, "lock_r": 9.0, "label": "TRAIL_LOCK_9R"},
]

MAX_DAILY_LOSS_R = -2.0
MAX_CONSECUTIVE_SL = 2


# ============================================================
# PROTECTED ADD-ON CONFIG
# ============================================================

ENABLE_PROTECTED_ADDONS = False
MAX_OPEN_CONTINUATION_TRADES = 2
REQUIRE_PRIMARY_PROTECTED_BEFORE_ADDON = True


# ============================================================
# A-TIER BYPASS CONFIG
# ============================================================

ROUTER_BYPASS_RULES = {
    "S_TIER": {
        "enabled": False,
        "requires_trend_health": False,
        "requires_red_shift_floor": False,
        "min_directional_red_shift_points": DEFAULT_MEAN_REVERSION_RED_SHIFT_POINTS,
        "max_extension_from_green": None,
    },

    "DYNAMIC_S_TIER": {
        "enabled": False,
        "requires_trend_health": False,
        "requires_red_shift_floor": False,
        "min_directional_red_shift_points": 0.0,
        "max_extension_from_green": None,
    },

    "A_TIER": {
        "enabled": True,

        "trend_health_mode": "after_time",
        # options:
        # "off"                  = bypass ignores trend health
        # "always"               = bypass always requires trend health
        # "after_time"            = bypass requires trend health after configured time
        # "follow_v2_activation"  = use existing global V2 trend-health activation logic

        "trend_health_after_time": "17:00",
        "trend_health_after_timezone": "Europe/London",

        "requires_red_shift_floor": True,
        "min_directional_red_shift_points": 2.20,

        "max_extension_from_green": 20.0,
    },

    "DELAYED_PULLBACK": {
        "enabled": False,
        "requires_trend_health": True,
        "requires_red_shift_floor": True,
        "min_directional_red_shift_points": DEFAULT_DELAYED_PULLBACK_RED_SHIFT_POINTS,
        "max_extension_from_green": None,
    },
}


# ============================================================
# SETUP PROFILES
# ============================================================

SETUP_PROFILES = {
    "S_TIER": {
        "enabled": True,
        "use_trend_health": False,
        "use_red_shift_floor": False,
        "min_directional_red_shift_points": DEFAULT_S_TIER_RED_SHIFT_POINTS,

        "allow_in_volatile_trend": False,
        "volatile_require_red_shift_floor": True,
        "volatile_min_directional_red_shift_points": 3.75,

        "use_candle_quality_filter": True,
        "use_extension_filter": True,
        # "max_entry_extension_from_green_points": DEFAULT_MAX_GREEN_EXTENSION_POINTS,
        "max_entry_extension_from_green_points": 8.0,
        "use_clean_state_filter": True,

        "runner_target_r": 10.0,
        "trail_profile": "standard_27",
    },

    "DYNAMIC_S_TIER": {
        "enabled": True,
        "use_trend_health": False,
        "use_red_shift_floor": False,
        "min_directional_red_shift_points": DEFAULT_DYNAMIC_S_TIER_RED_SHIFT_POINTS,

        "use_candle_quality_filter": True,
        "use_extension_filter": True,
        # "max_entry_extension_from_green_points": DEFAULT_MAX_GREEN_EXTENSION_POINTS,
        "max_entry_extension_from_green_points": 8.0,
        "use_clean_state_filter": True,

        "runner_target_r": 10.0,
        "trail_profile": "standard_27",
    },

    "A_TIER": {
        "enabled": True,
        "use_trend_health": True,
        "use_red_shift_floor": False,
        "min_directional_red_shift_points": DEFAULT_A_TIER_RED_SHIFT_POINTS,

        "allow_in_calm_trend": False,
        "calm_require_red_shift_floor": True,
        "calm_min_directional_red_shift_points": 4.00,

        "use_candle_quality_filter": True,
        "use_extension_filter": True,
        "max_entry_extension_from_green_points": DEFAULT_MAX_GREEN_EXTENSION_POINTS,
        # "max_entry_extension_from_green_points": 30.0,
        "use_clean_state_filter": False,

        "runner_target_r": 10.0,
        "trail_profile": "standard_27",
    },

    "DELAYED_PULLBACK": {
        "enabled": True,
        "use_trend_health": True,
        "use_red_shift_floor": False,
        "min_directional_red_shift_points": DEFAULT_DELAYED_PULLBACK_RED_SHIFT_POINTS,

        "use_candle_quality_filter": True,
        "use_extension_filter": True,
        "max_entry_extension_from_green_points": DEFAULT_MAX_GREEN_EXTENSION_POINTS,
        # "max_entry_extension_from_green_points": 30.0,
        "use_clean_state_filter": False,

        "runner_target_r": 10.0,
        "trail_profile": "standard_27",
    },

    "MEAN_REVERSION": {
        "enabled": False,
        "use_trend_health": False,
        "use_red_shift_floor": False,
        "min_directional_red_shift_points": DEFAULT_MEAN_REVERSION_RED_SHIFT_POINTS,
        "runner_target_r": None,
        "trail_profile": None,
    },
}


# ============================================================
# LOGGING CONFIG
# ============================================================

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

EVENT_LOG_PATH = LOG_DIR / "live_vwap_sigma_events.csv"

LOG_FIELDS = [
    "timestamp",
    "event_type",
    "symbol",
    "execution_mode",
    "signal_time",
    "direction",
    "setup_family",
    "entry_price",
    "sl_price",
    "tp_price",
    "runner_target_r",
    "runner_target_points",
    "decision",
    "block_reason",
    "order_ticket",
    "position_ticket",
    "retcode",
    "bot_start_time",
    "candles_loaded",
    "min_warmup_candles",
    "history_lookback_minutes",
    "require_full_lookback_before_trading",
    "market_open_blackout_enabled",
    "market_open_time",
    "market_open_timezone",
    "market_open_block_minutes",
    "timeframe",
    "bars_requested",
    "mt5_error_code",
    "mt5_error_message",
    "account_login",
    "account_server",
    "account_trade_mode",
    "account_company",
    "latest_closed_time",
    "last_processed_signal_time",
    "last_ordered_signal_time",
    "loop_iteration",
    "session_filter_enabled",
    "session_start",
    "session_end",
    "no_new_trades_after",
    "daily_realised_r",
    "max_daily_loss_r",
    "consecutive_sl_count",
    "max_consecutive_sl",
    "open_positions_count",
    "protected_addons_enabled",
    "max_open_continuation_trades",
    "position_type",
    "position_entry_price",
    "position_sl",
    "position_tp",
    "position_profit",
    "position_magic",
    "positions_source",
    "message",
]


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class TradeSignal:
    signal_time: Any
    direction: str
    setup_family: str
    entry_price: float
    sl_price: float
    tp_price: float
    runner_target_r: float
    runner_target_points: float
    reason: str
    block_reason: str | None = None


@dataclass
class LiveTradeState:
    ticket: int
    setup_family: str
    direction: str
    entry_price: float
    sl_price: float
    tp_price: float
    runner_target_r: float
    runner_target_points: float
    signal_time: Any
    trail_state: str = "OPEN"

# ============================================================
# RUNTIME STATE
# ============================================================

last_processed_signal_time: str | None = None
last_ordered_signal_time: str | None = None
loop_iteration = 0

daily_realised_r = 0.0
consecutive_sl_count = 0
daily_lockout_active = False
max_consecutive_sl_lockout_active = False


# ============================================================
# LOGGING HELPERS
# ============================================================

def log_event(event_type: str, **kwargs: Any) -> None:
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "symbol": SYMBOL,
        "execution_mode": EXECUTION_MODE,
    }

    for field in LOG_FIELDS:
        row.setdefault(field, "")

    for key, value in kwargs.items():
        if key in row:
            row[key] = value

    file_exists = EVENT_LOG_PATH.exists()

    with EVENT_LOG_PATH.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    print(f"[{row['timestamp']}] {event_type}: {kwargs.get('message', '')}")

# ============================================================
# MT5 HELPERS
# ============================================================

def mt5_available() -> bool:
    return mt5 is not None


def require_mt5() -> None:
    if mt5 is None:
        raise RuntimeError(
            "MetaTrader5 package is not installed. "
            "Install it with: pip install MetaTrader5"
        )


def get_mt5_last_error() -> tuple[Any, Any]:
    if mt5 is None:
        return "", ""

    error = mt5.last_error()

    if isinstance(error, tuple) and len(error) >= 2:
        return error[0], error[1]

    return "", str(error)


def get_mt5_timeframe(timeframe: str) -> Any:
    require_mt5()

    timeframe_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }

    if timeframe not in timeframe_map:
        raise ValueError(f"Unsupported TIMEFRAME for MT5: {timeframe}")

    return timeframe_map[timeframe]


def account_trade_mode_label(trade_mode: Any) -> str:
    require_mt5()

    labels = {
        mt5.ACCOUNT_TRADE_MODE_DEMO: "DEMO",
        mt5.ACCOUNT_TRADE_MODE_CONTEST: "CONTEST",
        mt5.ACCOUNT_TRADE_MODE_REAL: "REAL",
    }

    return labels.get(trade_mode, f"UNKNOWN_{trade_mode}")


def initialize_mt5() -> bool:
    require_mt5()

    initialize_kwargs = {
        "timeout": MT5_TIMEOUT_MS,
        "portable": MT5_PORTABLE_MODE,
    }

    if MT5_TERMINAL_PATH:
        initialize_kwargs["path"] = MT5_TERMINAL_PATH

    if MT5_LOGIN is not None:
        initialize_kwargs["login"] = int(MT5_LOGIN)

    if MT5_PASSWORD is not None:
        initialize_kwargs["password"] = MT5_PASSWORD

    if MT5_SERVER is not None:
        initialize_kwargs["server"] = MT5_SERVER

    initialized = mt5.initialize(**initialize_kwargs)

    if not initialized:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="MT5 initialize failed",
        )

        return False

    log_event(
        "HEARTBEAT",
        message="MT5 initialized successfully",
    )

    return True


def shutdown_mt5() -> None:
    if mt5 is not None:
        mt5.shutdown()

    log_event(
        "HEARTBEAT",
        message="MT5 shutdown completed",
    )


def get_account_info() -> Any:
    require_mt5()

    account_info = mt5.account_info()

    if account_info is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="Could not read MT5 account info",
        )

        return None

    account_data = account_info._asdict()
    trade_mode = account_trade_mode_label(account_data.get("trade_mode"))

    log_event(
        "HEARTBEAT",
        account_login=account_data.get("login"),
        account_server=account_data.get("server"),
        account_trade_mode=trade_mode,
        account_company=account_data.get("company"),
        message=f"Connected MT5 account detected: {trade_mode}",
    )

    return account_info


def validate_account_safety() -> bool:
    require_mt5()

    account_info = get_account_info()

    if account_info is None:
        return False

    account_data = account_info._asdict()
    trade_mode = account_data.get("trade_mode")
    trade_mode_label = account_trade_mode_label(trade_mode)

    if trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL and not ALLOW_LIVE_TRADING:
        log_event(
            "CRITICAL",
            account_login=account_data.get("login"),
            account_server=account_data.get("server"),
            account_trade_mode=trade_mode_label,
            account_company=account_data.get("company"),
            message=(
                "Real/live MT5 account detected and ALLOW_LIVE_TRADING is False. "
                "Automated trading is blocked."
            ),
        )

        return False

    return True


def ensure_symbol_selected() -> bool:
    require_mt5()

    symbol_info = mt5.symbol_info(SYMBOL)

    if symbol_info is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message=f"Symbol not found in MT5: {SYMBOL}",
        )

        return False

    if symbol_info.visible:
        log_event(
            "HEARTBEAT",
            message=f"Symbol already visible: {SYMBOL}",
        )

        return True

    selected = mt5.symbol_select(SYMBOL, True)

    if not selected:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message=f"Could not select symbol: {SYMBOL}",
        )

        return False

    log_event(
        "HEARTBEAT",
        message=f"Symbol selected: {SYMBOL}",
    )

    return True


def calculate_history_bar_count() -> int:
    if TIMEFRAME not in TIMEFRAME_SECONDS:
        raise ValueError(f"Unsupported TIMEFRAME: {TIMEFRAME}")

    timeframe_seconds = TIMEFRAME_SECONDS[TIMEFRAME]
    bars_for_lookback = ceil((HISTORY_LOOKBACK_MINUTES * 60) / timeframe_seconds)

    return max(
        bars_for_lookback + 5,
        MIN_WARMUP_CANDLES + 5,
        10,
    )


def fetch_recent_candles() -> pd.DataFrame:
    require_mt5()

    timeframe = get_mt5_timeframe(TIMEFRAME)
    bars_requested = calculate_history_bar_count()

    rates = mt5.copy_rates_from_pos(
        SYMBOL,
        timeframe,
        0,
        bars_requested,
    )

    if rates is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            timeframe=TIMEFRAME,
            bars_requested=bars_requested,
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="MT5 candle fetch returned None",
        )

        return pd.DataFrame()

    candles = pd.DataFrame(rates)

    if candles.empty:
        log_event(
            "ERROR",
            timeframe=TIMEFRAME,
            bars_requested=bars_requested,
            message="MT5 candle fetch returned an empty DataFrame",
        )

        return candles

    candles["time"] = pd.to_datetime(candles["time"], unit="s", utc=True)
    candles["time"] = candles["time"].dt.tz_convert(TRADING_TIMEZONE)

    candles = candles.set_index("time").sort_index()

    if "tick_volume" in candles.columns and "volume" not in candles.columns:
        candles["volume"] = candles["tick_volume"]

    numeric_columns = [
        "open",
        "high",
        "low",
        "close",
        "tick_volume",
        "spread",
        "real_volume",
        "volume",
    ]

    for column in numeric_columns:
        if column in candles.columns:
            candles[column] = pd.to_numeric(candles[column], errors="coerce")

    log_event(
        "HEARTBEAT",
        timeframe=TIMEFRAME,
        bars_requested=bars_requested,
        candles_loaded=len(candles),
        history_lookback_minutes=HISTORY_LOOKBACK_MINUTES,
        message=f"Fetched {len(candles)} candles from MT5",
    )

    return candles


def get_closed_candles(candles: pd.DataFrame) -> pd.DataFrame:
    if candles is None or candles.empty:
        return pd.DataFrame()

    if len(candles) < 2:
        return candles.iloc[0:0].copy()

    return candles.iloc[:-1].copy()


def get_latest_closed_candle(candles: pd.DataFrame) -> pd.Series | None:
    closed_candles = get_closed_candles(candles)

    if closed_candles.empty:
        return None

    return closed_candles.iloc[-1]

# ============================================================
# SIGNAL PROCESSING SHELL
# ============================================================

def normalise_signal_time(signal_time: Any) -> str:
    return pd.Timestamp(signal_time).isoformat()


def build_signal_from_live_context(candles: pd.DataFrame) -> TradeSignal | None:
    """
    Placeholder for the notebook strategy port.

    Future commits will replace this shell with VWAP/bands/regime/setup logic.
    For now, it intentionally returns None so Commit 4 cannot create signals
    or place orders.
    """
    latest_closed = get_latest_closed_candle(candles)

    if latest_closed is None:
        return None

    return None


def log_signal_only(signal: TradeSignal) -> None:
    event_type = "SIGNAL_BUY" if signal.direction == "BUY" else "SIGNAL_SELL"

    log_event(
        event_type,
        signal_time=signal.signal_time,
        direction=signal.direction,
        setup_family=signal.setup_family,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
        tp_price=signal.tp_price,
        runner_target_r=signal.runner_target_r,
        runner_target_points=signal.runner_target_points,
        decision="signal_only",
        message="Signal only mode: no order sent",
    )


def handle_signal(
    signal: TradeSignal,
    bot_start_time: datetime,
    closed_candles: pd.DataFrame,
    now: datetime | None = None,
) -> None:
    global last_ordered_signal_time

    allow_entry, block_reason = should_allow_new_entry_after_startup_checks(
        signal_time=signal.signal_time,
        bot_start_time=bot_start_time,
        candles=closed_candles,
        now=now,
    )

    if not allow_entry:
        return

    safety_ok, safety_message = should_allow_new_entry_after_safety_gates(
        signal=signal,
        now=now,
    )

    if not safety_ok:
        return

    if EXECUTION_MODE == "signal_only":
        log_signal_only(signal)
        return

    if EXECUTION_MODE == "place_orders":
        signal_time_key = normalise_signal_time(signal.signal_time)

        if signal_time_key == last_ordered_signal_time:
            log_event(
                "SIGNAL_BLOCKED",
                signal_time=signal.signal_time,
                direction=signal.direction,
                setup_family=signal.setup_family,
                block_reason="Duplicate order blocked for same candle",
                last_ordered_signal_time=last_ordered_signal_time,
                message="Duplicate order blocked for same candle",
            )
            return

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            entry_price=signal.entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            runner_target_r=signal.runner_target_r,
            runner_target_points=signal.runner_target_points,
            decision="blocked",
            block_reason="Order placement is not implemented yet",
            message="Signal passed shell checks, but order placement is not implemented yet",
        )

        last_ordered_signal_time = signal_time_key
        return

    raise ValueError(f"Invalid EXECUTION_MODE: {EXECUTION_MODE}")


def process_latest_closed_candle(
    candles: pd.DataFrame,
    bot_start_time: datetime,
    now: datetime | None = None,
) -> None:
    global last_processed_signal_time

    latest_closed = get_latest_closed_candle(candles)

    if latest_closed is None:
        log_event(
            "HEARTBEAT",
            message="No closed candle available yet",
        )
        return

    signal_time = latest_closed.name
    signal_time_key = normalise_signal_time(signal_time)

    if signal_time_key == last_processed_signal_time:
        return

    last_processed_signal_time = signal_time_key

    closed_candles = get_closed_candles(candles)

    warmup_ok, warmup_message = has_enough_warmup(closed_candles)

    log_event(
        "HEARTBEAT" if warmup_ok else "WARMUP_WAIT",
        signal_time=signal_time,
        latest_closed_time=signal_time,
        candles_loaded=len(closed_candles),
        min_warmup_candles=MIN_WARMUP_CANDLES,
        history_lookback_minutes=HISTORY_LOOKBACK_MINUTES,
        require_full_lookback_before_trading=REQUIRE_FULL_LOOKBACK_BEFORE_TRADING,
        last_processed_signal_time=last_processed_signal_time,
        message=warmup_message,
    )

    if not warmup_ok:
        return

    signal = build_signal_from_live_context(candles)

    if signal is None:
        log_event(
            "HEARTBEAT",
            signal_time=signal_time,
            latest_closed_time=signal_time,
            decision="no_signal",
            last_processed_signal_time=last_processed_signal_time,
            message="Closed candle processed; no signal generated by shell",
        )
        return

    handle_signal(
        signal=signal,
        bot_start_time=bot_start_time,
        closed_candles=closed_candles,
        now=now,
    )


# ============================================================
# ENGINE LOOP
# ============================================================

def manage_open_positions_shell() -> None:
    """
    Placeholder for future position management.

    This will later manage breakeven, trailing stops, runner targets,
    protected add-ons, and safety exits.
    """
    return


def run_single_engine_cycle(bot_start_time: datetime) -> None:
    global loop_iteration

    loop_iteration += 1

    candles = fetch_recent_candles()

    if candles.empty:
        log_event(
            "ERROR",
            loop_iteration=loop_iteration,
            message="No candles loaded during engine cycle",
        )
        return

    manage_open_positions_shell()

    process_latest_closed_candle(
        candles=candles,
        bot_start_time=bot_start_time,
    )

    latest_closed = get_latest_closed_candle(candles)

    if latest_closed is not None:
        print(f"Latest closed candle: {latest_closed.name}")
        print(
            "OHLC: "
            f"{latest_closed['open']} / "
            f"{latest_closed['high']} / "
            f"{latest_closed['low']} / "
            f"{latest_closed['close']}"
        )


def run_engine_loop(bot_start_time: datetime) -> None:
    log_event(
        "HEARTBEAT",
        message="Live engine loop started",
    )

    try:
        while True:
            if CANDLE_CONFIRMATION_DELAY_SECONDS > 0:
                time_module.sleep(CANDLE_CONFIRMATION_DELAY_SECONDS)

            run_single_engine_cycle(bot_start_time)

            time_module.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        log_event(
            "HEARTBEAT",
            message="Live engine loop stopped by user",
        )


# ============================================================
# CONFIG HELPERS
# ============================================================

def get_runner_target_for_setup(setup_family: str) -> float:
    profile = SETUP_PROFILES.get(setup_family, {})
    setup_target = profile.get("runner_target_r")

    if setup_target is not None:
        target = float(setup_target)
    else:
        target = float(RUNNER_TARGET_R)

    if target <= 0:
        raise ValueError(f"Invalid runner target for {setup_family}: {target}")

    return target


def get_runner_target_points_for_setup(setup_family: str) -> float:
    return get_runner_target_for_setup(setup_family) * float(SL_POINTS)


def build_sl_tp(direction: str, entry_price: float) -> tuple[float, float]:
    if direction == "BUY":
        sl_price = entry_price - SL_POINTS
        tp_price = entry_price + TP_POINTS

    elif direction == "SELL":
        sl_price = entry_price + SL_POINTS
        tp_price = entry_price - TP_POINTS

    else:
        raise ValueError(f"Invalid direction: {direction}")

    return sl_price, tp_price

def parse_hhmm_time(value: str, field_name: str) -> time:
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be in HH:MM format, got: {value}") from exc


def get_timezone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Invalid timezone: {timezone_name}") from exc


def get_bot_start_time() -> datetime:
    return datetime.now(get_timezone(TRADING_TIMEZONE))


def to_timezone_aware_datetime(value: Any, timezone_name: str = TRADING_TIMEZONE) -> datetime:
    timezone_obj = get_timezone(timezone_name)

    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()

    if isinstance(value, datetime):
        dt_value = value
    else:
        dt_value = datetime.fromisoformat(str(value))

    if dt_value.tzinfo is None:
        return dt_value.replace(tzinfo=timezone_obj)

    return dt_value.astimezone(timezone_obj)


def has_enough_warmup(candles: Any) -> tuple[bool, str]:
    usable_closed_count = len(candles)

    if usable_closed_count < MIN_WARMUP_CANDLES:
        return False, (
            f"Warmup wait: {usable_closed_count} closed candles loaded, "
            f"minimum required is {MIN_WARMUP_CANDLES}"
        )

    if REQUIRE_FULL_LOOKBACK_BEFORE_TRADING:
        if usable_closed_count < HISTORY_LOOKBACK_MINUTES:
            return False, (
                f"Full lookback required: {usable_closed_count} closed candles loaded, "
                f"required is {HISTORY_LOOKBACK_MINUTES}"
            )

    return True, f"Warmup passed: {usable_closed_count} closed candles loaded"


def is_fresh_signal_after_startup(signal_time: Any, bot_start_time: datetime) -> bool:
    signal_dt = to_timezone_aware_datetime(signal_time, TRADING_TIMEZONE)
    start_dt = to_timezone_aware_datetime(bot_start_time, TRADING_TIMEZONE)

    return signal_dt > start_dt


def get_market_open_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    timezone_obj = get_timezone(MARKET_OPEN_TIMEZONE)

    if now is None:
        now_dt = datetime.now(timezone_obj)
    else:
        now_dt = to_timezone_aware_datetime(now, MARKET_OPEN_TIMEZONE)

    open_time = parse_hhmm_time(MARKET_OPEN_TIME, "MARKET_OPEN_TIME")

    open_dt = datetime.combine(
        now_dt.date(),
        open_time,
        tzinfo=timezone_obj,
    )

    close_dt = open_dt + timedelta(minutes=MARKET_OPEN_BLOCK_MINUTES)

    return open_dt, close_dt


def is_in_market_open_blackout(now: datetime | None = None) -> bool:
    if not BLOCK_MARKET_OPEN_WINDOW:
        return False

    if MARKET_OPEN_BLOCK_MINUTES <= 0:
        return False

    timezone_obj = get_timezone(MARKET_OPEN_TIMEZONE)

    if now is None:
        now_dt = datetime.now(timezone_obj)
    else:
        now_dt = to_timezone_aware_datetime(now, MARKET_OPEN_TIMEZONE)

    open_dt, close_dt = get_market_open_window(now_dt)

    return open_dt <= now_dt < close_dt

def get_trading_now(now: datetime | None = None) -> datetime:
    timezone_obj = get_timezone(TRADING_TIMEZONE)

    if now is None:
        return datetime.now(timezone_obj)

    return to_timezone_aware_datetime(now, TRADING_TIMEZONE)


def is_after_no_new_trades_time(now: datetime | None = None) -> bool:
    now_dt = get_trading_now(now)
    cutoff_time = parse_hhmm_time(NO_NEW_TRADES_AFTER, "NO_NEW_TRADES_AFTER")

    cutoff_dt = datetime.combine(
        now_dt.date(),
        cutoff_time,
        tzinfo=get_timezone(TRADING_TIMEZONE),
    )

    return now_dt >= cutoff_dt


def is_inside_session_window(now: datetime | None = None) -> bool:
    if not USE_SESSION_FILTER:
        return True

    now_dt = get_trading_now(now)

    session_start_time = parse_hhmm_time(SESSION_START, "SESSION_START")
    session_end_time = parse_hhmm_time(SESSION_END, "SESSION_END")

    session_start_dt = datetime.combine(
        now_dt.date(),
        session_start_time,
        tzinfo=get_timezone(TRADING_TIMEZONE),
    )

    session_end_dt = datetime.combine(
        now_dt.date(),
        session_end_time,
        tzinfo=get_timezone(TRADING_TIMEZONE),
    )

    return session_start_dt <= now_dt < session_end_dt

def is_mt5_connected() -> bool:
    if mt5 is None:
        return False

    return mt5.terminal_info() is not None


def get_open_bot_positions() -> list[Any]:
    """
    Return open MT5 positions for this engine only.

    Positions are filtered by:
    - SYMBOL
    - MAGIC_NUMBER

    If MT5 is unavailable or not connected, return an empty list so signal-only
    testing can still run without requiring a terminal connection.
    """
    if mt5 is None:
        return []

    if not is_mt5_connected():
        return []

    positions = mt5.positions_get(symbol=SYMBOL)

    if positions is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="Could not read open MT5 positions",
        )

        return []

    bot_positions = [
        position
        for position in positions
        if getattr(position, "magic", None) == MAGIC_NUMBER
    ]

    log_event(
        "HEARTBEAT",
        open_positions_count=len(bot_positions),
        positions_source="mt5",
        message=f"Open bot positions detected: {len(bot_positions)}",
    )

    return bot_positions

def is_position_protected(position: Any) -> bool:
    """
    Protected means the stop loss has been moved to breakeven or better.

    BUY:
    - protected if SL >= entry

    SELL:
    - protected if SL <= entry
    """
    if mt5 is None:
        return False

    position_sl = float(getattr(position, "sl", 0.0) or 0.0)
    position_entry = float(getattr(position, "price_open", 0.0) or 0.0)
    position_type = getattr(position, "type", None)

    if position_sl == 0.0:
        return False

    if position_type == mt5.POSITION_TYPE_BUY:
        return position_sl >= position_entry

    if position_type == mt5.POSITION_TYPE_SELL:
        return position_sl <= position_entry

    return False


def can_open_new_continuation_trade(open_positions: list[Any]) -> tuple[bool, str]:
    open_positions_count = len(open_positions)

    if not ENABLE_PROTECTED_ADDONS:
        if open_positions_count > 0:
            return False, "Open continuation position already exists and add-ons are disabled"

        return True, "No open bot positions"

    if open_positions_count >= MAX_OPEN_CONTINUATION_TRADES:
        return False, "Max open continuation trades reached"

    if REQUIRE_PRIMARY_PROTECTED_BEFORE_ADDON and open_positions_count > 0:
        primary_position = open_positions[0]

        if not is_position_protected(primary_position):
            return False, "Primary trade is not protected at breakeven or better"

    return True, "Open-position rules passed"


def is_daily_loss_lockout_active() -> bool:
    if daily_lockout_active:
        return True

    return daily_realised_r <= MAX_DAILY_LOSS_R


def is_max_consecutive_sl_lockout_active() -> bool:
    if max_consecutive_sl_lockout_active:
        return True

    return consecutive_sl_count >= MAX_CONSECUTIVE_SL


def should_allow_new_entry_after_safety_gates(
    signal: TradeSignal,
    now: datetime | None = None,
) -> tuple[bool, str]:
    open_positions = get_open_bot_positions()
    open_positions_count = len(open_positions)

    if not is_inside_session_window(now):
        block_reason = "Outside configured trading session"

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            decision="blocked",
            block_reason=block_reason,
            session_filter_enabled=USE_SESSION_FILTER,
            session_start=SESSION_START,
            session_end=SESSION_END,
            message=block_reason,
        )

        return False, block_reason

    if is_after_no_new_trades_time(now):
        block_reason = "No-new-trades-after cutoff reached"

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            decision="blocked",
            block_reason=block_reason,
            no_new_trades_after=NO_NEW_TRADES_AFTER,
            message=block_reason,
        )

        return False, block_reason

    if is_daily_loss_lockout_active():
        block_reason = "Daily loss lockout active"

        log_event(
            "DAILY_LOCKOUT",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            decision="blocked",
            block_reason=block_reason,
            daily_realised_r=daily_realised_r,
            max_daily_loss_r=MAX_DAILY_LOSS_R,
            message=block_reason,
        )

        return False, block_reason

    if is_max_consecutive_sl_lockout_active():
        block_reason = "Max consecutive SL lockout active"

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            decision="blocked",
            block_reason=block_reason,
            consecutive_sl_count=consecutive_sl_count,
            max_consecutive_sl=MAX_CONSECUTIVE_SL,
            message=block_reason,
        )

        return False, block_reason

    can_open, open_position_reason = can_open_new_continuation_trade(open_positions)

    if not can_open:
        first_position = open_positions[0] if open_positions else None

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            decision="blocked",
            block_reason=open_position_reason,
            open_positions_count=open_positions_count,
            protected_addons_enabled=ENABLE_PROTECTED_ADDONS,
            max_open_continuation_trades=MAX_OPEN_CONTINUATION_TRADES,
            position_type=getattr(first_position, "type", "") if first_position else "",
            position_entry_price=getattr(first_position, "price_open", "") if first_position else "",
            position_sl=getattr(first_position, "sl", "") if first_position else "",
            position_tp=getattr(first_position, "tp", "") if first_position else "",
            position_profit=getattr(first_position, "profit", "") if first_position else "",
            position_magic=getattr(first_position, "magic", "") if first_position else "",
            positions_source="mt5" if is_mt5_connected() else "none",
            message=open_position_reason,
        )

        return False, open_position_reason

    return True, "New-entry safety gates passed"


def should_allow_new_entry_after_startup_checks(
    signal_time: Any,
    bot_start_time: datetime,
    candles: Any,
    now: datetime | None = None,
) -> tuple[bool, str]:
    candles_loaded = len(candles)

    warmup_ok, warmup_message = has_enough_warmup(candles)

    if not warmup_ok:
        log_event(
            "WARMUP_WAIT",
            signal_time=signal_time,
            bot_start_time=bot_start_time.isoformat(),
            candles_loaded=candles_loaded,
            min_warmup_candles=MIN_WARMUP_CANDLES,
            history_lookback_minutes=HISTORY_LOOKBACK_MINUTES,
            require_full_lookback_before_trading=REQUIRE_FULL_LOOKBACK_BEFORE_TRADING,
            block_reason=warmup_message,
            message=warmup_message,
        )
        return False, warmup_message

    if not is_fresh_signal_after_startup(signal_time, bot_start_time):
        block_reason = "Signal is from before bot startup"

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal_time,
            bot_start_time=bot_start_time.isoformat(),
            candles_loaded=candles_loaded,
            block_reason=block_reason,
            message=block_reason,
        )
        return False, block_reason

    if is_in_market_open_blackout(now):
        block_reason = "Market open blackout window"

        log_event(
            "SIGNAL_BLOCKED",
            signal_time=signal_time,
            bot_start_time=bot_start_time.isoformat(),
            candles_loaded=candles_loaded,
            block_reason=block_reason,
            market_open_blackout_enabled=BLOCK_MARKET_OPEN_WINDOW,
            market_open_time=MARKET_OPEN_TIME,
            market_open_timezone=MARKET_OPEN_TIMEZONE,
            market_open_block_minutes=MARKET_OPEN_BLOCK_MINUTES,
            message=block_reason,
        )
        return False, block_reason

    return True, "Startup/new-entry safety checks passed"


def validate_config() -> None:
    valid_execution_modes = {"signal_only", "place_orders"}
    valid_engine_modes = {"manual", "intelligent"}
    valid_trend_health_modes = {
        "off",
        "always",
        "after_time",
        "follow_v2_activation",
    }

    if EXECUTION_MODE not in valid_execution_modes:
        raise ValueError(f"Invalid EXECUTION_MODE: {EXECUTION_MODE}")

    if ENGINE_MODE not in valid_engine_modes:
        raise ValueError(f"Invalid ENGINE_MODE: {ENGINE_MODE}")

    if SL_POINTS <= 0:
        raise ValueError("SL_POINTS must be > 0")

    if TP_POINTS <= 0:
        raise ValueError("TP_POINTS must be > 0")

    if BE_TRIGGER_POINTS <= 0:
        raise ValueError("BE_TRIGGER_POINTS must be > 0")

    if LOT_SIZE <= 0:
        raise ValueError("LOT_SIZE must be > 0")
    
    if POLL_SECONDS <= 0:
        raise ValueError("POLL_SECONDS must be > 0")

    if CANDLE_CONFIRMATION_DELAY_SECONDS < 0:
        raise ValueError("CANDLE_CONFIRMATION_DELAY_SECONDS must be >= 0")
    
    parse_hhmm_time(NO_NEW_TRADES_AFTER, "NO_NEW_TRADES_AFTER")
    parse_hhmm_time(SESSION_START, "SESSION_START")
    parse_hhmm_time(SESSION_END, "SESSION_END")

    if MAX_CONSECUTIVE_SL <= 0:
        raise ValueError("MAX_CONSECUTIVE_SL must be > 0")

    if RUNNER_TARGET_R <= 0:
        raise ValueError("RUNNER_TARGET_R must be > 0")

    if MAX_OPEN_CONTINUATION_TRADES <= 0:
        raise ValueError("MAX_OPEN_CONTINUATION_TRADES must be > 0")
    
    if HISTORY_LOOKBACK_MINUTES <= 0:
        raise ValueError("HISTORY_LOOKBACK_MINUTES must be > 0")

    if MIN_WARMUP_CANDLES <= 0:
        raise ValueError("MIN_WARMUP_CANDLES must be > 0")

    if MARKET_OPEN_BLOCK_MINUTES < 0:
        raise ValueError("MARKET_OPEN_BLOCK_MINUTES must be >= 0")
    
    if TIMEFRAME not in TIMEFRAME_SECONDS:
        raise ValueError(
            f"Unsupported TIMEFRAME: {TIMEFRAME}. "
            f"Supported values: {sorted(TIMEFRAME_SECONDS)}"
        )

    if MT5_TIMEOUT_MS <= 0:
        raise ValueError("MT5_TIMEOUT_MS must be > 0")

    parse_hhmm_time(MARKET_OPEN_TIME, "MARKET_OPEN_TIME")
    get_timezone(TRADING_TIMEZONE)
    get_timezone(MARKET_OPEN_TIMEZONE)

    if MIN_WARMUP_CANDLES > HISTORY_LOOKBACK_MINUTES:
        print("")
        print("WARNING: MIN_WARMUP_CANDLES is greater than HISTORY_LOOKBACK_MINUTES.")
        print("This may be intended, but it means the bot may wait longer than the requested history lookback.")
        print("")

    for setup_family, profile in SETUP_PROFILES.items():
        runner_target = profile.get("runner_target_r")

        if runner_target is not None and float(runner_target) <= 0:
            raise ValueError(
                f"Invalid runner_target_r for {setup_family}: {runner_target}"
            )

    for setup_family, rule in ROUTER_BYPASS_RULES.items():
        trend_health_mode = rule.get("trend_health_mode")

        if trend_health_mode is not None and trend_health_mode not in valid_trend_health_modes:
            raise ValueError(
                f"Invalid trend_health_mode for {setup_family}: {trend_health_mode}"
            )

    if EXECUTION_MODE == "place_orders":
        print("")
        print("WARNING: EXECUTION_MODE is set to place_orders.")
        print("This mode will send orders once MT5 execution is implemented.")
        print("Check SYMBOL, LOT_SIZE, account type, SL/TP, and risk lockouts first.")
        print("")


def print_startup_config() -> None:
    print("")
    print("VWAP Sigma Live Execution Engine")
    print("")
    print(f"- Symbol: {SYMBOL}")
    print(f"- Timeframe: {TIMEFRAME}")
    print(f"- Connect MT5 on startup: {CONNECT_MT5_ON_STARTUP}")
    print(f"- MT5 terminal path: {MT5_TERMINAL_PATH}")
    print(f"- MT5 login configured: {MT5_LOGIN is not None}")
    print(f"- MT5 server configured: {MT5_SERVER is not None}")
    print(f"- Run live loop on startup: {RUN_LIVE_LOOP_ON_STARTUP}")
    print(f"- Poll seconds: {POLL_SECONDS}")
    print(f"- Candle confirmation delay seconds: {CANDLE_CONFIRMATION_DELAY_SECONDS}")
    print(f"- Execution mode: {EXECUTION_MODE}")
    print(f"- Engine mode: {ENGINE_MODE}")
    print(f"- Strategy filter: {USE_STRATEGY_FILTER}")
    print(f"- Strategy filter mode: {STRATEGY_FILTER_MODE}")
    print(f"- SL points: {SL_POINTS}")
    print(f"- TP points: {TP_POINTS}")
    print(f"- BE trigger: {BE_TRIGGER_POINTS}")
    print(f"- Runner mode: {RUNNER_MODE}")
    print(f"- Global runner target fallback: {RUNNER_TARGET_R}")
    print(f"- Protected add-ons enabled: {ENABLE_PROTECTED_ADDONS}")
    print(f"- Max open continuation trades: {MAX_OPEN_CONTINUATION_TRADES}")
    print(f"- Max daily loss R: {MAX_DAILY_LOSS_R}")
    print(f"- Max consecutive SL: {MAX_CONSECUTIVE_SL}")
    print(f"- No new trades after: {NO_NEW_TRADES_AFTER} {TRADING_TIMEZONE}")
    print(f"- Session filter enabled: {USE_SESSION_FILTER}")
    print(f"- Session start: {SESSION_START}")
    print(f"- Session end: {SESSION_END}")
    print(f"- History lookback minutes: {HISTORY_LOOKBACK_MINUTES}")
    print(f"- Minimum warmup candles: {MIN_WARMUP_CANDLES}")
    print(
        "- Require full lookback before trading: "
        f"{REQUIRE_FULL_LOOKBACK_BEFORE_TRADING}"
    )
    print(f"- Block market open window: {BLOCK_MARKET_OPEN_WINDOW}")
    print(f"- Market open time: {MARKET_OPEN_TIME}")
    print(f"- Market open timezone: {MARKET_OPEN_TIMEZONE}")
    print(f"- Market open block minutes: {MARKET_OPEN_BLOCK_MINUTES}")

    a_tier_bypass = ROUTER_BYPASS_RULES["A_TIER"]

    print(f"- A-tier bypass enabled: {a_tier_bypass['enabled']}")
    print(
        "- A-tier bypass red-shift floor: "
        f"{a_tier_bypass['min_directional_red_shift_points']}"
    )
    print(
        "- A-tier bypass trend-health mode: "
        f"{a_tier_bypass['trend_health_mode']}"
    )

    for setup_family in [
        "S_TIER",
        "DYNAMIC_S_TIER",
        "A_TIER",
        "DELAYED_PULLBACK",
    ]:
        print(
            f"- {setup_family} runner target: "
            f"{get_runner_target_for_setup(setup_family)}"
        )

    print("")


# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def main() -> None:
    validate_config()
    bot_start_time = get_bot_start_time()

    print_startup_config()

    log_event(
        "HEARTBEAT",
        bot_start_time=bot_start_time.isoformat(),
        history_lookback_minutes=HISTORY_LOOKBACK_MINUTES,
        min_warmup_candles=MIN_WARMUP_CANDLES,
        require_full_lookback_before_trading=REQUIRE_FULL_LOOKBACK_BEFORE_TRADING,
        market_open_blackout_enabled=BLOCK_MARKET_OPEN_WINDOW,
        market_open_time=MARKET_OPEN_TIME,
        market_open_timezone=MARKET_OPEN_TIMEZONE,
        market_open_block_minutes=MARKET_OPEN_BLOCK_MINUTES,
        timeframe=TIMEFRAME,
        message="VWAP Sigma live execution engine started",
    )

    if not CONNECT_MT5_ON_STARTUP:
        print("MT5 startup connection is disabled.")
        print("Set CONNECT_MT5_ON_STARTUP = True to test MT5 connection and candle loading.")
        print("Engine startup checks completed.")
        return

    mt5_started = initialize_mt5()

    if not mt5_started:
        print("MT5 startup connection failed. Check logs for details.")
        return

    try:
        if not validate_account_safety():
            print("MT5 account safety check failed. Check logs for details.")
            return

        if not ensure_symbol_selected():
            print("MT5 symbol selection failed. Check logs for details.")
            return
        
        get_open_bot_positions()

        if RUN_LIVE_LOOP_ON_STARTUP:
            run_engine_loop(bot_start_time)
        else:
            run_single_engine_cycle(bot_start_time)
            print("Single closed-candle processing cycle completed.")

    finally:
        shutdown_mt5()


if __name__ == "__main__":
    main()