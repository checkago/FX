//+------------------------------------------------------------------+
//| FX_Adaptive_EA.mq5                                                |
//| Адаптивная торговая система: режимная детекция + MR/MB стратегии |
//+------------------------------------------------------------------+
#property copyright "FX Adaptive System"
#property version   "1.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//--- Режимы рынка
enum ENUM_REGIME {
   REGIME_NEUTRAL = 0,
   REGIME_MEAN_REVERSION = 1,
   REGIME_MOMENTUM_BREAKOUT = 2
};

//--- Параметры режимной детекции
input group "=== Regime Detection ==="
input int    InpADXPeriod         = 14;
input int    InpATRPeriod         = 14;
input int    InpBBPeriod          = 20;
input double InpBBStdDev          = 2.0;
input int    InpMAPeriod          = 50;
input double InpADXLowThreshold   = 18.0;
input double InpADXHighThreshold  = 24.0;
input int    InpBBSqueezeLookback = 20;
input double InpPriceToMATolerance = 0.03;

//--- Параметры стратегии
input group "=== Strategy ==="
input double InpMRSLATRMult       = 1.3;
input double InpMBSLATRMult       = 1.0;
input double InpMBTPATRMult       = 2.0;
input int    InpMBBreakoutLookback = 20;

//--- Риск-менеджмент
input group "=== Risk ==="
input double InpRiskPerTrade      = 0.0025;
input double InpATRMultForSize    = 2.0;
input double InpValuePerPoint     = 100000.0;
input double InpMaxLots           = 2.0;
input double InpMinLots           = 0.01;

//--- Фильтр сессий (часы сервера, МСК)
input group "=== Session Filter ==="
input bool   InpUseSessionFilter   = false;
input int    InpStartHour         = 7;
input int    InpEndHour           = 22;
input int    InpFridayCutoffHour   = 20;

//--- Спецификации брокера (specifications-POINT.csv)
input group "=== Broker Specs ==="
input bool   InpUseBrokerSpecs    = false;
input double InpSpreadMaxPips     = 10.0;

//--- Визуализация режима
input group "=== Visualization ==="
input bool   InpShowRegimeBg      = true;
input int    InpRegimeBars       = 200;

//--- Прочее
input group "=== Other ==="
input int    InpMagic             = 123456;
input int    InpSlippage          = 10;

CTrade         trade;
CPositionInfo  posInfo;
int            handleADX, handleATR, handleBB, handleMA;
double         adxBuf[], atrBuf[], bbLower[], bbMiddle[], bbUpper[], maBuf[];
datetime       lastBarTime = 0;

//+------------------------------------------------------------------+
int OnInit() {
   trade.SetExpertMagicNumber(InpMagic);
   trade.SetDeviationInPoints(InpSlippage);
   trade.SetTypeFillingBySymbol(_Symbol);

   handleADX = iADX(_Symbol, PERIOD_CURRENT, InpADXPeriod);
   handleATR = iATR(_Symbol, PERIOD_CURRENT, InpATRPeriod);
   handleBB  = iBands(_Symbol, PERIOD_CURRENT, InpBBPeriod, 0, InpBBStdDev, PRICE_CLOSE);
   handleMA  = iMA(_Symbol, PERIOD_CURRENT, InpMAPeriod, 0, MODE_SMA, PRICE_CLOSE);

   if(handleADX == INVALID_HANDLE || handleATR == INVALID_HANDLE ||
      handleBB == INVALID_HANDLE || handleMA == INVALID_HANDLE) {
      Print("Error creating indicator handles");
      return INIT_FAILED;
   }

   ArraySetAsSeries(adxBuf, true);
   ArraySetAsSeries(atrBuf, true);
   ArraySetAsSeries(bbLower, true);
   ArraySetAsSeries(bbMiddle, true);
   ArraySetAsSeries(bbUpper, true);
   ArraySetAsSeries(maBuf, true);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason) {
   ObjectsDeleteAll(0, "FX_Regime_");
   IndicatorRelease(handleADX);
   IndicatorRelease(handleATR);
   IndicatorRelease(handleBB);
   IndicatorRelease(handleMA);
}

