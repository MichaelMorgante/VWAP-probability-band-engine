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
import importlib
import json
import sys
import time as time_module
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta, timezone
from math import ceil
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
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
# SOURCE MODEL CONFIG
# ============================================================

USE_SRC_FEATURE_ENGINE = True
RELOAD_SRC_MODULES_ON_STARTUP = False
REQUIRE_SRC_FEATURE_ENGINE = True
# True = use the existing src VWAP/band/z-score engine.
# False = skip src feature calculation and keep the live shell running.

ORDER_DEVIATION_POINTS = 20
ORDER_FILLING_MODE = "IOC"
# options:
# "IOC"    = immediate-or-cancel
# "FOK"    = fill-or-kill
# "RETURN" = return remainder if supported by broker

CLOSE_IF_SL_MISSING_AFTER_FILL = True

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
# LIVE STRATEGY FEATURE CONFIG
# ============================================================

AUTOMATION_FEATURE_CONFIG = {
    # Feature lookbacks
    "shift_lookback": 3,
    "acceptance_lookback": 3,
    "trend_lane_lookback": 5,
    "trend_damage_lookback": 5,
    "compression_lookback": 5,
    "flat_vwap_lookback": 5,
    "vwap_cross_lookback": 8,

    # Chop / compression settings
    "flat_vwap_threshold_points": 3.0,
    "min_band_expansion_points": 0.0,
    "max_vwap_crosses_before_chop": 2,

    # Red-band shift strength buckets
    "red_shift_minimum_points": 2.5,
    "red_shift_good_points": 5.0,
    "red_shift_strong_points": 7.0,
    "red_shift_very_strong_points": 10.0,
    "red_shift_extreme_points": 15.0,
    "red_shift_very_extreme_points": 25.0,
    "red_shift_abnormal_points": 30.0,

    # V4 regime context
    "v4_realised_range_lookback": 20,
    "v4_min_realised_range_periods": 10,
    "v4_high_realised_range_ratio": 1.25,
    "v4_extreme_realised_range_ratio": 2.00,
    "v4_vwap_slope_lookback": 10,
    "v4_flat_vwap_threshold_points": 3.0,
    "v4_band_width_lookback": 20,
    "v4_min_band_width_periods": 10,
    "v4_wide_band_width_ratio": 1.20,
    "v4_band_expansion_lookback": 5,
    "v4_min_band_expansion_points": 0.0,
    "v4_vwap_cross_lookback": 12,
    "v4_max_vwap_crosses_for_trend": 2,
    "v4_recent_extreme_lookback": 5,

    # Conditional V2 trend-health context
    "v4_use_conditional_v2_trend_health_layer": True,
    "v4_conditional_v2_min_recent_vwap_crosses": 2,
    "v4_conditional_v2_extreme_range_ratio": 1.60,
    "v4_conditional_v2_min_directional_red_shift_points": 5.0,

    # Adaptive trend-health helper settings
    "v2_trend_health_lookback": 5,
    "v2_min_trend_health_periods": 3,
    "v2_min_red_shift_relative_to_average": 0.70,
    "v2_min_band_spread_change_points": 0.0,
    "v2_min_opposite_band_expansion_points": 0.0,
    "v2_trend_dead_bad_candles": 5,

    # Reclaim / recovery state settings
    "v2_reclaim_recovery_lookback": 20,
    "v2_reclaim_acceptance_lookback": 6,
    "v2_min_reclaim_above_green_ratio": 0.65,
    "v2_min_reclaim_consecutive_green_closes": 2,
    "v2_min_pullback_green_damage_count": 3,
    "v2_vwap_slope_lookback": 5,
    "v2_flat_vwap_slope_points": 1.5,

    # Red-shift relative context
    "v5_red_shift_relative_lookback_bars": 20,
    "v5_red_shift_upgrade_ratio": 1.50,
    "v5_red_shift_downgrade_ratio": 0.75,

    # Second-close helper settings
    "v3_green_reentry_lookback": 4,
    "v3_trend_dead_bad_candles": 5,
    "v3_min_directional_red_shift_points": 5.0,
    "v3_band_spread_lookback": 1,

    # Candle quality
    "min_body_ratio": 0.25,
    "min_close_through_green": 1.0,
}

# ============================================================
# RAW CONTINUATION CANDIDATE CONFIG
# ============================================================

ENABLE_RAW_CONTINUATION_CANDIDATES = True
LOG_RAW_CONTINUATION_CANDIDATES = True
# Raw candidates are detected and logged only.
# They are not promoted to executable TradeSignal objects in this commit.

# ============================================================
# SETUP CLASSIFICATION CONFIG
# ============================================================

ENABLE_SETUP_CLASSIFICATION = True
LOG_SETUP_CLASSIFICATION = True

SETUP_CLASSIFICATION_PRIORITY = [
    "DYNAMIC_S_TIER",
    "S_TIER",
    "A_TIER",
    "DELAYED_PULLBACK",
]
# Raw candidates are checked against setup families in this order.
# This commit classifies/logs setup families only.
# It does not promote candidates to executable TradeSignal objects.

# ============================================================
# SIGNAL PROMOTION CONFIG
# ============================================================

ENABLE_CONTINUATION_SIGNAL_PROMOTION = True
LOG_SELECTED_CONTINUATION_SIGNAL = True

CONTINUATION_SIGNAL_SELECTION_MODE = "priority_first"
# options:
# "priority_first" = choose the first classified candidate by setup priority
# "strongest_red_shift" = choose the classified candidate with strongest red shift

# ============================================================
# REGIME ROUTER CONFIG
# ============================================================

LOG_REGIME_ROUTER_DECISIONS = True

CONTINUATION_BLOCKED_REGIMES = {
    "chop",
    "extreme_news",
    "abnormal_news",
    "extreme_expansion",
    "very_extreme_expansion",
}
# These regimes block continuation promotion by default.
# Later bypass commits can selectively override this.

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
# POSITION MANAGEMENT CONFIG
# ============================================================

ENABLE_POSITION_MANAGEMENT = False
# False = do not modify open positions.
# True  = manage breakeven and runner trailing stops for bot positions.

LOG_POSITION_MANAGEMENT_DECISIONS = True

MIN_SL_UPDATE_DISTANCE_POINTS = 1.0
# Avoid sending tiny SL updates.

REQUIRE_TRADE_STATE_FOR_POSITION_MANAGEMENT = True
# True = only manage positions that have a registered/recovered trade state.


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
TRADE_STATE_LOG_PATH = LOG_DIR / "live_vwap_sigma_trade_states.jsonl"

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
    "order_type",
    "order_price",
    "order_volume",
    "order_comment",
    "close_reason",
    "project_root",
    "src_feature_engine_enabled",
    "src_import_status",
    "src_import_error",
    "feature_rows",
    "latest_feature_time",
    "missing_feature_columns",
    "automation_feature_rows",
    "latest_automation_time",
    "latest_regime_label",
    "latest_long_trend_health",
    "latest_short_trend_health",
    "raw_candidate_count",
    "raw_candidate_direction",
    "raw_candidate_pass",
    "raw_candidate_reason",
    "raw_candidate_regime",
    "raw_candidate_red_shift_points",
    "raw_candidate_red_shift_label",
    "raw_candidate_trend_health_pass",
    "raw_candidate_extension_points",
    "raw_candidate_close_through_green_points",
    "raw_candidate_body_ratio",
    "classified_candidate_count",
    "classified_setup_family",
    "classified_candidate_pass",
    "classified_candidate_reason",
    "setup_profile_enabled",
    "setup_red_shift_floor_pass",
    "setup_trend_health_pass",
    "setup_extension_pass",
    "setup_family_priority_rank",
    "selected_signal_setup_family",
    "selected_signal_direction",
    "selected_signal_reason",
    "selected_signal_selection_mode",
    "router_pass",
    "router_reason",
    "router_regime",
    "router_setup_family",
    "router_mode",
    "router_bypass_pass",
    "router_bypass_reason",
    "router_bypass_setup_family",
    "router_bypass_trend_health_mode",
    "trade_state_action",
    "trade_state_ticket",
    "trade_state_setup_family",
    "trade_state_direction",
    "trade_state_trail_state",
    "trade_state_source",
    "trade_state_open_count",
    "position_management_enabled",
    "position_management_action",
    "position_management_reason",
    "position_current_price",
    "position_unrealised_points",
    "position_unrealised_r",
    "position_current_sl",
    "position_new_sl",
    "position_target_tp",
    "position_runner_target_price",
    "position_trail_rule_label",
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

@dataclass
class RawContinuationCandidate:
    candidate_time: Any
    direction: str
    entry_price: float
    reason: str
    regime_label: str
    red_shift_points: float
    red_shift_label: str
    trend_health_pass: bool
    extension_from_green_points: float
    close_through_green_points: float
    body_ratio: float

@dataclass
class ClassifiedContinuationCandidate:
    candidate_time: Any
    direction: str
    setup_family: str
    entry_price: float
    reason: str
    regime_label: str
    red_shift_points: float
    red_shift_label: str
    trend_health_pass: bool
    extension_from_green_points: float
    close_through_green_points: float
    body_ratio: float
    setup_profile_enabled: bool
    red_shift_floor_pass: bool
    setup_trend_health_pass: bool
    setup_extension_pass: bool
    setup_family_priority_rank: int

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

live_trade_states: dict[int, LiveTradeState] = {}


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
# SOURCE MODEL FEATURE ADAPTER
# ============================================================

REQUIRED_ENGINE_OUTPUT_COLUMNS = [
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "upper_green",
    "upper_orange",
    "upper_red",
    "lower_green",
    "lower_orange",
    "lower_red",
]


ENGINE_COLUMN_ALIASES = {
    "vwap": ["vwap", "VWAP", "reference", "ref", "reference_line"],
    "upper_green": [
        "upper_green",
        "upper_1",
        "upper_band_1",
        "band_1p",
        "band_1_plus",
        "band_1+",
        "z1_upper",
        "upper_sigma_1",
    ],
    "upper_orange": [
        "upper_orange",
        "upper_2",
        "upper_band_2",
        "band_2p",
        "band_2_plus",
        "band_2+",
        "z2_upper",
        "upper_sigma_2",
    ],
    "upper_red": [
        "upper_red",
        "upper_3",
        "upper_band_3",
        "band_3p",
        "band_3_plus",
        "band_3+",
        "z3_upper",
        "upper_sigma_3",
    ],
    "lower_green": [
        "lower_green",
        "lower_1",
        "lower_band_1",
        "band_1n",
        "band_1m",
        "band_1_minus",
        "band_1-",
        "z1_lower",
        "lower_sigma_1",
    ],
    "lower_orange": [
        "lower_orange",
        "lower_2",
        "lower_band_2",
        "band_2n",
        "band_2m",
        "band_2_minus",
        "band_2-",
        "z2_lower",
        "lower_sigma_2",
    ],
    "lower_red": [
        "lower_red",
        "lower_3",
        "lower_band_3",
        "band_3n",
        "band_3m",
        "band_3_minus",
        "band_3-",
        "z3_lower",
        "lower_sigma_3",
    ],
}


_src_feature_engine_cache: dict[str, Any] | None = None


def find_project_root(start_path: Path | None = None) -> Path:
    if start_path is None:
        start_path = Path(__file__).resolve().parent

    start_path = start_path.resolve()

    for path in [start_path, *start_path.parents]:
        has_src = (path / "src").is_dir()
        has_repo_marker = (
            (path / ".git").exists()
            or (path / "README.md").exists()
            or (path / "requirements.txt").exists()
        )

        if has_src and has_repo_marker:
            return path

    raise FileNotFoundError(
        "Could not find the project root. Run this script from inside the "
        "VWAP-probability-band-engine project folder."
    )


def ensure_project_import_path() -> Path:
    project_root = find_project_root()

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    return project_root


def import_src_feature_engine() -> dict[str, Any]:
    global _src_feature_engine_cache

    if _src_feature_engine_cache is not None and not RELOAD_SRC_MODULES_ON_STARTUP:
        return _src_feature_engine_cache

    project_root = ensure_project_import_path()

    try:
        import src.config as engine_config_module
        import src.reference as reference_module
        import src.sigma as sigma_module
        import src.zones as zones_module

        if RELOAD_SRC_MODULES_ON_STARTUP:
            engine_config_module = importlib.reload(engine_config_module)
            reference_module = importlib.reload(reference_module)
            sigma_module = importlib.reload(sigma_module)
            zones_module = importlib.reload(zones_module)

        engine = {
            "project_root": project_root,
            "engine_config": dict(engine_config_module.CONFIG),
            "compute_reference": reference_module.compute_reference,
            "compute_sigma": sigma_module.compute_sigma,
            "compute_bands": sigma_module.compute_bands,
            "compute_zscore": zones_module.compute_zscore,
            "classify_zones_series": zones_module.classify_zones_series,
        }

        _src_feature_engine_cache = engine

        log_event(
            "HEARTBEAT",
            project_root=str(project_root),
            src_feature_engine_enabled=USE_SRC_FEATURE_ENGINE,
            src_import_status="ok",
            message="Existing src VWAP feature engine loaded",
        )

        return engine

    except Exception as exc:
        log_event(
            "ERROR",
            project_root=str(project_root),
            src_feature_engine_enabled=USE_SRC_FEATURE_ENGINE,
            src_import_status="failed",
            src_import_error=str(exc),
            message="Could not load existing src VWAP feature engine",
        )

        if REQUIRE_SRC_FEATURE_ENGINE:
            raise

        return {}


