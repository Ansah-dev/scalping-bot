import logging
import asyncio
import os
import time
import threading
import MetaTrader5 as mt5
from dotenv import load_dotenv, set_key
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes
from mt5_connection import connect_mt5
from scalping_engine import scalp_on_demand, execute_auto_scalp

load_dotenv()

# Setup Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# --- TELEGRAM CONVERSATION STATES ---
ACCOUNT_ID, PASSWORD, SERVER = range(3)

# ----------------- TELEGRAM HANDLERS -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Advanced Auto-Scalp Bot Online!\n"
        "Commands:\n"
        "/scalp [pair] - Manually test strategy\n"
        "/login - Change Prop Firm or Broker Account dynamically!"
    )

async def scalp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pair = context.args[0].upper() if context.args else "EURUSD"
    await update.message.reply_text(f"🔍 Analyzing and attempting manual scalp on {pair}...")
    
    # Run MT5 synchronous code in executor
    reply = await asyncio.to_thread(scalp_on_demand, pair)
    await update.message.reply_text(str(reply))

# --- DYNAMIC LOGIN HANDLERS ---
async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Let's configure your MT5 Account.\nPlease enter your MT5 Account ID (Numbers only):")
    return ACCOUNT_ID

async def login_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['account_id'] = update.message.text
    await update.message.reply_text("Great. Now, please enter your MT5 Password:")
    return PASSWORD

async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['password'] = update.message.text
    await update.message.reply_text("Got it. Finally, enter your Broker's Server Name exactly as it appears (e.g., Vebson-Server):")
    return SERVER

async def login_server(update: Update, context: ContextTypes.DEFAULT_TYPE):
    server = update.message.text
    acc_id = context.user_data['account_id']
    password = context.user_data['password']
    
    # Save to .env file dynamically so it persists after reboots
    env_file = os.path.join(os.path.dirname(__file__), '.env')
    set_key(env_file, "MT5_ACCOUNT_ID", acc_id)
    set_key(env_file, "MT5_PASSWORD", password)
    set_key(env_file, "MT5_SERVER", server)
    
    # Reload environment to apply to current instance
    load_dotenv(override=True)
    
    # Attempt connection dynamically!
    authorized = False
    try:
        # Properly initialize using the same robust logic from mt5_connection
        terminal_path = os.getenv("MT5_TERMINAL_PATH", "")
        init_kwargs = {}
        if terminal_path:
            init_kwargs["path"] = terminal_path
            
        if not mt5.initialize(**init_kwargs):
            logging.error(f"MT5 Initialize failed within Telegram Login. Error: {mt5.last_error()}")
            
        authorized = mt5.login(int(acc_id), password, server)
    except Exception as e:
        logging.error(f"Login exception: {e}")
    
    if authorized:
        await update.message.reply_text("✅ Success! Your bot is now permanently connected to the new broker/account!")
    else:
        err = mt5.last_error()
        await update.message.reply_text(f"❌ Failed to login. MT5 Error: {err}\nPlease ensure MetaTrader 5 is literally opened on your server screen, OR provide the MT5_TERMINAL_PATH in the .env file. Then try /login again.")
        
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Login process cancelled.")
    return ConversationHandler.END

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

    # 1. Connect MT5 initially (on boot) using whatever is in .env currently
    if not connect_mt5():
        print("⚠️ Warning: Initial MT5 connection failed. You can use /login in Telegram to fix it.")

    # 2. Start Background thread for Auto Scalping
    bg_thread = threading.Thread(target=background_loop, daemon=True)
    bg_thread.start()

    # 3. Start Telegram Bot
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("scalp", scalp_cmd))
    
    # Setup Conversation Handler for /login
    login_conv_handler = ConversationHandler(
        entry_points=[CommandHandler('login', login_start)],
        states={
            ACCOUNT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_account)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
            SERVER: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_server)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    app.add_handler(login_conv_handler)

    print("🚀 Telegram Bot is polling...")
    app.run_polling()

if __name__ == "__main__":
    main()