//+------------------------------------------------------------------+
bool IsNewBar() {
   datetime barTime = iTime(_Symbol, PERIOD_CURRENT, 0);
   if(barTime != lastBarTime) {
      lastBarTime = barTime;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
double GetBrokerLimitLevel() {
   if(!InpUseBrokerSpecs) return 0;
   string sym = _Symbol;
   if(StringFind(sym, "EURUSD") >= 0) return 0.00007;
   if(StringFind(sym, "GBPUSD") >= 0) return 0.00011;
   if(StringFind(sym, "USDJPY") >= 0) return 0.009;
   if(StringFind(sym, "USDCHF") >= 0) return 0.0001;
   if(StringFind(sym, "USDCAD") >= 0) return 0.00011;
   return _Point * 10;
}

//+------------------------------------------------------------------+
bool IsSpreadAcceptable() {
   if(!InpUseBrokerSpecs) return true;
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   double spreadPoints = (ask - bid) / point;
   double pipSize = (digits == 3 || digits == 2) ? 0.01 : 0.0001;
   double spreadPips = spreadPoints * point / pipSize;
   return (spreadPips <= InpSpreadMaxPips);
}

//+------------------------------------------------------------------+
void EnforceLimitLevel(double price, double &sl, double &tp) {
   double minDist = GetBrokerLimitLevel();
   if(minDist <= 0) return;
   if(sl > 0 && MathAbs(price - sl) < minDist) {
      sl = (price > sl) ? price - minDist : price + minDist;
   }
   if(tp > 0 && MathAbs(price - tp) < minDist) {
      tp = (price < tp) ? price + minDist : price - minDist;
   }
}

//+------------------------------------------------------------------+
bool IsSessionAllowed() {
   if(!InpUseSessionFilter) return true;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   if(dt.hour < InpStartHour || dt.hour >= InpEndHour) return false;
   if(dt.day_of_week == 5 && dt.hour >= InpFridayCutoffHour) return false;
   return true;
}

//+------------------------------------------------------------------+
ENUM_REGIME DetectRegime() {
   if(CopyBuffer(handleADX, 0, 1, 3, adxBuf) < 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleATR, 0, 1, 3, atrBuf) < 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 0, 1, 3, bbMiddle) < 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 1, 1, 3, bbUpper) < 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 2, 1, 3, bbLower) < 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleMA, 0, 1, 3, maBuf) < 3) return REGIME_NEUTRAL;

   double adxVal = adxBuf[0];
   double close = iClose(_Symbol, PERIOD_CURRENT, 1);
   double maVal = maBuf[0];

   if(adxVal <= 0 || maVal <= 0) return REGIME_NEUTRAL;

   int lookback = MathMin(InpBBSqueezeLookback, 50);
   if(CopyBuffer(handleBB, 0, 1, lookback + 1, bbMiddle) < lookback + 1) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 1, 1, lookback + 1, bbUpper) < lookback + 1) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 2, 1, lookback + 1, bbLower) < lookback + 1) return REGIME_NEUTRAL;

   double bbWidth = (bbUpper[0] - bbLower[0]) / bbMiddle[0];
   double bbWidthMA = 0;
   for(int i = 0; i < lookback; i++) {
      double m = bbMiddle[i];
      if(m > 0) bbWidthMA += (bbUpper[i] - bbLower[i]) / m;
   }
   bbWidthMA /= lookback;
   bool bbSqueeze = (bbWidth < bbWidthMA);

   double priceToMA = MathAbs(close - maVal) / maVal;

   if(adxVal < InpADXLowThreshold && bbSqueeze && priceToMA < InpPriceToMATolerance)
      return REGIME_MEAN_REVERSION;

   if(adxVal > InpADXHighThreshold && !bbSqueeze)
      return REGIME_MOMENTUM_BREAKOUT;

   return REGIME_NEUTRAL;
}

