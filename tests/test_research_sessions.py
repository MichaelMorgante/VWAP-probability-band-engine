import unittest

import pandas as pd

from src.research_sessions import (
    validate_timestamp_index,
    classify_research_split,
    summarise_daily_coverage,
    assess_windows,
)


class TestResearchSessions(unittest.TestCase):

    def setUp(self):

        self.timestamps = pd.date_range(
            "2025-01-06 12:00",
            periods=600,
            freq="min",
            tz="UTC",
        )

    def make_window(self, start, end):

        return pd.DataFrame({
            "start": [pd.Timestamp(start)],
            "end": [pd.Timestamp(end)],
        })

    def test_arbitrary_complete_windows(self):

        for duration in [15, 60, 120, 300]:

            with self.subTest(duration=duration):

                start = self.timestamps[0]

                end = start + pd.Timedelta(
                    minutes=duration
                )

                result = assess_windows(
                    self.timestamps,
                    self.make_window(start, end),
                ).iloc[0]

                self.assertTrue(result["complete"])

                self.assertEqual(
                    result["observed_minutes"],
                    duration,
                )

    def test_missing_observation(self):

        timestamps = self.timestamps.delete(10)

        start = timestamps[0]

        end = start + pd.Timedelta(minutes=60)

        result = assess_windows(
            timestamps,
            self.make_window(start, end),
        ).iloc[0]

        self.assertFalse(result["complete"])

        self.assertEqual(
            result["missing_minutes"], 1
        )

    def test_half_open_window(self):

        start = self.timestamps[0]

        end = self.timestamps[30]

        result = assess_windows(
            self.timestamps,
            self.make_window(start, end),
        ).iloc[0]

        self.assertEqual(
            result["observed_minutes"], 30
        )

    def test_daily_coverage_without_model_assumptions(self):

        result = summarise_daily_coverage(
            self.timestamps.delete(100),
            "2025-01-06",
            "2025-01-07",
        )

        self.assertEqual(
            result.iloc[0]["observed_minutes"],
            599,
        )

        self.assertEqual(
            result.iloc[0]["internal_unobserved_minutes"],
            1,
        )

        self.assertEqual(
            result.iloc[1]["observed_minutes"],
            0,
        )

        self.assertTrue(
            pd.isna(
                result.iloc[1]["internal_unobserved_minutes"]
            )
        )

    def test_duplicate_timestamps_rejected(self):

        duplicated = self.timestamps.insert(
            0, self.timestamps[0]
        )

        with self.assertRaises(ValueError):
            validate_timestamp_index(duplicated)

    def test_naive_timestamps_rejected(self):

        with self.assertRaises(ValueError):

            validate_timestamp_index(
                self.timestamps.tz_localize(None)
            )

    def test_unordered_timestamps_rejected(self):

        with self.assertRaises(ValueError):
            validate_timestamp_index(
                self.timestamps[::-1]
            )

    def test_chronological_partitions(self):

        expected = {
            "2021-12-31": "unassigned",
            "2022-01-01": "development",
            "2024-12-31": "development",
            "2025-01-01": "known_development",
            "2025-12-31": "known_development",
            "2026-01-01": "validation",
            "2026-06-30": "validation",
            "2026-07-01": "retrospective_holdout",
            "2026-11-28": "unassigned",
        }

        for date, partition in expected.items():

            with self.subTest(date=date):

                self.assertEqual(
                    classify_research_split(date),
                    partition,
                )


if __name__ == "__main__":
    unittest.main()