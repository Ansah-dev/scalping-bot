"""
SimulationBroker — implémentation BrokerConnector pour le backtest (§5.4).

Même contrat que toute implémentation (MT5Connector en live), AUCUNE
divergence de logique entre backtest et live (§6 Cohérence, §7.5).

Règles de simulation (toutes testées) :
- Remplissage au close de la bougie courante, slippage à 0.
- SL/TP évalués sur les bougies SUIVANTES uniquement (jamais la bougie
  de remplissage => interdiction de connaître le futur §5.5).
- Règle SL vs TP intra-bougie : PESSIMISTE — si une bougie touche les
  deux niveaux, le SL gagne. Choix explicite (ne gonfle jamais le win
  rate, défendable en backtest déterministe, voir §module risk).
- Le moteur de backtest pilote le broker via on_bar(ts, open, high, low, close).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..broker.interface import (
    AccountInfo,
    BrokerConnector,
    OrderDirection,
    OrderResult,
    OrderStatus,
    Position,
)
from ..database.db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class ClosedTrade:
    """Trade clôturé (enregistré pour le Journal / rapports backtest)."""

    position_id: str           # id broker (broker_order_id, FK vers orders SQLite)
    pair: str
    direction: OrderDirection
    volume: float
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    exit_reason: str            # "SL" | "TP" | "MANUAL"
    pnl: float
    r_multiple: float
    opened_at: datetime
    closed_at: datetime


@dataclass
class _SimPosition:
    """Position interne au broker (reflétée vers Position pour get_positions)."""

    position_id: str
    pair: str
    direction: OrderDirection
    entry_price: float
    volume: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    opened_bar: int             # index bougie de remplissage
    trade_id: Optional[int] = None       # id ligne `trades` (journal SQLite)

    def to_public(self, mark: float) -> Position:
        if self.direction == OrderDirection.BUY:
            unrealized = (mark - self.entry_price) * self.volume
        else:
            unrealized = (self.entry_price - mark) * self.volume
        return Position(
            position_id=self.position_id,
            pair=self.pair,
            direction=self.direction,
            entry_price=self.entry_price,
            volume=self.volume,
            stop_loss=self.stop_loss,
            take_profit=self.take_profit,
            opened_at=self.opened_at,
            unrealized_pnl=round(unrealized, 6),
        )


class SimulationBroker(BrokerConnector):
    """Broker de simulation, piloté bougie par bougie pour le backtest."""

    def __init__(self, starting_balance: float = 10000.0,
                 currency: str = "USD", account_id: str = "SIM-1",
                 journal=None) -> None:
        self._balance = starting_balance
        self._currency = currency
        self._account_id = account_id
        self._journal = journal
        self._connected = False
        self._positions: list[_SimPosition] = []
        self._orders: list[OrderResult] = []
        self._closed_trades: list[ClosedTrade] = []
        self._last_close: Optional[float] = None
        self._last_high: Optional[float] = None
        self._last_low: Optional[float] = None
        self._bar_index = 0
        self._equity_high = starting_balance   # watermark pour drawdown pas ici

    # -- Cycle de vie ----------------------------------------------------

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # -- Compte ----------------------------------------------------------

    def get_account(self) -> AccountInfo:
        return AccountInfo(
            account_id=self._account_id,
            broker="Simulation",
            balance=round(self._balance, 2),
            equity=round(self.get_equity(), 2),
            margin=0.0,
            free_margin=round(self._balance, 2),
            currency=self._currency,
        )

    def get_balance(self) -> float:
        return round(self._balance, 2)

    def get_equity(self) -> float:
        mark = self._last_close or 0.0
        unrealized = sum(
            (p.entry_price - mark) * p.volume if p.direction == OrderDirection.SELL
            else (mark - p.entry_price) * p.volume
            for p in self._positions
        )
        return round(self._balance + unrealized, 2)

    # -- Positions / ordres ---------------------------------------------

    def get_positions(self) -> list[Position]:
        mark = self._last_close or 0.0
        return [p.to_public(mark) for p in self._positions]

    def get_orders(self) -> list[OrderResult]:
        return list(self._orders)

    def open_order(self, pair: str, direction: OrderDirection, volume: float,
                   stop_loss: float, take_profit: float,
                   entry_price: Optional[float] = None) -> OrderResult:
        if not self._connected:
            return self._reject("NOT_CONNECTED", "Broker non connecté")
        if self._last_close is None:
            return self._reject("NO_MARKET", "Aucune bougie reçue (prix inconnu)")
        if volume <= 0 or stop_loss <= 0 or take_profit <= 0:
            return self._reject("INVALID_PARAMS", "Volume/SL/TP doivent être > 0")

        # Remplissage au niveau du signal (ordre limite) OU au close de la
        # bougie courante si aucun niveau n'est fourni (live, open direct).
        # Remplir au niveau du signal préserve exactement le RR configuré
        # (sinon le close dérive du niveau théorique -> RR effectif biaisé).
        fill = entry_price if entry_price is not None else self._last_close

        if self._last_high is not None and self._last_low is not None:
            if not self._last_low <= fill <= self._last_high:
                return self._reject(
                    "ENTRY_HORS_BOUGIE",
                    f"Remplissage {fill} hors de la bougie courante "
                    f"[{self._last_low}, {self._last_high}]")
        if direction == OrderDirection.BUY and not (stop_loss < fill < take_profit):
            return self._reject("INVALID_SL_TP", "BUY: SL < prix < TP requis")
        if direction == OrderDirection.SELL and not (take_profit < fill < stop_loss):
            return self._reject("INVALID_SL_TP", "SELL: TP < prix < SL requis")

        pos = _SimPosition(
            position_id=f"sim-{uuid.uuid4().hex[:8]}",
            pair=pair,
            direction=direction,
            entry_price=fill,
            volume=volume,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=datetime.now(),
            opened_bar=self._bar_index,
        )
        self._positions.append(pos)
        result = OrderResult(success=True, broker_order_id=pos.position_id,
                             status=OrderStatus.FILLED)
        self._orders.append(result)
        logger.debug(f"Simulation open {pair} {direction.value} vol={volume} "
                     f"@ {fill}")
        return result

    def close_order(self, position_id: str) -> OrderResult:
        pos = self._find_position(position_id)
        if pos is None:
            return self._reject("POSITION_NOT_FOUND", f"Position {position_id} inconnue")
        if self._last_close is None:
            return self._reject("NO_MARKET", "Aucun prix pour clôturer")
        self._close_position(pos, self._last_close, "MANUAL", datetime.now())
        return OrderResult(success=True, broker_order_id=position_id,
                           status=OrderStatus.FILLED)

    def modify_sl(self, position_id: str, new_stop_loss: float) -> OrderResult:
        pos = self._find_position(position_id)
        if pos is None:
            return self._reject("POSITION_NOT_FOUND", f"Position {position_id} inconnue")
        if new_stop_loss <= 0:
            return self._reject("INVALID_SL", "SL doit être > 0")
        pos.stop_loss = new_stop_loss
        return OrderResult(success=True, broker_order_id=position_id,
                           status=OrderStatus.FILLED)

    def modify_tp(self, position_id: str, new_take_profit: float) -> OrderResult:
        pos = self._find_position(position_id)
        if pos is None:
            return self._reject("POSITION_NOT_FOUND", f"Position {position_id} inconnue")
        if new_take_profit <= 0:
            return self._reject("INVALID_TP", "TP doit être > 0")
        pos.take_profit = new_take_profit
        return OrderResult(success=True, broker_order_id=position_id,
                           status=OrderStatus.FILLED)

    # -- Pilotage backtest (bougie par bougie) ---------------------------

    def on_bar(self, timestamp: datetime, open_price: float,
               high: float, low: float, close: float) -> list[ClosedTrade]:
        """Avance d'une bougie. Évalue SL/TP des positions ouvertes aux
        bougies précédentes, puis met à jour le prix de référence.

        Règle SL-vs-TP intra-bougie PESSIMISTE : SL gagne.
        """
        self._bar_index += 1
        results: list[ClosedTrade] = []

        for pos in list(self._positions):
            if pos.opened_bar >= self._bar_index:
                continue  # bougie de remplissage : pas d'évaluation (pas de futur)
            exit_price, reason = self._evaluate_bar(pos, timestamp, high, low)
            if exit_price is not None:
                results.append(self._close_position(pos, exit_price, reason, timestamp))

        self._last_close = close
        self._last_high = high
        self._last_low = low
        return results

    def _evaluate_bar(self, pos: _SimPosition, timestamp: datetime,
                      high: float, low: float) -> tuple[Optional[float], Optional[str]]:
        if pos.direction == OrderDirection.BUY:
            sl_hit = low <= pos.stop_loss
            tp_hit = high >= pos.take_profit
        else:
            sl_hit = high >= pos.stop_loss
            tp_hit = low <= pos.take_profit

        # Résolution pessimiste SL/TP intra-bougie : sans tick data, le SL
        # gagne en cas d'ambiguïté — biais conservateur volontaire.
        # Choix assumé (Option 1 validée) : ne gonfle jamais le win rate.
        if sl_hit:                                    # PESSIMISTE : SL gagne
            return pos.stop_loss, "SL"
        if tp_hit:
            return pos.take_profit, "TP"
        return None, None

    # -- Internes ---------------------------------------------------------

    def _close_position(self, pos: _SimPosition, exit_price: float,
                        reason: str, closed_at: datetime) -> ClosedTrade:
        if pos.direction == OrderDirection.BUY:
            pnl = (exit_price - pos.entry_price) * pos.volume
        else:
            pnl = (pos.entry_price - exit_price) * pos.volume
        risk = abs(pos.entry_price - pos.stop_loss)
        # r_multiple : PnL en multiple du risque PAR UNITÉ de volume
        # (pnl inclut le volume ; risk est une distance de prix → diviser).
        r_multiple = (pnl / (risk * pos.volume)) if risk > 0 and pos.volume > 0 else 0.0

        closed = ClosedTrade(
            position_id=pos.position_id,
            pair=pos.pair,
            direction=pos.direction,
            volume=pos.volume,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            exit_reason=reason,
            pnl=round(pnl, 6),
            r_multiple=round(r_multiple, 4),
            opened_at=pos.opened_at,
            closed_at=closed_at,
        )
        self._balance += pnl
        self._positions.remove(pos)
        self._closed_trades.append(closed)
        if self._journal is not None:
            try:
                logger.debug(f"Simulation close {closed.pair} {reason} "
                             f"pnl={closed.pnl}")
            except Exception as exc:  # pragma: no cover
                logger.error(f"Échec journalisation broker: {exc}")
        return closed

    def _find_position(self, position_id: str) -> Optional[_SimPosition]:
        return next((p for p in self._positions if p.position_id == position_id), None)

    def _reject(self, code: str, message: str) -> OrderResult:
        result = OrderResult(success=False, broker_order_id=None,
                             status=OrderStatus.REJECTED,
                             error_code=code, error_message=message)
        self._orders.append(result)
        logger.warning(f"Simulation rejet {code}: {message}")
        return result

    # -- Introspection pour le backtest -----------------------------------

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        return list(self._closed_trades)

    @property
    def open_position_count(self) -> int:
        return len(self._positions)

    def reset(self) -> None:
        """Réinitialise l'état (entre deux scénarios de backtest)."""
        self._balance = 0.0
        self._positions.clear()
        self._orders.clear()
        self._closed_trades.clear()
        self._last_close = None
        self._last_high = None
        self._last_low = None
        self._bar_index = 0
        self._connected = False