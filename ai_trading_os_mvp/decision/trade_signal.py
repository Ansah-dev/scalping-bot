"""
TradeSignal — objet standard produit par le Decision Engine.

Voir §5.2 du cahier des charges. Ce fichier définit aussi Decision
(sortie brute du Decision Engine, toujours BUY/SELL/WAIT) et
RiskDecision (sortie du Risk Manager, APPROVED/REJECTED).

Ces trois objets forment le contrat de données qui traverse tout le
pipeline : Scanner -> Decision Engine -> Risk Manager -> Broker Connector.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DecisionResult(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"


class RiskOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


@dataclass
class ScannerFact:
    """Un constat brut produit par le Market Scanner (§5.1).

    Le Scanner ne juge rien — il constate. Le Decision Engine décide.
    """
    pair: str
    timeframe: str
    fact_type: str          # ex: "BOS", "CHoCH", "FVG", "ORDER_BLOCK", "LIQUIDITY_SWEEP"
    details: dict           # données spécifiques au type de constat
    timestamp: datetime


@dataclass
class Decision:
    """Sortie du Decision Engine — toujours BUY, SELL, ou WAIT.

    Le Decision Engine ne retourne JAMAIS autre chose que ces trois
    valeurs (voir critère d'acceptation §9 du cahier des charges).
    """
    pair: str
    result: DecisionResult
    strategy_id: int
    strategy_version: str
    reasoning_tags: list[str] = field(default_factory=list)
    wait_reason: Optional[str] = None   # rempli uniquement si result == WAIT
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TradeSignal:
    """Produit uniquement quand Decision.result est BUY ou SELL.

    C'est l'objet qui est ensuite transmis au Risk Manager.
    """
    decision: Decision
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    confidence: Optional[float] = None   # 0.0 - 1.0

    @property
    def pair(self) -> str:
        return self.decision.pair

    @property
    def direction(self) -> DecisionResult:
        return self.decision.result


@dataclass
class RiskDecision:
    """Sortie du Risk Manager — a le dernier mot avant exécution.

    Le Risk Manager peut REJETER un TradeSignal même si le Decision
    Engine a dit BUY/SELL (droit de veto, §5.3 du cahier des charges).
    """
    trade_signal: TradeSignal
    outcome: RiskOutcome
    reason: Optional[str] = None        # rempli si REJECTED, ex: "MAX_DAILY_LOSS"
    position_size: Optional[float] = None  # calculé uniquement si APPROVED
    timestamp: datetime = field(default_factory=datetime.utcnow)
