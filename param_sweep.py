from __future__ import annotations

import argparse
import logging
from itertools import product
from pathlib import Path
from typing import List
import json

import pandas as pd

from engine import EngineConfig, run_trading_engine_for_symbol
from equity_analysis import build_trades_and_equity, load_backtest
from regime_detection import RegimeConfig
from risk_management import PositionSizingConfig
from strategy_selection import StrategyConfig
from config import TRADING, RISK, REGIME_DEFAULTS


def load_base_data(path: str, symbol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = load_backtest(path)
    ohlc = df[["high", "low", "close"]].copy()
    if symbol not in df.columns:
        raise ValueError(f"Symbol {symbol} not in backtest columns: {list(df.columns)}")
    returns = pd.DataFrame({symbol: df[symbol]}, index=df.index)
    return ohlc, returns


def run_sweep(
    ohlc: pd.DataFrame,
    returns_df: pd.DataFrame,
    symbol: str,
    account_equity: float = TRADING["initial_equity"],
    include_strategy_params: bool = False,
) -> pd.DataFrame:
    existing_exposure = pd.Series({symbol: 0.0})

    baseline_position = PositionSizingConfig(
        risk_per_trade=RISK["risk_per_trade"],
        atr_multiplier=RISK["atr_multiplier"],
        value_per_point=RISK["value_per_point"],
    )
    baseline_engine_cfg = EngineConfig(position=baseline_position)
    baseline_res = run_trading_engine_for_symbol(
        ohlc=ohlc,
        returns_df=returns_df,
        symbol=symbol,
        existing_exposure=existing_exposure,
        account_equity=account_equity,
        config=baseline_engine_cfg,
    )
    baseline_df = ohlc.join(baseline_res, how="left")
    baseline_trades, baseline_equity = build_trades_and_equity(baseline_df, symbol=symbol)
    baseline_total_pnl = float(baseline_trades["pnl"].sum()) if not baseline_trades.empty else 0.0
    if not baseline_equity.empty:
        baseline_run_max = baseline_equity.cummax()
        baseline_dd = baseline_equity - baseline_run_max
        baseline_max_dd = float(baseline_dd.min())
    else:
        baseline_max_dd = 0.0

    base_low = REGIME_DEFAULTS["adx_low_threshold"]
    base_high = REGIME_DEFAULTS["adx_high_threshold"]
    base_bb = REGIME_DEFAULTS["bb_squeeze_lookback"]

    adx_low_vals: List[float] = [base_low - 2.0, base_low, base_low + 2.0]
    adx_high_vals: List[float] = [base_high, base_high + 2.0, base_high + 6.0]
    squeeze_lookbacks: List[int] = [max(10, base_bb - 10), base_bb, base_bb + 20]

    mr_sl_vals: List[float] = [1.1, 1.3, 1.5] if include_strategy_params else [1.3]
    mb_sl_vals: List[float] = [0.8, 1.0, 1.2] if include_strategy_params else [1.0]

    combos = list(product(adx_low_vals, adx_high_vals, squeeze_lookbacks, mr_sl_vals, mb_sl_vals))
    combos = [(a, b, c, d, e) for a, b, c, d, e in combos if b > a]
    total = len(combos)
    print(f"Baseline PnL: {baseline_total_pnl:.2f}. Сканирование {total} комбинаций...")
    logging.getLogger().setLevel(logging.WARNING)

    results: List[dict] = []
    for idx, (adx_low, adx_high, squeeze_lb, mr_sl, mb_sl) in enumerate(combos):
        if (idx + 1) % 20 == 0 or idx == 0:
            print(f"\rСканирование {idx + 1}/{total}...", end="", flush=True)

        regime_cfg = RegimeConfig(
            adx_low_threshold=adx_low,
            adx_high_threshold=adx_high,
            bb_squeeze_lookback=squeeze_lb,
        )
        strategy_cfg = StrategyConfig(mr_sl_atr_mult=mr_sl, mb_sl_atr_mult=mb_sl)
        engine_cfg = EngineConfig(
            regime=regime_cfg,
            strategy=strategy_cfg,
            position=baseline_position,
        )

        res = run_trading_engine_for_symbol(
            ohlc=ohlc,
            returns_df=returns_df,
            symbol=symbol,
            existing_exposure=existing_exposure,
            account_equity=account_equity,
            config=engine_cfg,
        )

        df_for_equity = ohlc.join(res, how="left")
        trades, equity = build_trades_and_equity(df_for_equity, symbol=symbol)

        total_pnl = float(trades["pnl"].sum()) if not trades.empty else 0.0
        n_trades = int(len(trades))
        if not equity.empty:
            run_max = equity.cummax()
            dd = equity - run_max
            max_dd = float(dd.min())
        else:
            max_dd = 0.0
        ret = total_pnl / account_equity if account_equity > 0 else 0.0

        better_than_baseline = (
            n_trades > 0
            and total_pnl >= baseline_total_pnl
            and max_dd >= baseline_max_dd
        )

        row: dict = {
            "adx_low": adx_low,
            "adx_high": adx_high,
            "bb_squeeze_lookback": squeeze_lb,
            "trades": n_trades,
            "total_pnl": total_pnl,
            "return_pct": ret * 100.0,
            "max_drawdown": max_dd,
            "better_than_baseline": better_than_baseline,
        }
        if include_strategy_params:
            row["mr_sl_atr_mult"] = mr_sl
            row["mb_sl_atr_mult"] = mb_sl
        results.append(row)

    print(f"\rСканирование {total}/{total} — готово.    ")
    return pd.DataFrame(results).sort_values("total_pnl", ascending=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Оптимизация параметров режимной детекции и стратегии")
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Символ для оптимизации (например USDCHF). Без суффикса — будет добавлен из config.",
    )
    parser.add_argument(
        "--strategy",
        action="store_true",
        help="Включить перебор параметров стратегии (mr_sl, mb_sl) для тонкой настройки",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Быстрый режим: только режимные параметры, без стратегии (~27 комбинаций)",
    )
    args = parser.parse_args()

    suffix = TRADING["symbol_suffix"]
    if args.symbol:
        base_symbol = args.symbol.upper()
        symbol = f"{base_symbol}{suffix}"
        symbol_specific = True
    else:
        base_symbol = TRADING["symbol_base"]
        symbol = f"{base_symbol}{suffix}"
        symbol_specific = False

    tf_name = TRADING["timeframe_name"]
    date_str = f"{TRADING['date_from'][0]}{TRADING['date_from'][1]:02d}{TRADING['date_from'][2]:02d}_{TRADING['date_to'][0]}{TRADING['date_to'][1]:02d}{TRADING['date_to'][2]:02d}"
    path_parquet = f"backtest_{symbol}_{tf_name}_{date_str}.parquet"
    path_csv = f"backtest_{symbol}_{tf_name}_{date_str}.csv"
    path = path_parquet if Path(path_parquet).exists() else (path_csv if Path(path_csv).exists() else path_parquet)

    ohlc, returns_df = load_base_data(path, symbol)

    include_strat = (args.strategy or symbol_specific) and not args.fast
    sweep_results = run_sweep(
        ohlc, returns_df, symbol, include_strategy_params=include_strat
    )

    print("Топ-10 параметров по прибыли:")
    print(sweep_results.head(10))

    sweep_results.to_csv("param_sweep_results.csv", index=False)

    better = sweep_results[sweep_results["better_than_baseline"]]
    if not better.empty:
        best_row = better.iloc[0]
        best_config: dict = {
            "adx_low_threshold": float(best_row["adx_low"]),
            "adx_high_threshold": float(best_row["adx_high"]),
            "bb_squeeze_lookback": int(best_row["bb_squeeze_lookback"]),
        }
        if "mr_sl_atr_mult" in best_row:
            best_config["mr_sl_atr_mult"] = float(best_row["mr_sl_atr_mult"])
            best_config["mb_sl_atr_mult"] = float(best_row["mb_sl_atr_mult"])
        out_path = f"best_params_{symbol}.json" if symbol_specific else "best_params.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(best_config, f, ensure_ascii=False, indent=2)
        print(f"Saved best params to {out_path}:", best_config)
    else:
        print("No configuration better than baseline found; best_params not updated.")


if __name__ == "__main__":
    main()

