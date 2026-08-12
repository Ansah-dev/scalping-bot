"""
Mt5DataSource — export de bougies réelles depuis MetaTrader 5 pour le backtest.

Phase 1 : alimenter BacktestEngine.run(df, strategy) avec de VRAIS M5.
Le code s'appuie sur l'expérience de l'ancien bot (data_extractor.py /
mt5_connection.py) : mt5.copy_rates_range() / copy_rates_from() renvoient
des bougies M5 directement en DataFrame-compatible, sans parsing CSV.

Contrat de sortie (BacktestEngine + MarketScanner) :
    - colonnes : time (datetime), open, high, low, close, volume
    - time : DatetimeIndex UTC (le serveur MT5 donne le temps du serveur ;
      on reste en UTC-naïf pour coller aux autres sources)
    - volume : tick_volume (disponible partout, même en M5)

MetaTrader5 n'existe pas sur cette machine (Linux sans Wine) — l'import
est donc tardif (lazy). Tout le reste du module s'importe sans erreur.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

MT5_TIMEFRAMES = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
}

CANONICAL_COLUMNS = ["time", "open", "high", "low", "close", "volume"]


@dataclass
class Mt5Credentials:
    """Identifiants MT5, passés explicitement (compte démo OK)."""

    account_id: Optional[int] = None
    password: str = ""
    server: str = ""
    terminal_path: Optional[str] = None

    @classmethod
    def from_env(cls) -> "Mt5Credentials":
        env_path = os.environ.get(
            "DOTENV_PATH", Path(__file__).parent.parent.parent / ".env")
        from dotenv import dotenv_values

        env = dotenv_values(env_path)
        return cls(
            account_id=int(env["MT5_ACCOUNT_ID"]) if env.get("MT5_ACCOUNT_ID") else None,
            password=env.get("MT5_PASSWORD", ""),
            server=env.get("MT5_SERVER", ""),
            terminal_path=env.get("MT5_TERMINAL_PATH") or None,
        )


class Mt5NotAvailableError(RuntimeError):
    """MetaTrader5 absent (pas d'installation MT5 / pas de Wine)."""


class Mt5ConnectionError(RuntimeError):
    """Échec d'initialisation / login MT5."""


def import_mt5():
    """Import paresseux de MetaTrader5 avec un message d'erreur clair."""
    try:
        import MetaTrader5

        return MetaTrader5
    except ImportError:
        raise Mt5NotAvailableError(
            "MetaTrader5 n'est pas installé. Il faut le terminal MT5 "
            "(Windows natif, ou Linux via Wine) pour exporter l'historique."
        ) from None


def rates_to_df(rates) -> pd.DataFrame:
    """Transforme le tableau numpy renvoyé par copy_rates_range/from en
    DataFrame canonique (time, open, high, low, close, volume).

    `rates`: None ou un array numpy avec les champs time (seconds epoch),
    open, high, low, close, tick_volume, [spread, real_volume].
    """
    if rates is None or len(rates) == 0:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(None)
    df["volume"] = df["tick_volume"] if "tick_volume" in df.columns else 0
    return df[CANONICAL_COLUMNS]


class Mt5DataSource:
    """Exporte l'historique réel depuis un account MT5 (démo ou réel).

    Usage:
        src = Mt5DataSource(Mt5Credentials.from_env())
        src.connect()
        df = src.fetch_rates(pair="EURUSD", timeframe="M5",
                             date_from=datetime(2026, 1, 1),
                             date_to=datetime(2026, 6, 1))
        src.export_to_csv(df, "data/eurusd_m5.csv")
    """

    def __init__(self, credentials: Optional[Mt5Credentials] = None,
                 mt5_module=None) -> None:
        self.credentials = credentials or Mt5Credentials.from_env()
        # module injectable pour les tests (pas de MT5 sur Linux)
        self._mt5 = mt5_module
        self._connected = False

    # -- Connexion -------------------------------------------------------

    @property
    def mt5(self):
        if self._mt5 is not None:
            return self._mt5
        self._mt5 = import_mt5()
        return self._mt5

    def connect(self) -> bool:
        mt5 = self.mt5
        init_kwargs = {}
        if self.credentials.terminal_path:
            init_kwargs["path"] = self.credentials.terminal_path
        if not mt5.initialize(**init_kwargs):
            raise Mt5ConnectionError(
                f"mt5.initialize échoué : {mt5.last_error()}")
        if self.credentials.account_id:
            if not mt5.login(self.credentials.account_id,
                             self.credentials.password,
                             self.credentials.server):
                # dernière_error en live = impossible à login sans terminal
                raise Mt5ConnectionError(
                    f"mt5.login échoué pour {self.credentials.account_id} "
                    f"@{self.credentials.server} : {mt5.last_error()}")
        self._connected = True
        return True

    def disconnect(self) -> None:
        if self._connected:
            try:
                self.mt5.shutdown()
            except Exception:  # pragma: no cover
                pass
            self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # -- Données ----------------------------------------------------------

    def fetch_rates(self, pair: str, timeframe: str = "M5",
                    date_from: Optional[datetime] = None,
                    date_to: Optional[datetime] = None,
                    count: Optional[int] = None) -> pd.DataFrame:
        """Bougies M5 (ou autre timeframe) d'un pair.

        Si date_from+date_to: copy_rates_range (fenêtre chronologique).
        Sinon si count:      copy_rates_from (les N dernières bougies
                             jusqu'à date_to, défaut = maintenant).
        """
        if not self._connected:
            raise Mt5ConnectionError("connect() doit être appelé avant fetch")
        mt5 = self.mt5
        tf_attr = MT5_TIMEFRAMES.get(timeframe)
        if tf_attr is None:
            raise ValueError(f"timeframe inconnu: {timeframe} "
                             f"(attendu: {sorted(MT5_TIMEFRAMES)})")
        tf = getattr(mt5, tf_attr)

        rates = None
        if date_from is not None and date_to is not None:
            rates = mt5.copy_rates_range(pair, tf, date_from, date_to)
        elif count is not None:
            rates = mt5.copy_rates_from(pair, tf, date_to or datetime.now(), count)
        elif date_from is not None:
            rates = mt5.copy_rates_from(pair, tf, date_from, 500_000)
        else:
            raise ValueError("Préciser date_from+date_to, ou count, ou date_from")

        if rates is None:
            logger.warning("copy_rates_* a retourné None (dernier MT5 error: %s)",
                           mt5.last_error())
        df = rates_to_df(rates)
        logger.info("%s %s : %d bougies exportées", pair, timeframe, len(df))
        return df

    def export_to_csv(self, df: pd.DataFrame, out_path: str | Path) -> Path:
        """Écrit df au format canonique CSV (time, open, high, low, close, volume)."""
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        df[CANONICAL_COLUMNS].to_csv(out, index=False)
        logger.info("CSV écrit: %s (%d bougies)", out, len(df))
        return out


def load_dataframe(csv_path: str | Path) -> pd.DataFrame:
    """Relit un CSV exporté (backtest hors-connexion MT5)."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Export introuvable: {path}")
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"])
    return df