//+------------------------------------------------------------------+
ENUM_REGIME DetectRegimeAtBar(int barIndex) {
   int lookback = MathMin(InpBBSqueezeLookback, 50);
   if(CopyBuffer(handleADX, 0, barIndex, 3, adxBuf) < 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 0, barIndex, lookback + 3, bbMiddle) < lookback + 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 1, barIndex, lookback + 3, bbUpper) < lookback + 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleBB, 2, barIndex, lookback + 3, bbLower) < lookback + 3) return REGIME_NEUTRAL;
   if(CopyBuffer(handleMA, 0, barIndex, 3, maBuf) < 3) return REGIME_NEUTRAL;

   double adxVal = adxBuf[0];
   double close = iClose(_Symbol, PERIOD_CURRENT, barIndex);
   double maVal = maBuf[0];
   if(adxVal <= 0 || maVal <= 0) return REGIME_NEUTRAL;

   double bbWidth = (bbUpper[0] - bbLower[0]) / bbMiddle[0];
   double bbWidthMA = 0;
   for(int i = 0; i < lookback; i++) {
      double m = bbMiddle[i];
      if(m > 0) bbWidthMA += (bbUpper[i] - bbLower[i]) / m;
   }
   bbWidthMA /= lookback;
   bool bbSqueeze = (bbWidth < bbWidthMA);
   double priceToMA = MathAbs(close - maVal) / maVal;

   if(adxVal < InpADXLowThreshold && bbSqueeze && priceToMA < InpPriceToMATolerance)
      return REGIME_MEAN_REVERSION;
   if(adxVal > InpADXHighThreshold && !bbSqueeze)
      return REGIME_MOMENTUM_BREAKOUT;
   return REGIME_NEUTRAL;
}

//+------------------------------------------------------------------+
color RegimeToColor(ENUM_REGIME r) {
   if(r == REGIME_MOMENTUM_BREAKOUT) return clrDarkGreen;
   if(r == REGIME_MEAN_REVERSION) return clrDarkRed;
   return clrDimGray;
}

//+------------------------------------------------------------------+
void DrawRegimeBackground() {
   if(!InpShowRegimeBg) return;
   int bars = MathMin(InpRegimeBars, Bars(_Symbol, PERIOD_CURRENT) - 2);
   if(bars <= 0) return;

   double priceMax = ChartGetDouble(0, CHART_PRICE_MAX);
   double priceMin = ChartGetDouble(0, CHART_PRICE_MIN);
   if(priceMax <= priceMin) return;

   for(int i = 0; i < bars; i++) {
      datetime t1 = iTime(_Symbol, PERIOD_CURRENT, i + 1);
      datetime t2 = iTime(_Symbol, PERIOD_CURRENT, i);

      ENUM_REGIME r = DetectRegimeAtBar(i + 1);
      color c = RegimeToColor(r);

      string name = "FX_Regime_" + IntegerToString(i);
      if(ObjectFind(0, name) < 0) {
         ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, priceMax, t2, priceMin);
      }
      ObjectSetInteger(0, name, OBJPROP_COLOR, c);
      ObjectSetInteger(0, name, OBJPROP_FILL, true);
      ObjectSetInteger(0, name, OBJPROP_BACK, true);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_TIMEFRAMES, OBJ_ALL_PERIODS);
      ObjectMove(0, name, 0, t1, priceMax);
      ObjectMove(0, name, 1, t2, priceMin);
   }

   ChartRedraw(0);
}

