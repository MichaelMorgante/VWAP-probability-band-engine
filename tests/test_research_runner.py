from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

from src.config import CONFIG
from src.engine import EngineState, update_engine_state
from src.replay import run_replay
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

    def test_existing_replay_engine_parity(self):

        candles = self.candles.copy()

        # Introduce non-uniform volume and asymmetric
        # candles to exercise the weighted calculations.
        candles["tick_volume"] = (
            100 + 10 * np.arange(len(candles))
        )

        candles["high"] += (
            np.arange(len(candles)) % 5
        )

        config = deepcopy(self.config)

        config["vwap_anchor_utc"] = self.anchor

        reconstructed = run_historical_session(
            candles,
            config,
            anchor_utc=self.anchor,
        )

        empty_table = pd.DataFrame(
            columns=["zone"]
        )

        replay = run_replay(
            candles,
            deepcopy(config),
            empty_table,
            EngineState=EngineState,
            update_engine_state=update_engine_state,
            speed=100_000.0,
        )

        replay_count = 0

        for i, state in enumerate(replay):

            row = reconstructed.iloc[i]

            self.assertEqual(
                row["datetime"],
                state.datetime,
            )

            for field in [
                "close",
                "reference",
                "sigma",
                "z_score",
            ]:

                self.assertAlmostEqual(
                    row[field],
                    getattr(state, field),
                    places=9,
                )

            self.assertEqual(
                row["session_bar_count"],
                state.session_bar_count,
            )

            self.assertEqual(
                row["ghost_ready"],
                state.ghost_distribution is not None,
            )

            for key, value in state.bands.items():

                self.assertAlmostEqual(
                    row[f"solid_{key}"],
                    value,
                    places=9,
                )

                if key in state.ghost_bands:

                    self.assertAlmostEqual(
                        row[f"ghost_{key}"],
                        state.ghost_bands[key],
                        places=9,
                    )

                else:

                    self.assertTrue(
                        pd.isna(row[f"ghost_{key}"])
                    )

            if state.ghost_distribution is not None:

                self.assertAlmostEqual(
                    row["ghost_sigma"],
                    state.ghost_distribution.stdev,
                    places=9,
                )

            replay_count += 1

        self.assertEqual(
            replay_count,
            len(reconstructed),
        )

    def test_deterministic_reconstruction(self):

        first = self.run_session()

        second = self.run_session()

        pd.testing.assert_frame_equal(
            first,
            second,
            check_exact=True,
        )

    def test_truncation_invariance(self):

        full = self.run_session()

        anchor_position = int(
            self.candles.index[
                self.candles["datetime"].eq(
                    self.anchor
                )
            ][0]
        )

        checkpoints = [
            anchor_position + 1,
            anchor_position + 10,
            len(self.candles) - 5,
        ]

        for end in checkpoints:

            with self.subTest(end=end):

                truncated = run_historical_session(
                    self.candles.iloc[:end].copy(),
                    self.config,
                    anchor_utc=self.anchor,
                )

                pd.testing.assert_frame_equal(
                    full.iloc[:end].reset_index(
                        drop=True
                    ),
                    truncated.reset_index(
                        drop=True
                    ),
                    check_exact=True,
                    check_dtype=False,
                )

    def test_current_and_future_candle_perturbation(self):

        original = self.run_session()

        altered_candles = self.candles.copy()

        shock_index = 40

        price_columns = [
            "open",
            "high",
            "low",
            "close",
        ]

        altered_candles.loc[
            shock_index:,
            price_columns,
        ] += 500.0

        altered = run_historical_session(
            altered_candles,
            self.config,
            anchor_utc=self.anchor,
        )

        # Every historical observation before the
        # artificial shock must remain identical.
        pd.testing.assert_frame_equal(
            original.iloc[:shock_index],
            altered.iloc[:shock_index],
            check_exact=True,
        )

        prior_columns = [
            column
            for column in original.columns
            if column.startswith("prior_")
        ]

        # The shock candle cannot influence the
        # estimates that existed before it.
        pd.testing.assert_series_equal(
            original.loc[
                shock_index,
                prior_columns,
            ],
            altered.loc[
                shock_index,
                prior_columns,
            ],
            check_exact=True,
        )

        # The updated state should respond to the shock.
        self.assertNotEqual(
            original.loc[shock_index, "reference"],
            altered.loc[shock_index, "reference"],
        )

        self.assertNotEqual(
            original.loc[shock_index, "sigma"],
            altered.loc[shock_index, "sigma"],
        )

    def test_independent_mathematical_verification(self):

        candles = self.candles.copy()

        candles["tick_volume"] = (
            100 + 10 * np.arange(len(candles))
        )

        candles["high"] += (
            np.arange(len(candles)) % 5
        )

        result = run_historical_session(
            candles,
            self.config,
            anchor_utc=self.anchor,
        )

        typical = (
            candles["high"]
            + candles["low"]
            + candles["close"]
        ) / 3.0

        volume = candles["tick_volume"]

        post_anchor = candles["datetime"].ge(
            self.anchor
        )

        # Independent cumulative weighted VWAP,
        # with separate pre-anchor and post-anchor
        # accumulation.
        expected_reference = (
            (typical * volume)
            .groupby(post_anchor)
            .cumsum()
            / volume.groupby(post_anchor).cumsum()
        )

        np.testing.assert_allclose(
            result["reference"],
            expected_reference,
            rtol=1e-10,
            atol=1e-9,
        )

        # Independent EWMA RMS calculation.
        # Dispersion is retained across the anchor.
        squared_deviation = (
            candles["close"] - expected_reference
        ).pow(2)

        expected_variance = squared_deviation.ewm(
            halflife=self.config["ewma_halflife"],
            adjust=False,
        ).mean()

        expected_sigma = np.maximum(
            np.sqrt(expected_variance),
            1e-10,
        )

        np.testing.assert_allclose(
            result["sigma"],
            expected_sigma,
            rtol=1e-10,
            atol=1e-9,
        )

        # Independent Gaussian gap RMS.
        # The anchor candle has no preceding
        # post-anchor VWAP.
        lookback = self.config[
            "ghost_lookback_bars"
        ]

        post_reference = expected_reference.loc[
            post_anchor
        ]

        post_close = candles.loc[
            post_anchor, "close"
        ]

        gaps = post_close - post_reference.shift(1)

        expected_ghost_sigma = np.sqrt(
            gaps.pow(2).rolling(
                window=lookback,
                min_periods=lookback,
            ).mean()
        )

        expected_ghost_sigma = (
            expected_ghost_sigma.where(
                expected_ghost_sigma.gt(0)
            )
        )

        np.testing.assert_allclose(
            result.loc[post_anchor, "ghost_sigma"],
            expected_ghost_sigma,
            rtol=1e-10,
            atol=1e-9,
            equal_nan=True,
        )

if __name__ == "__main__":
    unittest.main()