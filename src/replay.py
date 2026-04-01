import copy
import time
from typing import Iterator


def run_replay(df, config: dict,
               prob_table,
               EngineState=None,
               update_engine_state=None,
               speed: float = 1.0,
               start_idx: int = 0) -> Iterator:
    """
    Generator that yields EngineState one bar at a time — no look-ahead.

    Parameters
    ----------
    df         : normalised OHLCV DataFrame
    config     : CONFIG dictionary
    prob_table : pre-calibrated probability table (must be from separate period)
    speed      : replay speed multiplier (1.0 = real time, 60 = 60x fast)
    start_idx  : bar index to start replay from

    Yields
    ------
    EngineState at each bar

    Usage
    -----
    for state in run_replay(df, CONFIG, prob_table, speed=100):
        print(state.zone, state.probabilities)
        # or update a chart, log to file, etc.
    """
    if EngineState is None:
        raise ValueError("run_replay() requires EngineState")
    if update_engine_state is None:
        raise ValueError("run_replay() requires update_engine_state")

    state = EngineState()
    bar_duration_seconds = 60  # adjust for M5=300, M15=900, H1=3600
    sleep_time = bar_duration_seconds / max(speed, 0.001)

    for i in range(start_idx, len(df)):
        bar = df.iloc[i].to_dict()

        # Engine sees ONLY bars 0..i — no future data
        state = update_engine_state(state, bar, config, prob_table)

        yield copy.copy(state)  # yield a snapshot, not a reference

        if sleep_time > 0.001:
            time.sleep(sleep_time)