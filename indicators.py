from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("EMA period must be positive")
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("SMA period must be positive")
    return series.rolling(window=period, min_periods=period).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    high_low = high - low
    high_close = (high - prev_close).abs()
    low_close = (low - prev_close).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.rolling(window=period, min_periods=period).mean()


def bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    ma = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std()
    upper = ma + num_std * std
    lower = ma - num_std * std
    return lower, ma, upper


def bollinger_bandwidth(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    lower, ma, upper = bollinger_bands(close, period=period, num_std=num_std)
    bandwidth = (upper - lower) / ma.replace(0, np.nan)
    return bandwidth


def adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    if period <= 0:
        raise ValueError("ADX period must be positive")

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr = true_range(high, low, close)

    tr_smooth = tr.rolling(window=period, min_periods=period).sum()
    plus_dm_smooth = pd.Series(plus_dm, index=high.index).rolling(window=period, min_periods=period).sum()
    minus_dm_smooth = pd.Series(minus_dm, index=high.index).rolling(window=period, min_periods=period).sum()

    plus_di = 100 * plus_dm_smooth / tr_smooth.replace(0, np.nan)
    minus_di = 100 * minus_dm_smooth / tr_smooth.replace(0, np.nan)

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan) * 100
    adx_series = dx.rolling(window=period, min_periods=period).mean()
    return adx_series

