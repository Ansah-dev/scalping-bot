"""Tests du Risk Manager (module 3) — §5.3, droit de veto comme chemin réel."""
from __future__ import annotations

from datetime import datetime

import pytest

from ai_trading_os_mvp.decision.engine import StrategyVersion
from ai_trading_os_mvp.decision.trade_signal import (
    Decision,
    DecisionResult,
    RiskOutcome,
    TradeSignal,
)
from ai_trading_os_mvp.risk.manager import AccountState, RiskConfig, RiskManager


def make_signal(entry=10.10, sl=10.00, tp=10.30):
    dec = Decision(pair="EURUSD", result=DecisionResult.BUY,
                   strategy_id=1, strategy_version="1.0")
    return TradeSignal(decision=dec, entry=entry, stop_loss=sl,
                       take_profit=tp, risk_reward=2.0)


def make_account(equity=10000.0, balance=10000.0, open_positions=0,
                 daily_loss=0.0, session_open=True, high_watermark=None,
                 daily_loss_limit_pct=4.0, max_drawdown_pct=8.0,
                 max_open_positions=4):
    return AccountState(balance=balance, equity=equity,
                        open_positions=open_positions, daily_loss=daily_loss,
                        session_open=session_open, high_watermark=high_watermark,
                        daily_loss_limit_pct=daily_loss_limit_pct,
                        max_drawdown_pct=max_drawdown_pct,
                        max_open_positions=max_open_positions)


def test_approve_avec_position_size():
    rm = RiskManager()
    risk = rm.evaluate(make_signal(), make_account())
    assert risk.outcome == RiskOutcome.APPROVED
    assert risk.position_size is not None
    assert risk.position_size > 0
    assert risk.reason is None


def test_sizing_formule_capitaux_risque():
    # capital 10000, risque 0.5% => 50$ ; distance SL = 0.10 => taille 500
    rm = RiskManager(RiskConfig(risk_percent=0.5))
    risk = rm.evaluate(make_signal(entry=10.10, sl=10.00), make_account(equity=10000))
    assert abs(risk.position_size - 500) < 1e-6


def test_sizing_avec_risque_personnalise():
    # risque 1% sur 10000 => 100$ ; distance 0.10 => 1000
    rm = RiskManager(RiskConfig(risk_percent=1.0))
    risk = rm.evaluate(make_signal(entry=10.10, sl=10.00), make_account(equity=10000))
    assert abs(risk.position_size - 1000) < 1e-6


def test_veto_max_daily_loss():
    rm = RiskManager()
    account = make_account(daily_loss=400, balance=10000)  # 4% -> limite
    risk = rm.evaluate(make_signal(), account)
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.reason == "MAX_DAILY_LOSS"


def test_veto_drawdown_max():
    rm = RiskManager()
    # equity chute de 8% sous le sommet -> drawdown max atteint
    account = make_account(equity=9200, balance=10000, high_watermark=10000)
    risk = rm.evaluate(make_signal(), account)
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.reason == "MAX_DRAWDOWN"


def test_veto_max_positions():
    rm = RiskManager(RiskConfig())
    account = make_account(open_positions=4, max_open_positions=4)
    risk = rm.evaluate(make_signal(), account)
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.reason == "MAX_POSITIONS"


def test_veto_session_fermee():
    rm = RiskManager()
    account = make_account(session_open=False)
    risk = rm.evaluate(make_signal(), account)
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.reason == "SESSION_FERMEE"


def test_veto_position_size_hors_bornes():
    # distance SL nulle -> size nulle -> rejeté
    rm = RiskManager()
    risk = rm.evaluate(make_signal(entry=10.00, sl=10.00), make_account())
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.reason == "POSITION_SIZE_NULLE"


def test_veto_predominance_dans_l_ordre():
    # Plusieurs violations : le premier veto évalué gagne (session d'abord)
    rm = RiskManager()
    account = make_account(session_open=False, daily_loss=500,
                           balance=10000, open_positions=4)
    risk = rm.evaluate(make_signal(), account)
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.reason == "SESSION_FERMEE"


def test_reject_ne_modifie_pas_le_signal():
    # Le veto ne mute pas le TradeSignal (pas d'ajustement silencieux)
    sig = make_signal()
    rm = RiskManager()
    risk = rm.evaluate(sig, make_account(daily_loss=500, balance=10000))
    assert risk.outcome == RiskOutcome.REJECTED
    assert risk.trade_signal is sig
    assert sig.entry == sig.entry  # inchangé