def setup_profile_bool_setting(
    setup_family: str,
    field_name: str,
    fallback: bool,
) -> bool:
    profile = SETUP_PROFILES.get(setup_family, {})
    return bool(profile.get(field_name, fallback))


def setup_profile_max_green_extension_points(setup_family: str) -> float | None:
    profile = SETUP_PROFILES.get(setup_family, {})
    value = profile.get(
        "max_entry_extension_from_green_points",
        DEFAULT_MAX_GREEN_EXTENSION_POINTS,
    )

    if value is None:
        return None

    return float(value)


def build_live_engine_config() -> dict[str, Any]:
    src_engine = import_src_feature_engine()
    engine_config = dict(src_engine.get("engine_config", {}))

    engine_config.update(AUTOMATION_FEATURE_CONFIG)

    engine_config.update(
        {
            "session_timezone": TRADING_TIMEZONE,
            "no_new_trades_after": NO_NEW_TRADES_AFTER,

            "use_candle_quality_filter": USE_CANDLE_QUALITY_FILTER,
            "use_extension_filter": USE_GREEN_EXTENSION_FILTER,
            "use_green_extension_filter": USE_GREEN_EXTENSION_FILTER,

            "max_extension_from_green": setup_profile_max_green_extension_points(
                "S_TIER"
            ),

            "v3_a_tier_max_extension_from_green": setup_profile_max_green_extension_points(
                "A_TIER"
            ),

            "s_tier_use_extension_filter": (
                USE_GREEN_EXTENSION_FILTER
                and setup_profile_bool_setting(
                    "S_TIER",
                    "use_extension_filter",
                    True,
                )
            ),
            "dynamic_s_tier_use_extension_filter": (
                USE_GREEN_EXTENSION_FILTER
                and setup_profile_bool_setting(
                    "DYNAMIC_S_TIER",
                    "use_extension_filter",
                    True,
                )
            ),
            "a_tier_use_extension_filter": (
                USE_GREEN_EXTENSION_FILTER
                and setup_profile_bool_setting(
                    "A_TIER",
                    "use_extension_filter",
                    True,
                )
            ),
            "delayed_pullback_use_extension_filter": (
                USE_GREEN_EXTENSION_FILTER
                and setup_profile_bool_setting(
                    "DELAYED_PULLBACK",
                    "use_extension_filter",
                    True,
                )
            ),

            "s_tier_max_entry_extension_from_green_points": setup_profile_max_green_extension_points(
                "S_TIER"
            ),
            "dynamic_s_tier_max_entry_extension_from_green_points": setup_profile_max_green_extension_points(
                "DYNAMIC_S_TIER"
            ),
            "a_tier_max_entry_extension_from_green_points": setup_profile_max_green_extension_points(
                "A_TIER"
            ),
            "delayed_pullback_max_entry_extension_from_green_points": setup_profile_max_green_extension_points(
                "DELAYED_PULLBACK"
            ),

            "enable_v2_trend_health_filter": USE_TREND_HEALTH_FILTER,
            "s_tier_use_trend_health": setup_profile_bool_setting(
                "S_TIER",
                "use_trend_health",
                False,
            ),
            "dynamic_s_tier_use_trend_health": setup_profile_bool_setting(
                "DYNAMIC_S_TIER",
                "use_trend_health",
                False,
            ),
            "a_tier_use_trend_health": setup_profile_bool_setting(
                "A_TIER",
                "use_trend_health",
                True,
            ),
            "delayed_pullback_use_trend_health": setup_profile_bool_setting(
                "DELAYED_PULLBACK",
                "use_trend_health",
                True,
            ),
        }
    )

    return engine_config


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate

    lower_map = {str(col).lower(): col for col in df.columns}

    for candidate in candidates:
        matched = lower_map.get(candidate.lower())

        if matched is not None:
            return matched

    return None


