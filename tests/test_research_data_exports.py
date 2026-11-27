
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

import pandas as pd

from src.research_data_fetcher import (
    fetch_raw_mt5_candles,
)

from src.research_data_diagnostics import (
    diagnose_acquisition,
    sha256_file,
)

from src.research_data_exports import (
    calendar_year_bounds,
    fetch_calendar_year,
    select_closed_research_candles,
    export_raw_acquisition,
    PROJECT_ROOT,
)


UTC = timezone.utc


def make_candle(timestamp):
    return {
        "time": int(timestamp.timestamp()),
        "open": 20000.0,
        "high": 20005.0,
        "low": 19995.0,
        "close": 20001.0,
        "tick_volume": 0,
        "spread": 190,
        "real_volume": 0,
    }


class TestResearchDataExports(unittest.TestCase):

    def setUp(self):
        self.start = datetime(
            2025, 1, 6, 14, 30, tzinfo=UTC
        )

        self.end = self.start + timedelta(minutes=3)

        self.mt5 = Mock()
        self.mt5.TIMEFRAME_M1 = 1

        self.source = {
            "provider": "MetaTrader5",
            "symbol": "US100.cash",
            "broker_company": "Mock Broker",
            "broker_server": "Mock Server",
        }

    def acquire(self, candles=None):
        if candles is None:
            candles = [make_candle(self.start)]

        self.mt5.copy_rates_range.return_value = candles

        return fetch_raw_mt5_candles(
            self.mt5,
            "US100.cash",
            self.start,
            self.end,
        )

    def test_full_calendar_year(self):
        start, end = calendar_year_bounds(
            2025,
            as_of_utc=datetime(
                2026, 6, 1, tzinfo=UTC
            ),
        )

        self.assertEqual(
            start,
            datetime(2025, 1, 1, tzinfo=UTC),
        )

        self.assertEqual(
            end,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    def test_leap_year(self):
        start, end = calendar_year_bounds(
            2024,
            as_of_utc=datetime(
                2026, 6, 1, tzinfo=UTC
            ),
        )

        self.assertEqual((end - start).days, 366)

    def test_adjacent_years_do_not_overlap(self):
        as_of = datetime(
            2026, 6, 1, tzinfo=UTC
        )

        _, end_2024 = calendar_year_bounds(
            2024, as_of_utc=as_of
        )

        start_2025, _ = calendar_year_bounds(
            2025, as_of_utc=as_of
        )

        self.assertEqual(end_2024, start_2025)

    def test_year_to_date_excludes_current_minute(self):
        start, end = calendar_year_bounds(
            2026,
            as_of_utc=datetime(
                2026, 11, 26, 14, 34, 25,
                tzinfo=UTC,
            ),
        )

        self.assertEqual(
            start,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

        self.assertEqual(
            end,
            datetime(
                2026, 11, 26, 14, 34,
                tzinfo=UTC,
            ),
        )

    def test_future_year_rejected(self):
        with self.assertRaises(ValueError):
            calendar_year_bounds(
                2027,
                as_of_utc=datetime(
                    2026, 6, 1, tzinfo=UTC
                ),
            )

    def test_naive_reference_time_rejected(self):
        with self.assertRaises(ValueError):
            calendar_year_bounds(
                2025,
                as_of_utc=datetime(2026, 6, 1),
            )

    def test_fetch_calendar_year(self):
        self.mt5.copy_rates_range.return_value = [
            make_candle(self.start)
        ]

        result = fetch_calendar_year(
            self.mt5,
            "US100.cash",
            2025,
            chunk_days=366,
        )

        self.assertEqual(result.timeframe, "M1")

        self.assertEqual(
            result.requested_start,
            datetime(2025, 1, 1, tzinfo=UTC),
        )

        self.assertEqual(
            result.requested_end_exclusive,
            datetime(2026, 1, 1, tzinfo=UTC),
        )

        self.mt5.copy_rates_range.assert_called_once()

    def test_incomplete_candle_exclusion(self):
        result = self.acquire([
            make_candle(self.start),
            make_candle(
                self.start + timedelta(minutes=1)
            ),
            make_candle(
                self.start + timedelta(minutes=2)
            ),
        ])

        # Simulated acquisition during the third candle.
        result.started_at_utc = (
            self.start
            + timedelta(minutes=2, seconds=25)
        )

        before = result.candles.copy(deep=True)

        research = select_closed_research_candles(
            result,
            result.candles["datetime"],
            timestamp_evidence="Mock verified timestamps",
        )

        self.assertEqual(len(research), 2)

        self.assertIn(
            "verified_datetime_utc",
            research.columns,
        )

        pd.testing.assert_frame_equal(
            result.candles, before
        )

    def test_timestamp_evidence_required(self):
        result = self.acquire()

        with self.assertRaises(ValueError):
            select_closed_research_candles(
                result,
                result.candles["datetime"],
                timestamp_evidence="",
            )

    def test_naive_verified_timestamps_rejected(self):
        result = self.acquire()

        naive = result.candles[
            "datetime"
        ].dt.tz_localize(None)

        with self.assertRaises(ValueError):
            select_closed_research_candles(
                result,
                naive,
                timestamp_evidence="Mock evidence",
            )

    def test_raw_csv_and_metadata_export(self):
        result = self.acquire([
            make_candle(self.start),
            make_candle(self.start),
        ])

        with TemporaryDirectory() as folder:
            exported = export_raw_acquisition(
                result,
                self.source,
                folder,
                code_version="mock-commit",
                working_tree_dirty=False,
                label="sample",
            )

            csv_path = exported["csv_path"]
            metadata_path = exported["metadata_path"]

            self.assertTrue(csv_path.is_file())
            self.assertTrue(metadata_path.is_file())

            saved = pd.read_csv(
                csv_path,
                float_precision="round_trip",
            )

            self.assertEqual(len(saved), 2)

            self.assertEqual(
                saved["tick_volume"].tolist(),
                [0, 0],
            )

            self.assertEqual(
                saved["mt5_time_raw"].tolist(),
                result.candles["mt5_time_raw"].tolist(),
            )

            metadata = json.loads(
                metadata_path.read_text(
                    encoding="utf-8"
                )
            )

            self.assertEqual(
                metadata["sha256"],
                sha256_file(csv_path),
            )

            self.assertEqual(
                metadata["research_eligibility"],
                "pending_validation",
            )

    def test_existing_dataset_cannot_be_overwritten(self):
        result = self.acquire()

        with TemporaryDirectory() as folder:
            kwargs = {
                "code_version": "mock-commit",
                "working_tree_dirty": False,
                "label": "sample",
            }

            first = export_raw_acquisition(
                result,
                self.source,
                folder,
                **kwargs,
            )

            original_hash = sha256_file(
                first["csv_path"]
            )

            with self.assertRaises(FileExistsError):
                export_raw_acquisition(
                    result,
                    self.source,
                    folder,
                    **kwargs,
                )

            self.assertEqual(
                sha256_file(first["csv_path"]),
                original_hash,
            )

    def test_repository_storage_rejected(self):
        result = self.acquire()

        with self.assertRaises(ValueError):
            export_raw_acquisition(
                result,
                self.source,
                PROJECT_ROOT / "data",
                code_version="mock-commit",
                working_tree_dirty=False,
            )

    def test_failed_export_cleans_new_directory(self):
        result = self.acquire()

        incorrect_source = dict(
            self.source,
            symbol="EURUSD",
        )

        with TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                export_raw_acquisition(
                    result,
                    incorrect_source,
                    folder,
                    code_version="mock-commit",
                    working_tree_dirty=False,
                    label="invalid",
                )

            self.assertFalse(
                (Path(folder) / "invalid").exists()
            )

    def test_invalid_extra_candle_prevents_complete_status(self):
        result = self.acquire([
            make_candle(
                self.start + timedelta(minutes=i)
            )
            for i in range(3)
        ] + [
            make_candle(
                self.start + timedelta(seconds=30)
            )
        ])

        expected = pd.date_range(
            self.start,
            self.end,
            freq="1min",
            inclusive="left",
        )

        report = diagnose_acquisition(
            result,
            expected_minutes=expected,
            timestamp_evidence="Mock verified timestamps",
            coverage_reference="Mock trading schedule",
        )

        self.assertEqual(
            report["chunks"][0][
                "timestamp_coverage_status"
            ],
            "unexpected_observations",
        )


if __name__ == "__main__":
    unittest.main()
