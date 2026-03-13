from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import pandas as pd

from indicators import atr, bollinger_bands
from regime_detection import MarketRegime


class SignalType(Enum):
    NONE = auto()
    LONG = auto()
    SHORT = auto()


@dataclass
class StrategyConfig:
    mr_atr_period: int = 14
    mr_sl_atr_mult: float = 1.3
    mb_atr_period: int = 14
    mb_breakout_lookback: int = 20
    mb_sl_atr_mult: float = 1.0
    mb_tp_atr_mult: float = 2.0


@dataclass
class TradeSignal:
    signal: SignalType
    entry_price: Optional[float]
    stop_price: Optional[float]
    take_profit: Optional[float]


def generate_signals(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    regime: pd.Series,
    config: Optional[StrategyConfig] = None,
) -> pd.Series:
    if config is None:
        config = StrategyConfig()

    lower_bb, ma, upper_bb = bollinger_bands(close)
    atr_mr = atr(high, low, close, period=config.mr_atr_period)
    atr_mb = atr(high, low, close, period=config.mb_atr_period)

    signals = pd.Series(
        [
            TradeSignal(signal=SignalType.NONE, entry_price=None, stop_price=None, take_profit=None)
            for _ in range(len(close))
        ],
        index=close.index,
    )

    rolling_high = high.rolling(window=config.mb_breakout_lookback, min_periods=config.mb_breakout_lookback).max()
    rolling_low = low.rolling(window=config.mb_breakout_lookback, min_periods=config.mb_breakout_lookback).min()

    for idx in range(len(close)):
        price = close.iloc[idx]
        r = regime.iloc[idx]

        if pd.isna(price) or pd.isna(r):
            continue

        if r == MarketRegime.MEAN_REVERSION:
            atr_val = atr_mr.iloc[idx]
            if pd.isna(atr_val):
                continue
            lb = lower_bb.iloc[idx]
            ub = upper_bb.iloc[idx]
            ma_val = ma.iloc[idx]
            if pd.isna(lb) or pd.isna(ub) or pd.isna(ma_val):
                continue
            if price <= lb:
                entry = price
                stop = price - config.mr_sl_atr_mult * atr_val
                tp = ma_val
                signals.iloc[idx] = TradeSignal(
                    signal=SignalType.LONG,
                    entry_price=entry,
                    stop_price=stop,
                    take_profit=tp,
                )
            elif price >= ub:
                entry = price
                stop = price + config.mr_sl_atr_mult * atr_val
                tp = ma_val
                signals.iloc[idx] = TradeSignal(
                    signal=SignalType.SHORT,
                    entry_price=entry,
                    stop_price=stop,
                    take_profit=tp,
                )

        elif r == MarketRegime.MOMENTUM_BREAKOUT:
            atr_val = atr_mb.iloc[idx]
            if pd.isna(atr_val):
                continue
            rh = rolling_high.iloc[idx]
            rl = rolling_low.iloc[idx]
            if pd.isna(rh) or pd.isna(rl):
                continue

            if price > rh:
                entry = price
                stop = price - config.mb_sl_atr_mult * atr_val
                tp = price + config.mb_tp_atr_mult * atr_val
                signals.iloc[idx] = TradeSignal(
                    signal=SignalType.LONG,
                    entry_price=entry,
                    stop_price=stop,
                    take_profit=tp,
                )
            elif price < rl:
                entry = price
                stop = price + config.mb_sl_atr_mult * atr_val
                tp = price - config.mb_tp_atr_mult * atr_val
                signals.iloc[idx] = TradeSignal(
                    signal=SignalType.SHORT,
                    entry_price=entry,
                    stop_price=stop,
                    take_profit=tp,
                )

    return signals

