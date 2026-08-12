"""Tests du Market Scanner (module 1) — fixtures synthétiques."""
from __future__ import annotations

import pandas as pd
import pytest

from ai_trading_os_mvp.market.scanner import (
    MarketScanner,
    FACT_BOS,
    FACT_CHOCH,
    FACT_FVG,
    FACT_ORDER_BLOCK,
    FACT_SWEEP,
    UP,
    DOWN,
)
from ai_trading_os_mvp.decision.trade_signal import ScannerFact


def make_df(candles):
    """candles: liste de tuples (open, high, low, close). Retourne un
    DataFrame OHLCV chronologique (du plus ancien au plus récent)."""
    rows = []
    for i, (o, h, l, c) in enumerate(candles):
        rows.append({"time": pd.Timestamp("2026-01-01") + pd.Timedelta(minutes=5 * i),
                     "open": float(o), "high": float(h), "low": float(l),
                     "close": float(c), "volume": 100.0})
    return pd.DataFrame(rows)


def fact_types(facts: list[ScannerFact]) -> list[str]:
    return [f.fact_type for f in facts]


# ----------------------------------------------------------------------
# Fixture FVG haussier : low[i] > high[i-2]  (gap laissé par bougie i-1)
# ----------------------------------------------------------------------
def fvg_bullish_fixture() -> pd.DataFrame:
    return make_df([
        (10.00, 10.00, 9.50, 9.50),   # 0  (bas pour l'écart)
        (9.60, 9.70, 9.40, 9.55),     # 1  (bougie intermédiaire)
        (10.20, 10.30, 10.10, 10.20), # 2  low 10.10 > high[0]=10.00 -> FVG bull
        (10.30, 10.40, 10.15, 10.30),
        (10.20, 10.30, 10.10, 10.20),
        (10.10, 10.20, 10.00, 10.10),
    ])


def test_scanner_detecte_fvg_bullish():
    facts = MarketScanner().scan("EURUSD", "M5", fvg_bullish_fixture())
    fvgs = [f for f in facts if f.fact_type == FACT_FVG]
    assert any(f.details["side"] == "bull" for f in fvgs)
    assert all(isinstance(f, ScannerFact) for f in facts)


# ----------------------------------------------------------------------
# Fixture BOS : structure haussière, close brise le dernier swing high
# ----------------------------------------------------------------------
def bos_bullish_fixture() -> pd.DataFrame:
    candles = [
        (10.00, 10.00, 9.50, 9.50),   # 0
        (9.60, 9.70, 9.40, 9.55),     # 1
        (9.60, 9.80, 9.55, 9.75),     # 2
        (9.80, 9.90, 9.70, 9.85),     # 3  swing high @2 (9.80) confirmé vers 5
        (9.90, 10.00, 9.80, 9.95),    # 4
        (9.95, 10.05, 9.90, 10.00),   # 5
        (10.00, 10.20, 9.95, 10.15),  # 6
        (10.15, 10.30, 10.10, 10.25), # 7  close > 9.80 -> BOS bull
    ]
    return make_df(candles)


def test_scanner_detecte_bos_bullish():
    facts = MarketScanner().scan("EURUSD", "M5", bos_bullish_fixture())
    bos = [f for f in facts if f.fact_type == FACT_BOS]
    assert any(f.details["side"] == "bull" for f in bos)


# ----------------------------------------------------------------------
# Fixture CHoCH : montée (BOS établit UP), pullback plus haut, puis
# close casse le swing low confirmé -> CHoCH bear, flip DOWN
# ----------------------------------------------------------------------
def choch_fixture() -> pd.DataFrame:
    candles = [
        (9.50, 9.60, 9.45, 9.55),   # 0  swing low @0 (9.45) confirmé @3
        (9.60, 9.90, 9.55, 9.85),   # 1  swing high @1 (9.90) confirmé @4
        (9.80, 9.85, 9.60, 9.75),   # 2
        (9.75, 9.80, 9.55, 9.70),   # 3
        (9.70, 9.88, 9.65, 9.85),   # 4
        (9.85, 10.10, 9.80, 10.00), # 5  close 10.00 > 9.90 -> BOS bull, UP
        (9.95, 10.00, 9.70, 9.75),   # 6
        (9.75, 9.80, 9.55, 9.60),    # 7
        (9.60, 9.65, 9.50, 9.58),    # 8  swing low @8 (9.50) confirmé @11
        (9.62, 9.70, 9.58, 9.65),    # 9
        (9.70, 9.80, 9.62, 9.75),    # 10
        (9.78, 9.85, 9.70, 9.80),    # 11
        (9.80, 9.90, 9.75, 9.85),    # 12
        (9.85, 9.95, 9.80, 9.90),    # 13
        (9.90, 10.00, 9.85, 9.95),   # 14
        (9.90, 9.95, 9.60, 9.65),    # 15
        (9.60, 9.70, 9.30, 9.35),    # 16 close 9.35 < swing low 9.50 -> CHoCH bear
    ]
    return make_df(candles)


def test_scanner_detecte_choch():
    facts = MarketScanner().scan("EURUSD", "M5", choch_fixture())
    choch = [f for f in facts if f.fact_type == FACT_CHOCH]
    assert any(f.details["side"] == "bear" for f in choch)


