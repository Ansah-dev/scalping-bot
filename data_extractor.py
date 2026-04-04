import MetaTrader5 as mt5
import pandas as pd
import logging

logger = logging.getLogger(__name__)

def get_order_flow(pair, ticks=1000):
    """
    Pulls recent tick data to determine Order Flow (Buyers vs Sellers Volume).
    Ticks at the Ask price are considered BUY market orders.
    Ticks at the Bid price are considered SELL market orders.
    """
    tick_data = mt5.copy_ticks_from_pos(pair, ticks, mt5.COPY_TICKS_ALL)
    
    if tick_data is None or len(tick_data) == 0:
        return {"buyers_vol": 0, "sellers_vol": 0, "net_delta": 0, "dominant": "NONE"}
        
    df = pd.DataFrame(tick_data)
    
    # Flags in MT5 tick data:
    # TICK_FLAG_BUY = 32
    # TICK_FLAG_SELL = 64
    # We can approximate by checking if price moved up to ask or down to bid
    
    buyers_vol = 0
    sellers_vol = 0
    
    for i in range(1, len(df)):
        current = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Determine based on flag if available, else use price delta
        if "flags" in df.columns:
            flags = current["flags"]
            if flags & 32: # BUY
                buyers_vol += current["volume"]
            elif flags & 64: # SELL
                sellers_vol += current["volume"]
            else:
                # Fallback to price action direction
                if current["ask"] > prev["ask"]: buyers_vol += current["volume"]
                elif current["bid"] < prev["bid"]: sellers_vol += current["volume"]
                
    net_delta = buyers_vol - sellers_vol
    dominant = "BUYERS" if net_delta > 0 else "SELLERS" if net_delta < 0 else "NEUTRAL"
    
    return {
        "buyers_vol": buyers_vol,
        "sellers_vol": sellers_vol,
        "net_delta": net_delta,
        "dominant": dominant
    }

def get_current_state_summary(pair):
    """
    Packages the order flow into a neat string for the AI or logging.
    """
    flow = get_order_flow(pair)
    return (f"[{pair} Order Flow] dominant: {flow['dominant']}, "
            f"Buyers Vol: {flow['buyers_vol']}, Sellers Vol: {flow['sellers_vol']}, " 
            f"Net Delta: {flow['net_delta']}")
