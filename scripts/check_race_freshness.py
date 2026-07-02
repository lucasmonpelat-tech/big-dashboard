"""
check_race_freshness.py
=======================
Chequea que TODOS los archivos que alimentan los Race tabs esten frescos
(refreshedAt de HOY o del ultimo business day).

Output: JSON con status de cada archivo + banderas para el chat.

Usage:
    python scripts/check_race_freshness.py
    python scripts/check_race_freshness.py --json  # solo JSON, sin texto

Devuelve exit code 1 si algo NO esta fresco (util para cron).
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

# Archivos a chequear + edad maxima permitida en dias
# (0 = debe ser de hoy, 1 = puede ser de ayer, etc)
FILES_TO_CHECK = [
    # Fuente cruda de precios
    ("live_prices.json", 3, "Stooq T-1 (ETFs)"),
    ("ucits_daily_nav.json", 3, "baha T-1 (UCITS)"),
    ("lynk_data.json", 3, "Lynk NAV oficial"),
    ("lynk_nav_series.json", 3, "Lynk serie NAV"),

    # Sleeves (chart Base 100)
    ("equity_sleeve_real.json", 3, "Chart Equity Base 100"),
    ("fi_sleeve_real.json", 3, "Chart FI Base 100"),

    # Race JSONs (cuadros del UI)
    ("equity_race.json", 3, "Equity Race cuadro"),
    ("fi_race.json", 3, "FI Race cuadro"),
    ("alts_race.json", 3, "Alts Race cuadro"),

    # Holdings returns (cost basis + YTD)
    ("holdings_returns_equity.json", 3, "Equity YTD cost-basis"),
    ("holdings_returns_fixed_income.json", 3, "FI YTD cost-basis"),
    ("holdings_returns_alternatives.json", 3, "Alts YTD cost-basis"),

    # Attribution
    ("attribution_ytd.json", 3, "Brinson Attribution YTD"),

    # Positions
    ("positions_latest.json", 30, "Pershing positions (mensual)"),
]


def get_refreshed_at(fpath: Path):
    """Extrae refreshedAt o mtime como fallback."""
    if not fpath.exists():
        return None
    try:
        d = json.load(open(fpath, encoding="utf-8"))
        for key in ("refreshedAt", "_updated", "as_of_date", "asOf"):
            if key in d and d[key]:
                ts = str(d[key])
                # Normalizar: puede ser ISO datetime o solo fecha
                try:
                    return datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(tzinfo=None)
                except ValueError:
                    # solo fecha
                    try:
                        return datetime.combine(date.fromisoformat(ts[:10]), datetime.min.time())
                    except ValueError:
                        pass
    except Exception:
        pass
    # Fallback: mtime del archivo
    try:
        return datetime.fromtimestamp(fpath.stat().st_mtime)
    except Exception:
        return None


def business_days_between(d1: date, d2: date) -> int:
    """Cuenta business days (L-V) entre d1 y d2 inclusive."""
    if d1 > d2:
        d1, d2 = d2, d1
    count = 0
    curr = d1
    while curr < d2:
        curr += timedelta(days=1)
        if curr.weekday() < 5:  # 0-4 = L-V
            count += 1
    return count


def main():
    today = date.today()
    results = []
    stale_count = 0

    for fname, max_age_days, description in FILES_TO_CHECK:
        fpath = DATA / fname
        refreshed = get_refreshed_at(fpath)

        if refreshed is None:
            status = "MISSING"
            age_bd = None
            stale = True
        else:
            refreshed_date = refreshed.date()
            age_bd = business_days_between(refreshed_date, today)
            stale = age_bd > max_age_days

        if stale:
            stale_count += 1

        results.append({
            "file": fname,
            "description": description,
            "refreshedAt": refreshed.isoformat() if refreshed else None,
            "age_business_days": age_bd,
            "max_age_days": max_age_days,
            "status": "OK" if not stale else ("MISSING" if refreshed is None else "STALE"),
        })

    summary = {
        "checked_at": datetime.now().isoformat(),
        "today": today.isoformat(),
        "total_files": len(FILES_TO_CHECK),
        "stale_count": stale_count,
        "all_fresh": stale_count == 0,
        "results": results,
    }

    if "--json" in sys.argv:
        print(json.dumps(summary, indent=2))
    else:
        print(f"[{summary['checked_at'][:19]}] Race freshness check")
        print(f"Today: {today}")
        print()
        for r in results:
            emoji = "OK" if r["status"] == "OK" else ("!!" if r["status"] == "STALE" else "??")
            age = f"{r['age_business_days']}bd" if r['age_business_days'] is not None else "n/a"
            print(f"  [{emoji}] {r['file']:40s} {age:>6s} - {r['description']}")
        print()
        if stale_count == 0:
            print("[OK] Todos los archivos frescos")
        else:
            print(f"[STALE] {stale_count} archivos no fresh - REVISAR")

    return 0 if stale_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
