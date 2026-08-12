"""Intégration — câblage Journal <-> SimulationBroker (§5.6).

Un backtest complet branché sur un Journal SQLite doit persister toute la
chaîne : decisions -> trade_signals -> risk_events -> orders -> trades
(avec pnl/r_multiple de clôture). Aucune écriture silencieuse perdue.
"""
from __future__ import annotations

import pytest

from ai_trading_os_mvp.backtesting.engine import BacktestEngine
from ai_trading_os_mvp.decision.engine import StrategyVersion
from ai_trading_os_mvp.journal.journal import Journal
from ai_trading_os_mvp.scripts.demo_scan import build_df, generate_series


def seed_strategy(journal, pair="EURUSD"):
    cur = journal.conn.execute("INSERT INTO strategies (name) VALUES (?)",
                               ("strategy-1",))
    strategy_id = int(cur.lastrowid)
    cur = journal.conn.execute(
        """INSERT INTO strategy_versions
               (strategy_id, version, conditions_json, risk_percent, risk_reward,
                pair, timeframe, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (strategy_id, "1.0", '{"FVG": true}', 0.5, 2.0,
         pair, "M5", 1))
    sv_id = int(cur.lastrowid)
    return StrategyVersion(
        strategy_id=strategy_id, version="1.0",
        conditions={"FVG": True},
        risk_percent=0.5, risk_reward=2.0,
        pair=pair, timeframe="M5", is_active=True,
        strategy_version_id=sv_id,
    )


@pytest.fixture()
def journal(tmp_path):
    j = Journal(db_path=tmp_path / "wire.db")
    yield j
    j.close()


def test_cablage_decision_signal_risk_order_trade(journal):
    """Chaîne SQLite complète persistée quand la stratégie est persistée."""
    strategy = seed_strategy(journal)
    df = build_df(generate_series())
    engine = BacktestEngine(journal=journal, starting_balance=10000.0)
    report = engine.run(df, strategy)

    assert report.trades_count >= 1
    # Le rapport compte les trades CLÔTURÉS ; le journal a aussi les
    # positions encore ouvertes en fin de série (log_position).
    closed_in_db = journal.fetch(
        "SELECT COUNT(*) AS n FROM trades WHERE closed_at IS NOT NULL")[0]["n"]
    assert closed_in_db == report.trades_count

    # Chaque trade a un ordre, un signal, une decision, un évènement risque
    row = journal.fetch("""
        SELECT t.id AS trade_id, t.pnl, t.r_multiple, t.closed_at,
               o.id AS order_id, ts.id AS signal_id, d.id AS decision_id,
               re.id AS risk_event_id, t.direction, t.entry_price
        FROM trades t
        JOIN orders o ON o.id = t.order_id
        JOIN trade_signals ts ON ts.id = o.trade_signal_id
        JOIN decisions d ON d.id = ts.decision_id
        LEFT JOIN risk_events re ON re.trade_signal_id = ts.id
        WHERE t.closed_at IS NOT NULL
        ORDER BY t.id LIMIT 1
    """)[0]

    assert row["closed_at"] is not None          # clôture relayée
    assert row["pnl"] is not None                # pnl relayé
    assert row["risk_event_id"] is not None      # approuvé + tracé
    assert row["direction"] in ("BUY", "SELL")
    assert row["entry_price"] > 0


def test_cablage_rejet_broker_trace_pas_de_trade(journal):
    """Un rejet broker : signal+risk tracés, 0 trade fantôme.

    Sur la doc série, pas de rejet broker attendu (niveaux FVG dans leur
    bougie par construction) — on vérifie donc la cohérence : les counts
    du journal correspondent exactement à ceux du rapport.
    """
    strategy = seed_strategy(journal)
    engine = BacktestEngine(journal=journal, starting_balance=10000.0)
    df = build_df(generate_series())
    report = engine.run(df, strategy)

    assert report.rejected_fills == 0
    closed_in_db = journal.fetch(
        "SELECT COUNT(*) AS n FROM trades WHERE closed_at IS NOT NULL")[0]["n"]
    assert closed_in_db == report.trades_count


def test_cablage_strategie_non_persistee_trace_rien(journal):
    """Sans strategy_version_id, le pipeline tourne SANS écrire (traçage off)."""
    df = build_df(generate_series())
    strategy = StrategyVersion(
        strategy_id=99, version="1.0",
        conditions={"FVG": True}, risk_percent=0.5, risk_reward=2.0,
        pair="EURUSD", timeframe="M5", is_active=True,
        strategy_version_id=None,  # non persistée
    )
    engine = BacktestEngine(journal=journal, starting_balance=10000.0)
    report = engine.run(df, strategy)

    # Aucune écriture dans decisions/trades (FK ignorée, pas d'erreur)
    assert journal.trades_count() == 0
    assert len(journal.decisions()) == 0


def test_cablage_relie_pnl_journal_au_rapport(journal):
    """Le pnl SQLite total correspond au profit net du rapport backtest."""
    strategy = seed_strategy(journal)
    df = build_df(generate_series())
    engine = BacktestEngine(journal=journal, starting_balance=10000.0)
    report = engine.run(df, strategy)

    rows = journal.fetch("SELECT COALESCE(SUM(pnl), 0) AS total FROM trades")
    assert abs(rows[0]["total"] - report.net_profit) < 0.05