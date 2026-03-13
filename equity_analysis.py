from __future__ import annotations

from typing import Optional

import pandas as pd
import matplotlib.pyplot as plt

from config import TRADING, RISK

try:
    from config import BROKER_SPECS
except ImportError:
    BROKER_SPECS = {"use_broker_specs": False}


def load_backtest(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        try:
            df = pd.read_parquet(path)
        except ImportError:
            csv_path = path.replace(".parquet", ".csv")
            df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    else:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.sort_index()


def build_trades_and_equity(
    df: pd.DataFrame,
    symbol: Optional[str] = None,
) -> tuple[pd.DataFrame, pd.Series]:
    position = 0
    entry_price: float | None = None
    entry_time = None
    size = 0.0

    if BROKER_SPECS.get("use_broker_specs") and symbol:
        try:
            from broker_specs import get_spread_pips, get_pip_size, get_pip_value_per_lot
            pip_size = get_pip_size(symbol)
            pip_value = get_pip_value_per_lot(symbol)
            spread_pips = get_spread_pips(symbol)
        except ImportError:
            pip_size = 0.0001
            pip_value = 10.0
            spread_pips = RISK["spread_pips"]
    else:
        pip_size = 0.0001 if not symbol or "JPY" not in (symbol or "").upper() else 0.01
        pip_value = 10.0
        spread_pips = RISK["spread_pips"]

    equity = TRADING["initial_equity"]
    equity_series = []

    trades: list[dict] = []

    for ts, row in df.iterrows():
        price = float(row["close"])
        signal = str(row["signal"])
        bar_high = float(row["high"])
        bar_low = float(row["low"])
        bar_size = float(row.get("position_size") or 0.0)
        stop_price = row.get("stop_price")
        take_profit = row.get("take_profit")

        exit_reason = None
        exit_price = None

        if position != 0:
            if stop_price is not None:
                stop_price = float(stop_price)
            if take_profit is not None:
                take_profit = float(take_profit)

            if position == 1:
                if stop_price is not None and bar_low <= stop_price:
                    exit_price = stop_price
                    exit_reason = "stop"
                elif take_profit is not None and bar_high >= take_profit:
                    exit_price = take_profit
                    exit_reason = "tp"
            elif position == -1:
                if stop_price is not None and bar_high >= stop_price:
                    exit_price = stop_price
                    exit_reason = "stop"
                elif take_profit is not None and bar_low <= take_profit:
                    exit_price = take_profit
                    exit_reason = "tp"

        if position != 0 and exit_price is None:
            if (position == 1 and signal == "SHORT") or (position == -1 and signal == "LONG"):
                exit_price = price
                exit_reason = "reverse"

        if position != 0 and exit_price is not None:
            points = (exit_price - entry_price) / pip_size  # type: ignore[arg-type]
            pnl_per_lot = points * pip_value
            trade_pnl = position * pnl_per_lot * size

            cost = spread_pips * pip_value * size + RISK["commission_per_lot"] * size
            trade_pnl -= cost
            equity += trade_pnl

            entry_regime = df.loc[entry_time, "regime"] if "regime" in df.columns and entry_time is not None else None

            trades.append(
                {
                    "entry_time": entry_time,
                    "exit_time": ts,
                    "direction": "LONG" if position == 1 else "SHORT",
                    "size": size,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "pips": position * points,
                    "pnl": trade_pnl,
                    "equity_after": equity,
                    "exit_reason": exit_reason,
                    "entry_regime": entry_regime,
                }
            )

            position = 0
            entry_price = None
            entry_time = None
            size = 0.0

        if position == 0 and bar_size > 0 and signal in ("LONG", "SHORT"):
            position = 1 if signal == "LONG" else -1
            entry_price = price
            entry_time = ts
            size = bar_size

        equity_series.append(equity)

    equity_series_s = pd.Series(equity_series, index=df.index, name="equity")
    trades_df = pd.DataFrame(trades)
    return trades_df, equity_series_s


def summarize_by_regime(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "entry_regime" not in trades.columns:
        return pd.DataFrame()

    g = trades.groupby("entry_regime")

    def max_drawdown(equity_after: pd.Series) -> float:
        if equity_after.empty:
            return 0.0
        run_max = equity_after.cummax()
        dd = equity_after - run_max
        return float(dd.min())

    rows: list[dict] = []
    for regime, grp in g:
        n = len(grp)
        total_pnl = float(grp["pnl"].sum())
        wins = grp[grp["pnl"] > 0]
        losses = grp[grp["pnl"] < 0]
        win_rate = float(len(wins) / n) if n > 0 else 0.0
        avg_win = float(wins["pnl"].mean()) if not wins.empty else 0.0
        avg_loss = float(losses["pnl"].mean()) if not losses.empty else 0.0
        mdd = max_drawdown(grp["equity_after"])

        rows.append(
            {
                "regime": regime,
                "trades": n,
                "total_pnl": total_pnl,
                "win_rate": win_rate,
                "avg_win": avg_win,
                "avg_loss": avg_loss,
                "max_drawdown": mdd,
            }
        )

    return pd.DataFrame(rows).sort_values("total_pnl", ascending=False)


def plot_equity(equity: pd.Series) -> None:
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(equity.index, equity.values, label="Equity")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.show(block=False)
    plt.pause(15)
    plt.close(fig)


def plot_price_with_trades(df: pd.DataFrame, trades: pd.DataFrame) -> None:
    if trades.empty:
        return

    fig, ax = plt.subplots(figsize=(14, 7))
    ax.plot(df.index, df["close"], color="black", label="Close")

    for _, t in trades.iterrows():
        color = "green" if t["direction"] == "LONG" else "red"
        ax.scatter(t["entry_time"], t["entry_price"], marker="^", color=color, s=40)
        ax.scatter(t["exit_time"], t["exit_price"], marker="v", color=color, s=40)
        ax.plot(
            [t["entry_time"], t["exit_time"]],
            [t["entry_price"], t["exit_price"]],
            color=color,
            alpha=0.4,
        )

    ax.set_title("EURUSDrfd H1 — сделки на графике цены")
    ax.grid(True)
    ax.legend()
    plt.tight_layout()
    plt.show(block=False)
    plt.pause(15)
    plt.close(fig)


def main() -> None:
    path = "backtest_EURUSDrfd_H1_20240101_20260310.parquet"
    df = load_backtest(path)

    trades, equity = build_trades_and_equity(df, symbol="EURUSDrfd")

    print("Первые сделки:")
    print(trades.head())

    if not trades.empty:
        print("\nИтоговая прибыль:", trades["pnl"].sum())
    print("Конечная эквити:", equity.iloc[-1])

    regime_stats = summarize_by_regime(trades)
    if not regime_stats.empty:
        print("\nСтатистика по режимам:")
        print(regime_stats)

    trades.to_csv("trades_EURUSDrfd_H1.csv", index=False)
    equity.to_csv("equity_EURUSDrfd_H1.csv", header=True)

    plot_equity(equity)
    plot_price_with_trades(df, trades)


if __name__ == "__main__":
    main()

