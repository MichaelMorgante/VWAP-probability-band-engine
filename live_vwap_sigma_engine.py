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
from dataclasses import dataclass, asdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pathlib import Path
from typing import Any


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

ALLOW_LIVE_TRADING = False
# False should prevent accidental live-account trading if account type can be detected.
# Demo trading will be allowed once MT5 account checks are added.


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
        message="Live continuation engine skeleton started. Startup/lookback controls loaded. MT5 connection not implemented yet.",
    )


if __name__ == "__main__":
    main()