-- ============================================================
-- AI Trading OS — MVP
-- Schéma SQLite (basé sur §7.4 du cahier des charges)
-- ============================================================

PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- Comptes (broker, démo, simulation)
-- ------------------------------------------------------------
CREATE TABLE accounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    broker          TEXT NOT NULL,                 -- ex: 'MT5'
    account_type    TEXT NOT NULL CHECK (account_type IN ('PERSONAL', 'DEMO', 'SIMULATION')),
    currency        TEXT NOT NULL DEFAULT 'USD',
    balance         REAL NOT NULL DEFAULT 0,
    equity          REAL NOT NULL DEFAULT 0,
    leverage        INTEGER,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Stratégies et leurs versions
-- ------------------------------------------------------------
CREATE TABLE strategies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE strategy_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id     INTEGER NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
    version         TEXT NOT NULL,                 -- ex: '1.0'
    conditions_json TEXT NOT NULL,                 -- JSON : {"BOS": true, "FVG": true, ...}
    risk_percent    REAL NOT NULL,                 -- ex: 0.5
    risk_reward     REAL NOT NULL,                 -- ex: 2.0
    pair            TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 0,    -- 0/1
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (strategy_id, version)
);

-- ------------------------------------------------------------
-- Décisions du Decision Engine (BUY / SELL / WAIT)
-- Enregistre TOUT, y compris les WAIT (voir §5.6 du cahier des charges)
-- ------------------------------------------------------------
CREATE TABLE decisions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_version_id INTEGER NOT NULL REFERENCES strategy_versions(id),
    pair                TEXT NOT NULL,
    result              TEXT NOT NULL CHECK (result IN ('BUY', 'SELL', 'WAIT')),
    reasoning_tags      TEXT,                       -- JSON array, ex: '["BOS","FVG","SWEEP"]'
    wait_reason         TEXT,                        -- rempli seulement si result = 'WAIT'
    timestamp           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_decisions_pair_time ON decisions(pair, timestamp);
CREATE INDEX idx_decisions_result ON decisions(result);

-- ------------------------------------------------------------
-- TradeSignal — produit uniquement quand decisions.result IN ('BUY','SELL')
-- ------------------------------------------------------------
CREATE TABLE trade_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL UNIQUE REFERENCES decisions(id) ON DELETE CASCADE,
    entry           REAL NOT NULL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    confidence      REAL,                          -- 0.0 - 1.0, optionnel en MVP
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Passage devant le Risk Manager — APPROVE / REJECT (droit de veto)
-- ------------------------------------------------------------
CREATE TABLE risk_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_signal_id INTEGER NOT NULL REFERENCES trade_signals(id) ON DELETE CASCADE,
    outcome         TEXT NOT NULL CHECK (outcome IN ('APPROVED', 'REJECTED')),
    reason          TEXT,                          -- ex: 'MAX_DAILY_LOSS', 'MAX_POSITIONS', 'SPREAD_TOO_HIGH'
    position_size   REAL,                           -- calculé seulement si APPROVED
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_risk_events_outcome ON risk_events(outcome);

-- ------------------------------------------------------------
-- Ordres envoyés au Broker Connector (MT5 ou Simulation)
-- ------------------------------------------------------------
CREATE TABLE orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_signal_id INTEGER NOT NULL REFERENCES trade_signals(id),
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    broker_order_id TEXT,                          -- identifiant renvoyé par MT5/Simulation
    status          TEXT NOT NULL CHECK (status IN ('PENDING', 'FILLED', 'REJECTED', 'CANCELLED')),
    submitted_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ------------------------------------------------------------
-- Trades effectivement exécutés / clôturés
-- ------------------------------------------------------------
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id        INTEGER NOT NULL UNIQUE REFERENCES orders(id),
    account_id      INTEGER NOT NULL REFERENCES accounts(id),
    pair            TEXT NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('BUY', 'SELL')),
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    lot_size        REAL NOT NULL,
    pnl             REAL,                          -- rempli à la clôture
    r_multiple      REAL,                           -- pnl / risque initial
    opened_at       TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at       TEXT
);

CREATE INDEX idx_trades_pair ON trades(pair);
CREATE INDEX idx_trades_opened_at ON trades(opened_at);

-- ------------------------------------------------------------
-- Logs système — utile dès le MVP pour diagnostiquer les pannes
-- (ex: erreurs de login MT5, coupures réseau — voir historique du projet)
-- ------------------------------------------------------------
CREATE TABLE system_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    level           TEXT NOT NULL CHECK (level IN ('INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    component       TEXT NOT NULL,                 -- ex: 'MT5Connector', 'RiskManager'
    message         TEXT NOT NULL,
    error_code      TEXT,                           -- ex: code d'erreur MT5 (mt5.last_error())
    timestamp       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_system_logs_level_time ON system_logs(level, timestamp);
