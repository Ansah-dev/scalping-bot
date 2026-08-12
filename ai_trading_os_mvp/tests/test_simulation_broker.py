"""Tests du SimulationBroker (module 4) — §5.4, cohérence backtest/live."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from ai_trading_os_mvp.broker.interface import OrderDirection, OrderResult, OrderStatus
from ai_trading_os_mvp.broker.simulation_connector import SimulationBroker

T0 = datetime(2026, 1, 2, 8, 0)


def next_bar(i=1):
    return T0 + timedelta(minutes=5 * i)


def open_buy(broker, sl=99.0, tp=102.0, vol=1.0):
    broker.connect()
    broker.on_bar(next_bar(), 100.0, 101.0, 99.5, 100.5)  # prix de réf 100.5
    return broker.open_order("EURUSD", OrderDirection.BUY, vol, sl, tp)


def open_sell(broker, sl=101.0, tp=98.0, vol=1.0):
    broker.connect()
    broker.on_bar(next_bar(), 100.0, 101.0, 99.5, 100.5)
    return broker.open_order("EURUSD", OrderDirection.SELL, vol, sl, tp)


def test_open_order_fill():
    broker = SimulationBroker()
    result = open_buy(broker)
    assert result.success is True
    assert result.status == OrderStatus.FILLED
    assert broker.open_position_count == 1


def test_open_order_rejete_si_non_connecte():
    broker = SimulationBroker()
    result = broker.open_order("EURUSD", OrderDirection.BUY, 1.0, 99.0, 102.0)
    assert result.success is False
    assert result.status == OrderStatus.REJECTED
    assert result.error_code == "NOT_CONNECTED"


def test_open_order_rejete_sans_prix():
    broker = SimulationBroker()
    broker.connect()
    result = broker.open_order("EURUSD", OrderDirection.BUY, 1.0, 99.0, 102.0)
    assert result.status == OrderStatus.REJECTED
    assert result.error_code == "NO_MARKET"


def test_open_order_rejete_sl_tp_invalide_buy():
    broker = SimulationBroker()
    result = open_buy(broker, sl=101.0, tp=102.0)  # SL > prix -> invalide
    assert result.success is False
    assert result.error_code == "INVALID_SL_TP"


def test_buy_tp_hit():
    broker = SimulationBroker()
    open_buy(broker, sl=99.0, tp=102.0)
    closed = broker.on_bar(next_bar(2), 100.0, 103.0, 100.0, 102.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "TP"
    assert closed[0].pnl == pytest.approx((102.0 - 100.5) * 1.0)
    assert broker.open_position_count == 0


def test_buy_sl_hit():
    broker = SimulationBroker()
    open_buy(broker, sl=99.0, tp=102.0)
    closed = broker.on_bar(next_bar(2), 100.0, 100.8, 98.5, 99.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "SL"
    assert closed[0].pnl == pytest.approx((99.0 - 100.5) * 1.0)


def test_sell_tp_hit():
    broker = SimulationBroker()
    open_sell(broker, sl=101.0, tp=98.0)
    closed = broker.on_bar(next_bar(2), 100.0, 100.5, 97.0, 98.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "TP"


def test_sell_sl_hit():
    broker = SimulationBroker()
    open_sell(broker, sl=101.0, tp=98.0)
    closed = broker.on_bar(next_bar(2), 100.0, 102.0, 99.0, 101.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "SL"


def test_sl_tp_ambigus_buysle_gagne():
    """PESSIMISTE : même bougie touche SL ET TP -> SL gagne."""
    broker = SimulationBroker()
    open_buy(broker, sl=99.0, tp=102.0)  # entry 100.5
    closed = broker.on_bar(next_bar(2), 100.0, 103.0, 98.5, 100.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "SL"
    assert closed[0].exit_price == pytest.approx(99.0)
    assert closed[0].pnl < 0


def test_sl_tp_ambigus_sell_sl_gagne():
    broker = SimulationBroker()
    open_sell(broker, sl=101.0, tp=98.0)  # entry 100.5
    closed = broker.on_bar(next_bar(2), 100.0, 102.0, 97.0, 100.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "SL"


def test_position_non_evaluee_sur_bougie_de_remplissage():
    """La bougie de remplissage ne peut pas toucher SL/TP (pas de futur §5.5)."""
    broker = SimulationBroker()
    broker.connect()
    broker.on_bar(next_bar(1), 100.0, 101.0, 99.5, 100.5)
    broker.open_order("EURUSD", OrderDirection.BUY, 1.0, 99.0, 102.0)
    # bougie suivante touchant SL : évaluée normalement
    closed = broker.on_bar(next_bar(2), 99.0, 99.2, 98.0, 98.5)
    assert len(closed) == 1
    assert closed[0].exit_reason == "SL"


def test_close_order_manuel():
    broker = SimulationBroker()
    open_buy(broker, sl=99.0, tp=102.0)
    pid = broker.get_positions()[0].position_id
    result = broker.close_order(pid)
    assert result.success is True
    assert broker.open_position_count == 0
    assert broker.closed_trades[0].exit_reason == "MANUAL"


def test_modify_sl_tp():
    broker = SimulationBroker()
    open_buy(broker, sl=99.0, tp=102.0)
    pid = broker.get_positions()[0].position_id
    assert broker.modify_sl(pid, 100.0).success is True
    assert broker.modify_tp(pid, 103.0).success is True
    pos = broker.get_positions()[0]
    assert pos.stop_loss == 100.0
    assert pos.take_profit == 103.0


def test_balance_mise_a_jour_apres_perte():
    broker = SimulationBroker(starting_balance=10000.0)
    open_buy(broker, sl=99.0, tp=102.0, vol=1.0)
    closed = broker.on_bar(next_bar(2), 100.0, 100.5, 98.0, 99.0)
    assert closed[0].exit_reason == "SL"
    assert broker.get_balance() == pytest.approx(10000.0 + (99.0 - 100.5))


def test_equity_reflete_position_ouverte():
    broker = SimulationBroker(starting_balance=10000.0)
    open_buy(broker, sl=99.0, tp=102.0, vol=1.0)
    # nouvelle bougie : prix de référence monte -> equity > balance
    broker.on_bar(next_bar(2), 100.0, 101.8, 100.2, 101.7)
    assert broker.get_equity() == pytest.approx(10000.0 + (101.7 - 100.5))
    assert broker.get_balance() == pytest.approx(10000.0)


def test_reset():
    broker = SimulationBroker(starting_balance=10000.0)
    open_buy(broker)
    broker.reset()
    assert broker.open_position_count == 0
    assert broker.get_balance() == 0.0
    assert broker.is_connected() is False


def test_remplissage_niveau_du_signal():
    """Option 1 validée : remplir au niveau du signal préserve le RR configuré."""
    broker = SimulationBroker()
    broker.connect()
    broker.on_bar(next_bar(1), 100.0, 101.0, 99.5, 100.5)
    # niveau du signal 100.2 (dans [99.5, 101.0]), SL 99.0, TP 102.6
    result = broker.open_order("EURUSD", OrderDirection.BUY, 1.0, 99.0, 102.6,
                               entry_price=100.2)
    assert result.success is True
    pos = broker.get_positions()[0]
    assert pos.entry_price == pytest.approx(100.2)
    # RR effectif = (102.6-100.2)/(100.2-99.0) = 2.4/1.2 = 2.0 (préserve le RR du signal)
    assert (pos.take_profit - pos.entry_price) / (pos.entry_price - pos.stop_loss) \
        == pytest.approx(2.0)


def test_remplissage_hors_bougie_rejete():
    """Niveau du signal hors de la bougie courante -> rejet (cohérence)."""
    broker = SimulationBroker()
    broker.connect()
    broker.on_bar(next_bar(1), 100.0, 101.0, 99.5, 100.5)
    result = broker.open_order("EURUSD", OrderDirection.BUY, 1.0, 99.0, 105.0,
                               entry_price=98.0)  # sous le low 99.5
    assert result.success is False
    assert result.error_code == "ENTRY_HORS_BOUGIE"


def test_remplissage_close_par_defaut():
    """Sans niveau fourni (live/open direct), remplissage au close."""
    broker = SimulationBroker()
    broker.connect()
    broker.on_bar(next_bar(1), 100.0, 101.0, 99.5, 100.5)
    result = broker.open_order("EURUSD", OrderDirection.BUY, 1.0, 99.0, 102.0)
    assert result.success is True
    assert broker.get_positions()[0].entry_price == pytest.approx(100.5)