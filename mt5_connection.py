mport MetaTrader5 as mt5

# Change this to your MT5 login details
ACCOUNT_ID = 12345678
PASSWORD = "YOUR_MT5_PASSWORD"
SERVER = "YOUR_BROKER_SERVER"


def connect_mt5():
    print("Connecting to MT5...")

    if not mt5.initialize():
        print("❌ MT5 initialization failed")
        return False

    authorized = mt5.login(ACCOUNT_ID, PASSWORD, SERVER)

    if authorized:
        print("✅ Connected to MT5 account:")
        print(mt5.account_info())
        return True
    else:
        print("❌ Login failed. Check credentials.")
        return False


if __name__ == "__main__":
    connect_mt5()