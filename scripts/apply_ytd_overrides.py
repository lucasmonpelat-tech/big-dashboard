"""
apply_ytd_overrides.py
=======================
Fase B del fix YTD del race:
Toma los YTD reales (extraidos del Maximus factsheet 30-Jun-2026) y sobreescribe
los valores 'ytd_return_pct' en equity_race.json, fi_race.json, y alts_race.json.

Uso:
    python scripts/apply_ytd_overrides.py

Rerun cada mes con nuevos YTD del factsheet mensual Maximus.
"""
import json
from datetime import datetime
from pathlib import Path

ROOT = Path("C:/Users/lmonp/OneDrive/Desktop/Code/big-dashboard/data")
ANCHORS = ROOT / "year_start_anchors.json"

RACE_FILES = ["equity_race.json", "fi_race.json", "alts_race.json"]


def main():
    anchors = json.loads(ANCHORS.read_text(encoding="utf-8"))
    ytd_map = {}  # ticker -> ytd_pct
    for isin, info in anchors["anchors_2026"].items():
        if info.get("ytd_source_pct") is not None:
            ytd_map[info["ticker"]] = info["ytd_source_pct"]

    print(f"YTD overrides disponibles: {len(ytd_map)}")
    for t, v in ytd_map.items():
        print(f"  {t}: {v}%")

    updated_total = 0
    for race_fn in RACE_FILES:
        race_path = ROOT / race_fn
        if not race_path.exists():
            print(f"\n  [SKIP] {race_fn} no existe")
            continue

        data = json.loads(race_path.read_text(encoding="utf-8"))
        holdings = data.get("holdings", [])

        n_updated = 0
        for h in holdings:
            ticker = h.get("ticker")
            if not ticker:
                continue
            if ticker in ytd_map:
                old = h.get("ytd_return_pct")
                new = ytd_map[ticker]
                if old != new:
                    h["ytd_return_pct"] = new
                    n_updated += 1
                    print(f"  [{race_fn}] {ticker}: {old} -> {new}")

        if n_updated > 0:
            data["_ytd_override_applied"] = datetime.now().isoformat()
            data["_ytd_override_source"] = "Maximus factsheet 30-Jun-2026 via year_start_anchors.json"
            race_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  [{race_fn}] Guardado con {n_updated} updates")
            updated_total += n_updated

    print(f"\nTotal updates: {updated_total}")


if __name__ == "__main__":
    main()
