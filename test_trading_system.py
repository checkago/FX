from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from engine import EngineConfig, run_trading_engine_for_symbol
from indicators import adx, atr, bollinger_bandwidth, bollinger_bands, ema, sma
from regime_detection import MarketRegime, RegimeConfig, detect_regime
from risk_management import PositionSizingConfig, calculate_position_size, correlation_filter
from strategy_selection import SignalType, StrategyConfig, TradeSignal, generate_signals


class IndicatorsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        idx = pd.date_range("2020-01-01", periods=100, freq="D")
        self.close = pd.Series(np.linspace(1.0, 2.0, 100), index=idx)
        self.high = self.close + 0.01
        self.low = self.close - 0.01

    def test_sma_basic(self) -> None:
        period = 10
        result = sma(self.close, period)
        self.assertTrue(result.isna().sum() >= period - 1)
        self.assertAlmostEqual(result.iloc[-1], self.close.iloc[-period:].mean(), places=10)

    def test_ema_monotonic(self) -> None:
        period = 10
        result = ema(self.close, period)
        self.assertFalse(result.isna().all())
        self.assertGreater(result.iloc[-1], result.dropna().iloc[0])

    def test_atr_positive(self) -> None:
        result = atr(self.high, self.low, self.close, period=14)
        self.assertTrue((result.dropna() > 0).all())

    def test_bollinger_bandwidth_behavior(self) -> None:
        low_vol = self.close.rolling(20).mean()
        low_vol.iloc[-20:] = 1.5
        bb_width = bollinger_bandwidth(low_vol, period=20)
        self.assertTrue((bb_width.dropna() >= 0).all())

    def test_adx_range(self) -> None:
        result = adx(self.high, self.low, self.close, period=14)
        res = result.dropna()
        self.assertTrue(((res >= 0) & (res <= 100)).all())


class RegimeDetectionTestCase(unittest.TestCase):
    def test_detect_regime_outputs_enum_series(self) -> None:
        idx = pd.date_range("2020-01-01", periods=200, freq="D")
        price = pd.Series(1.2 + 0.001 * np.arange(200), index=idx)
        high = price + 0.01
        low = price - 0.01

        config = RegimeConfig()
        regime = detect_regime(high, low, price, config)

        self.assertEqual(len(regime), len(price))
        self.assertTrue(all(isinstance(r, MarketRegime) for r in regime.dropna()))


class RiskManagementTestCase(unittest.TestCase):
    def test_position_size_positive(self) -> None:
        cfg = PositionSizingConfig(risk_per_trade=0.01, atr_multiplier=2.0, value_per_point=1.0)
        size = calculate_position_size(
            entry_price=1.2,
            atr_value=0.001,
            account_equity=10_000,
            is_long=True,
            config=cfg,
        )
        self.assertGreater(size, 0.0)

    def test_correlation_filter_limits(self) -> None:
        idx = pd.date_range("2020-01-01", periods=50, freq="D")
        data = {
            "EURUSD": np.random.normal(0, 0.001, size=50),
            "GBPUSD": np.random.normal(0, 0.001, size=50),
        }
        returns_df = pd.DataFrame(data, index=idx)
        existing_exposure = pd.Series({"EURUSD": 0.5})

        factor = correlation_filter(returns_df, "GBPUSD", existing_exposure, max_correlation=0.0)
        self.assertGreaterEqual(factor, 0.0)
        self.assertLessEqual(factor, 1.0)


class StrategySelectionTestCase(unittest.TestCase):
    def test_generate_signals_types(self) -> None:
        idx = pd.date_range("2020-01-01", periods=120, freq="D")
        close = pd.Series(1.2 + 0.001 * np.arange(120), index=idx)
        high = close + 0.01
        low = close - 0.01

        regime = pd.Series(MarketRegime.MEAN_REVERSION, index=idx)
        config = StrategyConfig()
        signals = generate_signals(high, low, close, regime, config)

        self.assertEqual(len(signals), len(close))
        self.assertTrue(all(isinstance(s, TradeSignal) for s in signals))


class EngineTestCase(unittest.TestCase):
    def test_engine_runs_and_outputs_frame(self) -> None:
        idx = pd.date_range("2020-01-01", periods=150, freq="D")
        close = pd.Series(1.2 + 0.001 * np.arange(150), index=idx)
        high = close + 0.01
        low = close - 0.01
        ohlc = pd.DataFrame({"high": high, "low": low, "close": close})

        returns_df = pd.DataFrame({"EURUSD": close.pct_change().fillna(0.0)}, index=idx)
        existing_exposure = pd.Series({"EURUSD": 0.0})

        cfg = EngineConfig()
        result = run_trading_engine_for_symbol(
            ohlc=ohlc,
            returns_df=returns_df,
            symbol="EURUSD",
            existing_exposure=existing_exposure,
            account_equity=10_000.0,
            config=cfg,
        )

        self.assertEqual(len(result), len(ohlc))
        self.assertIn("signal", result.columns)
        self.assertIn("position_size", result.columns)


if __name__ == "__main__":
    unittest.main()

