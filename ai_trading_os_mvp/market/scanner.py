"""
Market Scanner MVP (§5.1) — constats bruts uniquement, aucune décision.

Le scanner observe une série de bougies OHLCV et émet des ScannerFact
(FVG, BOS, CHoCH, ORDER_BLOCK, LIQUIDITY_SWEEP). Il est délibérément
stateless-visage-l'externe : MarketScanner.scan(df) rejoue l'historique
dans l'ordre via MarketStructureState, qui garde l'état persistant de la
structure de marché. Jamais de recalcul indépendant sur une fenêtre
tronquée — la structure ne dépend que du passé, pas du futur.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from ..decision.trade_signal import ScannerFact

FACT_BOS = "BOS"
FACT_CHOCH = "CHoCH"
FACT_FVG = "FVG"
FACT_ORDER_BLOCK = "ORDER_BLOCK"
FACT_SWEEP = "LIQUIDITY_SWEEP"

UP = "UP"
DOWN = "DOWN"
NEUTRAL = "NEUTRAL"

BULL = "bull"
BEAR = "bear"


@dataclass
class Swing:
    """Swing confirmé : pic local à N bougies, validé N bougies APRÈS lui."""

    kind: str            # "high" | "low"
    price: float
    index: int
    timestamp: datetime


@dataclass
class MarketStructureState:
    """État persistant de la structure de marché — Option A pure (swings).

    update_state(candle, index) est appelé bougie par bougie, dans
    l'ordre chronologique. La confirmation d'un swing n'utilise que les
    bougies déjà vues (le pic est validé swing_neighbors bougies après
    lui), donc aucune bougie future n'est consultée.
    """

    swing_neighbors: int = 3
    impulse_body_ratio: float = 1.5
    order_block_min_candles: int = 20

    direction: str = NEUTRAL
    last_swing_high: Swing | None = None
    last_swing_low: Swing | None = None
    swings: list = field(default_factory=list)

    _opens: list = field(default_factory=list, repr=False)
    _highs: list = field(default_factory=list, repr=False)
    _lows: list = field(default_factory=list, repr=False)
    _closes: list = field(default_factory=list, repr=False)
    _bodies: list = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        if self.swing_neighbors < 1:
            raise ValueError("swing_neighbors doit être >= 1")

    # -- API publique ---------------------------------------------------

    def update_state(self, candle: pd.Series, index: int, timestamp: datetime) -> list[dict]:
        """Absorbe une bougie. Retourne les constats bruts émis sur elle.

        Chaque constat : {"fact_type": str, "details": dict, "index": int}.
        """
        high = float(candle["high"])
        low = float(candle["low"])
        close = float(candle["close"])
        open_ = float(candle["open"])
        body = abs(close - open_)

        self._opens.append(open_)
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        self._bodies.append(body)

        facts: list[dict] = []

        facts.extend(self._detect_fvg(index, timestamp))
        facts.extend(self._detect_order_block(index))

        self._confirm_swings(index, timestamp)
        facts.extend(self._detect_sweep(index, timestamp))
        facts.extend(self._update_structure(index, timestamp))

        return facts

    # -- Structure -------------------------------------------------------

    def _confirm_swings(self, idx: int, ts: datetime) -> None:
        """Valide le pic situé swing_neighbors bougies en arrière.

        À la bougie d'index `idx`, un candidat à `pos = idx - swing_neighbors`
        dispose exactement de ses N voisins de droite fermés — donc la
        confirmation n'utilise JAMAIS le futur. Les voisins de gauche
        disponibles (éventuellement en moins grand nombre en début de
        série) suffisent.
        """
        n = self.swing_neighbors
        pos = idx - n
        if pos < 0:
            return  # pas encore N bougies de droite pour le premier candidat

        swing_high = self._is_swing_high(pos)
        swing_low = self._is_swing_low(pos)
        if swing_high and not swing_low:
            s = Swing("high", self._highs[pos], pos, ts)
            self.last_swing_high = s
        elif swing_low and not swing_high:
            s = Swing("low", self._lows[pos], pos, ts)
            self.last_swing_low = s
        else:
            s = Swing("equal", self._closes[pos], pos, ts)
        self.swings.append(s)

    def _is_swing_high(self, pos: int) -> bool:
        hi = self._highs[pos]
        n = self.swing_neighbors
        lo = max(0, pos - n)
        hi_idx = pos + n
        return all(self._highs[g] < hi for g in range(lo, hi_idx + 1) if g != pos)

    def _is_swing_low(self, pos: int) -> bool:
        lo_price = self._lows[pos]
        n = self.swing_neighbors
        lo = max(0, pos - n)
        hi_idx = pos + n
        return all(self._lows[g] > lo_price for g in range(lo, hi_idx + 1) if g != pos)

    def _update_structure(self, idx: int, ts: datetime) -> list[dict]:
        """BOS / CHoCH sur CLÔTURE — jamais sur mèche."""
        facts: list[dict] = []
        close = self._closes[idx]
        n = self.swing_neighbors

        last_high = self.last_swing_high
        last_low = self.last_swing_low

        if self.direction == NEUTRAL:
            if last_high is not None and close > last_high.price:
                facts.append(self._break_fact(FACT_BOS, BULL, last_high, idx, ts))
                self.last_swing_high = None
                self.direction = UP
            elif last_low is not None and close < last_low.price:
                facts.append(self._break_fact(FACT_BOS, BEAR, last_low, idx, ts))
                self.last_swing_low = None
                self.direction = DOWN
            return facts

        if self.direction == UP:
            if last_high is not None and close > last_high.price:
                facts.append(self._break_fact(FACT_BOS, BULL, last_high, idx, ts))
                self.last_swing_high = None
            elif last_low is not None and close < last_low.price:
                facts.append(self._break_fact(FACT_CHOCH, BEAR, last_low, idx, ts))
                self.last_swing_low = None
                self.direction = DOWN
            return facts

        # direction == DOWN
        if last_low is not None and close < last_low.price:
            facts.append(self._break_fact(FACT_BOS, BEAR, last_low, idx, ts))
            self.last_swing_low = None
        elif last_high is not None and close > last_high.price:
            facts.append(self._break_fact(FACT_CHOCH, BULL, last_high, idx, ts))
            self.last_swing_high = None
            self.direction = UP
        return facts

    def _break_fact(self, fact_type, side, swing: Swing, idx: int, ts: datetime) -> dict:
        return {
            "fact_type": fact_type,
            "details": {"side": side, "level": swing.price, "swing_index": swing.index},
            "index": idx,
        }

    # -- Liquidity sweep -------------------------------------------------

    def _detect_sweep(self, idx: int, ts: datetime) -> list[dict]:
        """Mèche qui dépasse un swing confirmé SANS close au-delà."""
        facts: list[dict] = []
        high = self._highs[idx]
        low = self._lows[idx]
        close = self._closes[idx]

        last_low = self.last_swing_low
        if last_low is not None and low < last_low.price and close >= last_low.price:
            facts.append({"fact_type": FACT_SWEEP,
                          "details": {"side": BEAR, "level": last_low.price,
                                      "swing_index": last_low.index},
                          "index": idx})

        last_high = self.last_swing_high
        if last_high is not None and high > last_high.price and close <= last_high.price:
            facts.append({"fact_type": FACT_SWEEP,
                          "details": {"side": BULL, "level": last_high.price,
                                      "swing_index": last_high.index},
                          "index": idx})
        return facts

    # -- FVG -------------------------------------------------------------

    def _detect_fvg(self, idx: int, ts: datetime) -> list[dict]:
        if idx < 2:
            return []
        low = self._lows[idx]
        high = self._highs[idx]
        high2 = self._highs[idx - 2]
        low2 = self._lows[idx - 2]

        facts: list[dict] = []
        if low > high2:
            facts.append({"fact_type": FACT_FVG,
                          "details": {"side": BULL, "top": low, "bottom": high2},
                          "index": idx})
        if high < low2:
            facts.append({"fact_type": FACT_FVG,
                          "details": {"side": BEAR, "top": low2, "bottom": high},
                          "index": idx})
        return facts

    # -- Order block -------------------------------------------------------

    def _detect_order_block(self, idx: int) -> list[dict]:
        """Dernière bougie opposée avant un corps impulsif (bull/bear).

        Garde-fou : pas d'ORDER_BLOCK tant qu'il n'y a pas au moins
        order_block_min_candles bougies disponibles — sinon la moyenne
        glissante des corps serait calculée sur une fenêtre partielle,
        instable en début de série, et polluerait le backtest.
        """
        if idx < self.order_block_min_candles:
            return []

        body_now = self._bodies[idx]
        window = self._bodies[max(0, idx - 9):idx]
        if not window:
            return []
        mean_body = sum(window) / len(window)
        if mean_body <= 0 or body_now < self.impulse_body_ratio * mean_body:
            return []

        ob_idx = idx - 1
        ob_is_bearish = self._closes[ob_idx] < self._opens[ob_idx]
        ob_is_bullish = self._closes[ob_idx] > self._opens[ob_idx]
        impulse_bullish = self._closes[idx] > self._opens[idx]

        facts: list[dict] = []
        if impulse_bullish and ob_is_bearish:
            facts.append({"fact_type": FACT_ORDER_BLOCK,
                          "details": {"side": BULL, "index": ob_idx},
                          "index": idx})
        if not impulse_bullish and ob_is_bullish:
            facts.append({"fact_type": FACT_ORDER_BLOCK,
                          "details": {"side": BEAR, "index": ob_idx},
                          "index": idx})
        return facts


class MarketScanner:
    """Agrège l'état de structure et produit des ScannerFact horodatés."""

    def __init__(self, swing_neighbors: int = 3, impulse_body_ratio: float = 1.5,
                 order_block_min_candles: int = 20, journal=None) -> None:
        self.swing_neighbors = swing_neighbors
        self.impulse_body_ratio = impulse_body_ratio
        self.order_block_min_candles = order_block_min_candles
        self.journal = journal
        self._inc_state: MarketStructureState | None = None

    def scan(self, pair: str, timeframe: str, df: pd.DataFrame) -> list[ScannerFact]:
        """Rejoue tout l'historique dans l'ordre — mode backtest/live identique.

        Si un journal est fourni, chaque constat y est tracé (log_fact),
        rendant toute opportunité reconstitutable a posteriori (§5.6).
        """
        if df is None or len(df) == 0:
            return []

        required = {"time", "open", "high", "low", "close"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Colonnes manquantes: {sorted(missing)}")

        state = MarketStructureState(
            swing_neighbors=self.swing_neighbors,
            impulse_body_ratio=self.impulse_body_ratio,
            order_block_min_candles=self.order_block_min_candles,
        )

        facts: list[ScannerFact] = []
        for idx, (_, candle) in enumerate(df.iterrows()):
            ts = candle.get("time", None)
            dt = pd.to_datetime(ts).to_pydatetime() if ts is not None else datetime.utcnow()
            for raw in state.update_state(candle, idx, dt):
                fact = ScannerFact(
                    pair=pair,
                    timeframe=timeframe,
                    fact_type=raw["fact_type"],
                    details=raw["details"],
                    timestamp=dt,
                )
                facts.append(fact)
                if self.journal is not None:
                    self.journal.log_fact(fact)
        return facts

    def begin(self, pair: str, timeframe: str) -> "MarketScanner":
        """Démarre un scan incrémental — état persistant en interne.

        Mode O(n) pour le backtest au lieu de rejouer tout l'historique
        à chaque bougie. update() à suivre obligatoirement (sinon état
        incohérent entre deux scans).
        """
        self._inc_state = MarketStructureState(
            swing_neighbors=self.swing_neighbors,
            impulse_body_ratio=self.impulse_body_ratio,
            order_block_min_candles=self.order_block_min_candles,
        )
        self._inc_pair = pair
        self._inc_timeframe = timeframe
        return self

    def update(self, candle: pd.Series, index: int) -> list[ScannerFact]:
        """Absorbe une bougie dans l'état incrémental, retourne ses faits.

        Identique en sémantique à scan() fenêtré (une bougie = ses faits),
        mais chaque bougie n'est absorbée qu'une seule fois.
        """
        if self._inc_state is None:
            raise RuntimeError("begin() non appelé — scan incrémental requis")
        ts = candle.get("time", None)
        dt = pd.to_datetime(ts).to_pydatetime() if ts is not None else datetime.utcnow()
        facts: list[ScannerFact] = []
        for raw in self._inc_state.update_state(candle, index, dt):
            fact = ScannerFact(
                pair=self._inc_pair,
                timeframe=self._inc_timeframe,
                fact_type=raw["fact_type"],
                details=raw["details"],
                timestamp=dt,
            )
            facts.append(fact)
            if self.journal is not None:
                self.journal.log_fact(fact)
        return facts