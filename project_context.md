# Scalping-Bot — Full Project Context

## Short Description
Automated Forex/CFD scalping bot for MetaTrader 5, controlled via Telegram, with AI validation (Google Gemini), order-flow analysis, prop-firm risk management, and multi-channel alerts.

## Tech Stack
- Python 3.10+, MetaTrader5, python-telegram-bot (async)
- Google Generative AI (Gemini 1.5 Flash)
- pandas, ta (Technical Analysis Library), requests
- No database — state persisted in `.env` via `python-dotenv set_key`
- Deployment: Windows natively, or Linux via Wine

## Architecture (11 modules, ~880 LOC)

| Module | Purpose |
|---|---|
| `main.py` | Telegram bot entry point, command handlers (`/start`, `/scalp`, `/login`, `/target`), background auto-scalper thread |
| `scalping_engine.py` | Auto-scalper loop (every 60s), manual `/scalp` trigger |
| `strategy_advanced.py` | Technical analysis: EMA50/200 trend detection, Fair Value Gap (FVG) detection, 1:2 risk-reward logic |
| `data_extractor.py` | Tick classification (buy/sell), buyer vs seller volume delta for order flow |
| `ai_brain.py` | Gemini prompt combining signal + order flow → `APPROVED` / `REJECTED` |
| `fundamentals.py` | ForexFactory weekly JSON calendar check — blocks trading during high-impact news within 2h window |
| `risk_manager.py` | 4% daily / 8% total drawdown limits (prop-firm mode), `/target` equity profit-taking, dynamic lot sizing (0.01–0.05), asset-specific equity lockouts |
| `mt5_trade.py` | Low-level `order_send()` and `close_position()` wrapper (magic number 2024) |
| `mt5_connection.py` | MT5 terminal initialization, account login (static from `.env` + dynamic via `/login`) |
| `alerts_manager.py` | Multi-channel broadcast: Telegram, SMTP email, Africa's Talking SMS |

## Trading Parameters
- **Pairs:** EURUSD, BTCUSD, GBPUSD, USDCAD
- **Timeframes:** M5 / M15 for analysis
- **Lot size:** Dynamic 0.01–0.05 based on account equity
- **Prop-firm mode:** Daily drawdown 4%, total drawdown 8%
- **TP management:** Auto-collects 50% profit on profitable positions; `/target` command stops bot when equity goal is reached

## Scalp Flow (per trade)
1. **Technical Analysis** → Trend direction + FVG signal
2. **Order Flow** → Buyer/seller dominance from recent ticks
3. **Fundamental Filter** → High-impact news in base or quote currency?
4. **AI Validation** → Gemini evaluates the combined signal
5. **Risk Check** → Drawdown limits, equity lockouts, lot sizing
6. **Trade Execution** → Market order with SL/TP
7. **Alert** → Broadcast via enabled channels (Telegram/Email/SMS)

## Telegram Commands

| Command | Function |
|---|---|
| `/start` | Welcome message, shows current account equity |
| `/scalp [pair]` | Manual analysis and trade for a specific pair |
| `/login` | 3-step conversation to change MT5 broker/account |
| `/target [amount]` | Set profit target — when equity reaches it, all positions close and bot halts |

## Git History (9 commits, single `main` branch, March 18 – April 10 2026)

| Commit | Description |
|---|---|
| 1 | `6a3e32a` — Initial commit (README only) |
| 2 | `45b2165` — Empty `main.py` placeholder |
| 3 | `a33c506` — Basic polling loop + hardcoded MT5 connection |
| 4 | `d962a0f` — **Major**: Telegram bot, scalping engine, 4 pairs, news filter, `mt5_trade.py`, `strategy_advanced.py`, `fundamentals.py` |
| 5 | `f5ff927` — Wine setup script + Python 3.10 Windows installer |
| 6 | `4ea2a40` — MT5 installer binary (`mt5setup.exe`) added |
| 7 | `9875b31` — **Major**: AI validation (Gemini), order flow analysis, risk manager with prop-firm drawdown, `ai_brain.py`, `data_extractor.py`, `risk_manager.py` |
| 8 | `867f8ae` — Dynamic `/login` broker switching, GEMINI_API_KEY, safe division fixes |
| 9 | `8fe858c` — **Major**: Target equity (`/target`), multi-channel alerts (Telegram/SMS/Email), `alerts_manager.py` |

## Known Gaps & Next Steps

1. **No `.gitignore`** — `.pyc`, `.exe`, `.zip` files are tracked
2. **No backtesting** — strategy has never been validated on historical data
3. **No tests** — zero unit or integration tests
4. **Fault tolerance** — no retry logic for MT5 disconnects, API timeouts, or network failures
5. **Monitoring** — no dashboard, no centralized logging, no performance metrics
6. **Limited pairs** — only 4 hardcoded pairs; needs a configurable pair list
7. **No database** — everything in `.env`; no multi-session or persistent trade history
8. **Deployment** — no Docker, no CI/CD, no VPS provisioning script
9. **Performance metrics** — win rate, Sharpe ratio, equity curve, drawdown charts not tracked
10. **Single account** — only one MT5 account at a time
