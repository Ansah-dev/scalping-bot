import MetaTrader5 as mt5
from mt5_trade import place_order, close_position
from strategy_advanced import analyze_strategy
from fundamentals import can_trade
import logging

logger = logging.getLogger(__name__)

# User specific requested pairs
PAIRS = ["EURUSD", "BTCUSD", "GBPUSD", "USDCAD"]

def auto_lot():
    acc = mt5.account_info()
    if acc is None:
        return 0.01
    
    # For a $2 to $10 challenge, maximum lot based on max leverage.
    # Warning: Account is so small that 0.01 is often the smallest, and is highly leveraged.
    # If equity > $5, we could increase to 0.02.
    equity = acc.equity
    if equity >= 10.0:
        return 0.05
    elif equity >= 5.0:
        return 0.02
        
    return 0.01

def execute_auto_scalp():
    """Run continuously in a background loop."""
    acc = mt5.account_info()
    if acc is None:
        return

    # 1. Manage existing positions (The "50% Gain Auto Collect" Rule)
    # The user said: "when there is a gain of 50% the bot automatically collect the position"
    # We interpret this as: if an open position's profit is >= 50% of the current Account Balance.
    positions = mt5.positions_get()
    if positions:
        for pos in positions:
            if pos.magic == 2024: # Our bot's magic number
                target_profit = acc.balance * 0.50
                # Or another interpretation: 50% of margin used. Let's use 50% of balance as it scales $2 to $10.
                if pos.profit >= target_profit:
                    logger.info(f"Target 50% reached on ticket {pos.ticket}. Closing...")
                    close_position(pos.ticket)

    # 2. Find new trades
    for pair in PAIRS:
        # Check if we already have an open position for this pair
        pos_for_pair = [p for p in (positions or []) if p.symbol == pair and p.magic == 2024]
        if pos_for_pair:
            continue # Don't open multiple trades per pair at the same time to limit risk

        # 3. Check News / Fundamentals
        if not can_trade(pair):
            continue

        # 4. Check Strategy
        signal_data = analyze_strategy(pair)
        
        lot = auto_lot()
        
        if signal_data["signal"] == "BUY":
            logger.info(f"BUY Signal for {pair}. Risking lot {lot}")
            place_order(pair, mt5.ORDER_TYPE_BUY, lot, signal_data["sl"], signal_data["tp"])
        elif signal_data["signal"] == "SELL":
            logger.info(f"SELL Signal for {pair}. Risking lot {lot}")
            place_order(pair, mt5.ORDER_TYPE_SELL, lot, signal_data["sl"], signal_data["tp"])

def scalp_on_demand(pair):
    """Used for Telegram manual trigger"""
    if not can_trade(pair):
        return f"Trading blocked for {pair} due to upcoming High Impact News!"
        
    signal_data = analyze_strategy(pair)
    lot = auto_lot()
    
    if signal_data["signal"] == "BUY":
        res = place_order(pair, mt5.ORDER_TYPE_BUY, lot, signal_data["sl"], signal_data["tp"])
        if "error" in res: return res["error"]
        return f"✅ BUY Order placed on {pair} at {lot} lots. Ticket: {res['ticket']}"
        
    elif signal_data["signal"] == "SELL":
        res = place_order(pair, mt5.ORDER_TYPE_SELL, lot, signal_data["sl"], signal_data["tp"])
        if "error" in res: return res["error"]
        return f"✅ SELL Order placed on {pair} at {lot} lots. Ticket: {res['ticket']}"
        
    return "WAIT — No trade signal detected currently."