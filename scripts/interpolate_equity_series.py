"""
interpolate_equity_series.py
============================
Interpola linealmente la serie de equity_sleeve_real.json y fi_sleeve_real.json
para tener granularidad diaria.

El script original (portfolio_reconstructor.py) genera solo 1 punto por mes,
lo cual hace que el calculo de 1M/3M/6M en el dashboard agarre puntos viejos
(ej: "1M" agarra el punto de fin del mes anterior = 30+ dias atras).

Esta interpolacion lineal genera 1 punto por dia, suficiente para que los
calculos multi-period sean fieles al periodo solicitado.

Usage:
    python scripts/interpolate_equity_series.py
"""
import json
from datetime import date, timedelta
from pathlib import Path

DATA = Path(__file__).parent.parent / "data"


def interpolate_series(series: list[dict], value_key: str = "index") -> list[dict]:
    """Genera 1 punto por dia entre el primer y ultimo dia de la serie original.

    Para cada dia intermedio, interpola linealmente entre los puntos vecinos.
    Preserva los puntos originales sin modificarlos.
    """
    if len(series) < 2:
        return series

    # Indexar la serie original por fecha
    by_date = {p["date"]: p for p in series}
    sorted_dates = sorted(by_date.keys())
    first = date.fromisoformat(sorted_dates[0])
    last = date.fromisoformat(sorted_dates[-1])

    result = []
    cur = first
    # Cache de bracket actual
    bracket_start = None
    bracket_end = None

    while cur <= last:
        cur_iso = cur.isoformat()
        if cur_iso in by_date:
            # Punto original
            result.append(by_date[cur_iso])
            bracket_start = by_date[cur_iso]
            # Buscar el proximo punto original
            nxt = None
            for d in sorted_dates:
                if d > cur_iso:
                    nxt = by_date[d]
                    break
            bracket_end = nxt
        else:
            # Interpolar entre bracket_start y bracket_end
            if bracket_start is None or bracket_end is None:
                cur += timedelta(days=1)
                continue
            d0 = date.fromisoformat(bracket_start["date"])
            d1 = date.fromisoformat(bracket_end["date"])
            total = (d1 - d0).days
            elapsed = (cur - d0).days
            frac = elapsed / total if total > 0 else 0
            v0 = bracket_start[value_key]
            v1 = bracket_end[value_key]
            interp_val = v0 + (v1 - v0) * frac
            interp_point = {"date": cur_iso, value_key: round(interp_val, 4), "interpolated": True}
            # Mantener otros campos si existen en bracket_start
            for k in bracket_start:
                if k not in interp_point and k not in ("date", value_key):
                    if isinstance(bracket_start[k], (int, float)):
                        # Interpolar tambien
                        try:
                            v0k = bracket_start[k]
                            v1k = bracket_end.get(k, v0k)
                            interp_point[k] = round(v0k + (v1k - v0k) * frac, 4) if isinstance(v0k, (int, float)) else v0k
                        except Exception:
                            interp_point[k] = bracket_start[k]
            result.append(interp_point)
        cur += timedelta(days=1)

    return result


def process_file(path: Path, series_key: str, value_key: str = "index"):
    print(f"\n=== Processing {path.name} ===")
    if not path.exists():
        print(f"  [SKIP] no existe")
        return
    d = json.load(open(path, encoding="utf-8"))
    if series_key not in d:
        print(f"  [SKIP] no tiene clave '{series_key}'")
        return
    original = d[series_key]
    print(f"  Puntos originales: {len(original)}")
    if len(original) < 2:
        print(f"  [SKIP] menos de 2 puntos")
        return

    interpolated = interpolate_series(original, value_key=value_key)
    print(f"  Puntos despues de interp: {len(interpolated)}")

    # Backup
    d[f"{series_key}_original"] = original
    d[series_key] = interpolated

    json.dump(d, open(path, "w", encoding="utf-8"), indent=2)
    print(f"  [OK] guardado con serie interpolada")


def main():
    # Equity sleeve
    process_file(DATA / "equity_sleeve_real.json", "twr_series", value_key="index")
    process_file(DATA / "equity_sleeve_real.json", "acwi_index_series", value_key="index")

    # FI sleeve
    process_file(DATA / "fi_sleeve_real.json", "twr_series", value_key="index")
    process_file(DATA / "fi_sleeve_real.json", "agg_index_series", value_key="index")

    print("\n[DONE] Interpolacion completa")


if __name__ == "__main__":
    main()
