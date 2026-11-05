import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from multifactor_backtest import add_multifactor_features, factor_conditions


class MultiFactorFeatureTests(unittest.TestCase):
    def test_factor_direction_rules(self):
        bar = pd.Series({
            "ema20": 110.0, "ema50": 100.0, "rsi14": 60.0,
            "rvol_slot": 1.5, "adx14": 25.0,
        })
        self.assertTrue(factor_conditions(bar, ("trend", "momentum", "volume", "adx"), "LONG"))
        self.assertFalse(factor_conditions(bar, ("trend",), "SHORT"))

        short_bar = pd.Series({
            "ema20": 90.0, "ema50": 100.0, "rsi14": 40.0,
            "rvol_slot": 1.5, "adx14": 25.0,
        })
        self.assertTrue(factor_conditions(short_bar, ("trend", "momentum", "volume", "adx"), "SHORT"))
        self.assertFalse(factor_conditions(short_bar, ("momentum",), "LONG"))

    def test_features_are_sorted_and_have_expected_columns(self):
        stamps = pd.date_range("2026-09-01 09:15", periods=120, freq="5min", tz="Asia/Kolkata")
        close = np.linspace(100, 112, len(stamps))
        frame = pd.DataFrame({
            "timestamp": stamps[::-1],
            "symbol": "TEST",
            "open": close[::-1] - 0.1,
            "high": close[::-1] + 0.3,
            "low": close[::-1] - 0.3,
            "close": close[::-1],
            "volume": np.arange(1, len(stamps) + 1)[::-1] * 100,
        })
        result = add_multifactor_features(frame)
        self.assertTrue(result["timestamp"].is_monotonic_increasing)
        for column in ("ema20", "ema50", "rsi14", "adx14", "atr14", "rvol_slot"):
            self.assertIn(column, result.columns)
        self.assertTrue((result["atr14"].dropna() > 0).all())

    def test_nan_factor_never_passes(self):
        bar = pd.Series({
            "ema20": np.nan, "ema50": 100.0, "rsi14": 60.0,
            "rvol_slot": 1.5, "adx14": 25.0,
        })
        self.assertFalse(factor_conditions(bar, ("trend",), "LONG"))


if __name__ == "__main__":
    unittest.main()
