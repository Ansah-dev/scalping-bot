# AI Trading OS MVP — Catch-up / Session Context (for OpenCode DeepSeek)

> Created for a fresh agent session to resume instantly. Read this file FIRST,
> then verify with `cd /home/desmond/scalping-bot && python -m pytest ai_trading_os_mvp/tests/ -q`.

---

## What this project is

An **AI Trading OS MVP** redesigned from scratch inside
`/home/desmond/scalping-bot/ai_trading_os_mvp/` — a clean-room reimplementation of the
old MT5/TG bot (see root `project_context.md` for the OLD bot; do NOT confuse them).
Spec: `/home/desmond/Downloads/cahier_des_charges_ai_trading_os_mvp.md`.

**Contract copies come from `/home/desmond/Downloads/backend-scaffold-new/files/`
(broker_interface.py, schema.sql, trade_signal.py) — copied VERBATIM, never edit
their signatures.** `ai_trading_os_mvp/decision/trade_signal.py` is the untouched
contract (its `datetime.utcnow()` deprecation warnings are accepted).

## Status: ALL 6 modules implemented + Journal↔Broker wiring + MT5 datasource.

**82 tests, ALL PASSING** (`pytest ai_trading_os_mvp/tests/ -q`). 1200+ warnings =
known `utcnow` deprecation warnings from the trade_signal contract + `random.gauss`
in integration tests. NOT a problem.

---

## THE AIM (why this project exists)

**Prove — with real historical data — whether our scalping strategy has a real,
positive expected edge; and if it does, evolve it into a complete, trustworthy
"AI Trading OS" that replaces the old untested bot.**

The old bot (root `project_context.md`) never had a backtest or tests: it traded
live on faith, with no evidence of edge, no database, no traceability. This MVP is
the ground-up rebuild where **every decision is measurable before a single real
dollar is risked**. The single question the whole MVP must answer:

> "Does the FVG/BOS/CHoCH/sweep structure — detected via our pipeline — produce a
> win-rate × RR combination that beats the market (positive expectancy)?"

Non-negotiables baked into the design (already enforced):
- **No lookahead** — a backtest that cheats is worse than no backtest.
- **No divergence** between backtest logic and live logic (§6 of the spec).
- **Full traceability** — every opportunity, decision, and rejection is journaled
  (§5.6), so we can always answer "how many setups did we miss?"
- **Verified, not asserted** — every module ships with tests that prove behavior
  (including the pessimistic SL-vs-TP rule, the vetoes, the fill rule).

---

## THE ROAD (the path to that aim)

### Phase 0 — Foundation & MVP pipeline ✅ DONE
- Contracts verbatim (scanner/decision/risk/broker/schema)
- 6 modules + tests, 67 green; scanner O(n); backtest engine + reports
- Journal↔Broker SQLite wiring (full chain persisted)
- ✓ Every module validated step-by-step with the user (one at a time)

### Phase 1 — Prove the edge on REAL data ⏳ NEXT (awaiting user decision)
- Get real historical M5 candles: **MT5 export / Dukascopy / HistData** (TBD together)
- Run `BacktestEngine.run(df, strategy)` on months of real data, several pairs
- Decision gate: positive expectancy / healthy profit factor? if not, iterate params
- **Do NOT start without the user — they want to plan the data source together**

### Phase 2 — Iterate & hardening (post-edge-proof)
- Strategy parameter tuning from Phase 1 results, more pairs/timeframes
- Walk-forward / out-of-sample validation so the edge is not overfitted
- Edge-case hardening, performance profiling on big datasets

### Phase 3 — Live-ready (only if edge holds)
- `MT5Connector` (real broker, live pipeline) — same code path as backtest
- Telegram Assistant (§5.7): /status, /pause, /report…
- News filter (re-introduced with injectable, mockable calendar provider)
- SAFE_MODE, stop-loss at system level, alerts

