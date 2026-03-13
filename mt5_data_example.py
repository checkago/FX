from __future__ import annotations

from datetime import datetime
from functools import reduce
import logging
import json
from pathlib import Path

import matplotlib.pyplot as plt
import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from config import TRADING, RISK
from engine import EngineConfig, run_trading_engine_for_symbol
from risk_management import PositionSizingConfig
from regime_detection import RegimeConfig
from strategy_selection import StrategyConfig
from equity_analysis import (
    build_trades_and_equity,
    summarize_by_regime,
)


MT5_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5 Alfa-Forex\terminal64.exe"

logger = logging.getLogger(__name__)


def initialize_mt5(path: str = MT5_TERMINAL_PATH) -> None:
    logger.info("Initializing MetaTrader5 terminal at path: %s", path)
    initialized = mt5.initialize(path=path)
    if not initialized:
        error = mt5.last_error()
        logger.error("MetaTrader5 initialize() failed: %s", error)
        raise RuntimeError(f"MetaTrader5 initialize() failed, error: {error}")
    logger.info("MetaTrader5 initialized successfully")


def shutdown_mt5() -> None:
    mt5.shutdown()


def fetch_ohlc_from_mt5(
    symbol: str,
    timeframe: int,
    date_from: datetime,
    date_to: datetime,
) -> pd.DataFrame:
    logger.info(
        "Requesting MT5 history (from_pos): symbol=%s, timeframe=%s",
        symbol,
        timeframe,
    )
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 100000)
    if rates is None or len(rates) == 0:
        logger.warning(
            "No data from copy_rates_from_pos, trying explicit range for %s: %s -> %s",
            symbol,
            date_from,
            date_to,
        )
        rates = mt5.copy_rates_range(symbol, timeframe, date_from, date_to)
        if rates is None or len(rates) == 0:
            logger.error("Both from_pos and range returned no data for %s", symbol)
            raise RuntimeError(f"MT5 returned no data for {symbol}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)

    ohlc = df[["high", "low", "close"]].copy()
    logger.info("Received OHLC data for %s: rows=%d", symbol, len(ohlc))
    return ohlc


def build_returns_frame(ohlc: pd.DataFrame, symbol: str) -> pd.DataFrame:
    close = ohlc["close"]
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0)
    df = pd.DataFrame({symbol: returns}, index=ohlc.index)
    return df


def build_combined_returns(ohlc_by_symbol: dict[str, pd.DataFrame]) -> pd.DataFrame:
    all_returns: list[pd.DataFrame] = []
    for sym, ohlc in ohlc_by_symbol.items():
        df = build_returns_frame(ohlc, sym)
        all_returns.append(df)
    combined = pd.concat(all_returns, axis=1, join="outer").fillna(0.0)
    logger.info("Built combined returns: %d rows, symbols=%s", len(combined), list(combined.columns))
    return combined


