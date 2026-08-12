"""Export M5 réel depuis un account MT5 (démo) vers CSV — Phase 1 du MVP.

Usage:
    python -m ai_trading_os_mvp.scripts.export_mt5_data --pair EURUSD \
        --months 6 --out data/m5/eurusd_m5.csv
    python -m ai_trading_os_mvp.scripts.export_mt5_data \
        --from 2026-01-01 --to 2026-06-01 --pair GBPUSD --timeframe M15

Lit MT5_ACCOUNT_ID / MT5_PASSWORD / MT5_SERVER / MT5_TERMINAL_PATH dans
le .env racine (compte démo = historique identique au réel). Sans
MetaTrader5 installé (Linux sans Wine), l'erreur est explicite.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ai_trading_os_mvp.datasource.mt5 import (  # noqa: E402
    Mt5ConnectionError,
    Mt5Credentials,
    Mt5DataSource,
    Mt5NotAvailableError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export d'historique MT5 en CSV")
    p.add_argument("--pair", default="EURUSD", help="Symbole MT5 (EURUSD, ...)")
    p.add_argument("--timeframe", default="M5",
                   choices=["M1", "M5", "M15", "M30", "H1"])
    p.add_argument("--months", type=int, default=None,
                   help="Nombre de mois en arrière (depuis maintenant)")
    p.add_argument("--from", dest="date_from", type=lambda s: datetime.fromisoformat(s),
                   default=None, help="Date de début (ISO, ex 2026-01-01)")
    p.add_argument("--to", dest="date_to", type=lambda s: datetime.fromisoformat(s),
                   default=None, help="Date de fin (ISO, ex 2026-06-01)")
    p.add_argument("--out", default=None, help="Chemin CSV de sortie")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.months:
        date_to = args.date_to or datetime.now()
        date_from = args.date_from or (date_to - timedelta(days=args.months * 30))
    else:
        date_from = args.date_from
        date_to = args.date_to
        if date_from is None or date_to is None:
            print("Préciser --months, ou --from + --to", file=sys.stderr)
            return 2

    out = args.out or REPO_ROOT / "ai_trading_os_mvp" / "data" / \
        f"m5_{args.pair.lower()}.csv"

    try:
        src = Mt5DataSource(Mt5Credentials.from_env())
        src.connect()
        try:
            df = src.fetch_rates(pair=args.pair, timeframe=args.timeframe,
                                 date_from=date_from, date_to=date_to)
            if df.empty:
                print("Aucune bougie retournée — vérifier pair/date/période.",
                      file=sys.stderr)
                return 3
            src.export_to_csv(df, out)
        finally:
            src.disconnect()
    except Mt5NotAvailableError as exc:
        print(f"MT5 indisponible: {exc}", file=sys.stderr)
        return 4
    except Mt5ConnectionError as exc:
        print(f"Connexion MT5 échouée: {exc}", file=sys.stderr)
        return 5

    print(f"Export OK -> {out} ({len(df)} bougies {args.pair} {args.timeframe})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())