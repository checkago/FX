from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import pandas as pd

from indicators import adx, atr, bollinger_bandwidth, sma
from config import REGIME_DEFAULTS


class MarketRegime(Enum):
    MEAN_REVERSION = auto()
    MOMENTUM_BREAKOUT = auto()
    NEUTRAL = auto()


@dataclass
class RegimeConfig:
    adx_period: int = 14
    atr_period: int = 14
    bb_period: int = 20
    bb_num_std: float = 2.0
    ma_period: int = 50
    adx_low_threshold: float = REGIME_DEFAULTS["adx_low_threshold"]
    adx_high_threshold: float = REGIME_DEFAULTS["adx_high_threshold"]
    bb_squeeze_lookback: int = REGIME_DEFAULTS["bb_squeeze_lookback"]


def detect_regime(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    config: Optional[RegimeConfig] = None,
) -> pd.Series:
    if config is None:
        config = RegimeConfig()

    adx_series = adx(high, low, close, period=config.adx_period)
    atr_series = atr(high, low, close, period=config.atr_period)
    bb_width = bollinger_bandwidth(close, period=config.bb_period, num_std=config.bb_num_std)
    ma_series = sma(close, period=config.ma_period)

    bb_width_ma = bb_width.rolling(window=config.bb_squeeze_lookback, min_periods=config.bb_squeeze_lookback).mean()
    bb_squeeze = bb_width < bb_width_ma

    regime = pd.Series(MarketRegime.NEUTRAL, index=close.index)

    mean_rev_mask = (
        (adx_series < config.adx_low_threshold)
        & bb_squeeze
        & (close.notna() & ma_series.notna())
        & ((close - ma_series).abs() / ma_series.abs().replace(0, pd.NA) < 0.02)
    )

    breakout_mask = (
        (adx_series > config.adx_high_threshold)
        & ~bb_squeeze
    )

    regime[mean_rev_mask] = MarketRegime.MEAN_REVERSION
    regime[breakout_mask] = MarketRegime.MOMENTUM_BREAKOUT

    regime[atr_series.isna() | adx_series.isna()] = MarketRegime.NEUTRAL

    return regime