def add_engine_band_aliases(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for standard_name, aliases in ENGINE_COLUMN_ALIASES.items():
        if standard_name in out.columns:
            continue

        matched_column = find_column(out, aliases)

        if matched_column is not None:
            out[standard_name] = out[matched_column]

    return out


def validate_engine_output_columns(df: pd.DataFrame) -> None:
    missing = [column for column in REQUIRED_ENGINE_OUTPUT_COLUMNS if column not in df.columns]

    if missing:
        log_event(
            "ERROR",
            missing_feature_columns=", ".join(missing),
            message="Missing required VWAP feature output columns",
        )

        raise ValueError(
            "Missing required VWAP feature output columns: "
            + ", ".join(missing)
        )
    
REQUIRED_AUTOMATION_FEATURE_COLUMNS = [
    "bullish_red_shift_strength",
    "bearish_red_shift_strength",
    "bullish_red_shift_label",
    "bearish_red_shift_label",
    "accepted_above_vwap",
    "accepted_below_vwap",
    "v2_long_trend_health_pass",
    "v2_short_trend_health_pass",
    "v3_long_directional_red_shift_pass",
    "v3_short_directional_red_shift_pass",
    "long_extension_from_green_points",
    "short_extension_from_green_points",
    "v4_preliminary_regime_label",
    "v5_regime_20m",
]


RED_SHIFT_BUCKET_ORDER = [
    "weak",
    "minimum",
    "good",
    "strong",
    "very_strong",
    "extreme",
    "very_extreme",
    "abnormal_news",
]


def consecutive_true_count(condition: pd.Series) -> pd.Series:
    condition = condition.fillna(False).astype(bool)

    counts = []
    current_count = 0

    for value in condition:
        if value:
            current_count += 1
        else:
            current_count = 0

        counts.append(current_count)

    return pd.Series(counts, index=condition.index)


def classify_red_shift_strength(value: float, config: dict[str, Any]) -> str:
    if pd.isna(value):
        return "unknown"

    if value < config["red_shift_minimum_points"]:
        return "weak"

    if value < config["red_shift_good_points"]:
        return "minimum"

    if value < config["red_shift_strong_points"]:
        return "good"

    if value < config["red_shift_very_strong_points"]:
        return "strong"

    if value < config["red_shift_extreme_points"]:
        return "very_strong"

    if value < config["red_shift_very_extreme_points"]:
        return "extreme"

    if value < config["red_shift_abnormal_points"]:
        return "very_extreme"

    return "abnormal_news"


def adjust_red_shift_bucket_by_relative_strength(
    bucket: str,
    shift_ratio: float,
    config: dict[str, Any],
) -> str:
    if bucket not in RED_SHIFT_BUCKET_ORDER:
        return bucket

    if pd.isna(shift_ratio):
        return bucket

    bucket_index = RED_SHIFT_BUCKET_ORDER.index(bucket)

    if shift_ratio >= config.get("v5_red_shift_upgrade_ratio", 1.50):
        bucket_index = min(bucket_index + 1, len(RED_SHIFT_BUCKET_ORDER) - 1)

    elif shift_ratio <= config.get("v5_red_shift_downgrade_ratio", 0.75):
        bucket_index = max(bucket_index - 1, 0)

    return RED_SHIFT_BUCKET_ORDER[bucket_index]


def classify_red_shift_strength_with_relative_context(
    value: float,
    shift_ratio: float,
    config: dict[str, Any],
) -> str:
    absolute_bucket = classify_red_shift_strength(value, config)

    return adjust_red_shift_bucket_by_relative_strength(
        bucket=absolute_bucket,
        shift_ratio=shift_ratio,
        config=config,
    )


def validate_automation_feature_columns(df: pd.DataFrame) -> None:
    missing = [
        column
        for column in REQUIRED_AUTOMATION_FEATURE_COLUMNS
        if column not in df.columns
    ]

    if missing:
        log_event(
            "ERROR",
            missing_feature_columns=", ".join(missing),
            message="Missing required automation feature columns",
        )

        raise ValueError(
            "Missing required automation feature columns: "
            + ", ".join(missing)
        )


def add_live_automation_features(
    df: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    out = df.copy().sort_values("datetime").reset_index(drop=True)

    shift_lookback = int(config["shift_lookback"])
    acceptance_lookback = int(config["acceptance_lookback"])
    compression_lookback = int(config["compression_lookback"])
    flat_vwap_lookback = int(config["flat_vwap_lookback"])
    vwap_cross_lookback = int(config["vwap_cross_lookback"])

    shift_columns = [
        "vwap",
        "upper_green",
        "upper_orange",
        "upper_red",
        "lower_green",
        "lower_orange",
        "lower_red",
    ]

    for column in shift_columns:
        out[f"{column}_shift"] = out[column] - out[column].shift(shift_lookback)

    out["bullish_red_shift_strength"] = out["upper_red_shift"]
    out["bearish_red_shift_strength"] = -out["lower_red_shift"]

    out["bullish_red_shift_label"] = out["bullish_red_shift_strength"].apply(
        lambda value: classify_red_shift_strength(value, config)
    )
    out["bearish_red_shift_label"] = out["bearish_red_shift_strength"].apply(
        lambda value: classify_red_shift_strength(value, config)
    )

    out["green_band_width"] = out["upper_green"] - out["lower_green"]
    out["orange_band_width"] = out["upper_orange"] - out["lower_orange"]
    out["red_band_width"] = out["upper_red"] - out["lower_red"]

    out["red_band_width_change"] = (
        out["red_band_width"] - out["red_band_width"].shift(compression_lookback)
    )

    out["bands_expanding"] = (
        out["red_band_width_change"] > config["min_band_expansion_points"]
    )
    out["bands_compressing"] = out["red_band_width_change"] < 0

    out["close_above_vwap"] = out["close"] > out["vwap"]
    out["close_below_vwap"] = out["close"] < out["vwap"]

    out["closes_above_vwap_count"] = (
        out["close_above_vwap"]
        .astype(int)
        .rolling(acceptance_lookback, min_periods=1)
        .sum()
    )

    out["closes_below_vwap_count"] = (
        out["close_below_vwap"]
        .astype(int)
        .rolling(acceptance_lookback, min_periods=1)
        .sum()
    )

    out["accepted_above_vwap"] = out["closes_above_vwap_count"] >= 2
    out["accepted_below_vwap"] = out["closes_below_vwap_count"] >= 2

    out["v2_long_vwap_acceptance_pass"] = (
        out["accepted_above_vwap"] & (out["close"] > out["vwap"])
    )
    out["v2_short_vwap_acceptance_pass"] = (
        out["accepted_below_vwap"] & (out["close"] < out["vwap"])
    )

    out["v2_last_upper_red_shift"] = out["upper_red"] - out["upper_red"].shift(1)
    out["v2_last_lower_red_shift"] = out["lower_red"].shift(1) - out["lower_red"]

    out["v2_long_directional_red_shift"] = out["v2_last_upper_red_shift"]
    out["v2_short_directional_red_shift"] = out["v2_last_lower_red_shift"]

    trend_health_lookback = int(config["v2_trend_health_lookback"])
    min_trend_health_periods = int(config["v2_min_trend_health_periods"])

    out["v2_long_recent_avg_red_shift"] = (
        out["v2_long_directional_red_shift"]
        .clip(lower=0)
        .rolling(trend_health_lookback, min_periods=min_trend_health_periods)
        .mean()
        .shift(1)
    )

    out["v2_short_recent_avg_red_shift"] = (
        out["v2_short_directional_red_shift"]
        .clip(lower=0)
        .rolling(trend_health_lookback, min_periods=min_trend_health_periods)
        .mean()
        .shift(1)
    )

    out["v2_long_red_shift_relative_to_avg"] = np.where(
        out["v2_long_recent_avg_red_shift"] > 0,
        out["v2_long_directional_red_shift"] / out["v2_long_recent_avg_red_shift"],
        np.nan,
    )

    out["v2_short_red_shift_relative_to_avg"] = np.where(
        out["v2_short_recent_avg_red_shift"] > 0,
        out["v2_short_directional_red_shift"] / out["v2_short_recent_avg_red_shift"],
        np.nan,
    )

    out["v2_long_red_shift_adaptive_pass"] = (
        (out["v2_long_directional_red_shift"] > 0)
        & (
            out["v2_long_red_shift_relative_to_avg"]
            >= config["v2_min_red_shift_relative_to_average"]
        )
    )

    out["v2_short_red_shift_adaptive_pass"] = (
        (out["v2_short_directional_red_shift"] > 0)
        & (
            out["v2_short_red_shift_relative_to_avg"]
            >= config["v2_min_red_shift_relative_to_average"]
        )
    )

    out["v2_red_band_width_change_window"] = (
        out["red_band_width"] - out["red_band_width"].shift(trend_health_lookback)
    )

    out["v2_bands_not_compressing"] = (
        out["v2_red_band_width_change_window"]
        >= config["v2_min_band_spread_change_points"]
    )

    out["v2_long_opposite_band_expansion"] = (
        out["lower_red"].shift(1) - out["lower_red"]
    )
    out["v2_short_opposite_band_expansion"] = (
        out["upper_red"] - out["upper_red"].shift(1)
    )

    out["v2_long_opposite_band_expansion_pass"] = (
        out["v2_long_opposite_band_expansion"]
        >= config["v2_min_opposite_band_expansion_points"]
    )

    out["v2_short_opposite_band_expansion_pass"] = (
        out["v2_short_opposite_band_expansion"]
        >= config["v2_min_opposite_band_expansion_points"]
    )

    out["v2_long_bad_green_close"] = out["close"] < out["upper_green"]
    out["v2_short_bad_green_close"] = out["close"] > out["lower_green"]

    out["v2_long_bad_green_close_count"] = consecutive_true_count(
        out["v2_long_bad_green_close"]
    )
    out["v2_short_bad_green_close_count"] = consecutive_true_count(
        out["v2_short_bad_green_close"]
    )

    out["v2_long_trend_dead"] = (
        out["v2_long_bad_green_close_count"]
        >= config["v2_trend_dead_bad_candles"]
    )
    out["v2_short_trend_dead"] = (
        out["v2_short_bad_green_close_count"]
        >= config["v2_trend_dead_bad_candles"]
    )

    out["v2_long_trend_health_pass"] = (
        out["v2_long_vwap_acceptance_pass"]
        & out["v2_long_red_shift_adaptive_pass"]
        & out["v2_bands_not_compressing"]
        & out["v2_long_opposite_band_expansion_pass"]
        & ~out["v2_long_trend_dead"]
    )

    out["v2_short_trend_health_pass"] = (
        out["v2_short_vwap_acceptance_pass"]
        & out["v2_short_red_shift_adaptive_pass"]
        & out["v2_bands_not_compressing"]
        & out["v2_short_opposite_band_expansion_pass"]
        & ~out["v2_short_trend_dead"]
    )

    out["v2_long_continuation_health_pass"] = out["v2_long_trend_health_pass"]
    out["v2_short_continuation_health_pass"] = out["v2_short_trend_health_pass"]

    out["v3_long_directional_red_shift"] = (
        out["upper_red"] - out["upper_red"].shift(1)
    )
    out["v3_short_directional_red_shift"] = (
        out["lower_red"].shift(1) - out["lower_red"]
    )

    out["v3_long_red_shift_bucket"] = out["v3_long_directional_red_shift"].apply(
        lambda value: classify_red_shift_strength(value, config)
    )
    out["v3_short_red_shift_bucket"] = out["v3_short_directional_red_shift"].apply(
        lambda value: classify_red_shift_strength(value, config)
    )

    out["v3_long_directional_red_shift_pass"] = (
        out["v3_long_directional_red_shift"]
        >= config["v3_min_directional_red_shift_points"]
    )
    out["v3_short_directional_red_shift_pass"] = (
        out["v3_short_directional_red_shift"]
        >= config["v3_min_directional_red_shift_points"]
    )

    out["v3_long_vwap_acceptance_pass"] = out["v2_long_vwap_acceptance_pass"]
    out["v3_short_vwap_acceptance_pass"] = out["v2_short_vwap_acceptance_pass"]

    out["v3_long_trend_dead"] = out["v2_long_trend_dead"]
    out["v3_short_trend_dead"] = out["v2_short_trend_dead"]

    out["v3_red_bands_spreading"] = (
        out["red_band_width"] - out["red_band_width"].shift(
            int(config["v3_band_spread_lookback"])
        )
    ) > 0

    out["vwap_side"] = np.where(
        out["close"] > out["vwap"],
        1,
        np.where(out["close"] < out["vwap"], -1, 0),
    )

    out["vwap_cross"] = (
        (out["vwap_side"] != out["vwap_side"].shift(1))
        & (out["vwap_side"] != 0)
        & (out["vwap_side"].shift(1) != 0)
    )

    out["vwap_cross_count"] = (
        out["vwap_cross"]
        .astype(int)
        .rolling(vwap_cross_lookback, min_periods=1)
        .sum()
    )

    out["vwap_shift_flat_check"] = (
        out["vwap"] - out["vwap"].shift(flat_vwap_lookback)
    )
    out["vwap_is_flat"] = (
        out["vwap_shift_flat_check"].abs()
        <= config["flat_vwap_threshold_points"]
    )

    out["possible_chop"] = (
        (
            out["vwap_cross_count"]
            >= config["max_vwap_crosses_before_chop"]
        )
        & out["vwap_is_flat"]
    ) | (
        out["bands_compressing"]
        & out["vwap_is_flat"]
    )

    relative_lookback = int(config["v5_red_shift_relative_lookback_bars"])

    out["v5_long_avg_red_shift_20m"] = (
        out["v2_long_directional_red_shift"]
        .clip(lower=0)
        .rolling(relative_lookback, min_periods=3)
        .mean()
        .shift(1)
    )

    out["v5_short_avg_red_shift_20m"] = (
        out["v2_short_directional_red_shift"]
        .clip(lower=0)
        .rolling(relative_lookback, min_periods=3)
        .mean()
        .shift(1)
    )

    out["v5_long_red_shift_ratio_20m"] = np.where(
        out["v5_long_avg_red_shift_20m"] > 0,
        out["v2_long_directional_red_shift"] / out["v5_long_avg_red_shift_20m"],
        np.nan,
    )

    out["v5_short_red_shift_ratio_20m"] = np.where(
        out["v5_short_avg_red_shift_20m"] > 0,
        out["v2_short_directional_red_shift"] / out["v5_short_avg_red_shift_20m"],
        np.nan,
    )

    out["v5_long_red_shift_bucket"] = [
        classify_red_shift_strength_with_relative_context(value, ratio, config)
        for value, ratio in zip(
            out["v2_long_directional_red_shift"],
            out["v5_long_red_shift_ratio_20m"],
        )
    ]

    out["v5_short_red_shift_bucket"] = [
        classify_red_shift_strength_with_relative_context(value, ratio, config)
        for value, ratio in zip(
            out["v2_short_directional_red_shift"],
            out["v5_short_red_shift_ratio_20m"],
        )
    ]

    out["long_touched_upper_green"] = out["low"] <= out["upper_green"]
    out["long_locked_upper_green_touch"] = out["low"] <= out["upper_green"].shift(1)
    out["long_band_shift_touch"] = (
        out["long_touched_upper_green"]
        & ~out["long_locked_upper_green_touch"].fillna(False).astype(bool)
    )
    out["long_closed_above_upper_green"] = out["close"] > out["upper_green"]
    out["long_close_through_green_points"] = out["close"] - out["upper_green"]
    out["long_extension_from_green_points"] = out["close"] - out["upper_green"]

    out["short_touched_lower_green"] = out["high"] >= out["lower_green"]
    out["short_locked_lower_green_touch"] = out["high"] >= out["lower_green"].shift(1)
    out["short_band_shift_touch"] = (
        out["short_touched_lower_green"]
        & ~out["short_locked_lower_green_touch"].fillna(False).astype(bool)
    )
    out["short_closed_below_lower_green"] = out["close"] < out["lower_green"]
    out["short_close_through_green_points"] = out["lower_green"] - out["close"]
    out["short_extension_from_green_points"] = out["lower_green"] - out["close"]

    min_close_through_green = float(config["min_close_through_green"])
    min_body_ratio = float(config["min_body_ratio"])

    out["long_close_through_green_valid"] = (
        out["long_close_through_green_points"] >= min_close_through_green
    )
    out["short_close_through_green_valid"] = (
        out["short_close_through_green_points"] >= min_close_through_green
    )

    out["long_body_valid"] = out["body_ratio"] >= min_body_ratio
    out["short_body_valid"] = out["body_ratio"] >= min_body_ratio

    out["long_not_orange_chase"] = out["close"] < out["upper_orange"]
    out["short_not_orange_chase"] = out["close"] > out["lower_orange"]

    max_extension_from_green = config.get("max_extension_from_green")
    a_tier_max_extension_from_green = config.get(
        "v3_a_tier_max_extension_from_green"
    )

    if config.get("s_tier_use_extension_filter", True) and max_extension_from_green is not None:
        out["long_extension_valid"] = (
            out["long_extension_from_green_points"] <= float(max_extension_from_green)
        )
        out["short_extension_valid"] = (
            out["short_extension_from_green_points"] <= float(max_extension_from_green)
        )
    else:
        out["long_extension_valid"] = True
        out["short_extension_valid"] = True

    if config.get("a_tier_use_extension_filter", True) and a_tier_max_extension_from_green is not None:
        out["v3_long_a_tier_extension_valid"] = (
            out["long_extension_from_green_points"]
            <= float(a_tier_max_extension_from_green)
        )
        out["v3_short_a_tier_extension_valid"] = (
            out["short_extension_from_green_points"]
            <= float(a_tier_max_extension_from_green)
        )
    else:
        out["v3_long_a_tier_extension_valid"] = True
        out["v3_short_a_tier_extension_valid"] = True

    out["v3_long_v1_execution_quality_pass"] = (
        out["long_close_through_green_valid"]
        & out["v3_long_a_tier_extension_valid"]
        & out["long_body_valid"]
        & out["long_not_orange_chase"]
        & ~out["possible_chop"]
    )

    out["v3_short_v1_execution_quality_pass"] = (
        out["short_close_through_green_valid"]
        & out["v3_short_a_tier_extension_valid"]
        & out["short_body_valid"]
        & out["short_not_orange_chase"]
        & ~out["possible_chop"]
    )

    v4_realised_range_lookback = int(config["v4_realised_range_lookback"])
    v4_min_realised_range_periods = int(config["v4_min_realised_range_periods"])
    v4_vwap_slope_lookback = int(config["v4_vwap_slope_lookback"])
    v4_band_width_lookback = int(config["v4_band_width_lookback"])
    v4_min_band_width_periods = int(config["v4_min_band_width_periods"])
    v4_band_expansion_lookback = int(config["v4_band_expansion_lookback"])
    v4_vwap_cross_lookback = int(config["v4_vwap_cross_lookback"])
    v4_recent_extreme_lookback = int(config["v4_recent_extreme_lookback"])

    out["v4_realised_range_points"] = out["high"] - out["low"]

    out["v4_realised_range_average"] = (
        out["v4_realised_range_points"]
        .rolling(
            v4_realised_range_lookback,
            min_periods=v4_min_realised_range_periods,
        )
        .mean()
        .shift(1)
    )

    out["v4_realised_range_relative_to_average"] = np.where(
        out["v4_realised_range_average"] > 0,
        out["v4_realised_range_points"] / out["v4_realised_range_average"],
        np.nan,
    )

    out["v4_high_realised_volatility"] = (
        out["v4_realised_range_relative_to_average"]
        >= config["v4_high_realised_range_ratio"]
    )

    out["v4_extreme_realised_volatility"] = (
        out["v4_realised_range_relative_to_average"]
        >= config["v4_extreme_realised_range_ratio"]
    )

    out["v4_vwap_slope_points"] = (
        out["vwap"] - out["vwap"].shift(v4_vwap_slope_lookback)
    )

    out["v4_vwap_slope_abs_points"] = out["v4_vwap_slope_points"].abs()

    out["v4_vwap_is_flat"] = (
        out["v4_vwap_slope_abs_points"]
        <= config["v4_flat_vwap_threshold_points"]
    )

    out["v4_red_band_width"] = out["red_band_width"]

    out["v4_red_band_width_average"] = (
        out["v4_red_band_width"]
        .rolling(v4_band_width_lookback, min_periods=v4_min_band_width_periods)
        .mean()
        .shift(1)
    )

    out["v4_red_band_width_relative_to_average"] = np.where(
        out["v4_red_band_width_average"] > 0,
        out["v4_red_band_width"] / out["v4_red_band_width_average"],
        np.nan,
    )

    out["v4_red_band_width_change"] = (
        out["v4_red_band_width"]
        - out["v4_red_band_width"].shift(v4_band_expansion_lookback)
    )

    out["v4_red_bands_expanding"] = (
        out["v4_red_band_width_change"] > config["v4_min_band_expansion_points"]
    )

    out["v4_red_bands_compressing"] = out["v4_red_band_width_change"] < 0

    out["v4_wide_bands"] = (
        out["v4_red_band_width_relative_to_average"]
        >= config["v4_wide_band_width_ratio"]
    )

    out["v4_recent_vwap_cross_count"] = (
        out["vwap_cross"]
        .astype(int)
        .rolling(v4_vwap_cross_lookback, min_periods=1)
        .sum()
    )

    out["v4_chop_from_vwap_crosses"] = (
        out["v4_recent_vwap_cross_count"]
        > config["v4_max_vwap_crosses_for_trend"]
    )

    out["v4_chop_from_flat_vwap_and_compression"] = (
        out["v4_vwap_is_flat"] & out["v4_red_bands_compressing"]
    )

    out["v4_chop_or_unclear_value"] = (
        out["possible_chop"]
        | out["v4_chop_from_vwap_crosses"]
        | out["v4_chop_from_flat_vwap_and_compression"]
    )

    out["v4_bullish_directional_context"] = (
        out["accepted_above_vwap"]
        & (out["close"] > out["vwap"])
        & (out["close"] > out["upper_green"])
    )

    out["v4_bearish_directional_context"] = (
        out["accepted_below_vwap"]
        & (out["close"] < out["vwap"])
        & (out["close"] < out["lower_green"])
    )

    out["v4_directional_trend_context"] = (
        out["v4_bullish_directional_context"]
        | out["v4_bearish_directional_context"]
    )

    out["v4_directional_red_shift_strength"] = np.select(
        [
            out["v4_bullish_directional_context"],
            out["v4_bearish_directional_context"],
        ],
        [
            out["bullish_red_shift_strength"],
            out["bearish_red_shift_strength"],
        ],
        default=np.nan,
    )

    out["v4_abnormal_red_shift_context"] = (
        out["v4_directional_red_shift_strength"]
        >= config["red_shift_abnormal_points"]
    )

    out["v4_recent_abnormal_red_shift_context"] = (
        out["v4_abnormal_red_shift_context"]
        .astype(int)
        .rolling(v4_recent_extreme_lookback, min_periods=1)
        .max()
        .astype(bool)
    )

    out["v4_extreme_news_context"] = (
        out["v4_recent_abnormal_red_shift_context"]
        | out["v4_extreme_realised_volatility"]
    )

    out["v4_volatile_directional_context"] = (
        out["v4_directional_trend_context"]
        & (
            out["v4_high_realised_volatility"]
            | out["v4_wide_bands"]
            | out["v4_red_bands_expanding"]
        )
    )

    out["v4_calm_directional_context"] = (
        out["v4_directional_trend_context"]
        & ~out["v4_high_realised_volatility"]
        & ~out["v4_wide_bands"]
        & ~out["v4_chop_or_unclear_value"]
    )

    out["v4_preliminary_regime_label"] = np.select(
        [
            out["v4_extreme_news_context"],
            out["v4_chop_or_unclear_value"] | ~out["v4_directional_trend_context"],
            out["v4_volatile_directional_context"],
            out["v4_calm_directional_context"],
        ],
        [
            "extreme_news",
            "chop",
            "volatile_trend",
            "calm_trend",
        ],
        default="chop",
    )

    out["v5_abnormal_news_context"] = (
        out["v5_long_red_shift_bucket"].eq("abnormal_news")
        | out["v5_short_red_shift_bucket"].eq("abnormal_news")
        | out["v4_abnormal_red_shift_context"].fillna(False).astype(bool)
    )

    out["v5_extreme_expansion_context"] = (
        out["v4_red_bands_expanding"]
        & (
            out["v5_long_red_shift_bucket"].isin(["extreme", "very_extreme"])
            | out["v5_short_red_shift_bucket"].isin(["extreme", "very_extreme"])
        )
    )

    out["v5_very_extreme_expansion_context"] = (
        out["v5_extreme_expansion_context"]
        & (
            out["v5_long_red_shift_bucket"].eq("very_extreme")
            | out["v5_short_red_shift_bucket"].eq("very_extreme")
        )
    )

    out["v5_regime_20m"] = np.select(
        [
            out["v5_abnormal_news_context"],
            out["v5_very_extreme_expansion_context"],
            out["v5_extreme_expansion_context"],
        ],
        [
            "abnormal_news",
            "very_extreme_expansion",
            "extreme_expansion",
        ],
        default=out["v4_preliminary_regime_label"],
    )

    return out.copy()


def prepare_candles_for_src_engine(candles: pd.DataFrame) -> pd.DataFrame:
    if candles is None or candles.empty:
        return pd.DataFrame()

    out = candles.copy()

    if isinstance(out.index, pd.DatetimeIndex):
        out = out.reset_index()

    if "time" in out.columns and "datetime" not in out.columns:
        out = out.rename(columns={"time": "datetime"})

    if "index" in out.columns and "datetime" not in out.columns:
        out = out.rename(columns={"index": "datetime"})

    required_ohlc = ["datetime", "open", "high", "low", "close"]
    missing_ohlc = [column for column in required_ohlc if column not in out.columns]

    if missing_ohlc:
        raise ValueError(
            "Missing required OHLC columns for src feature engine: "
            + ", ".join(missing_ohlc)
        )

    out["datetime"] = pd.to_datetime(out["datetime"], utc=True, errors="coerce")
    out = out.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

    for column in ["open", "high", "low", "close"]:
        out[column] = pd.to_numeric(out[column], errors="coerce")

    if "tick_volume" not in out.columns:
        out["tick_volume"] = 1.0

    out["tick_volume"] = (
        pd.to_numeric(out["tick_volume"], errors="coerce")
        .fillna(1.0)
        .clip(lower=1.0)
    )

    out["typical_price"] = (out["high"] + out["low"] + out["close"]) / 3.0
    out["session_date"] = out["datetime"].dt.tz_convert(TRADING_TIMEZONE).dt.date

    return out


def compute_live_feature_context(candles: pd.DataFrame) -> pd.DataFrame:
    if not USE_SRC_FEATURE_ENGINE:
        log_event(
            "HEARTBEAT",
            src_feature_engine_enabled=USE_SRC_FEATURE_ENGINE,
            message="src feature engine disabled; skipping VWAP feature context",
        )

        return candles.copy()

    src_engine = import_src_feature_engine()
    engine_config = build_live_engine_config()

    df = prepare_candles_for_src_engine(candles)

    if df.empty:
        log_event(
            "ERROR",
            src_feature_engine_enabled=USE_SRC_FEATURE_ENGINE,
            message="No candles available for VWAP feature calculation",
        )

        return df

    compute_reference = src_engine["compute_reference"]
    compute_sigma = src_engine["compute_sigma"]
    compute_bands = src_engine["compute_bands"]
    compute_zscore = src_engine["compute_zscore"]
    classify_zones_series = src_engine["classify_zones_series"]

    df["reference"] = compute_reference(df, engine_config)
    df["price_deviation"] = df["close"] - df["reference"]

    df["sigma"] = compute_sigma(df, engine_config)

    bands = compute_bands(df, df["sigma"])
    df = pd.concat([df, bands], axis=1)

    df["z_score"] = compute_zscore(df)
    df["zone"] = classify_zones_series(
        df["z_score"],
        engine_config["zone_thresholds"],
    )

    df = add_engine_band_aliases(df)

    df["candle_range"] = df["high"] - df["low"]
    df["candle_body"] = (df["close"] - df["open"]).abs()
    df["body_ratio"] = np.where(
        df["candle_range"] > 0,
        df["candle_body"] / df["candle_range"],
        0.0,
    )

    validate_engine_output_columns(df)

    df = add_live_automation_features(df, engine_config)
    validate_automation_feature_columns(df)

    latest_feature_time = df["datetime"].iloc[-1] if not df.empty else ""
    latest_row = df.iloc[-1] if not df.empty else {}

    log_event(
        "HEARTBEAT",
        src_feature_engine_enabled=USE_SRC_FEATURE_ENGINE,
        src_import_status="ok",
        feature_rows=len(df),
        latest_feature_time=latest_feature_time,
        automation_feature_rows=len(df),
        latest_automation_time=latest_feature_time,
        latest_regime_label=latest_row.get("v5_regime_20m", ""),
        latest_long_trend_health=latest_row.get("v2_long_trend_health_pass", ""),
        latest_short_trend_health=latest_row.get("v2_short_trend_health_pass", ""),
        message=f"Built live automation feature context with {len(df)} rows",
    )

    return df

# ============================================================
# RAW CONTINUATION CANDIDATE DETECTION
# ============================================================

def safe_bool(value: Any) -> bool:
    if value is None:
        return False

    try:
        if pd.isna(value):
            return False
    except TypeError:
        pass

    return bool(value)


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    try:
        if pd.isna(value):
            return default
    except TypeError:
        pass

    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def latest_feature_row(features_df: pd.DataFrame) -> pd.Series | None:
    if features_df is None or features_df.empty:
        return None

    return features_df.iloc[-1]


def raw_long_continuation_pass(row: pd.Series) -> bool:
    return all(
        [
            safe_bool(row.get("long_touched_upper_green")),
            safe_bool(row.get("long_closed_above_upper_green")),
            safe_bool(row.get("v3_long_vwap_acceptance_pass")),
            safe_bool(row.get("v3_long_directional_red_shift_pass")),
            safe_bool(row.get("v3_long_v1_execution_quality_pass")),
        ]
    )


def raw_short_continuation_pass(row: pd.Series) -> bool:
    return all(
        [
            safe_bool(row.get("short_touched_lower_green")),
            safe_bool(row.get("short_closed_below_lower_green")),
            safe_bool(row.get("v3_short_vwap_acceptance_pass")),
            safe_bool(row.get("v3_short_directional_red_shift_pass")),
            safe_bool(row.get("v3_short_v1_execution_quality_pass")),
        ]
    )


def build_raw_candidate_reason(direction: str, row: pd.Series) -> str:
    regime_label = row.get("v5_regime_20m", "")
    red_shift_label = (
        row.get("v3_long_red_shift_bucket", "")
        if direction == "BUY"
        else row.get("v3_short_red_shift_bucket", "")
    )

    return (
        f"Raw {direction} continuation candidate: "
        f"green touch/reclaim, VWAP acceptance, red-shift pass, "
        f"execution quality pass; regime={regime_label}, red_shift={red_shift_label}"
    )


def build_raw_continuation_candidate(
    row: pd.Series,
    direction: str,
) -> RawContinuationCandidate:
    if direction == "BUY":
        red_shift_points = safe_float(row.get("v3_long_directional_red_shift"))
        red_shift_label = str(row.get("v3_long_red_shift_bucket", ""))
        trend_health_pass = safe_bool(row.get("v2_long_trend_health_pass"))
        extension_points = safe_float(row.get("long_extension_from_green_points"))
        close_through_points = safe_float(row.get("long_close_through_green_points"))

    elif direction == "SELL":
        red_shift_points = safe_float(row.get("v3_short_directional_red_shift"))
        red_shift_label = str(row.get("v3_short_red_shift_bucket", ""))
        trend_health_pass = safe_bool(row.get("v2_short_trend_health_pass"))
        extension_points = safe_float(row.get("short_extension_from_green_points"))
        close_through_points = safe_float(row.get("short_close_through_green_points"))

    else:
        raise ValueError(f"Invalid raw candidate direction: {direction}")

    return RawContinuationCandidate(
        candidate_time=row.get("datetime"),
        direction=direction,
        entry_price=safe_float(row.get("close")),
        reason=build_raw_candidate_reason(direction, row),
        regime_label=str(row.get("v5_regime_20m", "")),
        red_shift_points=red_shift_points,
        red_shift_label=red_shift_label,
        trend_health_pass=trend_health_pass,
        extension_from_green_points=extension_points,
        close_through_green_points=close_through_points,
        body_ratio=safe_float(row.get("body_ratio")),
    )


def detect_raw_continuation_candidates(
    features_df: pd.DataFrame,
) -> list[RawContinuationCandidate]:
    if not ENABLE_CONTINUATION:
        return []

    if not ENABLE_RAW_CONTINUATION_CANDIDATES:
        return []

    row = latest_feature_row(features_df)

    if row is None:
        return []

    candidates: list[RawContinuationCandidate] = []

    if raw_long_continuation_pass(row):
        candidates.append(
            build_raw_continuation_candidate(
                row=row,
                direction="BUY",
            )
        )

    if raw_short_continuation_pass(row):
        candidates.append(
            build_raw_continuation_candidate(
                row=row,
                direction="SELL",
            )
        )

    return candidates


def log_raw_continuation_candidate(candidate: RawContinuationCandidate) -> None:
    if not LOG_RAW_CONTINUATION_CANDIDATES:
        return

    log_event(
        "RAW_CONTINUATION_CANDIDATE",
        signal_time=candidate.candidate_time,
        direction=candidate.direction,
        entry_price=candidate.entry_price,
        decision="candidate_only",
        raw_candidate_direction=candidate.direction,
        raw_candidate_pass=True,
        raw_candidate_reason=candidate.reason,
        raw_candidate_regime=candidate.regime_label,
        raw_candidate_red_shift_points=candidate.red_shift_points,
        raw_candidate_red_shift_label=candidate.red_shift_label,
        raw_candidate_trend_health_pass=candidate.trend_health_pass,
        raw_candidate_extension_points=candidate.extension_from_green_points,
        raw_candidate_close_through_green_points=candidate.close_through_green_points,
        raw_candidate_body_ratio=candidate.body_ratio,
        message="Raw continuation candidate detected; not promoted to executable signal yet",
    )

# ============================================================
# SETUP-FAMILY CLASSIFICATION
# ============================================================

def global_setup_enabled(setup_family: str) -> bool:
    global_switches = {
        "S_TIER": ENABLE_S_TIER,
        "DYNAMIC_S_TIER": ENABLE_DYNAMIC_S_TIER,
        "A_TIER": ENABLE_A_TIER,
        "DELAYED_PULLBACK": ENABLE_DELAYED_PULLBACK,
    }

    return bool(global_switches.get(setup_family, False))


def setup_profile_enabled(setup_family: str) -> bool:
    profile = SETUP_PROFILES.get(setup_family, {})

    return bool(profile.get("enabled", False)) and global_setup_enabled(setup_family)


def setup_requires_red_shift_floor(setup_family: str) -> bool:
    profile = SETUP_PROFILES.get(setup_family, {})

    return bool(USE_RED_SHIFT_FLOOR or profile.get("use_red_shift_floor", False))


def setup_requires_trend_health(setup_family: str) -> bool:
    profile = SETUP_PROFILES.get(setup_family, {})

    return bool(USE_TREND_HEALTH_FILTER and profile.get("use_trend_health", False))


def setup_requires_extension_filter(setup_family: str) -> bool:
    profile = SETUP_PROFILES.get(setup_family, {})

    return bool(USE_GREEN_EXTENSION_FILTER and profile.get("use_extension_filter", False))


def setup_min_red_shift_points(setup_family: str) -> float:
    profile = SETUP_PROFILES.get(setup_family, {})

    return float(
        profile.get(
            "min_directional_red_shift_points",
            DEFAULT_MEAN_REVERSION_RED_SHIFT_POINTS,
        )
    )


def setup_max_extension_from_green_points(setup_family: str) -> float | None:
    profile = SETUP_PROFILES.get(setup_family, {})
    value = profile.get("max_entry_extension_from_green_points")

    if value is None:
        return None

    return float(value)


def candidate_band_shift_touch(
    row: pd.Series,
    candidate: RawContinuationCandidate,
) -> bool:
    if candidate.direction == "BUY":
        return safe_bool(row.get("long_band_shift_touch"))

    if candidate.direction == "SELL":
        return safe_bool(row.get("short_band_shift_touch"))

    return False


def setup_family_specific_candidate_pass(
    setup_family: str,
    row: pd.Series,
    candidate: RawContinuationCandidate,
) -> tuple[bool, str]:
    if setup_family == "DYNAMIC_S_TIER":
        if not candidate_band_shift_touch(row, candidate):
            return False, "Candidate is not a band-shift-assisted green touch"

        return True, "Dynamic S-tier band-shift touch candidate"

    if setup_family == "S_TIER":
        if candidate_band_shift_touch(row, candidate):
            return False, "Band-shift-assisted touch is reserved for Dynamic S-tier"

        return True, "S-tier direct green touch/reclaim candidate"

    if setup_family == "A_TIER":
        return True, "A-tier second-close continuation candidate"

    if setup_family == "DELAYED_PULLBACK":
        return False, "Delayed pullback state is not ported yet"

    return False, f"Unknown setup family: {setup_family}"


def setup_quality_passes(
    setup_family: str,
    candidate: RawContinuationCandidate,
) -> tuple[bool, bool, bool]:
    if setup_requires_red_shift_floor(setup_family):
        red_shift_floor_pass = (
            candidate.red_shift_points >= setup_min_red_shift_points(setup_family)
        )
    else:
        red_shift_floor_pass = True

    if setup_requires_trend_health(setup_family):
        setup_trend_health_pass = candidate.trend_health_pass
    else:
        setup_trend_health_pass = True

    if setup_requires_extension_filter(setup_family):
        max_extension = setup_max_extension_from_green_points(setup_family)

        if max_extension is None:
            setup_extension_pass = True
        else:
            setup_extension_pass = candidate.extension_from_green_points <= max_extension
    else:
        setup_extension_pass = True

    return (
        bool(red_shift_floor_pass),
        bool(setup_trend_health_pass),
        bool(setup_extension_pass),
    )


def classify_raw_continuation_candidate(
    row: pd.Series,
    candidate: RawContinuationCandidate,
) -> ClassifiedContinuationCandidate | None:
    if not ENABLE_SETUP_CLASSIFICATION:
        return None

    for priority_rank, setup_family in enumerate(SETUP_CLASSIFICATION_PRIORITY, start=1):
        profile_enabled = setup_profile_enabled(setup_family)

        if not profile_enabled:
            continue

        family_pass, family_reason = setup_family_specific_candidate_pass(
            setup_family=setup_family,
            row=row,
            candidate=candidate,
        )

        if not family_pass:
            continue

        (
            red_shift_floor_pass,
            setup_trend_health_pass,
            setup_extension_pass,
        ) = setup_quality_passes(
            setup_family=setup_family,
            candidate=candidate,
        )

        if not red_shift_floor_pass:
            continue

        if not setup_trend_health_pass:
            continue

        if not setup_extension_pass:
            continue

        return ClassifiedContinuationCandidate(
            candidate_time=candidate.candidate_time,
            direction=candidate.direction,
            setup_family=setup_family,
            entry_price=candidate.entry_price,
            reason=family_reason,
            regime_label=candidate.regime_label,
            red_shift_points=candidate.red_shift_points,
            red_shift_label=candidate.red_shift_label,
            trend_health_pass=candidate.trend_health_pass,
            extension_from_green_points=candidate.extension_from_green_points,
            close_through_green_points=candidate.close_through_green_points,
            body_ratio=candidate.body_ratio,
            setup_profile_enabled=profile_enabled,
            red_shift_floor_pass=red_shift_floor_pass,
            setup_trend_health_pass=setup_trend_health_pass,
            setup_extension_pass=setup_extension_pass,
            setup_family_priority_rank=priority_rank,
        )

    return None


def classify_raw_continuation_candidates(
    features_df: pd.DataFrame,
    raw_candidates: list[RawContinuationCandidate],
) -> list[ClassifiedContinuationCandidate]:
    if not ENABLE_SETUP_CLASSIFICATION:
        return []

    row = latest_feature_row(features_df)

    if row is None:
        return []

    classified_candidates: list[ClassifiedContinuationCandidate] = []

    for candidate in raw_candidates:
        classified_candidate = classify_raw_continuation_candidate(
            row=row,
            candidate=candidate,
        )

        if classified_candidate is not None:
            classified_candidates.append(classified_candidate)

    return classified_candidates


def log_classified_continuation_candidate(
    candidate: ClassifiedContinuationCandidate,
) -> None:
    if not LOG_SETUP_CLASSIFICATION:
        return

    log_event(
        "CLASSIFIED_CONTINUATION_CANDIDATE",
        signal_time=candidate.candidate_time,
        direction=candidate.direction,
        setup_family=candidate.setup_family,
        entry_price=candidate.entry_price,
        decision="classified_candidate_only",
        classified_setup_family=candidate.setup_family,
        classified_candidate_pass=True,
        classified_candidate_reason=candidate.reason,
        setup_profile_enabled=candidate.setup_profile_enabled,
        setup_red_shift_floor_pass=candidate.red_shift_floor_pass,
        setup_trend_health_pass=candidate.setup_trend_health_pass,
        setup_extension_pass=candidate.setup_extension_pass,
        setup_family_priority_rank=candidate.setup_family_priority_rank,
        raw_candidate_regime=candidate.regime_label,
        raw_candidate_red_shift_points=candidate.red_shift_points,
        raw_candidate_red_shift_label=candidate.red_shift_label,
        raw_candidate_trend_health_pass=candidate.trend_health_pass,
        raw_candidate_extension_points=candidate.extension_from_green_points,
        raw_candidate_close_through_green_points=candidate.close_through_green_points,
        raw_candidate_body_ratio=candidate.body_ratio,
        message="Raw continuation candidate classified by setup family; not executable yet",
    )

# ============================================================
# CONTINUATION SIGNAL PROMOTION
# ============================================================

def select_classified_continuation_candidate(
    candidates: list[ClassifiedContinuationCandidate],
) -> ClassifiedContinuationCandidate | None:
    if not candidates:
        return None

    if CONTINUATION_SIGNAL_SELECTION_MODE == "priority_first":
        return sorted(
            candidates,
            key=lambda candidate: candidate.setup_family_priority_rank,
        )[0]

    if CONTINUATION_SIGNAL_SELECTION_MODE == "strongest_red_shift":
        return sorted(
            candidates,
            key=lambda candidate: candidate.red_shift_points,
            reverse=True,
        )[0]

    raise ValueError(
        f"Invalid CONTINUATION_SIGNAL_SELECTION_MODE: {CONTINUATION_SIGNAL_SELECTION_MODE}"
    )


def build_trade_signal_from_classified_candidate(
    candidate: ClassifiedContinuationCandidate,
) -> TradeSignal:
    runner_target_r = get_runner_target_for_setup(candidate.setup_family)
    runner_target_points = runner_target_r * SL_POINTS

    sl_price, tp_price = build_sl_tp(
        direction=candidate.direction,
        entry_price=candidate.entry_price,
    )

    reason = (
        f"{candidate.setup_family} {candidate.direction} continuation signal: "
        f"{candidate.reason}; regime={candidate.regime_label}; "
        f"red_shift={candidate.red_shift_points:.2f} "
        f"({candidate.red_shift_label}); "
        f"runner_target_r={runner_target_r:.2f}"
    )

    return TradeSignal(
        signal_time=candidate.candidate_time,
        direction=candidate.direction,
        setup_family=candidate.setup_family,
        entry_price=candidate.entry_price,
        sl_price=sl_price,
        tp_price=tp_price,
        runner_target_r=runner_target_r,
        runner_target_points=runner_target_points,
        reason=reason,
    )


def log_selected_continuation_signal(signal: TradeSignal) -> None:
    if not LOG_SELECTED_CONTINUATION_SIGNAL:
        return

    log_event(
        "CONTINUATION_SIGNAL_SELECTED",
        signal_time=signal.signal_time,
        direction=signal.direction,
        setup_family=signal.setup_family,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
        tp_price=signal.tp_price,
        runner_target_r=signal.runner_target_r,
        runner_target_points=signal.runner_target_points,
        decision="selected_signal",
        selected_signal_setup_family=signal.setup_family,
        selected_signal_direction=signal.direction,
        selected_signal_reason=signal.reason,
        selected_signal_selection_mode=CONTINUATION_SIGNAL_SELECTION_MODE,
        message="Classified continuation candidate promoted to TradeSignal",
    )


def promote_classified_candidates_to_signal(
    candidates: list[ClassifiedContinuationCandidate],
) -> TradeSignal | None:
    if not ENABLE_CONTINUATION_SIGNAL_PROMOTION:
        return None

    selected_candidate = select_classified_continuation_candidate(candidates)

    if selected_candidate is None:
        return None

    signal = build_trade_signal_from_classified_candidate(selected_candidate)

    log_selected_continuation_signal(signal)

    return signal

# ============================================================
# REGIME ROUTER
# ============================================================

def candidate_regime_label(candidate: ClassifiedContinuationCandidate) -> str:
    return str(candidate.regime_label or "unknown")


def setup_allowed_in_calm_trend(candidate: ClassifiedContinuationCandidate) -> tuple[bool, str]:
    setup_family = candidate.setup_family
    profile = SETUP_PROFILES.get(setup_family, {})

    if setup_family in {"S_TIER", "DYNAMIC_S_TIER"}:
        return True, f"{setup_family} allowed in calm trend"

    if setup_family == "A_TIER":
        if not profile.get("allow_in_calm_trend", False):
            return False, "A-tier blocked in calm trend by setup profile"

        if profile.get("calm_require_red_shift_floor", False):
            min_points = float(
                profile.get(
                    "calm_min_directional_red_shift_points",
                    setup_min_red_shift_points(setup_family),
                )
            )

            if candidate.red_shift_points < min_points:
                return False, (
                    f"A-tier calm-trend red-shift floor failed: "
                    f"{candidate.red_shift_points:.2f} < {min_points:.2f}"
                )

        return True, "A-tier allowed in calm trend by setup profile"

    if setup_family == "DELAYED_PULLBACK":
        return False, "Delayed pullback calm-trend routing not enabled yet"

    return False, f"Unknown setup family for calm-trend routing: {setup_family}"


def setup_allowed_in_volatile_trend(candidate: ClassifiedContinuationCandidate) -> tuple[bool, str]:
    setup_family = candidate.setup_family
    profile = SETUP_PROFILES.get(setup_family, {})

    if setup_family == "S_TIER":
        if not profile.get("allow_in_volatile_trend", False):
            return False, "S-tier blocked in volatile trend by setup profile"

        if profile.get("volatile_require_red_shift_floor", False):
            min_points = float(
                profile.get(
                    "volatile_min_directional_red_shift_points",
                    setup_min_red_shift_points(setup_family),
                )
            )

            if candidate.red_shift_points < min_points:
                return False, (
                    f"S-tier volatile-trend red-shift floor failed: "
                    f"{candidate.red_shift_points:.2f} < {min_points:.2f}"
                )

        return True, "S-tier allowed in volatile trend by setup profile"

    if setup_family == "DYNAMIC_S_TIER":
        return True, "Dynamic S-tier allowed in volatile trend"

    if setup_family == "A_TIER":
        return True, "A-tier allowed in volatile trend"

    if setup_family == "DELAYED_PULLBACK":
        return True, "Delayed pullback allowed in volatile trend"

    return False, f"Unknown setup family for volatile-trend routing: {setup_family}"


def bypass_rule_for_setup(setup_family: str) -> dict[str, Any]:
    return ROUTER_BYPASS_RULES.get(setup_family, {})


def bypass_trend_health_required(
    candidate: ClassifiedContinuationCandidate,
    rule: dict[str, Any],
) -> tuple[bool, str]:
    trend_health_mode = rule.get("trend_health_mode")

    if trend_health_mode is None:
        legacy_requires_trend_health = bool(rule.get("requires_trend_health", False))

        if legacy_requires_trend_health:
            return True, "Legacy bypass trend-health requirement enabled"

        return False, "Bypass trend health not required"

    if trend_health_mode == "off":
        return False, "Bypass trend-health mode is off"

    if trend_health_mode == "always":
        return True, "Bypass trend-health mode always requires trend health"

    if trend_health_mode == "follow_v2_activation":
        return (
            bool(USE_TREND_HEALTH_FILTER),
            "Bypass follows global V2 trend-health activation",
        )

    if trend_health_mode == "after_time":
        after_time_value = rule.get("trend_health_after_time")
        after_timezone = rule.get("trend_health_after_timezone", TRADING_TIMEZONE)

        if not after_time_value:
            return False, "Bypass after_time has no configured time"

        candidate_dt = to_timezone_aware_datetime(
            candidate.candidate_time,
            after_timezone,
        )

        after_time = parse_hhmm_time(
            after_time_value,
            "trend_health_after_time",
        )

        after_dt = datetime.combine(
            candidate_dt.date(),
            after_time,
            tzinfo=get_timezone(after_timezone),
        )

        if candidate_dt >= after_dt:
            return True, f"Bypass requires trend health after {after_time_value} {after_timezone}"

        return False, f"Bypass trend health not required before {after_time_value} {after_timezone}"

    return True, f"Unknown bypass trend-health mode treated as required: {trend_health_mode}"


def router_bypass_decision(
    candidate: ClassifiedContinuationCandidate,
) -> tuple[bool, str]:
    rule = bypass_rule_for_setup(candidate.setup_family)

    if not rule:
        return False, f"No bypass rule configured for {candidate.setup_family}"

    if not bool(rule.get("enabled", False)):
        return False, f"Bypass disabled for {candidate.setup_family}"

    requires_red_shift_floor = bool(rule.get("requires_red_shift_floor", False))

    if requires_red_shift_floor:
        min_red_shift = float(
            rule.get(
                "min_directional_red_shift_points",
                setup_min_red_shift_points(candidate.setup_family),
            )
        )

        if candidate.red_shift_points < min_red_shift:
            return False, (
                f"Bypass red-shift floor failed: "
                f"{candidate.red_shift_points:.2f} < {min_red_shift:.2f}"
            )

    trend_health_required, trend_health_reason = bypass_trend_health_required(
        candidate=candidate,
        rule=rule,
    )

    if trend_health_required and not candidate.trend_health_pass:
        return False, f"Bypass trend-health failed: {trend_health_reason}"

    max_extension = rule.get("max_extension_from_green")

    if max_extension is not None:
        max_extension = float(max_extension)

        if candidate.extension_from_green_points > max_extension:
            return False, (
                f"Bypass extension failed: "
                f"{candidate.extension_from_green_points:.2f} > {max_extension:.2f}"
            )

    return True, f"Router bypass allowed for {candidate.setup_family}: {trend_health_reason}"


def log_router_bypass_decision(
    candidate: ClassifiedContinuationCandidate,
    bypass_pass: bool,
    bypass_reason: str,
) -> None:
    if not LOG_REGIME_ROUTER_DECISIONS:
        return

    rule = bypass_rule_for_setup(candidate.setup_family)

    log_event(
        "ROUTER_BYPASS_DECISION",
        signal_time=candidate.candidate_time,
        direction=candidate.direction,
        setup_family=candidate.setup_family,
        entry_price=candidate.entry_price,
        decision="bypass_pass" if bypass_pass else "bypass_block",
        router_bypass_pass=bypass_pass,
        router_bypass_reason=bypass_reason,
        router_bypass_setup_family=candidate.setup_family,
        router_bypass_trend_health_mode=rule.get("trend_health_mode", ""),
        router_regime=candidate_regime_label(candidate),
        router_mode=STRATEGY_FILTER_MODE,
        raw_candidate_red_shift_points=candidate.red_shift_points,
        raw_candidate_red_shift_label=candidate.red_shift_label,
        raw_candidate_trend_health_pass=candidate.trend_health_pass,
        raw_candidate_extension_points=candidate.extension_from_green_points,
        message=bypass_reason,
    )

def regime_router_decision(
    candidate: ClassifiedContinuationCandidate,
) -> tuple[bool, str]:
    if not USE_STRATEGY_FILTER:
        return True, "Strategy filter disabled"

    if not ENABLE_REGIME_ROUTER:
        return True, "Regime router disabled"

    if STRATEGY_FILTER_MODE != "v4_dynamic_regime_selector":
        return True, f"Router mode not handled here; allowing: {STRATEGY_FILTER_MODE}"

    regime_label = candidate_regime_label(candidate)

    if regime_label in CONTINUATION_BLOCKED_REGIMES:
        return False, f"Continuation blocked in regime: {regime_label}"

    if regime_label == "calm_trend":
        return setup_allowed_in_calm_trend(candidate)

    if regime_label == "volatile_trend":
        return setup_allowed_in_volatile_trend(candidate)

    return False, f"Unknown or unsupported continuation regime: {regime_label}"


def log_regime_router_decision(
    candidate: ClassifiedContinuationCandidate,
    router_pass: bool,
    router_reason: str,
) -> None:
    if not LOG_REGIME_ROUTER_DECISIONS:
        return

    log_event(
        "REGIME_ROUTER_DECISION",
        signal_time=candidate.candidate_time,
        direction=candidate.direction,
        setup_family=candidate.setup_family,
        entry_price=candidate.entry_price,
        decision="router_pass" if router_pass else "router_block",
        router_pass=router_pass,
        router_reason=router_reason,
        router_regime=candidate_regime_label(candidate),
        router_setup_family=candidate.setup_family,
        router_mode=STRATEGY_FILTER_MODE,
        raw_candidate_red_shift_points=candidate.red_shift_points,
        raw_candidate_red_shift_label=candidate.red_shift_label,
        raw_candidate_trend_health_pass=candidate.trend_health_pass,
        raw_candidate_extension_points=candidate.extension_from_green_points,
        message=router_reason,
    )


def apply_regime_router_to_classified_candidates(
    candidates: list[ClassifiedContinuationCandidate],
) -> list[ClassifiedContinuationCandidate]:
    routed_candidates: list[ClassifiedContinuationCandidate] = []

    for candidate in candidates:
        router_pass, router_reason = regime_router_decision(candidate)

        log_regime_router_decision(
            candidate=candidate,
            router_pass=router_pass,
            router_reason=router_reason,
        )

        if router_pass:
            routed_candidates.append(candidate)
            continue

        bypass_pass, bypass_reason = router_bypass_decision(candidate)

        log_router_bypass_decision(
            candidate=candidate,
            bypass_pass=bypass_pass,
            bypass_reason=bypass_reason,
        )

        if bypass_pass:
            routed_candidates.append(candidate)

    return routed_candidates

# ============================================================
# SIGNAL PROCESSING SHELL
# ============================================================

def normalise_signal_time(signal_time: Any) -> str:
    return pd.Timestamp(signal_time).isoformat()


def build_signal_from_live_context(candles: pd.DataFrame) -> TradeSignal | None:
    """
    Build live VWAP feature context from confirmed candles.

    Entry selection is still added separately. This function currently computes
    the model context and returns no signal.
    """
    latest_closed = get_latest_closed_candle(candles)

    if latest_closed is None:
        return None

    closed_candles = get_closed_candles(candles)

    if closed_candles.empty:
        return None

    features_df = compute_live_feature_context(closed_candles)

    if features_df.empty:
        return None

    latest_feature_row = features_df.iloc[-1]
    raw_candidates = detect_raw_continuation_candidates(features_df)

    for candidate in raw_candidates:
        log_raw_continuation_candidate(candidate)

    classified_candidates = classify_raw_continuation_candidates(
        features_df=features_df,
        raw_candidates=raw_candidates,
    )

    for candidate in classified_candidates:
        log_classified_continuation_candidate(candidate)

    routed_candidates = apply_regime_router_to_classified_candidates(
        classified_candidates
    )

    selected_signal = promote_classified_candidates_to_signal(routed_candidates)

    decision = "signal_selected" if selected_signal is not None else "no_signal"

    log_event(
        "HEARTBEAT",
        signal_time=latest_closed.name,
        feature_rows=len(features_df),
        latest_feature_time=latest_feature_row["datetime"],
        automation_feature_rows=len(features_df),
        latest_automation_time=latest_feature_row["datetime"],
        latest_regime_label=latest_feature_row.get("v5_regime_20m", ""),
        latest_long_trend_health=latest_feature_row.get("v2_long_trend_health_pass", ""),
        latest_short_trend_health=latest_feature_row.get("v2_short_trend_health_pass", ""),
        raw_candidate_count=len(raw_candidates),
        classified_candidate_count=len(classified_candidates),
        router_pass=len(routed_candidates) > 0,
        router_reason="At least one candidate passed router or bypass" if routed_candidates else "No candidate passed router or bypass",
        router_regime=latest_feature_row.get("v5_regime_20m", ""),
        router_mode=STRATEGY_FILTER_MODE,
        selected_signal_setup_family=selected_signal.setup_family if selected_signal else "",
        selected_signal_direction=selected_signal.direction if selected_signal else "",
        selected_signal_reason=selected_signal.reason if selected_signal else "",
        selected_signal_selection_mode=CONTINUATION_SIGNAL_SELECTION_MODE,
        decision=decision,
        message="Continuation signal promotion completed after regime-router gate",
    )

    return selected_signal


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

        result = place_trade(signal)

        if result is not None:
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

# ============================================================
# POSITION MANAGEMENT
# ============================================================

def get_position_current_price(position: Any) -> float | None:
    if mt5 is None:
        return None

    position_type = getattr(position, "type", None)
    tick = mt5.symbol_info_tick(SYMBOL)

    if tick is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            position_ticket=getattr(position, "ticket", ""),
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="No tick available for position management",
        )

        return None

    if position_type == mt5.POSITION_TYPE_BUY:
        return float(tick.bid)

    if position_type == mt5.POSITION_TYPE_SELL:
        return float(tick.ask)

    return None


def position_unrealised_points(
    position: Any,
    current_price: float,
) -> float:
    entry_price = float(getattr(position, "price_open", 0.0) or 0.0)
    position_type = getattr(position, "type", None)

    if mt5 is not None and position_type == mt5.POSITION_TYPE_BUY:
        return current_price - entry_price

    if mt5 is not None and position_type == mt5.POSITION_TYPE_SELL:
        return entry_price - current_price

    return 0.0


def position_runner_target_price(state: LiveTradeState) -> float:
    if state.direction == "BUY":
        return state.entry_price + state.runner_target_points

    if state.direction == "SELL":
        return state.entry_price - state.runner_target_points

    return state.tp_price


def calculate_candidate_sl_from_trail_rules(
    position: Any,
    state: LiveTradeState,
    unrealised_r: float,
) -> tuple[float | None, str]:
    matched_rule = None

    for rule in RUNNER_TRAIL_RULES_R:
        trigger_r = float(rule["trigger_r"])

        if unrealised_r >= trigger_r:
            matched_rule = rule

    if matched_rule is None:
        return None, "No trail rule triggered"

    lock_r = float(matched_rule["lock_r"])
    label = str(matched_rule.get("label", f"LOCK_{lock_r}R"))

    if state.direction == "BUY":
        new_sl = state.entry_price + (lock_r * SL_POINTS)

    elif state.direction == "SELL":
        new_sl = state.entry_price - (lock_r * SL_POINTS)

    else:
        return None, "Invalid trade-state direction"

    return float(new_sl), label


def is_sl_improvement(
    position: Any,
    new_sl: float,
) -> bool:
    current_sl = float(getattr(position, "sl", 0.0) or 0.0)
    position_type = getattr(position, "type", None)

    if current_sl == 0.0:
        return True

    if mt5 is not None and position_type == mt5.POSITION_TYPE_BUY:
        return new_sl > current_sl + MIN_SL_UPDATE_DISTANCE_POINTS

    if mt5 is not None and position_type == mt5.POSITION_TYPE_SELL:
        return new_sl < current_sl - MIN_SL_UPDATE_DISTANCE_POINTS

    return False


def update_position_sl(
    position: Any,
    new_sl: float,
    reason: str,
    trail_rule_label: str,
) -> Any | None:
    require_mt5()

    position_ticket = getattr(position, "ticket", None)
    current_tp = float(getattr(position, "tp", 0.0) or 0.0)

    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": SYMBOL,
        "position": position_ticket,
        "sl": float(new_sl),
        "tp": current_tp,
        "magic": MAGIC_NUMBER,
        "comment": ORDER_COMMENT,
    }

    log_event(
        "POSITION_MANAGEMENT",
        position_ticket=position_ticket,
        position_management_enabled=ENABLE_POSITION_MANAGEMENT,
        position_management_action="sl_update_attempt",
        position_management_reason=reason,
        position_current_sl=getattr(position, "sl", ""),
        position_new_sl=new_sl,
        position_target_tp=current_tp,
        position_trail_rule_label=trail_rule_label,
        message=f"Attempting SL update: {reason}",
    )

    result = mt5.order_send(request)

    if result is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            position_ticket=position_ticket,
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="sl_update_failed",
            position_management_reason="order_send returned None",
            position_new_sl=new_sl,
            position_trail_rule_label=trail_rule_label,
            message="SL update failed: order_send returned None",
        )

        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_event(
            "ERROR",
            position_ticket=position_ticket,
            retcode=result.retcode,
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="sl_update_rejected",
            position_management_reason=str(result),
            position_new_sl=new_sl,
            position_trail_rule_label=trail_rule_label,
            message="SL update rejected by MT5",
        )

        return None

    log_event(
        "POSITION_MANAGEMENT",
        position_ticket=position_ticket,
        retcode=result.retcode,
        position_management_enabled=ENABLE_POSITION_MANAGEMENT,
        position_management_action="sl_updated",
        position_management_reason=reason,
        position_current_sl=getattr(position, "sl", ""),
        position_new_sl=new_sl,
        position_target_tp=current_tp,
        position_trail_rule_label=trail_rule_label,
        message=f"SL updated: {reason}",
    )

    return result


