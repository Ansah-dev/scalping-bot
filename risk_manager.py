import MetaTrader5 as mt5
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# --- CONFIGURATION (Can be moved to .env later) ---
PROP_FIRM_MODE = True
DAILY_DRAWDOWN_LIMIT_PERCENT = 4.0 # 4% daily drawdown limit
TOTAL_DRAWDOWN_LIMIT_PERCENT = 8.0 # 8% total max drawdown limit
XAUUSD_UNLOCK_EQUITY = 1000.0 # Only trade Gold if equity > $1000

# Ideally we store starting balance in a database, but we can approximate it
# by remembering the peak or the start-of-day balance.
starting_balance_today = None
highest_equity = None

def get_account_stats():
    """Retrieve MT5 account information."""
    acc = mt5.account_info()
    if acc is None:
        logger.error("Failed to retrieve account info")
        return None
    return acc

def initialize_risk_daily():
    """Call this on startup or at midnight to reset daily drawdown marks."""
    global starting_balance_today, highest_equity
    acc = get_account_stats()
    if acc:
        starting_balance_today = acc.balance
        highest_equity = acc.equity

def update_high_watermark(equity):
    global highest_equity
    if highest_equity is None or equity > highest_equity:
        highest_equity = equity

def check_prop_firm_drawdown():
    """
    Returns True if trading is ALLOWED.
    Returns False if a Prop Firm Drawdown rule has been breached.
    """
    acc = get_account_stats()
    if acc is None:
        return False
        
    current_equity = acc.equity
    
    # --- TARGET EQUITY CHECK ---
    from dotenv import load_dotenv, set_key
    import os
    load_dotenv(override=True)
    
    target_str = os.getenv("TARGET_EQUITY")
    if target_str:
        try:
            target_equity = float(target_str)
            if current_equity >= target_equity:
                notified = os.getenv("TARGET_NOTIFIED")
                if notified != "True":
                    logger.info(f"🎉 TARGET ATTAINED! ${current_equity} >= ${target_equity}. Closing all trades!")
                    # Lock in profit by closing all open trades
                    from mt5_trade import close_position
                    positions = mt5.positions_get()
                    if positions:
                        for pos in positions:
                            if pos.magic == 2024:
                                close_position(pos.ticket)
                    
                    from alerts_manager import broadcast_alert
                    broadcast_alert(f"🎉 GOAL ATTAINED! Your current equity is ${current_equity:.2f}, reaching your target of ${target_equity:.2f}. All trades have been secured and the bot is paused.")
                    
                    env_file = os.path.join(os.path.dirname(__file__), '.env')
                    set_key(env_file, "TARGET_NOTIFIED", "True")
                    
                return False # Halt all future trades
        except ValueError:
            pass

    if not PROP_FIRM_MODE:
        return True # Not prop firm mode, let it run unconditionally
        
    global starting_balance_today, highest_equity
    if starting_balance_today is None:
        initialize_risk_daily()
        
    update_high_watermark(current_equity)
    
    # Check Daily Drawdown
    if starting_balance_today > 0:
        daily_dd = ((starting_balance_today - current_equity) / starting_balance_today) * 100
        if daily_dd >= DAILY_DRAWDOWN_LIMIT_PERCENT:
            logger.warning(f"🚫 DAILY DRAWDOWN HIT! ({daily_dd:.2f}%). Shutting down trading.")
            return False
        
    # Check Max/Total Drawdown (Trailing from highest equity or initial balance)
    if highest_equity > 0:
        total_dd = ((highest_equity - current_equity) / highest_equity) * 100
        if total_dd >= TOTAL_DRAWDOWN_LIMIT_PERCENT:
            logger.warning(f"🚫 TOTAL MAX DRAWDOWN HIT! ({total_dd:.2f}%). Shutting down trading.")
            return False
        
    return True

def auto_lot(risk_percent=1.0):
    """
    Dynamic lot sizing based on account equity and a risk percentage.
    Very small accounts default to 0.01
    """
    acc = get_account_stats()
    if acc is None:
        return 0.01

    equity = acc.equity
    if equity < 100:
        # Micro account (like a $10 challenge)
        if equity >= 10.0: return 0.05
        if equity >= 5.0: return 0.02
        return 0.01
        
    # Standard dynamic calculation (assuming $10 risk per 0.01 lot roughly)
    # This varies per asset, but for a simple risk model:
    risk_amount = equity * (risk_percent / 100)
    # Using an approximate of $100 per 0.10 lot value ...
    calculated_lot = round((risk_amount / 100) * 0.10, 2)
    
    # Ensure minimum lot is 0.01
    return max(0.01, calculated_lot)

def can_trade_asset(pair):
    """
    Additional lockouts for specific assets like XAUUSD.
    Only trades gold if equity allows a safe buffer.
    """
    acc = get_account_stats()
    if acc is None:
        return False
        
    if pair == "XAUUSD":
        if acc.equity < XAUUSD_UNLOCK_EQUITY:
            logger.info(f"🔒 XAUUSD Locked. Equity (${acc.equity}) is below buffer (${XAUUSD_UNLOCK_EQUITY})")
            return False
            
    return True
