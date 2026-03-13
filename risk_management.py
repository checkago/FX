from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd

from config import RISK


@dataclass
class PositionSizingConfig:
    risk_per_trade: float = RISK["risk_per_trade"]
    atr_multiplier: float = RISK["atr_multiplier"]
    value_per_point: float = RISK["value_per_point"]


def calculate_position_size(
    entry_price: float,
    atr_value: float,
    account_equity: float,
    is_long: bool,
    config: Optional[PositionSizingConfig] = None,
) -> float:
    if config is None:
        config = PositionSizingConfig()

    if account_equity <= 0:
        raise ValueError("Account equity must be positive")
    if atr_value <= 0:
        raise ValueError("ATR must be positive")
    if config.risk_per_trade <= 0:
        raise ValueError("risk_per_trade must be positive")
    if config.value_per_point <= 0:
        raise ValueError("value_per_point must be positive")

    stop_distance = config.atr_multiplier * atr_value

    risk_amount = account_equity * config.risk_per_trade
    position_size = risk_amount / (stop_distance * config.value_per_point)

    return max(position_size, 0.0)


def correlation_filter(
    returns_df: pd.DataFrame,
    current_symbol: str,
    existing_exposure: pd.Series,
    max_correlation: float = 0.8,
) -> float:
    if current_symbol not in returns_df.columns:
        raise ValueError("current_symbol must be present in returns_df columns")

    if existing_exposure.empty:
        return 1.0

    common_symbols = [s for s in existing_exposure.index if s in returns_df.columns]
    if not common_symbols:
        return 1.0

    corr_matrix = returns_df[[current_symbol] + common_symbols].corr()
    corrs = corr_matrix.loc[current_symbol, common_symbols]

    risky_symbols = corrs[corrs.abs() > max_correlation].index.tolist()
    if not risky_symbols:
        return 1.0

    total_risky_exposure = existing_exposure.get(risky_symbols).abs().sum()
    if total_risky_exposure <= 0:
        return 1.0

    factor = max(0.0, 1.0 - min(1.0, total_risky_exposure))
    return factor