def manage_single_position(position: Any) -> None:
    state = get_live_trade_state_for_position(position)

    if state is None:
        state = recover_live_trade_state_from_position(
            position=position,
            source="position_management_recovery",
        )

    if state is None and REQUIRE_TRADE_STATE_FOR_POSITION_MANAGEMENT:
        log_event(
            "POSITION_MANAGEMENT",
            position_ticket=getattr(position, "ticket", ""),
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="skipped",
            position_management_reason="No trade state available",
            message="Position management skipped because no trade state is available",
        )
        return

    if state is None:
        return

    current_price = get_position_current_price(position)

    if current_price is None:
        return

    unrealised_points = position_unrealised_points(
        position=position,
        current_price=current_price,
    )

    unrealised_r = unrealised_points / float(SL_POINTS)

    candidate_sl, trail_label = calculate_candidate_sl_from_trail_rules(
        position=position,
        state=state,
        unrealised_r=unrealised_r,
    )

    runner_target_price = position_runner_target_price(state)

    if LOG_POSITION_MANAGEMENT_DECISIONS:
        log_event(
            "POSITION_MANAGEMENT",
            position_ticket=getattr(position, "ticket", ""),
            setup_family=state.setup_family,
            direction=state.direction,
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="checked",
            position_management_reason=trail_label,
            position_current_price=current_price,
            position_unrealised_points=unrealised_points,
            position_unrealised_r=unrealised_r,
            position_current_sl=getattr(position, "sl", ""),
            position_new_sl=candidate_sl if candidate_sl is not None else "",
            position_target_tp=getattr(position, "tp", ""),
            position_runner_target_price=runner_target_price,
            position_trail_rule_label=trail_label,
            trade_state_ticket=state.ticket,
            trade_state_setup_family=state.setup_family,
            trade_state_direction=state.direction,
            trade_state_trail_state=state.trail_state,
            message="Position management check completed",
        )

    if candidate_sl is None:
        return

    if not is_sl_improvement(position, candidate_sl):
        return

    result = update_position_sl(
        position=position,
        new_sl=candidate_sl,
        reason=f"Trail rule triggered at {unrealised_r:.2f}R",
        trail_rule_label=trail_label,
    )

    if result is None:
        return

    state.sl_price = float(candidate_sl)
    state.trail_state = trail_label

    register_live_trade_state(
        state=state,
        action="trail_state_updated",
        source="position_management",
    )


