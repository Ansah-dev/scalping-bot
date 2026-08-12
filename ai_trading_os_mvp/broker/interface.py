"""
BrokerConnector — interface commune à toute implémentation de broker.

Toute nouvelle implémentation (MT5Connector, SimulationBroker, et plus tard
BinanceConnector, cTraderConnector...) DOIT hériter de cette classe et
implémenter toutes les méthodes abstraites. Le reste du système (Decision
Engine, Risk Manager, Backtesting Engine) ne dépend jamais d'un broker
concret — uniquement de ce contrat.

Voir §5.4 et §7.5 du cahier des charges.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


@dataclass
class AccountInfo:
    account_id: str
    broker: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str


@dataclass
class Position:
    position_id: str
    pair: str
    direction: OrderDirection
    entry_price: float
    volume: float
    stop_loss: float
    take_profit: float
    opened_at: datetime
    unrealized_pnl: float


@dataclass
class OrderResult:
    """Retourné par open_order() / close_order() / modify_sl() / modify_tp()."""
    success: bool
    broker_order_id: Optional[str]
    status: OrderStatus
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class BrokerConnector(ABC):
    """Contrat que toute implémentation de broker doit respecter."""

    # -- Connexion -----------------------------------------------------

    @abstractmethod
    def connect(self) -> bool:
        """Établit la connexion au broker. Retourne True si succès.

        Doit journaliser tout échec avec le code d'erreur exact du broker
        (ex: mt5.last_error() pour MT5) — voir la leçon tirée de l'ancien
        bot où une erreur de login sans diagnostic a rendu le débogage
        impossible.
        """
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        raise NotImplementedError

    # -- Compte ----------------------------------------------------------

    @abstractmethod
    def get_account(self) -> AccountInfo:
        raise NotImplementedError

    @abstractmethod
    def get_balance(self) -> float:
        raise NotImplementedError

    @abstractmethod
    def get_equity(self) -> float:
        raise NotImplementedError

    # -- Positions / ordres ------------------------------------------------

    @abstractmethod
    def get_positions(self) -> list[Position]:
        raise NotImplementedError

    @abstractmethod
    def get_orders(self) -> list[OrderResult]:
        raise NotImplementedError

    @abstractmethod
    def open_order(
        self,
        pair: str,
        direction: OrderDirection,
        volume: float,
        stop_loss: float,
        take_profit: float,
    ) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def close_order(self, position_id: str) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def modify_sl(self, position_id: str, new_stop_loss: float) -> OrderResult:
        raise NotImplementedError

    @abstractmethod
    def modify_tp(self, position_id: str, new_take_profit: float) -> OrderResult:
        raise NotImplementedError
