import os
import logging
import google.generativeai as genai
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Configure Gemini
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    # Using Flash for speed since scalping is time-sensitive
    # But it can be swapped to gemini-1.5-pro if deeper analysis is needed.
    model = genai.GenerativeModel('gemini-1.5-flash') 
else:
    model = None

def consult_ai_for_trade(pair, signal_data, order_flow_text):
    """
    Feeds the extracted data (Trend, FVG, Order Flow) into Gemini.
    Returns: (bool, str) -> (Approved, Reason)
    """
    if not model:
        logger.warning("No Gemini API Key found. Skipping AI confirmation.")
        return True, "No AI Key - Auto Approved by default"

    prompt = f"""
    You are an expert, highly profitable MT5 Forex Scalping AI.
    
    CURRENT MARKET STATE FOR {pair}:
    - Technical Analysis Signal: {signal_data['signal']} 
    - Proposed Stop Loss: {signal_data['sl']}
    - Proposed Take Profit: {signal_data['tp']}
    - LIVE Order Flow Data: {order_flow_text}
    
    Given this data, if the Order Flow strictly contradicts the Technical Signal (e.g. signal is BUY but Sellers Volume is heavily dominant), you MUST reject the trade.
    If the Order Flow supports or is neutral to the Technical Signal, you MUST approve the trade.
    
    Reply in strictly this format:
    DECISION: [APPROVED or REJECTED]
    REASON: [1 sentence explaining why based on the volume]
    """

    try:
        response = model.generate_content(prompt)
        reply = response.text.upper()
        
        reasoning = response.text.split("REASON:")[-1].strip() if "REASON:" in response.text else "AI did not provide reasoning."
        
        if "DECISION: APPROVED" in reply:
            return True, reasoning
        else:
            return False, reasoning
            
    except Exception as e:
        logger.error(f"Gemini API Error: {e}")
        # If API fails, we reject the trade to be safe, or approve. Let's reject to be safe.
        return False, f"API Error: {e}"
