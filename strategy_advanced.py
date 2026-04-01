import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import ta

def get_data(pair, timeframe=mt5.TIMEFRAME_M5, size=100):
    rates = mt5.copy_rates_from_pos(pair, timeframe, 0, size)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def analyze_trend(df):
    """
    Very simple trend analysis using EMA50 and EMA200
    """
    df['ema50'] = ta.trend.EMAIndicator(df['close'], window=50).ema_indicator()
    df['ema200'] = ta.trend.EMAIndicator(df['close'], window=200).ema_indicator()

    current_close = df['close'].iloc[-1]
    if current_close > df['ema50'].iloc[-1] and df['ema50'].iloc[-1] > df['ema200'].iloc[-1]:
        return "UP"
    elif current_close < df['ema50'].iloc[-1] and df['ema50'].iloc[-1] < df['ema200'].iloc[-1]:
        return "DOWN"
    return "RANGE"

def find_fvg(df):
    """
    Check for Fair Value Gap on the last few closed candles.
    Bullish FVG: Low of candle[i] > High of candle[i-2]
    Bearish FVG: High of candle[i] < Low of candle[i-2]
    """
    if len(df) < 4:
        return None
        
    c1 = df.iloc[-4] # Older candle
    c2 = df.iloc[-3] # Middle candle (gap)
    c3 = df.iloc[-2] # Current closed candle

    # Bullish FVG
    if c3['low'] > c1['high'] and c2['close'] > c2['open']:
        return {"type": "BULLISH_FVG", "top": c3['low'], "bottom": c1['high']}
        
    # Bearish FVG
    if c3['high'] < c1['low'] and c2['close'] < c2['open']:
        return {"type": "BEARISH_FVG", "top": c1['low'], "bottom": c3['high']}
        
    return None

def analyze_strategy(pair):
    """
    Returns a dict with {"signal": "BUY"|"SELL"|"NONE", "sl": float, "tp": float}
    """
    df_m5 = get_data(pair, mt5.TIMEFRAME_M5, 300)
    df_m15 = get_data(pair, mt5.TIMEFRAME_M15, 300)
    
    if df_m5 is None or df_m15 is None:
        return {"signal": "NONE", "sl": 0, "tp": 0}

    trend = analyze_trend(df_m15)
    fvg = find_fvg(df_m5)
    
    current_close = df_m5['close'].iloc[-1]
    
    # We need highly specific setups for this risky scaling bot
    # E.g. If trend is UP, and we spot a Bullish FVG on M5.
    
    if trend == "UP" and fvg and fvg['type'] == "BULLISH_FVG":
        sl = fvg['bottom'] - (df_m5['close'].iloc[-1] * 0.001) # a small buffer
        tp = current_close + (current_close - sl) * 2 # 1:2 R:R target
        return {"signal": "BUY", "sl": sl, "tp": tp}
        
    elif trend == "DOWN" and fvg and fvg['type'] == "BEARISH_FVG":
        sl = fvg['top'] + (df_m5['close'].iloc[-1] * 0.001)
        tp = current_close - (sl - current_close) * 2
        return {"signal": "SELL", "sl": sl, "tp": tp}

    return {"signal": "NONE", "sl": 0, "tp": 0}