def manage_open_positions() -> None:
    if not ENABLE_POSITION_MANAGEMENT:
        log_event(
            "POSITION_MANAGEMENT",
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="disabled",
            message="Position management disabled",
        )
        return

    if mt5 is None or not is_mt5_connected():
        log_event(
            "POSITION_MANAGEMENT",
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="skipped",
            position_management_reason="MT5 unavailable or disconnected",
            message="Position management skipped because MT5 is unavailable or disconnected",
        )
        return

    positions = get_open_bot_positions()

    if not positions:
        log_event(
            "POSITION_MANAGEMENT",
            position_management_enabled=ENABLE_POSITION_MANAGEMENT,
            position_management_action="no_positions",
            open_positions_count=0,
            trade_state_open_count=len(live_trade_states),
            message="No open bot positions to manage",
        )
        return

    for position in positions:
        manage_single_position(position)


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

    manage_open_positions()

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

    sync_live_trade_states_from_positions(
        positions=bot_positions,
        source="mt5_position_sync",
    )

    log_event(
        "HEARTBEAT",
        open_positions_count=len(bot_positions),
        positions_source="mt5",
        trade_state_open_count=len(live_trade_states),
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

# ============================================================
# LIVE TRADE-STATE REGISTRY
# ============================================================

def position_ticket_value(position: Any) -> int | None:
    ticket = getattr(position, "ticket", None)

    if ticket in (None, ""):
        return None

    try:
        return int(ticket)
    except (TypeError, ValueError):
        return None


def position_direction_label(position: Any) -> str:
    position_type = getattr(position, "type", None)

    if mt5 is not None:
        if position_type == mt5.POSITION_TYPE_BUY:
            return "BUY"

        if position_type == mt5.POSITION_TYPE_SELL:
            return "SELL"

    return "UNKNOWN"


def append_trade_state_record(
    action: str,
    state: LiveTradeState,
    source: str,
) -> None:
    record = asdict(state)
    record.update(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "source": source,
            "symbol": SYMBOL,
            "magic_number": MAGIC_NUMBER,
        }
    )

    with TRADE_STATE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def log_trade_state_event(
    action: str,
    state: LiveTradeState,
    source: str,
    message: str,
) -> None:
    log_event(
        "TRADE_STATE",
        signal_time=state.signal_time,
        direction=state.direction,
        setup_family=state.setup_family,
        entry_price=state.entry_price,
        sl_price=state.sl_price,
        tp_price=state.tp_price,
        runner_target_r=state.runner_target_r,
        runner_target_points=state.runner_target_points,
        position_ticket=state.ticket,
        trade_state_action=action,
        trade_state_ticket=state.ticket,
        trade_state_setup_family=state.setup_family,
        trade_state_direction=state.direction,
        trade_state_trail_state=state.trail_state,
        trade_state_source=source,
        trade_state_open_count=len(live_trade_states),
        message=message,
    )