//+------------------------------------------------------------------+
int GetSignal(double &outSL, double &outTP) {
   ENUM_REGIME regime = DetectRegime();
   double close = iClose(_Symbol, PERIOD_CURRENT, 1);
   double high = iHigh(_Symbol, PERIOD_CURRENT, 1);
   double low = iLow(_Symbol, PERIOD_CURRENT, 1);

   if(CopyBuffer(handleATR, 0, 1, InpMBBreakoutLookback + 2, atrBuf) < InpMBBreakoutLookback + 2)
      return 0;

   double atrVal = atrBuf[0];
   if(atrVal <= 0) return 0;

   if(regime == REGIME_MEAN_REVERSION) {
      if(CopyBuffer(handleBB, 0, 1, 3, bbMiddle) < 3) return 0;
      if(CopyBuffer(handleBB, 1, 1, 3, bbUpper) < 3) return 0;
      if(CopyBuffer(handleBB, 2, 1, 3, bbLower) < 3) return 0;

      if(close <= bbLower[0]) {
         outSL = close - InpMRSLATRMult * atrVal;
         outTP = bbMiddle[0];
         return 1;
      }
      if(close >= bbUpper[0]) {
         outSL = close + InpMRSLATRMult * atrVal;
         outTP = bbMiddle[0];
         return -1;
      }
   }
   else if(regime == REGIME_MOMENTUM_BREAKOUT) {
      double rh = iHigh(_Symbol, PERIOD_CURRENT, 2);
      double rl = iLow(_Symbol, PERIOD_CURRENT, 2);
      for(int i = 3; i <= InpMBBreakoutLookback + 1; i++) {
         double h = iHigh(_Symbol, PERIOD_CURRENT, i);
         double l = iLow(_Symbol, PERIOD_CURRENT, i);
         if(h > rh) rh = h;
         if(l < rl) rl = l;
      }

      if(close > rh) {
         outSL = close - InpMBSLATRMult * atrVal;
         outTP = close + InpMBTPATRMult * atrVal;
         return 1;
      }
      if(close < rl) {
         outSL = close + InpMBSLATRMult * atrVal;
         outTP = close - InpMBTPATRMult * atrVal;
         return -1;
      }
   }

   return 0;
}

//+------------------------------------------------------------------+
double CalcLotSize(double entryPrice, double slPrice, bool isLong) {
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity <= 0) return InpMinLots;

   double stopDist = MathAbs(entryPrice - slPrice);
   if(stopDist <= 0) return InpMinLots;

   double riskAmount = equity * InpRiskPerTrade;
   double pointValue = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tickSize = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   if(tickSize <= 0) tickSize = 0.0001;

   double lotStep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double minLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double maxLot = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);

   double valuePerPoint = (pointValue / tickSize) * _Point;
   if(valuePerPoint <= 0) valuePerPoint = InpValuePerPoint;

   double lots = riskAmount / (stopDist * valuePerPoint);
   lots = MathMax(minLot, MathMin(maxLot, MathMin(InpMaxLots, lots)));
   lots = MathFloor(lots / lotStep) * lotStep;
   return MathMax(InpMinLots, lots);
}

//+------------------------------------------------------------------+
bool HasPosition() {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(posInfo.SelectByIndex(i)) {
         if(posInfo.Symbol() == _Symbol && posInfo.Magic() == InpMagic)
            return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
void ClosePositionIfReverse(int signal) {
   for(int i = PositionsTotal() - 1; i >= 0; i--) {
      if(!posInfo.SelectByIndex(i)) continue;
      if(posInfo.Symbol() != _Symbol || posInfo.Magic() != InpMagic) continue;

      long type = posInfo.PositionType();
      if((type == POSITION_TYPE_BUY && signal == -1) || (type == POSITION_TYPE_SELL && signal == 1)) {
         trade.PositionClose(posInfo.Ticket());
      }
   }
}

//+------------------------------------------------------------------+
void OnTick() {
   if(IsNewBar()) {
      DrawRegimeBackground();
   }
   if(!IsNewBar()) return;
   if(!IsSessionAllowed()) return;

   double sl = 0, tp = 0;
   int signal = GetSignal(sl, tp);

   if(signal == 0) return;
   if(!IsSpreadAcceptable()) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(HasPosition()) {
      ClosePositionIfReverse(signal);
      if(HasPosition()) return;
   }

   double lots = CalcLotSize(signal == 1 ? ask : bid, sl, signal == 1);
   if(lots < InpMinLots) return;

   double entryPrice = (signal == 1) ? ask : bid;
   EnforceLimitLevel(entryPrice, sl, tp);

   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);

   if(signal == 1) {
      if(!trade.Buy(lots, _Symbol, ask, sl, tp, "FX_Adaptive")) {
         Print("Buy failed: ", GetLastError());
      }
   }
   else {
      if(!trade.Sell(lots, _Symbol, bid, sl, tp, "FX_Adaptive")) {
         Print("Sell failed: ", GetLastError());
      }
   }
}