### Phase 4 — Scale (post-live)
- Analytics dashboard, performance monitoring, multi-account
- Docker/deployment, CI/CD, retry/fault-tolerance (old bot's listed gaps)

---

## Architecture (module by module)

```
Pipeline (live AND backtest, identical logic):
 historique -> market/scanner.py -> decision/engine.py -> risk/manager.py
   -> broker/simulation_connector.py -> journal/journal.py (SQLite)
```

| Module | File | Notes |
|---|---|---|
| Scanner | `market/scanner.py` | `MarketScanner.scan(df)` (replay) + `begin()/update()` (incremental O(n), used by backtest). Swing-based structure ONLY (no EMA — "Option A"). Emits FVG, BOS, CHoCH, ORDER_BLOCK, LIQUIDITY_SWEEP facts. |
| Decision | `decision/engine.py` | `DecisionEngine.evaluate(facts, strategy) -> Decision(BUY/SELL/WAIT)` + `build_signal()`. `StrategyVersion`, `record_decision()` for journaling. WAIT reasons: STRATEGY_INACTIVE_OU_ABSENTE, CONDITIONS_MANQUANTES, SIGNAL_CONFLICTUEL. |
| Risk | `risk/manager.py` | `RiskManager.evaluate(signal, account) -> RiskDecision(APPROVED/REJECTED)`. Sizing = capital × risk% / SL distance. Veto order: SESSION → MAX_DAILY_LOSS → MAX_DRAWDOWN → MAX_POSITIONS. News filter explicitly OUT of scope (see below). |
| Broker | `broker/interface.py` | Abstract `BrokerConnector` (verbatim contract). |
| Broker | `broker/simulation_connector.py` | `SimulationBroker(BrokerConnector)` — driven bar-by-bar via `on_bar()`. Fills at the signal level (limit), validates in-bar, `ENTRY_HORS_BOUGIE` rejection. |
| Datasource | `datasource/mt5.py` | `Mt5DataSource` — export réel M5 depuis MT5 (compte démo OK) via `copy_rates_range/from`, sortie CSV canonique (time/open/high/low/close/volume). Lazy-import MetaTrader5 → tests OK sans terminal. Non-backtest = source privilégiée Phase 1. |
| Backtest | `backtesting/engine.py` | `BacktestEngine.run(df, strategy) -> BacktestReport` (win rate, profit factor, max drawdown, avg R, equity curve, perf by pair/month). |
| Journal | `journal/journal.py` | `Journal` → SQLite. logs facts, decisions (+WAIT), trade signals, risk events (+REJECTED reasons), orders, positions, trade closes. |
| Database | `database/db.py` | `get_connection()`, `init_db()` (idempotent). Schema: `schema.sql`. Default DB `data/ai_trading_os.db` — be careful not to create it accidentally. |

---

## Key decisions made deliberately (do NOT silently revert)

1. **Anti-lookahead**: BOS/CHoCH confirmed on CLOSE only; swings need
   `swing_neighbors` candles AFTER the peak; fill bar never evaluates SL/TP.
2. **SL-vs-TP intra-bar**: PESSIMISTIC — SL wins when both touched (no tick data).
3. **Intra-bar order in backtest**: (1) `broker.on_bar()` evaluates open positions
   FIRST, (2) THEN scanner/decision/risk/new entry on the same bar.
4. **Fill price**: signal entry level (limit order) validated within the fill
   candle's [low, high], NOT the candle close. Preserves the configured RR.
5. **Fact priority** (deliberate user choice): FVG > BOS > CHoCH > SWEEP > OB.
6. **News filter** (`fundamentals.py` from old bot): **explicitly OUT of scope** for
   MVP — not backtestable deterministically, external dependency, not in §5.3.
7. **`order_block_min_candles=20`** guard: no OB detected before 20 candles.
8. **scanner is stateless-external**: `scan()` replays full history; backtest uses
   `begin()/update()` incremental O(n) with IDENTICAL emitted facts (verified).
9. **Backtest only reacts to facts emitted ON THE CURRENT BAR** (incremental
   scanner), otherwise stale facts would trigger phantom re-entries.

---

## Critical gotchas / recent fixes (verify before changing)

- `StrategyVersion.from_db_row()` MUST set `strategy_version_id=row["id"]` — fixed
  a silent bug where DB-loaded strategies journaled nothing.
- Engine counts **rejected broker fills** (`rejected_fills`) — a signal approved
  by Risk but rejected by broker still gets decision+signal+risk journaled, NOT
  silently dropped (§5.6).
- `_ensure_account_id()` on engine: verifies the account row EXISTS (not just
  non-None) — a Journal seeded with a phantom account_id → `FOREIGN KEY constraint
  failed` would be swallowed as a silent journaling failure.
- `r_multiple = pnl/(risk_per_unit × volume)` — was `pnl/risk` (off by volume).
- Scanner incremental mode: call `scanner.begin(pair, timeframe)` BEFORE the loop,
  then `scanner.update(candle, index)` per bar. `scan(df)` still works for replay.

---

## Test suite layout

- `tests/test_scanner.py` (8), `test_journal.py` (5), `test_decision.py` (8),
  `test_risk.py` (10), `test_simulation_broker.py` (16+3), `test_backtesting.py` (7),
  `test_integration.py` (5, synthetic 500-1000 candles, O(n)), `test_journal_wiring.py` (4),
  `test_mt5_datasource.py` (15, MT5 stubé — pas de terminal requis).
- Demo data: `scripts/demo_scan.py` (visual scanner demo) & `scripts/demo_backtest.py`
  (visual pipeline on 20 M5 candles). Demo series in `data/demo_m5.csv`.
- Export réel: `scripts/export_mt5_data.py --pair EURUSD --months 6 --out <csv>`.
  Lit les identifiants dans le `.env` racine (MT5_ACCOUNT_ID / MT5_PASSWORD /
  MT5_SERVER / MT5_TERMINAL_PATH). Sans terminal MT5 → erreur explicite (code 4).

---

## NEXT STEP (waiting on the user)

**The real backtest on real data is the open question of the MVP.** The pipeline is
ready and wired. Data source DECIDED with the user: **MT5 export** (compte démo déjà
actif), visée **quelques mois** de M5 pour le premier backtest rapide.
`datasource/mt5.py` + `scripts/export_mt5_data.py` sont écrits (15 tests, stub MT5).
Il reste à EXÉCUTER l'export sur une machine où MT5 tourne (Windows natif ou Wine :
`MT5_TERMINAL_PATH` dans le `.env`) puis lancer
`BacktestEngine.run(load_dataframe(csv), strategy)` — et à laisser l'utilisateur
arbitrer le nombre de pairs et la date du run.

Possible follow-ups (not yet approved): Telegram integration, MT5Connector (live),
analytics dashboard, Docker/deployment.

---

## How to run things

```bash
cd /home/desmond/scalping-bot
python -m pytest ai_trading_os_mvp/tests/ -q          # 67 passed
python -m ai_trading_os_mvp.scripts.demo_backtest     # visual pipeline
python -m ai_trading_os_mvp.scripts.demo_scan         # visual scanner
```