def register_live_trade_state(
    state: LiveTradeState,
    action: str,
    source: str,
) -> LiveTradeState:
    live_trade_states[int(state.ticket)] = state

    append_trade_state_record(
        action=action,
        state=state,
        source=source,
    )

    log_trade_state_event(
        action=action,
        state=state,
        source=source,
        message=f"Live trade state {action}: ticket={state.ticket}",
    )

    return state


def register_live_trade_state_from_fill(
    position: Any,
    signal: TradeSignal,
) -> LiveTradeState | None:
    ticket = position_ticket_value(position)

    if ticket is None:
        log_event(
            "CRITICAL",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            message="Could not register trade state because position ticket is missing",
        )
        return None

    state = LiveTradeState(
        ticket=ticket,
        setup_family=signal.setup_family,
        direction=signal.direction,
        entry_price=float(getattr(position, "price_open", signal.entry_price) or signal.entry_price),
        sl_price=float(getattr(position, "sl", signal.sl_price) or signal.sl_price),
        tp_price=float(getattr(position, "tp", signal.tp_price) or signal.tp_price),
        runner_target_r=float(signal.runner_target_r),
        runner_target_points=float(signal.runner_target_points),
        signal_time=signal.signal_time,
        trail_state="OPEN",
    )

    return register_live_trade_state(
        state=state,
        action="registered_from_fill",
        source="order_fill",
    )


