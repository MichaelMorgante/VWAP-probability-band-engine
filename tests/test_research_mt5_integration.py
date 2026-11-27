
import os
import unittest
from datetime import datetime, timezone

from src.research_data_fetcher import (
    fetch_raw_mt5_candles,
    RAW_CANDLE_COLUMNS,
)

from src.research_data_diagnostics import (
    capture_mt5_source,
    diagnose_acquisition,
)


UTC = timezone.utc
SYMBOL = "US100.cash"


@unittest.skipUnless(
    os.environ.get("RUN_MT5_INTEGRATION") == "1",
    "Real MT5 integration tests are disabled.",
)
class TestResearchMT5Integration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import MetaTrader5 as mt5

        cls.mt5 = mt5

        if not mt5.initialize():
            raise RuntimeError(
                f"MT5 connection failed: {mt5.last_error()}"
            )

        cls.addClassCleanup(mt5.shutdown)

        if not mt5.symbol_select(SYMBOL, True):
            raise RuntimeError(
                f"Could not select {SYMBOL}."
            )

        cls.source = capture_mt5_source(
            mt5, SYMBOL
        )

        broker = (
            f"{cls.source['broker_company']} "
            f"{cls.source['broker_server']}"
        )

        if "ftmo" not in broker.lower():
            raise RuntimeError(
                "Connected source is not recognised "
                "as FTMO. Check the MT5 terminal."
            )

        print("\nMT5 SOURCE")
        print(cls.source)

    def test_historical_samples(self):

        sample_dates = [
            (2025, 1, 7),
            (2025, 3, 10),
            (2025, 3, 31),
            (2025, 7, 8),
            (2025, 11, 3),
        ]

        for year, month, day in sample_dates:

            with self.subTest(
                year=year,
                month=month,
                day=day,
            ):
                start = datetime(
                    year, month, day, 12,
                    tzinfo=UTC,
                )

                end = datetime(
                    year, month, day, 18,
                    tzinfo=UTC,
                )

                result = fetch_raw_mt5_candles(
                    self.mt5,
                    SYMBOL,
                    start,
                    end,
                )

                report = diagnose_acquisition(result)

                quality = report["quality"]

                print(
                    f"\nSAMPLE: {start.date()}"
                )

                print(
                    f"Rows: {len(result.candles)}"
                )

                print(
                    f"Request status: "
                    f"{result.chunks[0].status}"
                )

                print(
                    f"Coverage: "
                    f"{report['chunks'][0]}"
                )

                print(f"Quality: {quality}")

                if not result.candles.empty:
                    print(
                        result.candles.head(3)
                        .to_string(index=False)
                    )

                self.assertFalse(
                    result.candles.empty,
                    "Historical sample unavailable.",
                )

                self.assertEqual(
                    tuple(result.candles.columns),
                    RAW_CANDLE_COLUMNS,
                )

                self.assertEqual(
                    result.chunks[0].status,
                    "returned",
                )

                for field in (
                    "invalid_timestamp_rows",
                    "non_minute_aligned_rows",
                    "timestamp_mismatch_rows",
                    "invalid_ohlc_rows",
                    "invalid_volume_spread_rows",
                    "conflicting_timestamps",
                    "backward_timestamp_moves",
                ):
                    self.assertEqual(
                        quality[field],
                        0,
                        f"Data-quality issue: {field}",
                    )

                self.assertEqual(
                    report["chunks"][0][
                        "outside_requested_range_rows"
                    ],
                    0,
                )

                # Do not certify timestamp correctness
                # without independent evidence.
                self.assertEqual(
                    report["timestamp_alignment"],
                    "unverified",
                )


if __name__ == "__main__":
    unittest.main()
