import MetaTrader5 as mt5
from mt5_trade import place_order, close_position
from strategy_advanced import analyze_strategy
from fundamentals import can_trade
import logging

logger = logging.getLogger(__name__)

# User specific requested pairs
PAIRS = ["EURUSD", "BTCUSD", "GBPUSD", "USDCAD"]

from risk_manager import auto_lot, check_prop_firm_drawdown, can_trade_asset
from data_extractor import get_current_state_summary
from ai_brain import consult_ai_for_trade

def execute_auto_scalp():
    """Run continuously in a background loop."""
    if not check_prop_firm_drawdown():
        return # Locked out by Prop Firm Rules

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

        # 3. Check News / Fundamentals and Asset Lockouts
        if not can_trade(pair) or not can_trade_asset(pair):
            continue

        # 4. Check Strategy & Extract Order Flow Data
        signal_data = analyze_strategy(pair)
        
        # Pull rich data (for AI later and immediate context)
        order_flow_text = get_current_state_summary(pair)
        
        lot = auto_lot()
        
        if signal_data["signal"] in ["BUY", "SELL"]:
            logger.info(f"Checking AI for {pair}... {order_flow_text}")
            is_approved, ai_reason = consult_ai_for_trade(pair, signal_data, order_flow_text)
            
            if not is_approved:
                logger.info(f"🚫 AI REJECTED {pair} {signal_data['signal']}. AI Reason: {ai_reason}")
                continue
                
            logger.info(f"🤖 AI APPROVED {pair} {signal_data['signal']}. AI Reason: {ai_reason}")
            
            if signal_data["signal"] == "BUY":
                place_order(pair, mt5.ORDER_TYPE_BUY, lot, signal_data["sl"], signal_data["tp"])
            else:
                place_order(pair, mt5.ORDER_TYPE_SELL, lot, signal_data["sl"], signal_data["tp"])

def scalp_on_demand(pair):
    """Used for Telegram manual trigger"""
    if not check_prop_firm_drawdown():
        return "⚠️ Trading locked due to Daily/Max Drawdown Limit!"
        
    if not can_trade(pair) or not can_trade_asset(pair):
        return f"⚠️ Trading blocked for {pair} due to News or Equity restrictions!"
        
    signal_data = analyze_strategy(pair)
    lot = auto_lot()
    
    if signal_data["signal"] in ["BUY", "SELL"]:
        order_flow_text = get_current_state_summary(pair)
        is_approved, ai_reason = consult_ai_for_trade(pair, signal_data, order_flow_text)
        
        if not is_approved:
            return f"🚫 AI REJECTED {pair} {signal_data['signal']}.\nOrder Flow: {order_flow_text}\nAI Reasoning: {ai_reason}"
            
        if signal_data["signal"] == "BUY":
            res = place_order(pair, mt5.ORDER_TYPE_BUY, lot, signal_data["sl"], signal_data["tp"])
            if "error" in res: return f"Error: {res['error']}"
            return f"✅ AI APPROVED BUY on {pair} ({lot} lots).\nReason: {ai_reason}\nTicket: {res['ticket']}"
        else:
            res = place_order(pair, mt5.ORDER_TYPE_SELL, lot, signal_data["sl"], signal_data["tp"])
            if "error" in res: return f"Error: {res['error']}"
            return f"✅ AI APPROVED SELL on {pair} ({lot} lots).\nReason: {ai_reason}\nTicket: {res['ticket']}"
        
    return "WAIT — No trade signal detected currently."