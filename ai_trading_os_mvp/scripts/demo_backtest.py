"""Démo du Backtesting Engine (module 6) — pipeline complet ante-futur.

Enchaîne Market Scanner -> Decision Engine -> Risk Manager ->
Simulation Broker sur la série M5 de démo et affiche le rapport :
win rate, profit factor, drawdown max (peak-to-trough), RR moyen,
courbe d'equity sommaire et performance par paire/mois.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_trading_os_mvp.backtesting.engine import BacktestEngine
from ai_trading_os_mvp.decision.engine import StrategyVersion
from ai_trading_os_mvp.scripts.demo_scan import build_df, generate_series


def main() -> None:
    df = build_df(generate_series())

    strategy = StrategyVersion(
        strategy_id=1,
        version="1.0",
        conditions={"FVG": True},
        risk_percent=0.5,
        risk_reward=2.0,
        pair="EURUSD",
        timeframe="M5",
        is_active=True,
    )

    engine = BacktestEngine(starting_balance=10000.0)
    report = engine.run(df, strategy)

    print("=" * 62)
    print("Backtest — EURUSD M5 (série synthétique de démo, 20 bougies)")
    print("=" * 62)
    print(f"Conditions stratégie : {strategy.conditions}")
    print(f"Risque / RR          : {strategy.risk_percent:.2f}% / {strategy.risk_reward:.1f}\n")

    print(f"Balance départ       : {report.start_balance:>10.2f}")
    print(f"Balance fin          : {report.end_balance:>10.2f}")
    print(f"Profit net           : {report.net_profit:>+10.2f}")
    print(f"Trades               : {report.trades_count:>10}")
    print(f"Gains / Pertes       : {report.win_count:>6} / {report.loss_count:>7}")
    print(f"Win rate             : {report.win_rate * 100:>9.2f}%")
    print(f"Profit factor        : {report.profit_factor:>10.4f}")
    print(f"Drawdown max (peak-trough) : {report.max_drawdown_pct:>7.2f}%")
    print(f"RR moyen             : {report.avg_r_multiple:>10.4f} R")

    print("\nTrades exécutés :")
    print(f"{'exit':>6} {'dir':>5} {'entry':>9} {'exitPx':>9} {'pnl':>10} {'R':>8}")
    for t in report.trades:
        print(f"{t.exit_reason:>6} {t.direction.value:>5} {t.entry_price:>9.4f} "
              f"{t.exit_price:>9.4f} {t.pnl:>+10.2f} {t.r_multiple:>8.2f}")

    print("\nPerformance par paire :")
    for pair, d in report.perf_by_pair.items():
        print(f"  {pair:>8}  {d['trades']} trades, pnl {d['pnl']:+.2f}")
    print("Performance par mois :")
    for month, d in report.perf_by_month.items():
        print(f"  {month:>8}  {d['trades']} trades, pnl {d['pnl']:+.2f}")

    print(f"\nCourbe d'equity (fin de bougie) :")
    for ts, eq in report.equity_curve:
        print(f"  {ts:%m-%d %H:%M}  {eq:>10.2f}")


if __name__ == "__main__":
    main()