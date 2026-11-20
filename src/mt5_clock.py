import time


def detect_mt5_timestamp_offset_minutes(symbol: str) -> int:
    """Estimate MT5's raw timestamp offset from the computer's UTC clock.

    Requires an initialised MT5 connection, an active symbol and a synced
    computer clock. A positive result means MT5 timestamps are ahead of UTC.
    """
    import MetaTrader5 as mt5

    deadline = time.monotonic() + 10.0
    previous_tick_ms = None
    previous_offset_minutes = None

    while time.monotonic() < deadline:
        tick = mt5.symbol_info_tick(symbol)
        if tick is not None and tick.time > 0:
            tick_ms = tick.time_msc or tick.time * 1_000
            if previous_tick_ms is not None and tick_ms > previous_tick_ms:
                difference_seconds = tick_ms / 1_000 - time.time()
                offset_minutes = round(difference_seconds / 900) * 15
                residual_seconds = difference_seconds - offset_minutes * 60
                if abs(offset_minutes) <= 14 * 60 and abs(residual_seconds) <= 5:
                    if offset_minutes == previous_offset_minutes:
                        return offset_minutes
                    previous_offset_minutes = offset_minutes
                else:
                    previous_offset_minutes = None
            elif previous_tick_ms is not None and tick_ms < previous_tick_ms:
                previous_offset_minutes = None
            previous_tick_ms = tick_ms

        time.sleep(0.2)

    raise RuntimeError(
        f"Could not verify the MT5 timestamp offset for {symbol}. "
        "Check that the symbol is receiving live ticks and the computer clock is synced."
    )