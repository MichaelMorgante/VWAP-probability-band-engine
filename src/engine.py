from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.lookup import lookup_probabilities
from src.zones import classify_zone


@dataclass
class EngineState:
    """
    The complete state of the engine at a single point in time.
    New fields vs original: signal, session_bar_count, z_velocity,
    marginal_table reference for shrinkage lookup.
    """
    datetime:          object = None
    close:             float  = 0.0
    reference:         float  = 0.0
    sigma:             float  = 0.0
    bands:             dict   = field(default_factory=dict)
    z_score:           float  = 0.0
    zone:              str    = 'Z0'
    context:           dict   = field(default_factory=dict)
    probabilities:     dict   = field(default_factory=dict)
    reference_type:    str    = 'VWAP'
    bar_index:         int    = 0

    # New fields
    session_bar_count: int    = 0    # bars since VWAP reset — for warmup guard
    z_velocity:        float  = 0.0  # 5-bar change in z-score

    _cum_pv:           float  = 0.0
    _cum_v:            float  = 0.0
    _ewma_var:         float  = 0.0
    _prev_close:       float  = 0.0
    _session_date:     object = None
    _z_history:        list   = field(default_factory=list)
    _ref_history:      list   = field(default_factory=list)
    _vol_ema:          float  = 0.0


def update_engine_state(state: EngineState, bar: dict,
                        config: dict,
                        prob_table: pd.DataFrame,
                        marginal_table: pd.DataFrame = None) -> EngineState:
    """
    Process one bar and return the updated EngineState.
    marginal_table: the zone-only table used as shrinkage fallback.
                    If None, prob_table is used as both conditioned and marginal.
    """
    if marginal_table is None:
        marginal_table = prob_table

    ts        = bar['datetime']
    close     = bar['close']
    high      = bar['high']
    low       = bar['low']
    volume    = max(bar['tick_volume'], 1.0)
    typ_price = (high + low + close) / 3.0
    session   = bar.get('session_id') or (ts.date() if hasattr(ts, 'date') else ts)

    # ── Session reset ──
# ── Session tracking only: do NOT hard-reset VWAP at session boundary ──
# ── Session tracking only: do NOT hard-reset VWAP at session boundary ──
    if state._session_date is None:
        state._session_date = session
        state.session_bar_count = 0

    state.session_bar_count += 1

    # ── Reference line ──
    ref_type = config['reference_type']
    if ref_type == 'VWAP':
        state._cum_pv += typ_price * volume
        state._cum_v  += volume
        reference = state._cum_pv / state._cum_v
    elif ref_type == 'TWAP':
        state._cum_pv += typ_price
        state._cum_v  += 1
        reference = state._cum_pv / state._cum_v
    else:
        alpha     = 2 / (config['ema_span'] + 1)
        reference = (typ_price * alpha + state.reference * (1 - alpha)
                     if state.bar_index > 0 else typ_price)

    # ── EWMA sigma ──
    deviation = close - reference
    lam       = np.exp(-np.log(2) / config['ewma_halflife'])  # matches pandas ewm(halflife=)
    if state.bar_index == 0:
        state._ewma_var = deviation**2
    else:
        state._ewma_var = (1 - lam) * deviation**2 + lam * state._ewma_var
    sigma = max(np.sqrt(state._ewma_var), 1e-10)

    # ── Z-score and zone ──
    z_score = (close - reference) / sigma
    zone    = classify_zone(z_score, config['zone_thresholds'])

    # ── Z-velocity (5-bar rate of change) ──
    state._z_history.append(z_score)
    z_velocity = z_score - state._z_history[-6] if len(state._z_history) >= 6 else 0.0

    # ── Context ──
    state._ref_history.append(reference)
    k = config['slope_lookback']
    
    trend_threshold = config.get('trend_slope_threshold', 0.08)
    if len(state._ref_history) >= k:
        slope = (reference - state._ref_history[-k]) / (k * sigma)
        trend_bin = 'up' if slope > trend_threshold else ('down' if slope < -trend_threshold else 'flat')
    else:
        trend_bin = 'flat'

    bias_threshold = config.get('bias_z_threshold', 0.50)

    if z_score >= bias_threshold:
        bias_display = 'BULLISH'
    elif z_score <= -bias_threshold:
        bias_display = 'BEARISH'
    else:
        bias_display = 'NEUTRAL'

    vol_alpha      = 2 / (config['volume_ema_span'] + 1)
    state._vol_ema = (volume * vol_alpha + state._vol_ema * (1 - vol_alpha)
                      if state.bar_index > 0 else volume)
    vol_ratio  = volume / max(state._vol_ema, 1.0)
    volume_bin = 'high' if vol_ratio > 1.5 else ('low' if vol_ratio < 0.6 else 'normal')

    hour = ts.hour if hasattr(ts, 'hour') else 12
    if   0 <= hour < 2:   time_bin = 'asian_open'
    elif 2 <= hour < 8:   time_bin = 'asian_mid'
    elif 8 <= hour < 10:  time_bin = 'london_open'
    elif 10 <= hour < 13: time_bin = 'london_mid'
    elif 13 <= hour < 16: time_bin = 'overlap'
    elif 16 <= hour < 19: time_bin = 'ny_open'
    elif 19 <= hour < 21: time_bin = 'ny_close'
    else:                 time_bin = 'sydney'

    # z_velocity_bin for context (used by regime gate)
    if z_velocity > 0.3:
        z_vel_bin = 'extending'
    elif z_velocity < -0.3:
        z_vel_bin = 'reverting'
    else:
        z_vel_bin = 'neutral'

    context = {
        'trend_bin':      trend_bin,
        'volume_bin':     volume_bin,
        'time_bin':       time_bin,
        'z_velocity_bin': z_vel_bin,
        'bias_display': bias_display,
    }

    # ── Probability lookup (new v2 with shrinkage) ──
    probabilities = lookup_probabilities(
        zone, prob_table, marginal_table, context, config
    )

    # ── Update state ──
    state.datetime       = ts
    state.close          = close
    state.reference      = reference
    state.sigma          = sigma
    state.bands          = {f'{k}+': reference + k * sigma for k in [1, 2, 3]}
    state.bands.update(  {f'{k}-': reference - k * sigma for k in [1, 2, 3]})
    state.z_score        = z_score
    state.z_velocity     = z_velocity
    state.zone           = zone
    state.context        = context
    state.probabilities  = probabilities
    state.reference_type = ref_type
    state._prev_close    = close
    state.bar_index     += 1

    return state