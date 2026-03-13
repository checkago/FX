"""
Загрузка спецификаций брокера из CSV.
Используется для учёта спредов, limit/stop level и маржи по инструментам.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

def _mt5_to_spec_key(symbol: str) -> str:
    base = symbol.upper().replace("RFD", "").replace("RFd", "")
    if len(base) >= 6:
        return base[:6]
    return base


def _parse_float(s: str) -> float:
    s = str(s).strip().replace(",", ".")
    for suffix in (" коп", "%"):
        s = s.replace(suffix, "")
    s = s.strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def load_specifications(path: str = "specifications-POINT.csv") -> dict[str, dict]:
    """Загружает specifications-POINT.csv. Возвращает {spec_key: {spread, limit_stop, ...}}."""
    result: dict[str, dict] = {}
    p = Path(path)
    if not p.exists():
        return result

    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            with p.open("r", encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        return result

    for line in lines[1:]:
        parts = line.strip().split(";")
        if len(parts) < 4:
            continue
        instrument = parts[0].strip()
        spread_str = parts[1].strip()
        limit_stop_str = parts[3].strip() if len(parts) > 3 else "0"

        spread = _parse_float(spread_str)
        limit_stop = _parse_float(limit_stop_str)

        if "/" not in instrument:
            continue
        key = instrument.replace(" ", "").replace("/", "")
        result[key] = {"spread": spread, "limit_stop_level": limit_stop}

    return result


def load_margins(path: str = "marginal-RUB.csv") -> dict[str, dict]:
    """Загружает marginal-RUB.csv. Возвращает {spec_key: {margin_rub, leverage, stop_out}}."""
    result: dict[str, dict] = {}
    p = Path(path)
    if not p.exists():
        return result

    for enc in ("utf-8-sig", "cp1251", "utf-8"):
        try:
            with p.open("r", encoding=enc) as f:
                lines = f.readlines()
            break
        except UnicodeDecodeError:
            continue
    else:
        return result

    for line in lines[1:]:
        parts = line.strip().split(";")
        if len(parts) < 3:
            continue
        instrument = parts[0].strip()
        if "/" not in instrument:
            continue
        key = instrument.replace(" ", "").replace("/", "")
        try:
            margin = int(str(parts[2]).strip().replace(" ", "")) if parts[2].strip() else 0
        except ValueError:
            margin = 0
        result[key] = {"margin_rub": margin, "stop_out_pct": 81.0}

    return result


_SPECS_CACHE: Optional[dict] = None
_MARGINS_CACHE: Optional[dict] = None


def get_specs() -> tuple[dict, dict]:
    global _SPECS_CACHE, _MARGINS_CACHE
    if _SPECS_CACHE is None or _MARGINS_CACHE is None:
        try:
            from config import BROKER_SPECS
            spec_path = BROKER_SPECS.get("specifications_path", "specifications-POINT.csv")
            margin_path = BROKER_SPECS.get("margins_path", "marginal-RUB.csv")
        except ImportError:
            spec_path = "specifications-POINT.csv"
            margin_path = "marginal-RUB.csv"
        _SPECS_CACHE = load_specifications(spec_path)
        _MARGINS_CACHE = load_margins(margin_path)
    return _SPECS_CACHE, _MARGINS_CACHE


def get_spread_pips(symbol: str) -> float:
    """Спред в пипсах для символа (EURUSDrfd -> 1.4 для EUR/USD)."""
    specs, _ = get_specs()
    key = _mt5_to_spec_key(symbol)
    return specs.get(key, {}).get("spread", 2.0)


def get_limit_stop_level(symbol: str) -> float:
    """Минимальное расстояние SL/TP от цены (в пунктах брокера)."""
    specs, _ = get_specs()
    key = _mt5_to_spec_key(symbol)
    return specs.get(key, {}).get("limit_stop_level", 1.0)


def get_pip_size(symbol: str) -> float:
    """Размер пипа: 0.0001 для XXX/USD, 0.01 для XXX/JPY."""
    s = symbol.upper()
    if "JPY" in s:
        return 0.01
    return 0.0001


def get_pip_value_per_lot(symbol: str) -> float:
    """Стоимость 1 пипа за 1 лот в USD (приблизительно)."""
    s = symbol.upper()
    if "JPY" in s:
        return 100000.0 / 100.0
    return 10.0
