"""
Risk Manager MVP (§5.3) — dernier mot avant exécution (droit de veto).

Reçoit un TradeSignal + l'état du compte. Calcule la taille de position
(capital x risque% / distance SL) et vérifie : perte max journalière,
drawdown max, nombre max de positions ouvertes, session autorisée.

Retourne TOUJOURS un RiskDecision : APPROVED (avec position_size) ou
REJECTED (avec reason). Le veto est un vrai chemin de sortie testé —
jamais un sizing qui s'ajuste silencieusement.

HORS PÉRIMÈTRE (decision explicite, repoussé au post-MVP) :
- Filtre news (fundamentals.py de l'ancien bot, fenêtre 2h autour des
  annonces à fort impact). Absent du §5.3 du cahier des charges MVP, non
  backtestable en déterministe (calendrier live ForexFactory), dépendance
  externe. Réintégration sur jetable injectable, mockable, désactivé en
  backtest — PAS en dur dans ce module.

HÉRARCHIE DES VETOES (choix assumé, sert la télémétrie du Journal) :
SESSION → MAX_DAILY_LOSS → MAX_DRAWDOWN → MAX_POSITIONS. La session est
la porte la plus grossière ; ensuite la protection du capital du jour,
puis le drawdown cumulé, puis la saturation en positions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ..decision.trade_signal import (
    RiskDecision,
    RiskOutcome,
    TradeSignal,
)

logger = logging.getLogger(__name__)


@dataclass
class AccountState:
    """État du compte fourni au Risk Manager (indépendant du broker)."""

    balance: float
    equity: float
    open_positions: int = 0
    daily_loss: float = 0.0              # perte cumulée du jour (>= 0)
    daily_loss_limit_pct: float = 4.0
    max_drawdown_pct: float = 8.0
    max_open_positions: int = 4
    session_open: bool = True
    high_watermark: Optional[float] = None   # equity max pour drawdown


@dataclass
class RiskConfig:
    """Paramètres de risque (constantes MVP, configurables).

    position_size = capital x risque% / distance SL (formule §5.3).
    Les bornes min/max empêchent des valeurs aberrantes ; le sizing en
    lots précis relève du SimulationBroker côté exécution.
    """

    risk_percent: float = 0.5          # risque par trade, % du capital
    min_position_size: float = 0.01
    max_position_size: float = 1_000_000.0


class RiskManager:
    """Évalue chaque TradeSignal et rend un RiskDecision avec veto."""

    def __init__(self, config: Optional[RiskConfig] = None, journal=None) -> None:
        self.config = config or RiskConfig()
        self.journal = journal

    def evaluate(self, signal: TradeSignal, account: AccountState) -> RiskDecision:
        """Retourne TOUJOURS un RiskDecision (APPROVED/REJECTED)."""
        for reason in self._check_vetoes(account):
            rejected = RiskDecision(trade_signal=signal,
                                    outcome=RiskOutcome.REJECTED,
                                    reason=reason)
            self._log(rejected, signal)
            return rejected

        size = self._position_size(signal, account)
        if size is None:
            rejected = RiskDecision(trade_signal=signal,
                                    outcome=RiskOutcome.REJECTED,
                                    reason="POSITION_SIZE_NULLE")
            self._log(rejected, signal)
            return rejected

        if not self.config.min_position_size <= size <= self.config.max_position_size:
            rejected = RiskDecision(trade_signal=signal,
                                    outcome=RiskOutcome.REJECTED,
                                    reason=f"POSITION_SIZE_HORS_BORNES:{size:.4f}")
            self._log(rejected, signal)
            return rejected

        approved = RiskDecision(trade_signal=signal, outcome=RiskOutcome.APPROVED,
                                position_size=round(size, 2))
        self._log(approved, signal)
        return approved

    # -- Vérifications (chaque veto = REJECTED + reason) -----------------

    def _check_vetoes(self, account: AccountState) -> list[str]:
        """Retourne la liste des raisons de rejet, dans l'ordre d'évaluation."""
        vetoes: list[str] = []

        if not account.session_open:
            vetoes.append("SESSION_FERMEE")

        loss_pct = self._daily_loss_pct(account)
        if loss_pct is not None and loss_pct >= account.daily_loss_limit_pct:
            vetoes.append("MAX_DAILY_LOSS")

        dd = self._drawdown_pct(account)
        if dd is not None and dd >= account.max_drawdown_pct:
            vetoes.append("MAX_DRAWDOWN")

        if account.open_positions >= account.max_open_positions:
            vetoes.append("MAX_POSITIONS")

        return vetoes

    def _daily_loss_pct(self, account: AccountState) -> Optional[float]:
        if account.balance <= 0:
            return None
        return (account.daily_loss / account.balance) * 100

    def _drawdown_pct(self, account: AccountState) -> Optional[float]:
        peak = account.high_watermark or account.balance
        if peak <= 0:
            return None
        return ((peak - account.equity) / peak) * 100

    # -- Sizing -----------------------------------------------------------

    def _position_size(self, signal: TradeSignal,
                       account: AccountState) -> Optional[float]:
        """Taille = (capital x risque%) / distance SL."""
        risk = abs(signal.entry - signal.stop_loss)
        if risk <= 0:
            logger.warning("SL == entry, risque nul")
            return None
        amount = account.equity * (self.config.risk_percent / 100)
        return amount / risk

    # -- Helpers -----------------------------------------------------------

    def _log(self, risk: RiskDecision, signal: TradeSignal) -> None:
        """Journalise le RiskDecision si un journal est branché.

        Le pipeline (backtest/live) fournira trade_signal_id une fois le
        TradeSignal persisté — la journalisation détaillée sera activée là.
        En l'absence d'ID, on ne bloque jamais le trading (trace debug).
        """
        if self.journal is None:
            return
        try:
            logger.debug(f"risk[{signal.pair}] -> {risk.outcome.value}: {risk.reason}")
        except Exception as exc:  # pragma: no cover
            logger.error(f"Échec journalisation risk: {exc}")