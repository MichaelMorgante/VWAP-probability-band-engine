from dataclasses import dataclass

@dataclass
class SignalResult:
    """
    The output of the signal layer for one bar.
    Consumed by evaluate_signals(), run_live(), and the MQL5 overlay.
    """
    datetime:        object  = None
    symbol:          str     = ''
    signal_type:     str     = 'NO_SIGNAL'   # MR_LONG, MR_SHORT, CONT_LONG, CONT_SHORT, NO_SIGNAL
    dominant:        str     = 'NEU'
    setup_type:      str     = 'NEUTRAL'
    signal_display:  str     = 'WAIT'
    edge_gap:        float   = 0.0
    edge_gap:        float   = 0.0
    z_score:         float   = 0.0
    z_velocity:      float   = 0.0
    zone:            str     = 'Z0'
    trend_bin:       str     = 'flat'
    bias_display: str = 'NEUTRAL'
    p_mr:            float   = 0.0
    p_cont:          float   = 0.0
    p_neu:           float   = 0.0
    suggested_target_z: float = 0.0    # z-score target (e.g. 0.0 for VWAP return)
    session_bar:     int     = 0
    suppressed_by:   str     = ''      # '' = live signal, else reason for suppression


def generate_signal(state, config: dict) -> SignalResult:
    """
    Convert an EngineState into a typed SignalResult.
    Does NOT apply filters — call apply_filters() after.
    """
    probs    = state.probabilities
    dominant = probs.get('dominant', 'NEU')
    edge_gap = probs.get('edge_gap', 0.0)
    z        = state.z_score

    p_mr   = probs.get('MR',   {}).get('prob', 0.0) if isinstance(probs.get('MR'), dict) else 0.0
    p_cont = probs.get('CONT', {}).get('prob', 0.0) if isinstance(probs.get('CONT'), dict) else 0.0
    p_neu  = probs.get('NEU',  {}).get('prob', 0.0) if isinstance(probs.get('NEU'), dict) else 0.0

    # Determine raw signal type from dominant outcome + z-score sign
    if dominant == 'MR':
        signal_type = 'MR_SHORT' if z > 0 else 'MR_LONG'
        target_z    = 0.0   # mean reversion target is VWAP
    elif dominant == 'CONT':
        signal_type = 'CONT_LONG' if z > 0 else 'CONT_SHORT'
        target_z    = z + (1.0 if z > 0 else -1.0)   # continuation adds 1 sigma
    else:
        signal_type = 'NO_SIGNAL'
        target_z    = 0.0

    setup_type = {
        'MR': 'MR',
        'CONT': 'CONT',
        'NEU': 'NEUTRAL'
    }.get(dominant, 'NEUTRAL')

    signal_display = signal_type if signal_type != 'NO_SIGNAL' else 'WAIT'

    return SignalResult(
        datetime        = state.datetime,
        symbol          = config.get('instrument', ''),
        signal_type     = signal_type,
        dominant        = dominant,
        setup_type=setup_type,
        signal_display  = signal_display,
        edge_gap        = edge_gap,
        z_score         = z,
        z_velocity      = state.z_velocity,
        zone            = state.zone,
        trend_bin       = state.context.get('trend_bin', 'flat'),
        bias_display    = state.context.get('bias_display', 'NEUTRAL'),
        p_mr            = p_mr,
        p_cont          = p_cont,
        p_neu           = p_neu,
        suggested_target_z = target_z,
        session_bar     = state.session_bar_count,
    )


def regime_gate(signal: SignalResult, config: dict) -> SignalResult:
    """
    Suppress signals that conflict with the current directional regime.

    Rules:
    - MR_SHORT only allowed when trend is flat or down
    - MR_LONG  only allowed when trend is flat or up
    - CONT_LONG blocked when trend is clearly down or z_velocity strongly reverses
    - CONT_SHORT blocked when trend is clearly up or z_velocity strongly reverses
    """
    if signal.signal_type == 'NO_SIGNAL':
        return signal

    trend = signal.trend_bin
    bias  = signal.bias_display
    z_vel = signal.z_velocity

    blocked = False
    reason  = ''

    if signal.signal_type == 'MR_SHORT' and trend == 'up':
        blocked = True
        reason  = 'regime_gate: MR_SHORT suppressed, trend=up'

    elif signal.signal_type == 'MR_LONG' and trend == 'down':
        blocked = True
        reason  = 'regime_gate: MR_LONG suppressed, trend=down'

    elif signal.signal_type == 'CONT_LONG':
        # Allow rough continuation long if price bias is bullish,
        # unless trend is clearly bearish or momentum is strongly reversing.
        if trend == 'down' and bias != 'BULLISH':
            blocked = True
            reason  = f'regime_gate: CONT_LONG blocked because trend=down and bias={bias}'
        elif bias == 'BEARISH':
            blocked = True
            reason  = f'regime_gate: CONT_LONG blocked because bias={bias}'
        elif z_vel < -0.20:
            blocked = True
            reason  = f'regime_gate: CONT_LONG blocked because z_vel strongly negative ({z_vel:.2f})'

    elif signal.signal_type == 'CONT_SHORT':
        # Allow rough continuation short if price bias is bearish,
        # unless trend is clearly bullish or momentum is strongly reversing.
        if trend == 'up' and bias != 'BEARISH':
            blocked = True
            reason  = f'regime_gate: CONT_SHORT blocked because trend=up and bias={bias}'
        elif bias == 'BULLISH':
            blocked = True
            reason  = f'regime_gate: CONT_SHORT blocked because bias={bias}'
        elif z_vel > 0.20:
            blocked = True
            reason  = f'regime_gate: CONT_SHORT blocked because z_vel strongly positive ({z_vel:.2f})'

    if blocked:
        signal.signal_type = 'NO_SIGNAL'
        signal.signal_display = 'WAIT'
        signal.suppressed_by = reason
    return signal


def apply_filters(signal: SignalResult, state, config: dict) -> SignalResult:
    """
    Apply minimum quality filters. Suppresses signal if any condition fails.

    Filters:
    1. Edge gap must exceed minimum threshold
    2. Must be past session warmup period
    3. |z_score| must exceed minimum to avoid trading Z0 noise
    4. time_bin must not be dead_hours
    """
    if signal.signal_type == 'NO_SIGNAL':
        return signal

    checks = [
        (signal.edge_gap < config['edge_gap_threshold'],
         f'filter: edge_gap {signal.edge_gap:.2f} < threshold {config["edge_gap_threshold"]}'),

        (signal.session_bar < config['session_warmup_bars'],
         f'filter: session warmup ({signal.session_bar}/{config["session_warmup_bars"]} bars)'),

        (abs(signal.z_score) < config['min_signal_zscore'],
         f'filter: |z| {abs(signal.z_score):.2f} < min {config["min_signal_zscore"]}'),

        #(signal.zone in ('Z0', 'Z1+', 'Z1-'),
        # f'filter: zone {signal.zone} excluded (only Z2/Z3 zones accepted)'),

        (state.context.get('time_bin') == 'dead_hours',
         'filter: dead_hours session segment'),
    ]

    for condition, reason in checks:
        if condition:
            signal.signal_type   = 'NO_SIGNAL'
            signal.signal_display = 'WAIT'
            signal.suppressed_by = reason
            return signal

    return signal