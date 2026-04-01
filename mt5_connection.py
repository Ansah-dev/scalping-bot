import MetaTrader5 as mt5
import os
from dotenv import load_dotenv

load_dotenv()

ACCOUNT_ID = int(os.getenv("MT5_ACCOUNT_ID", "0"))
PASSWORD = os.getenv("MT5_PASSWORD", "")
SERVER = os.getenv("MT5_SERVER", "")
TERMINAL_PATH = os.getenv("MT5_TERMINAL_PATH", "")

def connect_mt5():
    print("Connecting to MT5...")

    init_kwargs = {}
    if TERMINAL_PATH:
        init_kwargs["path"] = TERMINAL_PATH

    if not mt5.initialize(**init_kwargs):
        print(f"❌ MT5 initialization failed. Error: {mt5.last_error()}")
        return False

    authorized = mt5.login(ACCOUNT_ID, PASSWORD, SERVER)

    if authorized:
        print("✅ Connected to MT5 account")
        return True
    else:
        print(f"❌ Login failed. Check credentials. Error: {mt5.last_error()}")
        return False

if __name__ == "__main__":
    connect_mt5()