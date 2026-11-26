
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pandas as pd

from src.research_data_fetcher import (
    RAW_CANDLE_COLUMNS,
    rates_to_raw_dataframe,
    fetch_raw_mt5_candles,
)


UTC = timezone.utc


def make_candle(timestamp, close=20001.0):
    """Construct a mock native MT5 candle."""
    return {
        "time": int(timestamp.timestamp()),
        "open": 20000.0,
        "high": 20005.0,
        "low": 19995.0,
        "close": close,
        "tick_volume": 0,
        "spread": 190,
        "real_volume": 0,
    }


class TestResearchDataFetcher(unittest.TestCase):

    def setUp(self):
        self.start = datetime(2025, 1, 6, tzinfo=UTC)

        self.mt5 = Mock()
        self.mt5.TIMEFRAME_M1 = 1

    def test_original_fields_preserved(self):
        candle = make_candle(self.start)

        result = rates_to_raw_dataframe([candle])

        self.assertEqual(
            tuple(result.columns),
            RAW_CANDLE_COLUMNS,
        )

        self.assertEqual(
            result.loc[0, "mt5_time_raw"],
            candle["time"],
        )

        self.assertEqual(
            result.loc[0, "datetime"],
            pd.Timestamp(self.start),
        )

        for field in (
            "open", "high", "low", "close",
            "tick_volume", "spread", "real_volume",
        ):
            self.assertEqual(
                result.loc[0, field],
                candle[field],
            )

    def test_conflicting_duplicates_preserved(self):
        first = make_candle(self.start, close=20001.0)
        second = make_candle(self.start, close=20002.0)

        result = rates_to_raw_dataframe([first, second])

        self.assertEqual(len(result), 2)

        self.assertEqual(
            result["mt5_time_raw"].duplicated().sum(),
            1,
        )

        self.assertNotEqual(
            result.loc[0, "close"],
            result.loc[1, "close"],
        )

    def test_chunk_boundaries_and_native_m1(self):
        boundary = self.start + timedelta(days=1)
        end = self.start + timedelta(days=2)

        self.mt5.copy_rates_range.side_effect = [
            [make_candle(self.start)],
            [make_candle(boundary)],
        ]

        result = fetch_raw_mt5_candles(
            self.mt5,
            "US100.cash",
            self.start,
            end,
            chunk_days=1,
        )

        calls = self.mt5.copy_rates_range.call_args_list

        self.assertEqual(len(calls), 2)

        self.assertEqual(
            calls[0].args,
            (
                "US100.cash",
                self.mt5.TIMEFRAME_M1,
                self.start,
                boundary - timedelta(seconds=1),
            ),
        )

        self.assertEqual(
            calls[1].args,
            (
                "US100.cash",
                self.mt5.TIMEFRAME_M1,
                boundary,
                end - timedelta(seconds=1),
            ),
        )

        self.assertEqual(len(result.candles), 2)
        self.assertEqual(result.timeframe, "M1")

        self.assertEqual(
            [chunk.status for chunk in result.chunks],
            ["returned", "returned"],
        )

    def test_empty_and_failed_requests(self):
        end = self.start + timedelta(days=3)

        self.mt5.copy_rates_range.side_effect = [
            [make_candle(self.start)],
            [],
            None,
        ]

        self.mt5.last_error.return_value = (
            -1, "Mock MT5 failure"
        )

        result = fetch_raw_mt5_candles(
            self.mt5,
            "US100.cash",
            self.start,
            end,
            chunk_days=1,
        )

        self.assertEqual(len(result.candles), 1)

        self.assertEqual(
            [chunk.status for chunk in result.chunks],
            ["returned", "empty", "failed"],
        )

        self.assertEqual(
            result.chunks[-1].error,
            (-1, "Mock MT5 failure"),
        )

    def test_naive_timestamps_rejected(self):
        naive_start = self.start.replace(tzinfo=None)

        with self.assertRaises(ValueError):
            fetch_raw_mt5_candles(
                self.mt5,
                "US100.cash",
                naive_start,
                self.start + timedelta(days=1),
            )

        self.mt5.copy_rates_range.assert_not_called()

    def test_invalid_chunk_size_rejected(self):
        with self.assertRaises(ValueError):
            fetch_raw_mt5_candles(
                self.mt5,
                "US100.cash",
                self.start,
                self.start + timedelta(days=1),
                chunk_days=0,
            )

        self.mt5.copy_rates_range.assert_not_called()

    def test_missing_required_fields_rejected(self):
        candle = make_candle(self.start)
        del candle["spread"]

        with self.assertRaises(ValueError):
            rates_to_raw_dataframe([candle])


if __name__ == "__main__":
    unittest.main()
