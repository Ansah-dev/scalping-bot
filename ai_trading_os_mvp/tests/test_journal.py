"""Tests du Journal minimal + base SQLite (schema.sql)."""
from __future__ import annotations

import pandas as pd
import pytest

from ai_trading_os_mvp.database.db import DEFAULT_DB_PATH, init_db
from ai_trading_os_mvp.decision.trade_signal import (
    Decision,
    DecisionResult,
    RiskDecision,
    RiskOutcome,
    ScannerFact,
    TradeSignal,
)
from ai_trading_os_mvp.journal.journal import Journal


@pytest.fixture()
def journal(tmp_path):
    db = tmp_path / "test.db"
    j = Journal(db_path=db)
    yield j
    j.close()


def seed_strategy_version(journal, strategy_id: int = 1, version: str = "1.0",
                          pair: str = "EURUSD") -> int:
    cur = journal.conn.execute(
        "INSERT INTO strategies (name) VALUES (?)", (f"strategy-{strategy_id}",))
    sid = cur.lastrowid
    cur = journal.conn.execute(
        """INSERT INTO strategy_versions
               (strategy_id, version, conditions_json, risk_percent, risk_reward,
                pair, timeframe, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (sid, version, '{"BOS": true, "FVG": true}', 0.5, 2.0, pair, "M5", 1))
    return int(cur.lastrowid)


def test_schema_initialise_depuis_schema_sql(tmp_path):
    conn = init_db(tmp_path / "schema.db")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {
        "accounts", "strategies", "strategy_versions", "decisions",
        "trade_signals", "risk_events", "orders", "trades", "system_logs",
    } <= tables
    conn.close()


def test_log_fact_trace_chaque_constat(journal):
    fact = ScannerFact(
        pair="EURUSD", timeframe="M5", fact_type="BOS",
        details={"side": "bull", "level": 1.2},
        timestamp=pd.Timestamp("2026-03-02 08:45"),
    )
    for _ in range(3):
        journal.log_fact(fact)
    assert journal.facts_count() == 3
    rows = journal.fetch(
        "SELECT message FROM system_logs WHERE component = 'MarketScanner'")
    assert all('"fact_type": "BOS"' in r["message"] for r in rows)


def test_log_decision_y_compris_wait(journal):
    svid = seed_strategy_version(journal, pair="GBPUSD")
    dec = Decision(pair="GBPUSD", result=DecisionResult.WAIT,
                   strategy_id=1, strategy_version="1.0",
                   reasoning_tags=["BOS"], wait_reason="PAS_DE_FVG")
    did = journal.log_decision(dec, strategy_version_id=svid)
    assert did > 0
    rows = journal.decisions()
    assert rows[0]["result"] == "WAIT"
    assert rows[0]["wait_reason"] == "PAS_DE_FVG"


def test_log_risk_rejected_avec_reason(journal):
    svid = seed_strategy_version(journal)
    dec = Decision(pair="EURUSD", result=DecisionResult.BUY,
                   strategy_id=1, strategy_version="1.0")
    ts = TradeSignal(decision=dec, entry=1.1, stop_loss=1.09,
                     take_profit=1.12, risk_reward=2.0)
    did = journal.log_decision(dec, strategy_version_id=svid)
    tsid = journal.log_trade_signal(ts, decision_id=did)

    risk = RiskDecision(trade_signal=ts, outcome=RiskOutcome.REJECTED,
                        reason="MAX_DAILY_LOSS")
    journal.log_risk_decision(risk, trade_signal_id=tsid)

    rejected = journal.rejected()
    assert any(r["reason"] == "MAX_DAILY_LOSS" for r in rejected)


def seed_account(journal) -> int:
    cur = journal.conn.execute(
        """INSERT INTO accounts (broker, account_type, balance, equity)
           VALUES ('SIMULATION', 'SIMULATION', 10000, 10000)""")
    return int(cur.lastrowid)


def test_log_trade_et_fermeture(journal):
    svid = seed_strategy_version(journal)
    acc = seed_account(journal)
    dec = Decision(pair="EURUSD", result=DecisionResult.BUY,
                   strategy_id=1, strategy_version="1.0")
    ts = TradeSignal(decision=dec, entry=1.1, stop_loss=1.09,
                     take_profit=1.12, risk_reward=2.0)
    did = journal.log_decision(dec, strategy_version_id=svid)
    tsid = journal.log_trade_signal(ts, decision_id=did)

    oid = journal.log_order(trade_signal_id=tsid, account_id=acc)
    tid = journal.log_position(order_id=oid, account_id=acc, pair="EURUSD",
                               direction="BUY", entry_price=1.10,
                               stop_loss=1.09, take_profit=1.12, lot_size=0.01)
    assert tid > 0
    journal.update_trade_close(tid, exit_price=1.12, pnl=2.0, r_multiple=2.0)
    assert journal.trades_count() == 1
    row = journal.fetch("SELECT pnl, r_multiple, closed_at, order_id FROM trades "
                        "WHERE id = ?", (tid,))[0]
    assert row["pnl"] == 2.0
    assert row["order_id"] == oid
    assert row["closed_at"] is not None