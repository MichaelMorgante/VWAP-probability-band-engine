
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd

from src.research_data_fetcher import (
    fetch_raw_mt5_candles,
    rates_to_raw_dataframe,
)

from src.research_data_diagnostics import (
    diagnose_raw_candles,
    diagnose_acquisition,
    capture_mt5_source,
    sha256_file,
    build_acquisition_metadata,
    FTMO_US100_DST_DATES,
    ftmo_us100_utc_from_raw,
)


UTC = timezone.utc


def make_candle(timestamp, **overrides):
    candle = {
        "time": int(timestamp.timestamp()),
        "open": 20000.0,
        "high": 20005.0,
        "low": 19995.0,
        "close": 20001.0,
        "tick_volume": 100,
        "spread": 190,
        "real_volume": 0,
    }

    candle.update(overrides)

    return candle


class TestResearchDataDiagnostics(unittest.TestCase):

    def setUp(self):
        self.start = datetime(
            2025, 1, 6, 14, 30, tzinfo=UTC
        )

        self.end = self.start + timedelta(minutes=3)

        self.mt5 = Mock()
        self.mt5.TIMEFRAME_M1 = 1

    def acquire(self, candles):
        self.mt5.copy_rates_range.return_value = candles

        return fetch_raw_mt5_candles(
            self.mt5,
            "US100.cash",
            self.start,
            self.end,
        )

    def expected_minutes(self):
        return pd.date_range(
            self.start,
            self.end,
            freq="1min",
            inclusive="left",
        )

    def test_exact_and_conflicting_duplicates(self):
        first = make_candle(self.start)

        second = make_candle(
            self.start + timedelta(minutes=1)
        )

        conflict = dict(second, close=20002.0)

        df = rates_to_raw_dataframe(
            [first, first.copy(), second, conflict]
        )

        before = df.copy(deep=True)

        report = diagnose_raw_candles(df)

        self.assertEqual(
            report["exact_duplicate_rows"], 1
        )

        self.assertEqual(
            report["conflicting_timestamps"], 1
        )

        self.assertEqual(
            report["conflicting_ohlc_timestamps"], 1
        )

        pd.testing.assert_frame_equal(df, before)

    def test_volume_conflict_is_not_ohlc_conflict(self):
        first = make_candle(self.start)
        second = dict(first, tick_volume=200)

        df = rates_to_raw_dataframe([first, second])

        report = diagnose_raw_candles(df)

        self.assertEqual(
            report["conflicting_timestamps"], 1
        )

        self.assertEqual(
            report["conflicting_ohlc_timestamps"], 0
        )

    def test_invalid_ohlc_volume_and_spread(self):
        df = rates_to_raw_dataframe([
            make_candle(
                self.start,
                high=19990.0,
                tick_volume=-1,
            ),
            make_candle(
                self.start + timedelta(minutes=1),
                close=float("nan"),
                spread=-5,
            ),
            make_candle(
                self.start + timedelta(minutes=2),
                tick_volume=0,
            ),
        ])

        report = diagnose_raw_candles(df)

        self.assertEqual(report["invalid_ohlc_rows"], 2)

        self.assertEqual(
            report["invalid_volume_spread_rows"], 2
        )

        self.assertEqual(
            report["zero_tick_volume_rows"], 1
        )

    def test_timestamp_integrity(self):
        df = rates_to_raw_dataframe([
            make_candle(self.start),
            make_candle(
                self.start + timedelta(seconds=90)
            ),
        ])

        df.loc[0, "datetime"] += pd.Timedelta(
            minutes=1
        )

        report = diagnose_raw_candles(df)

        self.assertEqual(
            report["non_minute_aligned_rows"], 1
        )

        self.assertEqual(
            report["timestamp_mismatch_rows"], 1
        )

    def test_gaps_do_not_imply_missing_market_data(self):
        result = self.acquire([
            make_candle(self.start),
            make_candle(
                self.start + timedelta(minutes=2)
            ),
        ])

        report = diagnose_acquisition(result)

        self.assertEqual(
            report["quality"][
                "intervals_above_one_minute"
            ],
            1,
        )

        self.assertEqual(
            report["chunks"][0][
                "timestamp_coverage_status"
            ],
            "unverified",
        )

        self.assertIsNone(
            report["chunks"][0][
                "missing_expected_minutes"
            ]
        )

    def test_partial_coverage(self):
        result = self.acquire([
            make_candle(self.start),
            make_candle(
                self.start + timedelta(minutes=2)
            ),
        ])

        report = diagnose_acquisition(
            result,
            expected_minutes=self.expected_minutes(),
            timestamp_evidence="Mock verified timestamps",
            coverage_reference="Mock trading schedule",
        )

        chunk = report["chunks"][0]

        self.assertEqual(
            chunk["timestamp_coverage_status"],
            "partial",
        )

        self.assertEqual(
            chunk["missing_expected_minutes"], 1
        )

    def test_complete_coverage(self):
        result = self.acquire([
            make_candle(
                self.start + timedelta(minutes=i)
            )
            for i in range(3)
        ])

        report = diagnose_acquisition(
            result,
            expected_minutes=self.expected_minutes(),
            timestamp_evidence="Mock verified timestamps",
            coverage_reference="Mock trading schedule",
        )

        self.assertEqual(
            report["chunks"][0][
                "timestamp_coverage_status"
            ],
            "complete",
        )

    def test_unverified_schedule_rejected(self):
        result = self.acquire([
            make_candle(self.start)
        ])

        with self.assertRaises(ValueError):
            diagnose_acquisition(
                result,
                expected_minutes=self.expected_minutes(),
            )

    def test_outside_chunk_observations(self):
        result = self.acquire([
            make_candle(self.start),
            make_candle(self.end),
        ])

        report = diagnose_acquisition(result)

        self.assertEqual(
            report["chunks"][0][
                "outside_requested_range_rows"
            ],
            1,
        )

        # Raw data must remain unchanged.
        self.assertEqual(len(result.candles), 2)

    def test_empty_and_failed_chunks(self):
        self.mt5.copy_rates_range.side_effect = [
            [],
            None,
        ]

        self.mt5.last_error.return_value = (
            -1, "Mock failure"
        )

        result = fetch_raw_mt5_candles(
            self.mt5,
            "US100.cash",
            self.start,
            self.start + timedelta(days=2),
            chunk_days=1,
        )

        report = diagnose_acquisition(result)

        self.assertEqual(
            [c["status"] for c in report["chunks"]],
            ["empty", "failed"],
        )

        self.assertEqual(
            report["quality"]["rows"], 0
        )

    def test_source_metadata_excludes_account_id(self):
        self.mt5.account_info.return_value = (
            SimpleNamespace(
                company="Mock Broker",
                server="Mock Server",
                login=123456,
            )
        )

        self.mt5.terminal_info.return_value = (
            SimpleNamespace(
                maxbars=5000000,
                build=5000,
            )
        )

        self.mt5.symbol_info.return_value = (
            SimpleNamespace(
                digits=2,
                point=0.01,
            )
        )

        self.mt5.__version__ = "mock-version"

        source = capture_mt5_source(
            self.mt5, "US100.cash"
        )

        self.assertEqual(
            source["broker_server"], "Mock Server"
        )

        self.assertNotIn("login", source)

    def test_sha256_file(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "sample.txt"

            path.write_bytes(b"abc")

            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223"
                "b00361a396177a9cb410ff61f20015ad",
            )

            original_hash = sha256_file(path)

            path.write_bytes(b"abcd")

            self.assertNotEqual(
                sha256_file(path), original_hash
            )

    def test_metadata_is_json_serializable(self):
        result = self.acquire([
            make_candle(self.start)
        ])

        source = {
            "provider": "MetaTrader5",
            "symbol": "US100.cash",
            "broker_server": "Mock Server",
            "login": 123456,
        }

        with TemporaryDirectory() as folder:
            path = Path(folder) / "sample.csv"

            result.candles.to_csv(path, index=False)

            metadata = build_acquisition_metadata(
                result,
                source,
                path,
                code_version="mock-commit",
                working_tree_dirty=False,
            )

            json.dumps(metadata, allow_nan=False)

            self.assertEqual(
                metadata["sha256"],
                sha256_file(path),
            )

            self.assertEqual(metadata["rows"], 1)

            self.assertNotIn(
                "login", metadata["source"]
            )

            self.assertFalse(
                metadata[
                    "broker_offset_correction_applied"
                ]
            )


