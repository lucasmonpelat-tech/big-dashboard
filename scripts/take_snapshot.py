"""
take_snapshot.py
================
Toma un snapshot del estado actual de los datos del dashboard y lo guarda
en data/snapshots/<YYYY-MM>/. Permite analisis retrospectivo:
  - "como estaba el portfolio al cierre de Abril 2026?"
  - "como evoluciono el sleeve FI trimestre a trimestre?"
  - "cuanto pesaba CSPX hace 6 meses?"

Usage:
    python scripts/take_snapshot.py                    # snapshotea el mes anterior
    python scripts/take_snapshot.py --month 2026-04    # snapshotea un mes especifico

Frecuencia recomendada:
  - Manual: cuando cierras el mes y la data esta refrescada
  - Automatica: workflow GitHub Actions corre el 15 de cada mes
"""

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"

# Archivos individuales a snapshotear (relativos a data/)
FILES_TO_SNAPSHOT = [
    # Posiciones + Lynk
    "positions_latest.json",
    "lynk_data.json",
    "lynk_nav_series.json",
    "live_prices.json",
    # Race / TWR
    "equity_race.json",
    "equity_sleeve_real.json",
    "equity_contributions_real.json",
    "equity_breakdown_latest.json",
    "acwi_overlap.json",
    "fi_race.json",
    "fi_sleeve_real.json",
    "fi_breakdown_latest.json",
    "alts_race.json",
    # Metadata (incluye BIG_POSITIONS, dicts de currency/country/yield/etc.)
    "funds_metadata.js",
    "live_prices.js",
]

# Subcarpeta entera a snapshotear (per-fund JSONs)
DIRS_TO_SNAPSHOT = [
    "funds",
]


def previous_month_iso():
    """Devuelve el mes anterior como string 'YYYY-MM'."""
    today = date.today()
    y, m = today.year, today.month
    if m == 1:
        return f"{y - 1}-12"
    return f"{y}-{m - 1:02d}"


def take_snapshot(month_iso):
    """Copia los archivos clave de data/ a data/snapshots/<month>/."""
    target_dir = SNAPSHOTS_DIR / month_iso
    target_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "snapshot_date": date.today().isoformat(),
        "month_label": month_iso,
        "files": [],
        "missing": [],
    }

    print(f"=== Snapshot para {month_iso} ===")
    print(f"Target: {target_dir}\n")

    # Files
    for rel in FILES_TO_SNAPSHOT:
        src = DATA_DIR / rel
        if not src.exists():
            manifest["missing"].append(rel)
            print(f"  [SKIP]  {rel} no existe")
            continue
        dst = target_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        size_kb = src.stat().st_size / 1024
        manifest["files"].append({
            "path": rel,
            "size_kb": round(size_kb, 1),
            "src_mtime": date.fromtimestamp(src.stat().st_mtime).isoformat(),
        })
        print(f"  [OK]    {rel} ({size_kb:.1f} KB)")

    # Dirs
    for rel in DIRS_TO_SNAPSHOT:
        src = DATA_DIR / rel
        if not src.exists():
            manifest["missing"].append(rel + "/")
            print(f"  [SKIP]  {rel}/ no existe")
            continue
        dst = target_dir / rel
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("snapshots*"))
        n_files = sum(1 for _ in dst.rglob("*") if _.is_file())
        total_kb = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) / 1024
        manifest["files"].append({
            "path": rel + "/",
            "n_files": n_files,
            "size_kb": round(total_kb, 1),
        })
        print(f"  [OK]    {rel}/ ({n_files} files, {total_kb:.1f} KB)")

    # Manifest
    manifest_path = target_dir / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nManifest: {manifest_path}")
    print(f"Total files: {len(manifest['files'])} (missing: {len(manifest['missing'])})")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--month", help="YYYY-MM (default: mes anterior)")
    args = ap.parse_args()

    month = args.month or previous_month_iso()
    if not (len(month) == 7 and month[4] == "-" and month[:4].isdigit() and month[5:].isdigit()):
        raise SystemExit(f"--month debe ser 'YYYY-MM', recibido: {month}")

    take_snapshot(month)


if __name__ == "__main__":
    main()