# ----------------------------------------------------------------------
# Fixture sweep : mèche sous un swing low confirmé, close au-dessus
# ----------------------------------------------------------------------
def sweep_fixture() -> pd.DataFrame:
    candles = [
        (10.00, 10.00, 9.50, 9.50),   # 0
        (9.60, 9.70, 9.40, 9.55),     # 1  swing low @1 (9.40) confirmé vers 4
        (9.60, 9.80, 9.55, 9.75),     # 2
        (9.80, 9.90, 9.70, 9.85),     # 3
        (9.90, 10.00, 9.80, 9.95),    # 4
        (9.95, 10.05, 9.85, 9.95),    # 5
        (9.60, 9.70, 9.35, 9.55),     # 6  mèche 9.35 < 9.40 mais close 9.55
        (9.70, 9.80, 9.60, 9.75),     # 7
    ]
    return make_df(candles)


def test_scanner_detecte_liquidity_sweep():
    facts = MarketScanner().scan("EURUSD", "M5", sweep_fixture())
    sweeps = [f for f in facts if f.fact_type == FACT_SWEEP]
    assert any(f.details["side"] == "bear" for f in sweeps)


# ----------------------------------------------------------------------
# Fixture Order Block : bougie baissière (i-1) précédant un impulsif haut
# ----------------------------------------------------------------------
def order_block_fixture() -> pd.DataFrame:
    candles = [
        (10.00, 10.00, 9.50, 9.50),   # 0
    ]
    # Plaine de bougies neutres (corps minimaux) : mean_body doit être
    # stable avant l'impulsif (garde-fou order_block_min_candles=20).
    candles += [(9.50, 9.55, 9.45, 9.52)] * 24      # 1..24
    candles += [
        (9.50, 9.55, 9.45, 9.48),     # 25 bougie baissière (OB candidat)
        (9.70, 9.90, 9.65, 9.85),     # 26 impulsif haut -> OB @25
    ]
    return make_df(candles)


def test_scanner_detecte_order_block():
    facts = MarketScanner().scan("EURUSD", "M5", order_block_fixture())
    obs = [f for f in facts if f.fact_type == FACT_ORDER_BLOCK]
    assert any(f.details["side"] == "bull" and f.details["index"] == 25 for f in obs)


def test_order_block_garde_fou_serie_courte():
    """Aucun ORDER_BLOCK tant que order_block_min_candles bougies ne sont
    pas disponibles — la moyenne glissante serait instable (fenêtre
    partielle en début de série)."""
    short = order_block_fixture().iloc[:19]  # OB candidat à 18, soit < 20
    facts = MarketScanner().scan("EURUSD", "M5", short)
    assert not [f for f in facts if f.fact_type == FACT_ORDER_BLOCK]

    full = order_block_fixture()
    facts = MarketScanner().scan("EURUSD", "M5", full)
    assert [f for f in facts if f.fact_type == FACT_ORDER_BLOCK]


# ----------------------------------------------------------------------
# Garantie "pas de fuite future" : swing confirmé seulement APRÈS coup
# ----------------------------------------------------------------------
def test_swing_confirme_apres_coup_pas_avant():
    """Un pic ne doit JAMAIS être confirmé avant d'avoir vu N bougies de
    droite (sinon le backtest "connaîtrait le futur")."""
    n = 3
    candles = [
        (10.00, 10.00, 9.90, 9.95),   # 0
        (10.00, 10.20, 9.95, 10.15),  # 1
        (10.15, 10.50, 10.10, 10.40), # 2  pic haut 10.50
        (10.40, 10.45, 10.20, 10.30), # 3
        (10.30, 10.35, 10.15, 10.25), # 4
        (10.25, 10.30, 10.10, 10.20), # 5  confirmation possible dès ici
        (10.20, 10.25, 10.05, 10.15), # 6
    ]
    df = make_df(candles)
    from ai_trading_os_mvp.market.scanner import MarketStructureState
    st = MarketStructureState(swing_neighbors=n)
    swing_confirmed_at = None
    for idx, (_, candle) in enumerate(df.iterrows()):
        st.update_state(candle, idx, pd.Timestamp(df.iloc[idx]["time"]).to_pydatetime())
        confirmed = [s for s in st.swings if s.kind == "high"]
        if confirmed and swing_confirmed_at is None:
            swing_confirmed_at = idx
    assert swing_confirmed_at == 5, f"confirmation attendue à 5, obtenue à {swing_confirmed_at}"


# ----------------------------------------------------------------------
# Série trop courte : aucun constat de structure (pas de futur connu)
# ----------------------------------------------------------------------
def test_serie_courte_sans_fuite_future():
    df = make_df([(10.0, 10.0, 9.5, 9.5),
                  (9.5, 9.7, 9.4, 9.6),
                  (9.6, 9.8, 9.5, 9.7)])
    facts = MarketScanner().scan("EURUSD", "M5", df)
    bos = [f for f in facts if f.fact_type in (FACT_BOS, FACT_CHOCH)]
    assert bos == []  # pas assez de bougies pour confirmer un swing


def test_direction_finale_structure_haussiere():
    df = bos_bullish_fixture()
    scanner = MarketScanner()
    facts = scanner.scan("EURUSD", "M5", df)
    assert facts  # des constats ont été émis
    bos = [f for f in facts if f.fact_type == FACT_BOS]
    assert bos and bos[-1].details["side"] == "bull"