def recover_live_trade_state_from_position(
    position: Any,
    source: str = "mt5_position_sync",
) -> LiveTradeState | None:
    ticket = position_ticket_value(position)

    if ticket is None:
        return None

    if ticket in live_trade_states:
        return live_trade_states[ticket]

    direction = position_direction_label(position)

    state = LiveTradeState(
        ticket=ticket,
        setup_family="UNKNOWN",
        direction=direction,
        entry_price=float(getattr(position, "price_open", 0.0) or 0.0),
        sl_price=float(getattr(position, "sl", 0.0) or 0.0),
        tp_price=float(getattr(position, "tp", 0.0) or 0.0),
        runner_target_r=float(RUNNER_TARGET_R),
        runner_target_points=float(RUNNER_TARGET_R) * float(SL_POINTS),
        signal_time="recovered_from_mt5",
        trail_state="RECOVERED",
    )

    return register_live_trade_state(
        state=state,
        action="recovered_from_mt5",
        source=source,
    )


def sync_live_trade_states_from_positions(
    positions: list[Any],
    source: str = "mt5_position_sync",
) -> None:
    for position in positions:
        recover_live_trade_state_from_position(
            position=position,
            source=source,
        )


def get_live_trade_state_for_position(position: Any) -> LiveTradeState | None:
    ticket = position_ticket_value(position)

    if ticket is None:
        return None

    return live_trade_states.get(ticket)

# ============================================================
# ORDER EXECUTION HELPERS
# ============================================================

def get_order_filling_mode() -> Any:
    require_mt5()

    filling_modes = {
        "IOC": mt5.ORDER_FILLING_IOC,
        "FOK": mt5.ORDER_FILLING_FOK,
        "RETURN": mt5.ORDER_FILLING_RETURN,
    }

    if ORDER_FILLING_MODE not in filling_modes:
        raise ValueError(f"Invalid ORDER_FILLING_MODE: {ORDER_FILLING_MODE}")

    return filling_modes[ORDER_FILLING_MODE]


def get_order_type(direction: str) -> Any:
    require_mt5()

    if direction == "BUY":
        return mt5.ORDER_TYPE_BUY

    if direction == "SELL":
        return mt5.ORDER_TYPE_SELL

    raise ValueError(f"Invalid direction: {direction}")


def get_order_price(direction: str) -> float | None:
    require_mt5()

    tick = mt5.symbol_info_tick(SYMBOL)

    if tick is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ERROR",
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="No MT5 tick data available",
        )

        return None

    if direction == "BUY":
        return float(tick.ask)

    if direction == "SELL":
        return float(tick.bid)

    raise ValueError(f"Invalid direction: {direction}")


def validate_signal_order_inputs(signal: TradeSignal) -> tuple[bool, str]:
    if not mt5_available():
        return False, "MetaTrader5 package is not installed"

    if not is_mt5_connected():
        return False, "MT5 is not connected"

    if LOT_SIZE <= 0:
        return False, "LOT_SIZE must be > 0"

    if signal.direction not in {"BUY", "SELL"}:
        return False, f"Invalid signal direction: {signal.direction}"

    if signal.sl_price <= 0:
        return False, "SL price must be > 0"

    if signal.tp_price <= 0:
        return False, "TP price must be > 0"

    if signal.direction == "BUY":
        if not signal.sl_price < signal.entry_price < signal.tp_price:
            return False, "Invalid BUY SL/entry/TP ordering"

    if signal.direction == "SELL":
        if not signal.tp_price < signal.entry_price < signal.sl_price:
            return False, "Invalid SELL TP/entry/SL ordering"

    return True, "Order inputs valid"


