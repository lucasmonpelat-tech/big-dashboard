"""
record_run_status.py
====================
Registra el estado de cada corrida del cron unificado daily-refresh.

Escribe a `data/_alerts/last_run.json` con:
  - timestamp UTC
  - dia de la semana
  - status del job (success / failure)
  - listado de archivos data/ modificados en la corrida

Si el job termino en failure, ADEMAS escribe `data/_alerts/cron_failure_YYYY-MM-DD.json`
que el chequeo de inicio de sesion de Claude detecta y muestra a Lucas.

Uso (desde el yml):
    python scripts/record_run_status.py --job-status "${{ job.status }}"

job-status puede ser: success | failure | cancelled
"""
import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def get_modified_data_files() -> list[str]:
    """Lista los archivos en data/ que cambiaron en esta corrida."""
    try:
        # git diff --name-only HEAD~1..HEAD -- data/
        # Si no hubo commit, vemos el working tree contra HEAD
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", "data/"],
            capture_output=True, text=True, check=False
        )
        files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not files:
            # Fallback: ver el ultimo commit del bot
            result = subprocess.run(
                ["git", "log", "-1", "--name-only", "--format=", "--", "data/"],
                capture_output=True, text=True, check=False
            )
            files = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return files[:20]  # cap por si hay demasiados
    except Exception as e:
        return [f"(error listing files: {e})"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-status", default="success",
                        help="Estado del job: success | failure | cancelled")
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    alerts_dir = root / "data" / "_alerts"
    alerts_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    today_iso = now.strftime("%Y-%m-%d")
    dow_name = now.strftime("%A")  # Monday, Tuesday, ...

    payload = {
        "ranAt": now.isoformat(),
        "date": today_iso,
        "dayOfWeek": dow_name,
        "jobStatus": args.job_status,
        "modifiedFiles": get_modified_data_files(),
    }

    # Last run (siempre)
    last_run_path = alerts_dir / "last_run.json"
    last_run_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Recorded last_run.json -> status: {args.job_status}")

    # Failure marker (solo si fallo)
    if args.job_status.lower() == "failure":
        failure_path = alerts_dir / f"cron_failure_{today_iso}.json"
        failure_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Recorded FAILURE marker: {failure_path.name}")
    else:
        # Si la corrida termino OK, eliminamos cualquier failure marker viejo del mismo dia
        old_failure = alerts_dir / f"cron_failure_{today_iso}.json"
        if old_failure.exists():
            old_failure.unlink()
            print(f"Removed stale failure marker for {today_iso}")


if __name__ == "__main__":
    main()
