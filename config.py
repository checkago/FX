from __future__ import annotations

"""
Единый конфигурационный файл торговой системы.

Все ключевые настройки (символ, даты теста, риск, комиссии, базовые пороги режимов)
собраны здесь, чтобы не искать их по разным модулям.
"""

# --- Общие настройки теста / символа ---

TRADING = {
    # список инструментов: (базовый символ, суффикс брокера)
    "symbols": [
        ("EURUSD", "rfd"),
        ("GBPUSD", "rfd"),
        ("USDJPY", "rfd"),
        ("USDCHF", "rfd"),
    ],
    # для обратной совместимости (param_sweep и т.п.)
    "symbol_base": "EURUSD",
    "symbol_suffix": "rfd",
    # таймфрейм для MT5
    "timeframe_name": "H1",
    # диапазон дат для теста
    "date_from": (2023, 1, 1),
    "date_to": (2026, 3, 11),
    # стартовый депозит
    "initial_equity": 50_000.0,
}


# --- Риск и издержки ---

RISK = {
    # риск на сделку в долях капитала (0.0025 = 0.25%)
    "risk_per_trade": 0.0025,
    # множитель ATR для расчёта стопа
    "atr_multiplier": 2.0,
    # масштаб цены: сколько денежных единиц соответствует движению цены на 1.0
    # (используется совместно с PIP_SIZE/PIP_VALUE_PER_LOT в equity_analysis)
    "value_per_point": 100_000.0,
    # спред в пипсах, вычитается из каждой сделки в equity_analysis
    "spread_pips": 2.0,
    # комиссия за 1 лот (если есть), в валюте депозита; 0.0 если не учитываем
    "commission_per_lot": 0.0,
}


# --- Базовые пороги режимной детекции (могут быть перекрыты best_params.json) ---

REGIME_DEFAULTS = {
    "adx_low_threshold": 20.0,
    "adx_high_threshold": 22.0,
    "bb_squeeze_lookback": 20,
}


# --- Фильтр по сессиям (МСК, время брокера) ---

SESSION_FILTER = {
    # торгуем только между этими часами МСК (включительно по start, исключительно по end)
    "start_hour": 7,
    "end_hour": 22,
    # в пятницу закрываем новые входы после этого часа
    "friday_cutoff_hour": 20,
    # смещение сервера MT5 относительно МСК (если сервер в МСК — 0)
    "server_offset_hours": 0,
}

# --- Спецификации брокера (из specifications-POINT.csv, marginal-RUB.csv) ---

BROKER_SPECS = {
    "use_broker_specs": True,
    "specifications_path": "specifications-POINT.csv",
    "margins_path": "marginal-RUB.csv",
}