class TestFTMOHistoricalTimestamps(unittest.TestCase):

    def raw_seconds(self, timestamps):
        return pd.Series([
            int(pd.Timestamp(t).timestamp())
            for t in timestamps
        ])

    def test_winter_and_summer_conversion(self):
        raw = self.raw_seconds([
            "2025-01-06T16:30:00+00:00",
            "2025-07-07T16:30:00+00:00",
        ])

        corrected = ftmo_us100_utc_from_raw(raw)

        expected = pd.to_datetime([
            "2025-01-06T14:30:00+00:00",
            "2025-07-07T13:30:00+00:00",
        ])

        self.assertEqual(
            corrected.tolist(),
            expected.tolist(),
        )

        ny = corrected.dt.tz_convert(
            "America/New_York"
        )

        self.assertEqual(
            ny.dt.strftime("%H:%M").tolist(),
            ["09:30", "09:30"],
        )

    def test_all_historical_dst_transitions(self):

        for year, dates in FTMO_US100_DST_DATES.items():

            with self.subTest(year=year):

                spring = pd.Timestamp(
                    dates[0],
                    tz="UTC",
                )

                autumn = pd.Timestamp(
                    dates[1],
                    tz="UTC",
                )

                raw = self.raw_seconds([
                    spring - pd.Timedelta(days=2)
                    + pd.Timedelta(hours=16),
                    spring + pd.Timedelta(days=1)
                    + pd.Timedelta(hours=16),
                    autumn - pd.Timedelta(days=2)
                    + pd.Timedelta(hours=16),
                    autumn + pd.Timedelta(days=1)
                    + pd.Timedelta(hours=16),
                ])

                corrected = (
                    ftmo_us100_utc_from_raw(raw)
                )

                decoded = pd.to_datetime(
                    raw,
                    unit="s",
                    utc=True,
                )

                offsets = (
                    decoded - corrected
                ).dt.total_seconds() / 3600

                self.assertEqual(
                    offsets.tolist(),
                    [2, 3, 3, 2],
                )

    def test_raw_timestamps_remain_unchanged(self):
        raw = self.raw_seconds([
            "2025-06-02T16:30:00+00:00",
        ])

        original = raw.copy(deep=True)

        ftmo_us100_utc_from_raw(raw)

        pd.testing.assert_series_equal(
            raw,
            original,
        )

    def test_unsupported_year_rejected(self):
        raw = self.raw_seconds([
            "2021-10-04T16:30:00+00:00",
        ])

        with self.assertRaises(ValueError):
            ftmo_us100_utc_from_raw(raw)

    def test_weekend_timestamp_rejected(self):
        raw = self.raw_seconds([
            "2025-03-09T16:30:00+00:00",
        ])

        with self.assertRaises(ValueError):
            ftmo_us100_utc_from_raw(raw)

    def test_duplicate_timestamps_rejected(self):
        raw = self.raw_seconds([
            "2025-06-02T16:30:00+00:00",
            "2025-06-02T16:30:00+00:00",
        ])

        with self.assertRaises(ValueError):
            ftmo_us100_utc_from_raw(raw)

    def test_non_minute_aligned_timestamp_rejected(self):
        raw = self.raw_seconds([
            "2025-06-02T16:30:15+00:00",
        ])

        with self.assertRaises(ValueError):
            ftmo_us100_utc_from_raw(raw)

if __name__ == "__main__":
    unittest.main()