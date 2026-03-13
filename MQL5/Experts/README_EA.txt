Спецификации брокера (встроены в EA по specifications-POINT.csv):
- Limit/Stop level: EURUSD 0.7, GBPUSD 1.1, USDJPY 0.9, USDCHF 1
- Фильтр спреда: не открывать при спреде > InpSpreadMaxPips (по умолчанию 5)
- Время сервера: МСК (7-22 ч — торговая сессия)

Установка советника FX_Adaptive_EA:

1. Скопируй FX_Adaptive_EA.mq5 в папку:
   C:\Program Files\MetaTrader 5 Alfa-Forex\MQL5\Experts\

2. В MT5: Файл -> Открыть каталог данных -> MQL5 -> Experts
   (или перезапусти MT5 после копирования)

3. В Навигаторе нажми "Обновить" в разделе Советники

4. Перетащи советник на график нужной пары (EURUSD, GBPUSD, USDJPY, USDCHF)

5. Рекомендуемый таймфрейм: H1

6. Для мультисимвольной торговли — прикрепи копию советника на каждый график

Параметры по умолчанию соответствуют config.py Python-системы.
Для символов с best_params_*.json — скорректируй InpADXLowThreshold,
InpADXHighThreshold, InpBBSqueezeLookback, InpMRSLATRMult, InpMBSLATRMult.
