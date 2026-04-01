print("Bot started")

import time

def get_data():
    print("Getting data...")

def analyze():
    print("Analyzing...")
    return "BUY"

def execute(signal):
    print("Executing:", signal)

while True:
    get_data()
    signal = analyze()
    execute(signal)
    time.sleep(5)