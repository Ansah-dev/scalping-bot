"""Tests du Decision Engine (module 2) — contrat §5.2 et critère §9."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from ai_trading_os_mvp.decision.engine import DecisionEngine, StrategyVersion
from ai_trading_os_mvp.decision.trade_signal import (
    Decision,
    DecisionResult,
    ScannerFact,
    TradeSignal,
)


def fact(pair="EURUSD", tf="M5", ftype="FVG", details=None):
    return ScannerFact(pair=pair, timeframe=tf, fact_type=ftype,
                       details=details or {"side": "bull", "top": 10.10, "bottom": 10.00},
                       timestamp=datetime(2026, 3, 2, 8, 45))


def strategy(fvg=False, bos=False, rr=2.0, pair="EURUSD", tf="M5"):
    return StrategyVersion(strategy_id=1, version="1.0",
                           conditions={"FVG": fvg, "BOS": bos},
                           risk_percent=0.5, risk_reward=rr,
                           pair=pair, timeframe=tf)


def test_evaluate_retourne_toujours_un_decision():
    engine = DecisionEngine()
    cases = [
        [],                                          # aucun constat
        [fact()],                                    # constat présent
        [fact(ftype="LIQUIDITY_SWEEP", details={"side": "bear", "level": 10.0})],
    ]
    for facts in cases:
        d = engine.evaluate(facts, strategy(fvg=True))
        assert isinstance(d, Decision)
        assert d.result in (DecisionResult.BUY, DecisionResult.SELL, DecisionResult.WAIT)


def test_wait_si_conditions_manquantes():
    d = DecisionEngine().evaluate([fact(ftype="FVG")], strategy(fvg=True, bos=True))
    assert d.result == DecisionResult.WAIT
    assert "CONDITIONS_MANQUANTES" in d.wait_reason


def test_wait_si_strategie_inactive():
    s = strategy(fvg=True)
    s.is_active = False
    d = DecisionEngine().evaluate([fact()], s)
    assert d.result == DecisionResult.WAIT
    assert "STRATEGY_INACTIVE" in d.wait_reason


def test_BUY_sur_fvg_bull_et_build_signal_bu():
    engine = DecisionEngine()
    d = engine.evaluate([fact(ftype="FVG", details={"side": "bull", "top": 10.10, "bottom": 10.00})],
                        strategy(fvg=True))
    assert d.result == DecisionResult.BUY
    assert "FVG" in d.reasoning_tags

    sig = engine.build_signal(d, [fact()], strategy(fvg=True))
    assert isinstance(sig, TradeSignal)
    assert sig.entry == 10.10                 # entrée au top du FVG (BUY)
    assert sig.stop_loss < sig.entry          # SL sous l'entrée
    assert sig.take_profit > sig.entry        # TP au-dessus
    # risk_reward = (TP-entry)/(entry-SL) == 2.0
    rr_eff = (sig.take_profit - sig.entry) / (sig.entry - sig.stop_loss)
    assert abs(rr_eff - 2.0) < 1e-6


def test_SELL_sur_fvg_bear():
    details = {"side": "bear", "top": 10.10, "bottom": 10.00}
    engine = DecisionEngine()
    d = engine.evaluate([fact(ftype="FVG", details=details)], strategy(fvg=True))
    assert d.result == DecisionResult.SELL
    sig = engine.build_signal(d, [fact(ftype="FVG", details=details)], strategy(fvg=True))
    assert sig.entry == 10.00                 # entrée au bottom (SELL)
    assert sig.stop_loss > sig.entry
    assert sig.take_profit < sig.entry


def test_wait_si_signaux_conflictuels():
    facts = [
        fact(ftype="FVG", details={"side": "bull", "top": 10.10, "bottom": 10.00}),
        fact(ftype="BOS", details={"side": "bear", "level": 10.05}),
    ]
    d = DecisionEngine().evaluate(facts, strategy(fvg=True, bos=True))
    assert d.result == DecisionResult.WAIT
    assert "SIGNAL_CONFLICTUEL" in d.wait_reason


def test_build_signal_None_si_WAIT():
    d = DecisionEngine().evaluate([], strategy(fvg=True))
    assert d.result == DecisionResult.WAIT
    assert DecisionEngine().build_signal(d, [], strategy(fvg=True)) is None


def test_filtre_par_paire_et_timeframe():
    off = fact(pair="GBPUSD", tf="M5")
    d = DecisionEngine().evaluate([off], strategy(fvg=True))
    assert d.result == DecisionResult.WAIT  # rien d'utilisable pour EURUSD