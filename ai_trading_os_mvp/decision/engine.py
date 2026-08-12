"""
Decision Engine MVP (§5.2) — combine les constats du Scanner et la
stratégie active en BUY / SELL / WAIT, et rien d'autre.

Contrat : evaluate() retourne TOUJOURS un Decision dont result est
DecisionResult.BUY, SELL ou WAIT. build_signal() ne produit un
TradeSignal que lorsque la décision est BUY ou SELL (entry / SL / TP
calculés selon le ratio risk_reward de la stratégie).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..decision.trade_signal import (
    Decision,
    DecisionResult,
    ScannerFact,
    TradeSignal,
)

logger = logging.getLogger(__name__)

FACT_PRIORITY = ["FVG", "BOS", "CHoCH", "LIQUIDITY_SWEEP", "ORDER_BLOCK"]

BULL = "bull"
BEAR = "bear"


@dataclass
class StrategyVersion:
    """Version de stratégie telle que stockée dans strategy_versions.

    conditions: {"FVG": true, "BOS": true, ...} — constats requis.
    risk_percent / risk_reward alimentent le Risk Manager en aval.
    """

    strategy_id: int
    version: str
    conditions: dict[str, bool] = field(default_factory=dict)
    risk_percent: float = 0.5
    risk_reward: float = 2.0
    pair: str = "EURUSD"
    timeframe: str = "M5"
    is_active: bool = True
    strategy_version_id: Optional[int] = None  # id ligne strategy_versions (journal FK)

    @classmethod
    def from_db_row(cls, row) -> "StrategyVersion":
        """Construit depuis une ligne sqlite3.Row (strategy_versions)."""
        import json

        conditions = json.loads(row["conditions_json"] or "{}")
        return cls(
            strategy_id=row["strategy_id"],
            version=row["version"],
            conditions=conditions,
            risk_percent=row["risk_percent"],
            risk_reward=row["risk_reward"],
            pair=row["pair"],
            timeframe=row["timeframe"],
            is_active=bool(row["is_active"]),
            strategy_version_id=row["id"],  # FK du journal (log_decision)
        )


class DecisionEngine:
    """Transforme constats + stratégie en décision BUY/SELL/WAIT."""

    def __init__(self, journal=None) -> None:
        self.journal = journal

    def _log(self, decision: Decision, strategy: StrategyVersion) -> Optional[int]:
        if self.journal is None:
            return None
        svid = strategy.strategy_version_id
        if svid is None:
            return None  # pas de version persistée -> traçage ignoré (pas d'erreur)
        try:
            return self.journal.log_decision(decision, strategy_version_id=svid)
        except Exception as exc:  # pragma: no cover - jamais bloquer le trading
            logger.error(f"Échec journalisation decision: {exc}")
            return None

    def _keep_wait(self, decision: Decision, strategy: StrategyVersion) -> None:
        """Trace un WAIT (évaluations sans signal) — pas d'id à enchaîner."""
        self._log(decision, strategy)

    # -- API -------------------------------------------------------------

    def evaluate(self, facts: list[ScannerFact], strategy: StrategyVersion) -> Decision:
        """Retourne TOUJOURS un Decision (BUY/SELL/WAIT). Jamais autre chose.

        Cas WAIT journalisé ici même ; BUY/SELL sont tracés par l'appelant
        via record_decision() pour ne pas tracer deux fois une décision
        dont on fera un signal (l'id de decision sert de FK au signal).
        """
        if strategy is None or not strategy.is_active:
            d = self._wait(facts, "STRATEGY_INACTIVE_OU_ABSENTE")
            self._keep_wait(d, strategy or StrategyVersion(0, "0.0"))
            return d

        relevant = [f for f in facts
                    if f.pair == strategy.pair and f.timeframe == strategy.timeframe]

        missing = self._missing_conditions(relevant, strategy)
        if missing:
            d = self._wait(relevant, f"CONDITIONS_MANQUANTES:{','.join(missing)}")
            self._keep_wait(d, strategy)
            return d

        side, primary = self._resolve_direction(relevant, strategy)
        if side is None:
            d = self._wait(relevant, "SIGNAL_CONFLICTUEL")
            self._keep_wait(d, strategy)
            return d

        result = DecisionResult.BUY if side == BULL else DecisionResult.SELL
        tags = [f.fact_type for f in relevant
                if f.fact_type in strategy.conditions
                and strategy.conditions.get(f.fact_type)]
        return Decision(
            pair=strategy.pair,
            result=result,
            strategy_id=strategy.strategy_id,
            strategy_version=strategy.version,
            reasoning_tags=sorted(set(tags)),
        )

    def record_decision(self, decision: Decision,
                        strategy: StrategyVersion) -> Optional[int]:
        """Persiste une décision BUY/SELL via le journal. Retourne decision_id.

        ATTENTION : n'appeler QUE sur les décisions BUY/SELL (celles qui
        généreront un signal). Les WAIT sont tracés par evaluate().
        """
        if decision.result == DecisionResult.WAIT:
            return None
        return self._log(decision, strategy)

    def build_signal(self, decision: Decision, facts: list[ScannerFact],
                     strategy: StrategyVersion,
                     entry: Optional[float] = None) -> Optional[TradeSignal]:
        """TradeSignal UNIQUEMENT si la décision est BUY/SELL. Sinon None."""
        if decision.result == DecisionResult.WAIT:
            return None

        relevant = [f for f in facts
                    if f.pair == strategy.pair and f.timeframe == strategy.timeframe]
        primary = self._pick_primary(relevant)
        entry_price = entry
        stop_loss = self._stop_level(primary, decision.result)

        if entry_price is None:
            entry_price = self._entry_level(primary, decision.result)

        risk = abs(entry_price - stop_loss)
        if risk <= 0:
            logger.warning("Risque nul (entry==SL) — signal rejeté en WAIT")
            return None

        if decision.result == DecisionResult.BUY:
            take_profit = entry_price + strategy.risk_reward * risk
        else:
            take_profit = entry_price - strategy.risk_reward * risk

        confidence = self._confidence(relevant, strategy)
        return TradeSignal(
            decision=decision,
            entry=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_reward=strategy.risk_reward,
            confidence=confidence,
        )

    # -- Helpers ---------------------------------------------------------

    def _wait(self, facts: list[ScannerFact], reason: str) -> Decision:
        pair = facts[0].pair if facts else "UNKNOWN"
        return Decision(pair=pair, result=DecisionResult.WAIT,
                        strategy_id=0, strategy_version="0.0",
                        wait_reason=reason)

    def _missing_conditions(self, facts: list[ScannerFact],
                            strategy: StrategyVersion) -> list[str]:
        present = {f.fact_type for f in facts}
        return [ft for ft, required in strategy.conditions.items()
                if required and ft not in present]

    def _pick_primary(self, facts: list[ScannerFact]) -> Optional[ScannerFact]:
        ranked = [(FACT_PRIORITY.index(f.fact_type), f)
                  for f in facts if f.fact_type in FACT_PRIORITY]
        return min(ranked, key=lambda pair: pair[0])[1] if ranked else None

    def _resolve_direction(self, facts: list[ScannerFact],
                           strategy: StrategyVersion) -> tuple[Optional[str], Optional[ScannerFact]]:
        """La direction découle du constat prioritaire, à condition que
        les constats liés s'accordent — sinon conflict (WAIT)."""
        primary = self._pick_primary(facts)
        if primary is None:
            return None, None
        side = primary.details.get("side")
        if side not in (BULL, BEAR):
            return None, primary

        for f in facts:
            if f.fact_type in strategy.conditions and strategy.conditions.get(f.fact_type):
                fs = f.details.get("side")
                if fs in (BULL, BEAR) and fs != side:
                    return None, primary  # signaux opposés -> WAIT
        return side, primary

    def _entry_level(self, primary: Optional[ScannerFact],
                     result: DecisionResult) -> float:
        if primary is None:
            raise ValueError("Impossible de calculer l'entrée sans constat")
        side = primary.details.get("side")
        if primary.fact_type == "FVG":
            return float(primary.details["top"]) if side == BULL else float(primary.details["bottom"])
        return float(primary.details["level"])

    def _stop_level(self, primary: Optional[ScannerFact],
                    result: DecisionResult) -> float:
        """SL à l'extrémité du constat (sous le FVG pour BUY, au-dessus pour SELL)."""
        if primary is None:
            raise ValueError("Impossible de calculer le SL sans constat")
        side = primary.details.get("side")
        if primary.fact_type == "FVG":
            level = float(primary.details["bottom"]) if side == BULL else float(primary.details["top"])
        else:
            level = float(primary.details["level"])
        buffer = max(level * 0.0005, 1e-6)
        return level - buffer if result == DecisionResult.BUY else level + buffer

    def _confidence(self, facts: list[ScannerFact],
                    strategy: StrategyVersion) -> float:
        required = [ft for ft, r in strategy.conditions.items() if r]
        if not required:
            return 0.5
        present = sum(1 for ft in required
                      if any(f.fact_type == ft for f in facts))
        return round(min(1.0, present / len(required) + 0.1), 2)