"""Tests de la source de données MT5 (module datasource) — Phase 1.

MetaTrader5 n'est pas installé sur cette machine (Linux sans Wine) :
tous les tests passent par un module MT5 stubé, et vérifient la
conversion rates-numpy -> DataFrame canonique (BacktestEngine/Scanner).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from ai_trading_os_mvp.datasource.mt5 import (
    CANONICAL_COLUMNS,
    Mt5ConnectionError,
    Mt5Credentials,
    Mt5DataSource,
    Mt5NotAvailableError,
    import_mt5,
    load_dataframe,
    rates_to_df,
)


def make_rates(n=3, base=1.1000, start_ts=1710000000):
    """Array numpy au format exact de mt5.copy_rates_* (champs dtypes)."""
    dt = np.dtype([
        ("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"),
        ("close", "<f8"), ("tick_volume", "<i8"), ("spread", "<i4"),
        ("real_volume", "<i8")])
    rows = []
    for i in range(n):
        o = base + i * 0.001
        rows.append((start_ts + i * 300, o, o + 0.0006, o - 0.0005,
                     o + 0.0002, 1200 + i, 0, 1100 + i))
    return np.array(rows, dtype=dt)


class StubMt5:
    """Mini-module MetaTrader5 pour les tests (pas de terminal réel)."""

    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60

    def __init__(self, rates=None):
        self._rates = rates
        self._initialized = False
        self._login_called = False
        self.last_error_free = (1, "no error")

    def initialize(self, **kwargs):
        self._initialized = True
        return True

    def login(self, *args):
        self._login_called = True
        return True

    def shutdown(self):
        self._initialized = False

    def copy_rates_range(self, pair, tf, dt_from, dt_to):
        return self._rates

    def copy_rates_from(self, pair, tf, dt_from, count):
        return self._rates

    def last_error(self):
        return self.last_error_free


# -- rates_to_df ---------------------------------------------------------


def test_rates_to_df_columns_canoniques():
    df = rates_to_df(make_rates())
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 3


def test_rates_to_df_time_converti_en_datetime():
    df = rates_to_df(make_rates(start_ts=1710000000))
    assert pd.api.types.is_datetime64_any_dtype(df["time"])
    # 1710000000 s depuis epoch
    assert df["time"].iloc[0] == pd.Timestamp("2024-03-09 16:00:00")


def test_rates_to_df_volume_tick_volume():
    df = rates_to_df(make_rates())
    assert df["volume"].tolist() == [1200, 1201, 1202]


def test_rates_to_df_none_ou_vide():
    empty = rates_to_df(None)
    assert empty.empty
    assert list(empty.columns) == CANONICAL_COLUMNS
    empty2 = rates_to_df(np.array([], dtype=make_rates().dtype))
    assert empty2.empty


def test_rates_to_df_hauteurs_et_clos_preserves():
    rates = make_rates()
    df = rates_to_df(rates)
    assert df["high"].iloc[1] == pytest.approx(rates["high"][1])
    assert df["low"].iloc[1] == pytest.approx(rates["low"][1])
    assert df["close"].iloc[0] == pytest.approx(rates["close"][0])


# -- import_mt5 -----------------------------------------------------------


def test_import_mt5_leve_erreur_claire_sans_module():
    # MetaTrader5 absent ici -> message explicite, pas une ImportError brute
    with pytest.raises(Mt5NotAvailableError) as exc:
        import_mt5()
    assert "MetaTrader5" in str(exc.value)


# -- Mt5DataSource (stub) --------------------------------------------------


@pytest.fixture
def source():
    return Mt5DataSource(
        credentials=Mt5Credentials(account_id=123, password="x",
                                   server="Demo"),
        mt5_module=StubMt5(rates=make_rates()))


def test_connect_initialise_et_login(source):
    assert source.connect() is True
    assert source.is_connected() is True
    assert source.mt5._initialized is True
    assert source.mt5._login_called is True


def test_disconnect_shutdown(source):
    source.connect()
    source.disconnect()
    assert source.is_connected() is False
    assert source.mt5._initialized is False


def test_fetch_rates_retourne_df_canonique(source):
    source.connect()
    df = source.fetch_rates(pair="EURUSD", timeframe="M5",
                            date_from=pd.Timestamp("2026-01-01"),
                            date_to=pd.Timestamp("2026-02-01"))
    assert list(df.columns) == CANONICAL_COLUMNS
    assert len(df) == 3


def test_fetch_rates_echoue_sans_connect(source):
    with pytest.raises(Mt5ConnectionError):
        source.fetch_rates(pair="EURUSD")


def test_fetch_rates_timeframe_inconnu(source):
    source.connect()
    with pytest.raises(ValueError):
        source.fetch_rates(pair="EURUSD", timeframe="D1")


def test_fetch_rates_retourne_vide_si_none(source):
    source._mt5 = StubMt5(rates=None)
    source.connect()
    df = source.fetch_rates(pair="EURUSD", timeframe="M5",
                            date_from=pd.Timestamp("2026-01-01"),
                            date_to=pd.Timestamp("2026-02-01"))
    assert df.empty


def test_export_csv_et_relecture(tmp_path):
    src = Mt5DataSource(mt5_module=StubMt5(rates=make_rates()))
    src.connect()
    df = src.fetch_rates(pair="EURUSD",
                         date_from=pd.Timestamp("2026-01-01"),
                         date_to=pd.Timestamp("2026-02-01"))
    out = tmp_path / "test.csv"
    written = src.export_to_csv(df, out)
    assert written.exists()
    reloaded = load_dataframe(out)
    assert list(reloaded.columns) == CANONICAL_COLUMNS
    assert len(reloaded) == len(df)
    assert pd.api.types.is_datetime64_any_dtype(reloaded["time"])


def test_load_dataframe_fichier_absent(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_dataframe(tmp_path / "absent.csv")


def test_credentials_from_env_fichier_racine():
    creds = Mt5Credentials.from_env()
    # .env racine du repo : MT5_ACCOUNT_ID présent
    assert isinstance(creds.account_id, int)
    assert creds.account_id > 0
    assert creds.server  # MT5_SERVER renseigné