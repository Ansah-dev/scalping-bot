"""Démo du Market Scanner — à vérifier avec l'œil humain (module 1).

Génère un CSV M5 fictif (série synthétique) puis fait tourner le scanner
dessus, en affichant chaque ScannerFact détecté en clair, bougie par
bougie, afin de vérifier visuellement que les constats correspondent à
ce qu'on voit sur les bougies.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_trading_os_mvp.market.scanner import MarketScanner
from ai_trading_os_mvp.journal.journal import Journal

OUT_CSV = "/home/desmond/scalping-bot/ai_trading_os_mvp/data/demo_m5.csv"


def candle(o, h, l, c):
    return (o, h, l, c)


def generate_series():
    """Série M5 synthétique construite pour faire apparaître, dans l'ordre,
    un sweep du swing low, un BOS haussier, un FVG haussier, puis un CHoCH
    baissier — chacun sur la bougie attendue (voir commentaires)."""
    candles = [
        # -- Range initial : swing low @4 (142.42), swing high @3 (142.75)
        (142.60, 142.70, 142.40, 142.55),   # 0
        (142.55, 142.65, 142.45, 142.60),   # 1
        (142.60, 142.70, 142.44, 142.50),   # 2
        (142.50, 142.75, 142.43, 142.70),   # 3  swing high 142.75
        (142.70, 142.74, 142.42, 142.45),   # 4  swing low 142.42
        (142.45, 142.50, 142.43, 142.48),   # 5
        (142.48, 142.72, 142.46, 142.70),   # 6  confirme swing high @3
        (142.70, 142.74, 142.46, 142.50),   # 7  confirme swing low @4
        # -- SWEEP bear (idx 8) : mèche 142.35 sous le swing low 142.42,
        #    mais close 142.55 au-dessus -> pas un BOS
        (142.50, 142.55, 142.35, 142.55),   # 8  SWEEP
        # -- BOS bull (idx 9) : close 142.85 au-dessus du swing high 142.75
        (142.60, 142.90, 142.58, 142.85),   # 9  BOS
        # -- Montée : FVG haussier (idx 12) low[12] > high[10]
        (142.85, 143.05, 142.82, 143.00),   # 10
        (143.00, 143.10, 142.98, 143.05),   # 11
        (143.05, 143.35, 143.25, 143.30),   # 12 FVG bull (143.25 > 143.05)
        # -- Sommet + pullback : swing high @13 (143.45), swing low @15 (143.20)
        (143.30, 143.45, 143.28, 143.40),   # 13 swing high 143.45
        (143.40, 143.42, 143.25, 143.30),   # 14
        (143.30, 143.35, 143.20, 143.25),   # 15 swing low 143.20
        (143.25, 143.42, 143.22, 143.38),   # 16 confirme swing high @13
        (143.38, 143.40, 143.25, 143.30),   # 17
        (143.30, 143.35, 143.22, 143.26),   # 18 confirme swing low @15
        # -- CHoCH bear (idx 19) : close 143.14 sous le swing low 143.20
        (143.26, 143.28, 143.10, 143.14),   # 19 CHoCH
    ]
    return candles


def build_df(candles):
    rows = []
    start = pd.Timestamp("2026-03-02 08:00")
    for i, (o, h, l, c) in enumerate(candles):
        rows.append({"time": start + pd.Timedelta(minutes=5 * i),
                     "open": float(o), "high": float(h), "low": float(l),
                     "close": float(c), "volume": 100.0})
    return pd.DataFrame(rows)


def main() -> None:
    candles = generate_series()
    df = build_df(candles)
    df.to_csv(OUT_CSV, index=False)
    print(f"CSV écrit: {OUT_CSV} ({len(df)} bougies M5)\n")

    journal = Journal(db_path="/tmp/demo_scanner.db")
    facts = MarketScanner(journal=journal).scan("EURUSD", "M5", df)
    facts_by_idx: dict[int, list] = {}
    for f in facts:
        i = df.index[df["time"] == pd.Timestamp(f.timestamp)][0]
        facts_by_idx.setdefault(i, []).append(f)

    print("Bougies OHLC (vérification visuelle) :")
    print(f"{'idx':>3}  {'open':>7} {'high':>7} {'low':>7} {'close':>7}   constats")
    print("-" * 78)
    for idx, row in df.iterrows():
        tags = []
        for f in facts_by_idx.get(idx, []):
            d = f.details
            level = d.get("level", d.get("top", d.get("index", "")))
            tags.append(f"{f.fact_type.replace('LIQUIDITY_', 'Sweep_')}({d['side']}, {level})")
        print(f"{idx:>3}  {row['open']:>7.2f} {row['high']:>7.2f} "
              f"{row['low']:>7.2f} {row['close']:>7.2f}   {'  '.join(tags)}")

    print("\nDétail des constats :")
    for f in facts:
        i = df.index[df["time"] == pd.Timestamp(f.timestamp)][0]
        print(f"  [{i}] {f.timestamp:%b %d %H:%M}  {f.fact_type:<16} {f.details}")
    print(f"\nTotal constats: {len(facts)}")

    print(f"\nJournal SQLite (/tmp/demo_scanner.db) :")
    print(f"  ScannerFacts tracés : {journal.facts_count()}")
    rows = journal.fetch(
        "SELECT message FROM system_logs WHERE component = 'MarketScanner' "
        "ORDER BY id LIMIT 3")
    for r in rows:
        print(f"  {r['message']}")
    journal.close()


if __name__ == "__main__":
    main()