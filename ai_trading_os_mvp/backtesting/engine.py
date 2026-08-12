"""
Backtesting Engine MVP (§5.5) — pipeline bougie par bougie, ante-futur.

Pipeline IDENTIQUE au live (§6 Cohérence) :
    Historique -> Scanner -> Decision Engine -> Risk Manager
               -> Simulation Broker -> Journal

Contrat d'exécution intra-bougie (choix assumé, ordre (a)) :
    1. Évaluer les positions ouvertes du broker (SL/TP touchés ?) via
       on_bar() — jamais de lookahead : la bougie de remplissage d'une
       position ne peut pas toucher son SL/TP.
    2. Puis scanner + décision + risk + éventuelle entrée sur la même
       bougie, au CLOSE (remplissage bougie courante, slippage 0).

Métriques (formules standards, aucun chiffre inventé) :
    - win_rate        = gains / trades clôturés
    - profit_factor   = sum(gains) / |sum(pertes)|  (infini si 0 perte)
    - max_drawdown_pct = peak-to-trough sur la courbe d'equity,
                         PAS la plus grosse perte d'un seul trade
    - avg_r_multiple  = moyenne des r_multiple (pnl/risque initial)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from ..broker.interface import OrderDirection, OrderResult, OrderStatus
from ..broker.simulation_connector import ClosedTrade, SimulationBroker
from ..decision.engine import DecisionEngine, StrategyVersion
from ..decision.trade_signal import DecisionResult
from ..market.scanner import MarketScanner, ScannerFact
from ..risk.manager import AccountState, RiskConfig, RiskManager

logger = logging.getLogger(__name__)


@dataclass
class BacktestReport:
    """Rapport final du backtest — le chiffre qui répond à la question MVP."""

    start_balance: float
    end_balance: float
    net_profit: float
    trades_count: int
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: float
    max_drawdown_pct: float
    avg_r_multiple: float
    equity_curve: list[tuple] = field(default_factory=list)   # (timestamp, equity)
    trades: list[ClosedTrade] = field(default_factory=list)
    perf_by_pair: dict[str, dict] = field(default_factory=dict)
    perf_by_month: dict[str, dict] = field(default_factory=dict)
    rejected_fills: int = 0          # §5.6 : opportunités perdues côté broker


class BacktestEngine:
    """Exécute le pipeline complet sur un DataFrame OHLCV, bougie par bougie."""

    def __init__(self, scanner: Optional[MarketScanner] = None,
                 decision_engine: Optional[DecisionEngine] = None,
                 risk_manager: Optional[RiskManager] = None,
                 broker: Optional[SimulationBroker] = None,
                 journal=None,
                 starting_balance: float = 10000.0) -> None:
        self.scanner = scanner or MarketScanner()
        self.decision_engine = decision_engine or DecisionEngine(journal=journal)
        self.risk_manager = risk_manager or RiskManager(journal=journal)
        self.broker = broker or SimulationBroker(starting_balance=starting_balance,
                                                 journal=journal)
        self.journal = journal
        self.starting_balance = starting_balance
        self._rejected_fills = 0
        self._active: Optional[StrategyVersion] = None
        self._trade_ids: dict[str, int] = {}
        self._account_id: Optional[int] = None
        if journal is not None:
            self._account_id = getattr(journal, "account_id", None)

    # -- API ---------------------------------------------------------------

    def run(self, df, strategy: StrategyVersion,
            pair: Optional[str] = None,
            timeframe: Optional[str] = None,
            account_state_kwargs: Optional[dict] = None) -> BacktestReport:
        """Lance le backtest sur df (colonnes open/high/low/close + index temps).

        StrategyVersion peut être construit en dur OU lu depuis la table
        strategy_versions (via StrategyVersion.from_db_row) — le moteur
        accepte les deux ; si strategy_version_id est renseigné, le
        journal trace la chaîne complète SQLite (decision, risk, trades).
        """
        pair = pair or strategy.pair
        timeframe = timeframe or strategy.timeframe
        kwargs = account_state_kwargs or {}
        self._active = strategy
        self._trade_ids = {}
        self._ensure_account_id()

        self.broker.connect()
        peak_equity = self.starting_balance
        current_day = None
        daily_loss = 0.0
        equity_curve: list[tuple] = []
        closed_all: list[ClosedTrade] = []

        timestamps = self._timestamps(df)
        opens = list(df["open"])
        highs = list(df["high"])
        lows = list(df["low"])
        closes = list(df["close"])

        self.scanner.begin(pair, timeframe)

        for i in range(len(df)):
            ts = timestamps[i]

            # --- (1) Évaluer les positions ouvertes (SL/TP) -------------
            closed = self.broker.on_bar(ts, opens[i], highs[i], lows[i], closes[i])
            closed_all.extend(closed)
            for trade in closed:
                if trade.pnl < 0:
                    if ts.date() == current_day:
                        daily_loss += -trade.pnl
                    else:
                        current_day = ts.date()
                        daily_loss = -trade.pnl

            equity = self.broker.get_equity()
            peak_equity = max(peak_equity, equity)
            equity_curve.append((ts, equity))

            # --- (2) Scanner -> Decision -> Risk -> entrée ---------------
            # Uniquement les faits ÉMIS SUR CETTE BOUGIE (scan incrémental,
            # O(n)) : sans ce filtre un fait ancien re-déclencherait la
            # décision à chaque bougie suivante (ré-entrées fantômes, §5.5).
            current_facts = self.scanner.update(df.iloc[i], i)
            if not current_facts:
                continue

            decision = self.decision_engine.evaluate(current_facts, strategy)
            if decision.result == DecisionResult.WAIT:
                continue

            signal = self.decision_engine.build_signal(decision, current_facts, strategy)
            if signal is None:
                continue

            account = AccountState(
                balance=self.broker.get_balance(),
                equity=self.broker.get_equity(),
                open_positions=self.broker.open_position_count,
                daily_loss=daily_loss,
                high_watermark=peak_equity,
                **kwargs,
            )
            risk = self.risk_manager.evaluate(signal, account)
            if risk.outcome.value != "APPROVED":
                continue

            direction = (OrderDirection.BUY
                         if signal.decision.result == DecisionResult.BUY
                         else OrderDirection.SELL)
            filled = self.broker.open_order(pair, direction, risk.position_size,
                                            signal.stop_loss, signal.take_profit,
                                            entry_price=signal.entry)

            if filled.success:
                # Câblage Journal -> Broker : decision -> signal -> risk ->
                # ordre -> position -> clôture. Ne trace rien si pas de
                # stratégie persistée (strategy_version_id) — traçage ignoré.
                self._journal_open(decision, signal, risk,
                                   filled.broker_order_id, pair, direction)
            else:
                # §5.6 : une opportunité rejetée côté broker (ex. niveau du
                # signal hors de la bougie de remplissage) doit être comptée,
                # sinon elle disparaît silencieusement des résultats.
                self._rejected_fills += 1
                self._journal_rejected(decision, signal, risk)
                logger.debug(f"Signal sans suite (broker) : {filled.error_code}")

        self._journal_close_all(closed_all)
        report = self._build_report(strategy, timestamps, equity_curve, closed_all)
        self._rejected_fills = 0  # reset pour run() successif
        self.broker.disconnect()
        return report

    # -- Câblage Journal <-> Broker (§5.6, persistance SQLite) ------------

    def _ensure_account_id(self) -> None:
        """Un account_id valide est requis (FK orders/trades).

        Si l'account pointé par le journal n'existe pas en base (ex.
        journal créé avec un account_id fantôme), on seed un compte
        SIMULATION — sans jamais bloquer le backtest.
        """
        if self.journal is None:
            return
        if self._account_id is not None:
            exists = self.journal.conn.execute(
                "SELECT 1 FROM accounts WHERE id = ?", (self._account_id,)
            ).fetchone()
            if exists:
                return
        try:
            cur = self.journal.conn.execute(
                """INSERT INTO accounts (broker, account_type, balance, equity)
                   VALUES ('SIMULATION', 'SIMULATION', ?, ?)""",
                (self.starting_balance, self.starting_balance))
            self.journal.conn.commit()
            self._account_id = int(cur.lastrowid)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Échec seed account journal: {exc}")

    def _journal_open(self, decision, signal, risk, position_id: Optional[str],
                      pair: str, direction: OrderDirection) -> None:
        """Enchaîne decision -> trade_signal -> risk_event -> order -> trades.

        Les WAIT sont déjà tracés par evaluate(). Decision id sert de FK au
        trade_signal ; order_id sert de FK à la position (trades.order_id).
        """
        j = self.journal
        if j is None:
            return
        try:
            decision_id = self.decision_engine.record_decision(decision, self._active)
            if decision_id is None:
                return  # stratégie non persistée -> chaîne SQLite ignorée
            trade_signal_id = j.log_trade_signal(signal, decision_id=decision_id)
            risk_event_id = j.log_risk_decision(risk, trade_signal_id=trade_signal_id)
            order_id = j.log_order(trade_signal_id=trade_signal_id,
                                   account_id=self._account_id or 0)
            self._trade_ids[position_id] = j.log_position(
                order_id=order_id,
                account_id=self._account_id or 0,
                pair=pair,
                direction=direction.value,
                entry_price=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                lot_size=risk.position_size,
            )
        except Exception as exc:  # pragma: no cover - ne jamais bloquer le backtest
            logger.error(f"Échec câblage journal (open): {exc}")

    def _journal_rejected(self, decision, signal, risk) -> None:
        """Trace le rejet broker d'un signal pourtant approuvé (§5.6)."""
        j = self.journal
        if j is None:
            return
        try:
            decision_id = self.decision_engine.record_decision(decision, self._active)
            if decision_id is None:
                return
            trade_signal_id = j.log_trade_signal(signal, decision_id=decision_id)
            j.log_risk_decision(risk, trade_signal_id=trade_signal_id)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Échec câblage journal (rejet): {exc}")

    def _journal_close_all(self, closed_all: list[ClosedTrade]) -> None:
        """Reporte les clôtures broker vers les lignes trades (pnl, r_multiple)."""
        j = self.journal
        if j is None:
            return
        try:
            for trade in closed_all:
                trade_id = self._trade_ids.get(trade.position_id)
                if trade_id is not None:
                    self.journal.update_trade_close(
                        trade_id, exit_price=trade.exit_price,
                        pnl=trade.pnl, r_multiple=trade.r_multiple)
        except Exception as exc:  # pragma: no cover
            logger.error(f"Échec câblage journal (close): {exc}")

    # -- Métriques ----------------------------------------------------------

    def _build_report(self, strategy: StrategyVersion,
                      timestamps, equity_curve, closed_all) -> BacktestReport:
        wins = sum(1 for t in closed_all if t.pnl > 0)
        losses = sum(1 for t in closed_all if t.pnl <= 0)
        gains = sum(t.pnl for t in closed_all if t.pnl > 0)
        losses_sum = sum(-t.pnl for t in closed_all if t.pnl < 0)

        profit_factor = gains / losses_sum if losses_sum > 0 else (
            float("inf") if gains > 0 else 0.0)
        max_dd = self._max_drawdown_pct(equity_curve)
        avg_r = (sum(t.r_multiple for t in closed_all) / len(closed_all)
                 if closed_all else 0.0)

        report = BacktestReport(
            start_balance=round(self.starting_balance, 2),
            end_balance=self.broker.get_balance(),
            net_profit=round(self.broker.get_balance() - self.starting_balance, 2),
            trades_count=len(closed_all),
            win_count=wins,
            loss_count=losses,
            win_rate=round(wins / len(closed_all), 4) if closed_all else 0.0,
            profit_factor=round(profit_factor, 4),
            max_drawdown_pct=round(max_dd, 4),
            avg_r_multiple=round(avg_r, 4),
            equity_curve=equity_curve,
            trades=closed_all,
            perf_by_pair=self._perf_by_pair(closed_all),
            perf_by_month=self._perf_by_month(closed_all),
            rejected_fills=self._rejected_fills,
        )
        return report

    def _max_drawdown_pct(self, equity_curve) -> float:
        """Peak-to-trough sur la courbe d'equity (pas par trade)."""
        peak = float("-inf")
        max_dd = 0.0
        for _, equity in equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak * 100)
        return max_dd

    def _perf_by_pair(self, closed_all) -> dict[str, dict]:
        perf: dict[str, dict] = {}
        for t in closed_all:
            d = perf.setdefault(t.pair, {"trades": 0, "pnl": 0.0})
            d["trades"] += 1
            d["pnl"] = round(d["pnl"] + t.pnl, 6)
        return perf

    def _perf_by_month(self, closed_all) -> dict[str, dict]:
        perf: dict[str, dict] = {}
        for t in closed_all:
            key = t.closed_at.strftime("%Y-%m")
            d = perf.setdefault(key, {"trades": 0, "pnl": 0.0})
            d["trades"] += 1
            d["pnl"] = round(d["pnl"] + t.pnl, 6)
        return perf

    # -- Helpers ------------------------------------------------------------

    def _timestamps(self, df):
        if hasattr(df.index, "date") and isinstance(df.index[0], object):
            return list(df.index)
        for col in ("timestamp", "time", "datetime"):
            if col in df.columns:
                return list(df[col])
        raise ValueError("df doit avoir un index DatetimeIndex ou une colonne "
                         "timestamp/time/datetime")