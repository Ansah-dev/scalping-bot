"""
Journal MVP (§5.6) — toute opportunité est tracée, pas seulement les trades.

Enregistre dans SQLite (schema.sql) : chaque ScannerFact, chaque Decision
(y compris WAIT avec wait_reason), chaque RiskDecision (y compris REJECTED
avec reason) et chaque trade exécuté. Répond à la question « combien
d'opportunités la stratégie a-t-elle manquées ? ».
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database.db import init_db
from ..decision.trade_signal import (
    Decision,
    RiskDecision,
    ScannerFact,
    TradeSignal,
)

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Journal:
    """Écrit les évènements du pipeline dans la base SQLite."""

    def __init__(self, db_path: str | Path | None = None, account_id: int | None = None) -> None:
        self.conn = init_db(db_path)
        self.account_id = account_id

    def _insert(self, sql: str, params: tuple) -> int:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return int(cur.lastrowid)

    # -- Scanner ----------------------------------------------------------

    def log_fact(self, fact: ScannerFact) -> int:
        """Trace un ScannerFact détecté (details sérialisés en JSON)."""
        sql = """
            INSERT INTO system_logs (level, component, message, error_code, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """
        message = json.dumps({
            "fact_type": fact.fact_type,
            "pair": fact.pair,
            "timeframe": fact.timeframe,
            "details": fact.details,
        }, default=str)
        return self._insert(sql, ("INFO", "MarketScanner", message, None,
                                  fact.timestamp.isoformat()))

    # -- Decision (y compris WAIT) ----------------------------------------

    def log_decision(self, decision: Decision, strategy_version_id: int) -> int:
        """Trace une décision BUY/SELL/WAIT. Retourne decision_id."""
        sql = """
            INSERT INTO decisions
                (strategy_version_id, pair, result, reasoning_tags, wait_reason, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        tags = json.dumps(decision.reasoning_tags)
        return self._insert(sql, (strategy_version_id, decision.pair,
                                  decision.result.value, tags,
                                  decision.wait_reason,
                                  decision.timestamp.isoformat()))

    def log_trade_signal(self, signal: TradeSignal, decision_id: int) -> int:
        """Trace un TradeSignal associé à sa decision. Retourne trade_signal_id."""
        sql = """
            INSERT INTO trade_signals (decision_id, entry, stop_loss, take_profit, confidence)
            VALUES (?, ?, ?, ?, ?)
        """
        return self._insert(sql, (decision_id, signal.entry, signal.stop_loss,
                                  signal.take_profit, signal.confidence))

    # -- Risk --------------------------------------------------------------

    def log_risk_decision(self, risk: RiskDecision, trade_signal_id: int) -> int:
        """Trace APPROVED/REJECTED. Retourne risk_event_id."""
        sql = """
            INSERT INTO risk_events (trade_signal_id, outcome, reason, position_size)
            VALUES (?, ?, ?, ?)
        """
        return self._insert(sql, (trade_signal_id, risk.outcome.value, risk.reason,
                                  risk.position_size))

    # -- Trades ----------------------------------------------------------

    def log_order(self, trade_signal_id: int, account_id: int,
                  status: str = "FILLED") -> int:
        """Enregistre un ordre envoyé au broker. Retourne order_id."""
        if self.account_id is not None:
            account_id = self.account_id
        sql = """
            INSERT INTO orders (trade_signal_id, account_id, status, submitted_at)
            VALUES (?, ?, ?, ?)
        """
        return self._insert(sql, (trade_signal_id, account_id, status,
                                  _utcnow().isoformat()))

    def log_position(self, order_id: int, account_id: int, pair: str,
                     direction: str, entry_price: float, stop_loss: float,
                     take_profit: float, lot_size: float) -> int:
        """Enregistre le trade ouvert résultant de l'ordre. Retourne trade_id."""
        if self.account_id is not None:
            account_id = self.account_id
        sql = """
            INSERT INTO trades (order_id, account_id, pair, direction, entry_price,
                                stop_loss, take_profit, lot_size, opened_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        return self._insert(sql, (order_id, account_id, pair, direction,
                                  entry_price, stop_loss, take_profit, lot_size,
                                  _utcnow().isoformat()))

    def update_trade_close(self, trade_id: int, exit_price: float, pnl: float,
                           r_multiple: float) -> None:
        sql = """
            UPDATE trades SET exit_price = ?, pnl = ?, r_multiple = ?, closed_at = ?
            WHERE id = ?
        """
        self._insert(sql, (exit_price, pnl, r_multiple,
                           _utcnow().isoformat(), trade_id))

    # -- Lecture (diagnostic) ----------------------------------------------

    def fetch(self, sql: str, params: tuple = ()) -> list[Any]:
        return self.conn.execute(sql, params).fetchall()

    def facts_count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM system_logs WHERE component = 'MarketScanner'"
        ).fetchone()
        return int(row["n"])

    def decisions(self) -> list[Any]:
        return self.fetch("SELECT pair, result, wait_reason, timestamp FROM decisions")

    def rejected(self) -> list[Any]:
        return self.fetch("SELECT reason, COUNT(*) AS n FROM risk_events "
                          "WHERE outcome = 'REJECTED' GROUP BY reason")

    def trades_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()
        return int(row["n"])

    def close(self) -> None:
        self.conn.close()