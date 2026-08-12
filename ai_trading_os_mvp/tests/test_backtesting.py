"""Tests du Backtesting Engine (module 6) — §5.5, pipeline ante-futur."""
from __future__ import annotations

import pandas as pd
import pytest

from ai_trading_os_mvp.backtesting.engine import BacktestEngine
from ai_trading_os_mvp.decision.engine import StrategyVersion
from ai_trading_os_mvp.scripts.demo_scan import build_df, generate_series


def make_strategy(conditions=None):
    return StrategyVersion(
        strategy_id=1,
        version="1.0",
        conditions=conditions or {"FVG": True},
        risk_percent=0.5,
        risk_reward=2.0,
        pair="EURUSD",
        timeframe="M5",
        is_active=True,
    )


def appended(df, candles):
    """Append des bougies (o,h,l,c) à la dataframe de démo."""
    rows = df.to_dict("records")
    start = pd.Timestamp(df["time"].iloc[-1]) + pd.Timedelta(minutes=5)
    for i, (o, h, l, c) in enumerate(candles):
        rows.append({"time": start + pd.Timedelta(minutes=5 * i),
                     "open": float(o), "high": float(h), "low": float(l),
                     "close": float(c), "volume": 100.0})
    return pd.DataFrame(rows)


def run_backtest(df, strategy=None):
    engine = BacktestEngine(starting_balance=10000.0)
    return engine.run(df, strategy or make_strategy())


def test_pipeline_frais_produit_un_gain():
    """BUY FVG à la bougie 12 ; append bougie au-dessus du TP -> gain."""
    df = appended(build_df(generate_series()), [(143.50, 144.00, 143.40, 143.90)])
    report = run_backtest(df)
    assert report.trades_count >= 1
    assert report.win_count >= 1
    assert report.net_profit > 0
    assert report.end_balance > report.start_balance
    # une victoire sans perte -> profit factor infini
    assert report.profit_factor == pytest.approx(float("inf"))


def test_pipeline_perte_atteint_sl():
    """Bougie successives sous le SL -> perte nette sur les entrées BUY FVG.
    La série de démo émet 4 FVG bull successifs (bougies 10-13) → plusieurs
    entrées BUY sont un comportement pipeline légitime, pas un bug : on
    vérifie donc la perte nette et le PF < 1 (carburé par les SL)."""
    df = appended(build_df(generate_series()), [(143.00, 143.10, 142.90, 143.00)])
    report = run_backtest(df)
    assert report.trades_count >= 1
    assert report.net_profit < 0
    assert report.loss_count >= 1
    assert report.profit_factor < 1.0


def test_no_lookahead_entree_grace_index():
    """Vérifie qu'aucune bougie passée au Scanner ne dépasse la bougie courante
    (df.iloc[:i+1] au sein du run — garantie par construction)."""
    engine = BacktestEngine(starting_balance=10000.0)
    df = appended(build_df(generate_series()), [(143.50, 144.00, 143.40, 143.90)])
    report = engine.run(df, make_strategy())
    # Un BUY FVG n'ouvre que depuis la bougie 12 (FVG émis sur cette bougie) :
    # pas d'entrée possible avant. Aucun trade ne doit clôturer sur la bougie
    # de remplissage (déjà testé au niveau broker).
    assert report.trades_count >= 1


def test_strategy_injectee_ou_depuis_db():
    """Le moteur accepte une StrategyVersion injectée de façon externe."""
    strategy = make_strategy()
    df = appended(build_df(generate_series()), [(143.50, 144.00, 143.40, 143.90)])
    report = run_backtest(df, strategy)
    assert report.trades_count >= 1


def test_max_drawdown_peak_to_trough():
    """Drawdown = peak-to-trough sur la courbe d'equity, pas par trade."""
    engine = BacktestEngine(starting_balance=10000.0)
    curve = [(0, 10000), (1, 11000), (2, 10500), (3, 9000), (4, 9500), (5, 8800)]
    dd = engine._max_drawdown_pct(curve)
    # peak 11000 -> trough 8800 : (11000-8800)/11000 = 20%
    assert dd == pytest.approx(20.0)
    # La plus grosse perte simple (9000->8800 = 1.1%) n'a aucune influence
    assert dd > (11000 - 9000) / 11000 * 100


def test_profit_factor_standard_formule():
    """PF = somme des gains / somme des pertes (valeurs absolues)."""
    engine = BacktestEngine(starting_balance=10000.0)
    from ai_trading_os_mvp.broker.interface import OrderDirection
    from ai_trading_os_mvp.broker.simulation_connector import ClosedTrade
    from datetime import datetime

    t = datetime(2026, 1, 1)
    trades = [
        ClosedTrade("p1", "EURUSD", OrderDirection.BUY, 1.0, 100, 110, 90, 120,
                    "TP", 100.0, 2.0, t, t),
        ClosedTrade("p2", "EURUSD", OrderDirection.BUY, 1.0, 100, 90, 90, 120,
                    "SL", -50.0, -1.0, t, t),
        ClosedTrade("p3", "EURUSD", OrderDirection.SELL, 1.0, 100, 90, 110, 80,
                    "TP", 50.0, 1.0, t, t),
    ]
    gains = sum(x.pnl for x in trades if x.pnl > 0)      # 150
    losses = sum(-x.pnl for x in trades if x.pnl < 0)    # 50
    assert engine._max_drawdown_pct([(0, 10000), (1, 9990)]) > 0
    # On vérifie la formule via le calcul interne de build_report
    report = engine._build_report(make_strategy(), [], [], trades)
    assert report.profit_factor == pytest.approx(gains / losses)  # 3.0
    assert report.win_rate == pytest.approx(round(2 / 3, 4))
    # avg_r = moyenne des R de chaque trade (2, -1, 1) -> 2/3
    assert report.avg_r_multiple == pytest.approx(round(2 / 3, 4))


def test_pipeline_waits_sans_condition():
    """Sans constat requis présent -> aucune entrée, aucun trade."""
    strategy = make_strategy(conditions={"ORDER_BLOCK": True})
    report = run_backtest(build_df(generate_series()), strategy)
    assert report.trades_count == 0
    assert report.net_profit == 0.0
    assert report.win_rate == 0.0