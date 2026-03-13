from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import logging
import pandas as pd

from config import SESSION_FILTER
from regime_detection import RegimeConfig, detect_regime
from risk_management import PositionSizingConfig, calculate_position_size, correlation_filter
from strategy_selection import StrategyConfig, TradeSignal, generate_signals


logger = logging.getLogger(__name__)


@dataclass
class EngineConfig:
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    position: PositionSizingConfig = field(default_factory=PositionSizingConfig)
    max_correlation: float = 0.8
    fixed_position_size: Optional[float] = None


def run_trading_engine_for_symbol(
    ohlc: pd.DataFrame,
    returns_df: pd.DataFrame,
    symbol: str,
    existing_exposure: pd.Series,
    account_equity: float,
    config: Optional[EngineConfig] = None,
) -> pd.DataFrame:
    if config is None:
        config = EngineConfig()

    logger.info(
        "Engine start for symbol=%s, bars=%d, account_equity=%.2f",
        symbol,
        len(ohlc),
        account_equity,
    )

    high = ohlc["high"]
    low = ohlc["low"]
    close = ohlc["close"]

    regime = detect_regime(high, low, close, config.regime)
    signals = generate_signals(high, low, close, regime, config.strategy)

    size_adjust_factor = correlation_filter(
        returns_df=returns_df,
        current_symbol=symbol,
        existing_exposure=existing_exposure,
        max_correlation=config.max_correlation,
    )
    logger.info("Correlation size adjust factor for %s: %.4f", symbol, size_adjust_factor)

    records: Dict[str, list] = {
        "signal": [],
        "entry_price": [],
        "stop_price": [],
        "take_profit": [],
        "position_size": [],
        "regime": [],
    }

    long_count = 0
    short_count = 0
    prev_regime = None

    for ts, sig in signals.items():
        # фильтр по времени суток и дням недели
        if isinstance(ts, pd.Timestamp):
            hour = ts.hour
            weekday = ts.weekday()
            start_hour = SESSION_FILTER["start_hour"]
            end_hour = SESSION_FILTER["end_hour"]
            friday_cutoff = SESSION_FILTER["friday_cutoff_hour"]
            if hour < start_hour or hour >= end_hour or (weekday == 4 and hour >= friday_cutoff):
                records["signal"].append("NONE")
                records["entry_price"].append(None)
                records["stop_price"].append(None)
                records["take_profit"].append(None)
                records["position_size"].append(0.0)
                records["regime"].append(
                    regime.loc[ts].name if hasattr(regime.loc[ts], "name") else str(regime.loc[ts])
                )
                continue
        current_regime = regime.loc[ts]
        current_regime_name = getattr(current_regime, "name", str(current_regime))

        if prev_regime is None:
            prev_regime = current_regime
        elif current_regime != prev_regime:
            logger.info(
                "Regime change at %s: %s -> %s",
                ts,
                getattr(prev_regime, "name", str(prev_regime)),
                current_regime_name,
            )
            prev_regime = current_regime

        if not isinstance(sig, TradeSignal) or sig.signal.name == "NONE":
            records["signal"].append("NONE")
            records["entry_price"].append(None)
            records["stop_price"].append(None)
            records["take_profit"].append(None)
            records["position_size"].append(0.0)
            records["regime"].append(current_regime_name)
            continue

        is_long = sig.signal.name == "LONG"
        if is_long:
            long_count += 1
        else:
            short_count += 1

        stop_distance = abs((sig.entry_price or 0.0) - (sig.stop_price or 0.0))
        atr_proxy = (
            stop_distance / config.position.atr_multiplier
            if config.position.atr_multiplier > 0
            else stop_distance
        )
        if config.fixed_position_size is not None:
            base_size = max(config.fixed_position_size, 0.0)
        else:
            base_size = calculate_position_size(
                entry_price=sig.entry_price or 0.0,
                atr_value=atr_proxy,
                account_equity=account_equity,
                is_long=is_long,
                config=config.position,
            )
        position_size = base_size * size_adjust_factor

        records["signal"].append(sig.signal.name)
        records["entry_price"].append(sig.entry_price)
        records["stop_price"].append(sig.stop_price)
        records["take_profit"].append(sig.take_profit)
        records["position_size"].append(position_size)
        records["regime"].append(current_regime_name)

    result = pd.DataFrame(records, index=ohlc.index)

    logger.info(
        "Engine finished for %s: total_bars=%d, long_signals=%d, short_signals=%d",
        symbol,
        len(result),
        long_count,
        short_count,
    )
    return result


