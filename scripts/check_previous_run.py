"""
check_previous_run.py
=====================
Los lunes a la manana, chequea si la corrida del sabado anterior termino bien.
Si NO corrio o termino en failure, escribe `data/_alerts/health_check_warning.json`
para que Claude lo muestre al iniciar sesion.

Logica:
  - Lee `data/_alerts/last_run.json` (la corrida mas reciente)
  - Verifica que sea de `--expected-day` (ej. "saturday")
  - Verifica que `jobStatus == success`
  - Si algo no esta OK -> escribe el warning marker

Uso (desde el yml, solo los lunes):
    python scripts/check_previous_run.py --expected-day saturday
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-day", default="saturday",
                        help="Dia esperado de la corrida previa (saturday, friday, etc.)")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    alerts_dir = root / "data" / "_alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)

    last_run_path = alerts_dir / "last_run.json"
    today = datetime.now(timezone.utc).date()
    today_iso = today.isoformat()

    warning = None

    if not last_run_path.exists():
        warning = {
            "warningType": "missing_last_run_marker",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "checkedFor": today_iso,
            "expectedDay": args.expected_day,
            "details": "No existe data/_alerts/last_run.json. La corrida del sabado anterior no dejo marker.",
        }
    else:
        try:
            data = json.loads(last_run_path.read_text(encoding="utf-8"))
            day = (data.get("dayOfWeek") or "").lower()
            status = (data.get("jobStatus") or "").lower()
            ran_date = data.get("date")

            if day != args.expected_day.lower():
                warning = {
                    "warningType": "wrong_previous_day",
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                    "checkedFor": today_iso,
                    "expectedDay": args.expected_day,
                    "lastRunDay": data.get("dayOfWeek"),
                    "lastRunDate": ran_date,
                    "details": f"La ultima corrida fue {day}, no {args.expected_day}. Saltada o fallida.",
                }
            elif status != "success":
                warning = {
                    "warningType": "previous_run_failed",
                    "checkedAt": datetime.now(timezone.utc).isoformat(),
                    "checkedFor": today_iso,
                    "expectedDay": args.expected_day,
                    "lastRunStatus": status,
                    "lastRunDate": ran_date,
                    "details": f"La corrida del {args.expected_day} ({ran_date}) termino en {status}.",
                }
        except Exception as e:
            warning = {
                "warningType": "last_run_unparseable",
                "checkedAt": datetime.now(timezone.utc).isoformat(),
                "details": f"Error parseando last_run.json: {e}",
            }

    if warning:
        path = alerts_dir / f"health_check_warning_{today_iso}.json"
        path.write_text(json.dumps(warning, indent=2), encoding="utf-8")
        print(f"WARNING -> {path.name}: {warning['warningType']}")
    else:
        print(f"OK: la corrida previa ({args.expected_day}) termino bien.")
        # Limpieza de warnings viejos del dia
        old = alerts_dir / f"health_check_warning_{today_iso}.json"
        if old.exists():
            old.unlink()


if __name__ == "__main__":
    main()