def find_position_by_order_result(result: Any) -> Any | None:
    if mt5 is None:
        return None

    positions = get_open_bot_positions()

    result_position_ticket = getattr(result, "position", 0)
    result_order_ticket = getattr(result, "order", 0)

    for position in positions:
        position_ticket = getattr(position, "ticket", None)
        position_identifier = getattr(position, "identifier", None)

        if result_position_ticket and position_ticket == result_position_ticket:
            return position

        if result_position_ticket and position_identifier == result_position_ticket:
            return position

        if result_order_ticket and position_ticket == result_order_ticket:
            return position

    if len(positions) == 1:
        return positions[0]

    return None


def close_position_immediately(position: Any, reason: str) -> Any | None:
    require_mt5()

    position_type = getattr(position, "type", None)
    position_volume = float(getattr(position, "volume", 0.0) or 0.0)
    position_ticket = getattr(position, "ticket", None)

    if position_volume <= 0:
        log_event(
            "CRITICAL",
            position_ticket=position_ticket,
            close_reason=reason,
            message="Cannot close position because volume is invalid",
        )
        return None

    if position_type == mt5.POSITION_TYPE_BUY:
        close_direction = "SELL"
        close_order_type = mt5.ORDER_TYPE_SELL
        close_price = get_order_price("SELL")

    elif position_type == mt5.POSITION_TYPE_SELL:
        close_direction = "BUY"
        close_order_type = mt5.ORDER_TYPE_BUY
        close_price = get_order_price("BUY")

    else:
        log_event(
            "CRITICAL",
            position_ticket=position_ticket,
            close_reason=reason,
            message="Cannot close position because type is invalid",
        )
        return None

    if close_price is None:
        return None

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": position_volume,
        "type": close_order_type,
        "position": position_ticket,
        "price": close_price,
        "deviation": ORDER_DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": f"{ORDER_COMMENT}_SAFETY_CLOSE",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": get_order_filling_mode(),
    }

    log_event(
        "CRITICAL",
        direction=close_direction,
        position_ticket=position_ticket,
        order_price=close_price,
        order_volume=position_volume,
        close_reason=reason,
        message="Attempting immediate safety close",
    )

    result = mt5.order_send(request)

    if result is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "CRITICAL",
            position_ticket=position_ticket,
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            close_reason=reason,
            message="Safety close failed: order_send returned None",
        )

        return None

    log_event(
        "POSITION_CLOSED",
        position_ticket=position_ticket,
        retcode=getattr(result, "retcode", ""),
        close_reason=reason,
        message="Safety close order sent",
    )

    return result


def verify_filled_position_has_sl_tp(position: Any, signal: TradeSignal) -> bool:
    position_sl = float(getattr(position, "sl", 0.0) or 0.0)
    position_tp = float(getattr(position, "tp", 0.0) or 0.0)
    position_ticket = getattr(position, "ticket", "")

    has_sl = position_sl != 0.0
    has_tp = position_tp != 0.0

    if has_sl and has_tp:
        log_event(
            "HEARTBEAT",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            position_ticket=position_ticket,
            position_sl=position_sl,
            position_tp=position_tp,
            message="Filled position has SL and TP attached",
        )

        return True

    log_event(
        "CRITICAL",
        signal_time=signal.signal_time,
        direction=signal.direction,
        setup_family=signal.setup_family,
        position_ticket=position_ticket,
        position_sl=position_sl,
        position_tp=position_tp,
        block_reason="Filled position missing SL or TP",
        message="Filled position missing SL or TP",
    )

    if CLOSE_IF_SL_MISSING_AFTER_FILL and not has_sl:
        close_position_immediately(
            position,
            reason="Filled position missing SL after order fill",
        )

    return False


def place_trade(signal: TradeSignal) -> Any | None:
    order_inputs_ok, order_inputs_message = validate_signal_order_inputs(signal)

    if not order_inputs_ok:
        log_event(
            "ORDER_REJECTED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            entry_price=signal.entry_price,
            sl_price=signal.sl_price,
            tp_price=signal.tp_price,
            runner_target_r=signal.runner_target_r,
            runner_target_points=signal.runner_target_points,
            decision="blocked",
            block_reason=order_inputs_message,
            message=order_inputs_message,
        )

        return None

    order_type = get_order_type(signal.direction)
    price = get_order_price(signal.direction)

    if price is None:
        log_event(
            "ORDER_REJECTED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            decision="blocked",
            block_reason="No executable order price available",
            message="No executable order price available",
        )

        return None

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "sl": signal.sl_price,
        "tp": signal.tp_price,
        "deviation": ORDER_DEVIATION_POINTS,
        "magic": MAGIC_NUMBER,
        "comment": ORDER_COMMENT,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": get_order_filling_mode(),
    }

    log_event(
        "ORDER_ATTEMPT",
        signal_time=signal.signal_time,
        direction=signal.direction,
        setup_family=signal.setup_family,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
        tp_price=signal.tp_price,
        runner_target_r=signal.runner_target_r,
        runner_target_points=signal.runner_target_points,
        order_type=signal.direction,
        order_price=price,
        order_volume=LOT_SIZE,
        order_comment=ORDER_COMMENT,
        message="Sending MT5 order",
    )

    result = mt5.order_send(request)

    if result is None:
        error_code, error_message = get_mt5_last_error()

        log_event(
            "ORDER_REJECTED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            mt5_error_code=error_code,
            mt5_error_message=error_message,
            message="order_send returned None",
        )

        return None

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        log_event(
            "ORDER_REJECTED",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            retcode=result.retcode,
            message=str(result),
        )

        return None

    log_event(
        "ORDER_FILLED",
        signal_time=signal.signal_time,
        direction=signal.direction,
        setup_family=signal.setup_family,
        entry_price=signal.entry_price,
        sl_price=signal.sl_price,
        tp_price=signal.tp_price,
        runner_target_r=signal.runner_target_r,
        runner_target_points=signal.runner_target_points,
        order_ticket=getattr(result, "order", ""),
        position_ticket=getattr(result, "position", ""),
        retcode=result.retcode,
        message="Order filled",
    )

    filled_position = find_position_by_order_result(result)

    if filled_position is None:
        log_event(
            "CRITICAL",
            signal_time=signal.signal_time,
            direction=signal.direction,
            setup_family=signal.setup_family,
            order_ticket=getattr(result, "order", ""),
            position_ticket=getattr(result, "position", ""),
            message="Order filled but matching position could not be confirmed",
        )

        return result

    verify_filled_position_has_sl_tp(filled_position, signal)

    register_live_trade_state_from_fill(
        position=filled_position,
        signal=signal,
    )

    return result


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

    if REQUIRE_SRC_FEATURE_ENGINE and not USE_SRC_FEATURE_ENGINE:
        raise ValueError(
            "REQUIRE_SRC_FEATURE_ENGINE cannot be True when USE_SRC_FEATURE_ENGINE is False"
        )
    
    required_automation_keys = [
        "shift_lookback",
        "acceptance_lookback",
        "compression_lookback",
        "flat_vwap_lookback",
        "vwap_cross_lookback",
        "v2_trend_health_lookback",
        "v3_min_directional_red_shift_points",
        "v4_realised_range_lookback",
        "v5_red_shift_relative_lookback_bars",
    ]

    missing_automation_keys = [
        key
        for key in required_automation_keys
        if key not in AUTOMATION_FEATURE_CONFIG
    ]

    if missing_automation_keys:
        raise ValueError(
            "Missing automation feature config keys: "
            + ", ".join(missing_automation_keys)
        )
    
    if LOG_RAW_CONTINUATION_CANDIDATES and not ENABLE_RAW_CONTINUATION_CANDIDATES:
        print("")
        print("WARNING: LOG_RAW_CONTINUATION_CANDIDATES is True but raw candidate detection is disabled.")
        print("")

    if ENABLE_SETUP_CLASSIFICATION and not ENABLE_RAW_CONTINUATION_CANDIDATES:
        raise ValueError(
            "ENABLE_SETUP_CLASSIFICATION requires ENABLE_RAW_CONTINUATION_CANDIDATES"
        )

    invalid_setup_priority = [
        setup_family
        for setup_family in SETUP_CLASSIFICATION_PRIORITY
        if setup_family not in SETUP_PROFILES
    ]

    if invalid_setup_priority:
        raise ValueError(
            "Invalid setup family in SETUP_CLASSIFICATION_PRIORITY: "
            + ", ".join(invalid_setup_priority)
        )
    
    if ENABLE_CONTINUATION_SIGNAL_PROMOTION and not ENABLE_SETUP_CLASSIFICATION:
        raise ValueError(
            "ENABLE_CONTINUATION_SIGNAL_PROMOTION requires ENABLE_SETUP_CLASSIFICATION"
        )

    if CONTINUATION_SIGNAL_SELECTION_MODE not in {
        "priority_first",
        "strongest_red_shift",
    }:
        raise ValueError(
            "CONTINUATION_SIGNAL_SELECTION_MODE must be one of: "
            "priority_first, strongest_red_shift"
        )
    
    if not isinstance(CONTINUATION_BLOCKED_REGIMES, set):
        raise ValueError("CONTINUATION_BLOCKED_REGIMES must be a set")

    if LOG_REGIME_ROUTER_DECISIONS and not ENABLE_REGIME_ROUTER:
        print("")
        print("WARNING: LOG_REGIME_ROUTER_DECISIONS is True but ENABLE_REGIME_ROUTER is False.")
        print("")

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
    
    if MIN_SL_UPDATE_DISTANCE_POINTS < 0:
        raise ValueError("MIN_SL_UPDATE_DISTANCE_POINTS must be >= 0")

    if REQUIRE_TRADE_STATE_FOR_POSITION_MANAGEMENT and not ENABLE_POSITION_MANAGEMENT:
        pass
    
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
    
    if ORDER_DEVIATION_POINTS < 0:
        raise ValueError("ORDER_DEVIATION_POINTS must be >= 0")

    if ORDER_FILLING_MODE not in {"IOC", "FOK", "RETURN"}:
        raise ValueError("ORDER_FILLING_MODE must be one of: IOC, FOK, RETURN")

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

        trend_health_after_time = rule.get("trend_health_after_time")

        if trend_health_after_time is not None:
            parse_hhmm_time(
                trend_health_after_time,
                f"{setup_family}.trend_health_after_time",
            )

        trend_health_after_timezone = rule.get("trend_health_after_timezone")

        if trend_health_after_timezone is not None:
            get_timezone(trend_health_after_timezone)
        
    if USE_SRC_FEATURE_ENGINE and CONNECT_MT5_ON_STARTUP:
        import_src_feature_engine()

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
    print(f"- Use src feature engine: {USE_SRC_FEATURE_ENGINE}")
    print(f"- Reload src modules on startup: {RELOAD_SRC_MODULES_ON_STARTUP}")
    print(f"- Require src feature engine: {REQUIRE_SRC_FEATURE_ENGINE}")
    print(f"- Enable raw continuation candidates: {ENABLE_RAW_CONTINUATION_CANDIDATES}")
    print(f"- Log raw continuation candidates: {LOG_RAW_CONTINUATION_CANDIDATES}")
    print(f"- Enable setup classification: {ENABLE_SETUP_CLASSIFICATION}")
    print(f"- Log setup classification: {LOG_SETUP_CLASSIFICATION}")
    print(f"- Setup classification priority: {SETUP_CLASSIFICATION_PRIORITY}")
    print(f"- Enable continuation signal promotion: {ENABLE_CONTINUATION_SIGNAL_PROMOTION}")
    print(f"- Log selected continuation signal: {LOG_SELECTED_CONTINUATION_SIGNAL}")
    print(f"- Continuation signal selection mode: {CONTINUATION_SIGNAL_SELECTION_MODE}")
    print(f"- Log regime-router decisions: {LOG_REGIME_ROUTER_DECISIONS}")
    print(f"- Continuation blocked regimes: {sorted(CONTINUATION_BLOCKED_REGIMES)}")
    print(f"- Router bypass rules enabled: {[k for k, v in ROUTER_BYPASS_RULES.items() if v.get('enabled', False)]}")
    print(f"- Order deviation points: {ORDER_DEVIATION_POINTS}")
    print(f"- Order filling mode: {ORDER_FILLING_MODE}")
    print(f"- Close if SL missing after fill: {CLOSE_IF_SL_MISSING_AFTER_FILL}")
    print(f"- Event log path: {EVENT_LOG_PATH}")
    print(f"- Trade state log path: {TRADE_STATE_LOG_PATH}")
    print(f"- Position management enabled: {ENABLE_POSITION_MANAGEMENT}")
    print(f"- Log position management decisions: {LOG_POSITION_MANAGEMENT_DECISIONS}")
    print(f"- Minimum SL update distance points: {MIN_SL_UPDATE_DISTANCE_POINTS}")
    print(
        "- Require trade state for position management: "
        f"{REQUIRE_TRADE_STATE_FOR_POSITION_MANAGEMENT}"
    )
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