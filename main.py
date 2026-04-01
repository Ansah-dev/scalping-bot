import logging
import asyncio
import os
import time
import threading
from dotenv import load_dotenv
from telegram.ext import Application, CommandHandler
from mt5_connection import connect_mt5
from scalping_engine import scalp_on_demand, execute_auto_scalp

load_dotenv()

# Setup Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ----------------- TELEGRAM HANDLERS -----------------
async def start(update, context):
    await update.message.reply_text("🤖 Advanced Auto-Scalp Bot Online!\nPairs: EURUSD, BTCUSD, GBPUSD, USDCAD\nUse /scalp [pair] to manually test.")

async def scalp_cmd(update, context):
    pair = context.args[0].upper() if context.args else "EURUSD"
    await update.message.reply_text(f"🔍 Analyzing and attempting manual scalp on {pair}...")
    
    # Run MT5 synchronous code in executor
    reply = await asyncio.to_thread(scalp_on_demand, pair)
    await update.message.reply_text(str(reply))

# ----------------- BACKGROUND SCALPER -----------------
def background_loop():
    logging.info("Starting background MT5 auto-scalper loop...")
    while True:
        try:
            execute_auto_scalp()
        except Exception as e:
            logging.error(f"Error in auto scaler: {e}")
        # Run every 60 seconds (M1 equivalent check rate)
        time.sleep(60)

# ----------------- MAIN ENTRYPOINT -------------------
def main():
    if not TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN not found in .env")
        return

    # 1. Connect MT5
    if not connect_mt5():
        print("❌ Could not start bot: MT5 Connection Failed.")
        return

    # 2. Start Background thread for Auto Scalping
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    # 3. Start Telegram Bot
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scalp", scalp_cmd))

    print("🚀 Telegram Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()