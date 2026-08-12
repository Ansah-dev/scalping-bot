"""
Couche d'accès SQLite — initialisation depuis schema.sql (§7.4).

Une seule connexion par chemin de base. Le schéma est appliqué
idempotemment via schema.sql (CREATE TABLE IF NOT EXISTS implicite
via PRAGMA + lecture SQL). Chaque module (Journal, Risk Manager, ...)
reçoit la connexion partagée.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "ai_trading_os.db"

_connections: dict[str, sqlite3.Connection] = {}


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Retourne la connexion partagée pour un chemin de base donné."""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    key = str(path.resolve())
    if key in _connections:
        return _connections[key]

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _connections[key] = conn
    return conn


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Applique schema.sql sur une nouvelle connexion. Idempotent."""
    conn = get_connection(db_path)
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"schema.sql introuvable: {SCHEMA_PATH}")
    if not _schema_applied(conn):
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    return conn


def _schema_applied(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' "
        "AND name IN ('accounts', 'decisions', 'trades') LIMIT 1"
    ).fetchone()
    return row is not None


def close_all() -> None:
    for conn in _connections.values():
        conn.close()
    _connections.clear()
