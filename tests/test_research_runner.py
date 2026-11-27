from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

from src.config import CONFIG
from src.research_runner import run_historical_session


class TestHistoricalResearchRunner(unittest.TestCase):

    def setUp(self):

        timestamps = pd.date_range(
            "2025-01-06 13:00",
            periods=60,
            freq="min",
            tz="UTC",
        )

        prices = 20000.0 + np.arange(60)

        self.candles = pd.DataFrame({
            "datetime": timestamps,
            "open": prices,
            "high": prices + 1,
            "low": prices - 1,
            "close": prices,
            "tick_volume": np.full(60, 100),
        })

        self.config = deepcopy(CONFIG)

        self.anchor = timestamps[10]

    def run_session(self):

        return run_historical_session(
            self.candles,
            self.config,
            anchor_utc=self.anchor,
        )

    def test_one_observation_per_candle(self):

        result = self.run_session()

        self.assertEqual(
            len(result),
            len(self.candles),
        )

        self.assertEqual(
            result["datetime"].tolist(),
            self.candles["datetime"].tolist(),
        )

    def test_configuration_is_not_modified(self):

        original = deepcopy(self.config)

        self.run_session()

        self.assertEqual(
            self.config,
            original,
        )

    def test_vwap_resets_at_anchor(self):

        result = self.run_session()

        anchor_row = result.loc[
            result["datetime"].eq(self.anchor)
        ].iloc[0]

        self.assertAlmostEqual(
            anchor_row["reference"],
            self.candles.iloc[10]["close"],
        )

        self.assertEqual(
            anchor_row["session_bar_count"],
            1,
        )

        self.assertFalse(
            anchor_row["ghost_ready"]
        )

    def test_post_anchor_weighted_reference(self):

        result = self.run_session()

        post_anchor = self.candles.iloc[10:]

        typical_price = (
            post_anchor["high"]
            + post_anchor["low"]
            + post_anchor["close"]
        ) / 3

        expected = np.average(
            typical_price,
            weights=post_anchor["tick_volume"],
        )

        self.assertAlmostEqual(
            result.iloc[-1]["reference"],
            expected,
        )

    def test_missing_minutes_rejected(self):

        with self.assertRaises(ValueError):

            run_historical_session(
                self.candles.drop(index=5),
                self.config,
                anchor_utc=self.anchor,
            )

    def test_unavailable_anchor_rejected(self):

        with self.assertRaises(ValueError):

            run_historical_session(
                self.candles,
                self.config,
                anchor_utc=(
                    self.anchor
                    - pd.Timedelta(hours=5)
                ),
            )

    def test_state_availability_after_candle_close(self):

        result = self.run_session()

        self.assertTrue(
            (
                result["available_at_utc"]
                == result["datetime"]
                + pd.Timedelta(minutes=1)
            ).all()
        )


    def test_first_candle_has_no_prior_state(self):

        result = self.run_session()

        first = result.iloc[0]

        self.assertFalse(first["prior_exists"])
        self.assertFalse(first["prior_ghost_ready"])

        self.assertTrue(
            pd.isna(first["prior_reference"])
        )

        self.assertTrue(
            pd.isna(first["prior_available_at_utc"])
        )

    def test_prior_matches_previous_updated_state(self):

        result = self.run_session()

        columns = [
            column
            for column in result.columns
            if f"prior_{column}" in result.columns
        ]

        for column in columns:

            with self.subTest(column=column):

                pd.testing.assert_series_equal(
                    result[f"prior_{column}"]
                    .iloc[1:]
                    .reset_index(drop=True),

                    result[column]
                    .iloc[:-1]
                    .reset_index(drop=True),

                    check_names=False,
                    check_dtype=False,
                )

    def test_prior_state_available_at_candle_open(self):

        result = self.run_session()

        valid = result.loc[
            result["prior_exists"]
        ]

        self.assertTrue(
            (
                valid["prior_available_at_utc"]
                == valid["datetime"]
            ).all()
        )

    def test_anchor_and_gaussian_readiness(self):

        # Arbitrary synthetic test parameter.
        # This is not a research model default.
        self.config["ghost_lookback_bars"] = 4

        result = self.run_session()

        anchor_index = result.index[
            result["datetime"].eq(self.anchor)
        ][0]

        anchor_row = result.loc[anchor_index]

        # The previous warmup state exists, but belongs
        # to the pre-anchor reference.
        self.assertTrue(
            anchor_row["prior_exists"]
        )

        self.assertFalse(
            anchor_row["prior_is_post_anchor"]
        )

        self.assertTrue(
            anchor_row["prior_ghost_ready"]
        )

        self.assertFalse(
            anchor_row["ghost_ready"]
        )

        lookback = self.config[
            "ghost_lookback_bars"
        ]

        first_ready = anchor_index + lookback

        self.assertFalse(
            result.loc[first_ready - 1, "ghost_ready"]
        )

        self.assertTrue(
            result.loc[first_ready, "ghost_ready"]
        )

        self.assertFalse(
            result.loc[first_ready, "prior_ghost_ready"]
        )

        self.assertTrue(
            result.loc[first_ready + 1, "prior_ghost_ready"]
        )

    def test_disabled_gaussian_preserves_schema(self):

        self.config["ghost_lookback_bars"] = 0

        result = self.run_session()

        self.assertFalse(
            result["ghost_ready"].any()
        )

        self.assertFalse(
            result["prior_ghost_ready"].any()
        )

        ghost_columns = [
            column
            for column in result.columns
            if column.startswith("ghost_")
            and column.endswith(("+", "-"))
        ]

        self.assertTrue(ghost_columns)

        for column in ghost_columns:

            self.assertTrue(
                result[column].isna().all()
            )

            self.assertTrue(
                result[f"prior_{column}"].isna().all()
            )

if __name__ == "__main__":
    unittest.main()