def main() -> None:
    symbols_config = TRADING.get("symbols")
    if symbols_config:
        symbols_list = [(f"{base}{suffix}", base) for base, suffix in symbols_config]
    else:
        base = TRADING["symbol_base"]
        suffix = TRADING["symbol_suffix"]
        symbols_list = [(f"{base}{suffix}", base)]

    tf_name = TRADING["timeframe_name"]
    if tf_name == "H1":
        timeframe = mt5.TIMEFRAME_H1
    elif tf_name == "H30":
        timeframe = mt5.TIMEFRAME_M30
    else:
        timeframe = mt5.TIMEFRAME_H1
    timeframe_name = tf_name

    df_year, df_month, df_day = TRADING["date_from"]
    dt_year, dt_month, dt_day = TRADING["date_to"]
    date_from = datetime(df_year, df_month, df_day)
    date_to = datetime(dt_year, dt_month, dt_day)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    logger.info("Starting MT5 data example for %d symbols, timeframe=%s", len(symbols_list), timeframe)

    initialize_mt5()
    try:
        ohlc_by_symbol: dict[str, pd.DataFrame] = {}
        for mt5_symbol, _ in symbols_list:
            ohlc = fetch_ohlc_from_mt5(mt5_symbol, timeframe, date_from, date_to)
            ohlc_by_symbol[mt5_symbol] = ohlc

        returns_df = build_combined_returns(ohlc_by_symbol)

        position_cfg = PositionSizingConfig(
            risk_per_trade=RISK["risk_per_trade"],
            atr_multiplier=RISK["atr_multiplier"],
            value_per_point=RISK["value_per_point"],
        )
        all_trades: list[pd.DataFrame] = []
        all_equity: list[pd.Series] = []

        for mt5_symbol, _ in symbols_list:
            regime_cfg = RegimeConfig()
            strategy_cfg = StrategyConfig()

            for params_file in (f"best_params_{mt5_symbol}.json", "best_params.json"):
                params_path = Path(params_file)
                if params_path.exists():
                    try:
                        with params_path.open("r", encoding="utf-8") as f:
                            data = json.load(f)
                        regime_cfg.adx_low_threshold = float(data.get("adx_low_threshold", regime_cfg.adx_low_threshold))
                        regime_cfg.adx_high_threshold = float(data.get("adx_high_threshold", regime_cfg.adx_high_threshold))
                        regime_cfg.bb_squeeze_lookback = int(data.get("bb_squeeze_lookback", regime_cfg.bb_squeeze_lookback))
                        if "mr_sl_atr_mult" in data:
                            strategy_cfg.mr_sl_atr_mult = float(data["mr_sl_atr_mult"])
                        if "mb_sl_atr_mult" in data:
                            strategy_cfg.mb_sl_atr_mult = float(data["mb_sl_atr_mult"])
                        logger.info("Loaded params for %s from %s", mt5_symbol, params_file)
                        break
                    except Exception as e:
                        logger.warning("Failed to load %s: %s", params_file, e)

            cfg = EngineConfig(
                position=position_cfg,
                regime=regime_cfg,
                strategy=strategy_cfg,
            )
            ohlc = ohlc_by_symbol[mt5_symbol]
            # returns_df для текущего символа: нужны все колонки для correlation_filter
            sym_returns = returns_df.reindex(ohlc.index, method="ffill").fillna(0.0)
            if mt5_symbol not in sym_returns.columns:
                sym_returns[mt5_symbol] = ohlc["close"].pct_change().fillna(0.0)

            existing_exposure = pd.Series(dtype=float)

            result = run_trading_engine_for_symbol(
                ohlc=ohlc,
                returns_df=sym_returns,
                symbol=mt5_symbol,
                existing_exposure=existing_exposure,
                account_equity=TRADING["initial_equity"],
                config=cfg,
            )

            combined = (
                ohlc.join(sym_returns, how="left")
                .join(result, how="left")
            )

            trades, equity = build_trades_and_equity(combined, symbol=mt5_symbol)

            if not trades.empty:
                logger.info("%s: PnL=%.2f, trades=%d", mt5_symbol, trades["pnl"].sum(), len(trades))
            logger.info("%s: final equity=%.2f", mt5_symbol, equity.iloc[-1])

            regime_stats = summarize_by_regime(trades)
            if not regime_stats.empty:
                logger.info("%s regime stats:\n%s", mt5_symbol, regime_stats)

            csv_name = f"backtest_{mt5_symbol}_{timeframe_name}_{date_from:%Y%m%d}_{date_to:%Y%m%d}.csv"
            parquet_name = f"backtest_{mt5_symbol}_{timeframe_name}_{date_from:%Y%m%d}_{date_to:%Y%m%d}.parquet"

            try:
                combined.to_csv(csv_name)
                logger.info("Saved backtest to CSV: %s", csv_name)
            except PermissionError as e:
                logger.warning("Could not write CSV %s: %s", csv_name, e)

            try:
                combined.to_parquet(parquet_name)
                logger.info("Saved backtest to Parquet: %s", parquet_name)
            except ImportError as e:
                logger.warning("Could not save Parquet %s: %s", parquet_name, e)
            except PermissionError as e:
                logger.warning("Could not write Parquet %s: %s", parquet_name, e)

            trades.to_csv(f"trades_{mt5_symbol}_{timeframe_name}.csv", index=False)
            equity.to_csv(f"equity_{mt5_symbol}_{timeframe_name}.csv", header=True)

            all_trades.append(trades)
            all_equity.append(equity)

        if all_trades:
            total_pnl = sum(t["pnl"].sum() for t in all_trades)
            total_trades = sum(len(t) for t in all_trades)
            logger.info("Portfolio: total PnL=%.2f, total trades=%d", total_pnl, total_trades)

        if all_equity:
            idx_list = [eq.index for eq in all_equity]
            common_index = idx_list[0] if len(idx_list) == 1 else reduce(lambda a, b: a.union(b), idx_list).sort_values()
            excesses = [
                (eq - TRADING["initial_equity"]).reindex(common_index, method="ffill").fillna(0.0)
                for eq in all_equity
            ]
            portfolio_equity = TRADING["initial_equity"] + sum(excesses)
            portfolio_equity.to_csv(f"equity_portfolio_{timeframe_name}.csv", header=True)

            fig, ax = plt.subplots(figsize=(12, 6))
            for i, (mt5_symbol, _) in enumerate(symbols_list):
                ax.plot(all_equity[i].index, all_equity[i].values, label=mt5_symbol, alpha=0.7)
            ax.plot(
                portfolio_equity.index,
                portfolio_equity.values,
                label="Портфель",
                color="black",
                linewidth=2,
            )
            ax.set_title("Equity")
            ax.grid(True)
            ax.legend()
            plt.tight_layout()
            plt.show(block=False)
            plt.pause(15)
            plt.close(fig)

    finally:
        shutdown_mt5()


if __name__ == "__main__":
    main()
