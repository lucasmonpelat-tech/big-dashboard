"""
send_failure_alert.py
======================
Manda un mail INMEDIATO (el mismo dia) a Lucas si el cron diario
escribio alguna alerta hoy en data/_alerts/ -- sin esperar al weekly digest
de los sabados (que ademas esta desactivado, ver weekly_digest.py).

Por que no alcanza con "if: failure()" en el workflow: la mayoria de los
steps del cron tienen `continue-on-error: true` (baha, netx360, bench
indices, validate_sleeve_returns, etc.), asi que el job entero puede
terminar en "success" aunque varios de esos steps hayan fallado en
silencio. Este script en cambio escanea data/_alerts/ por CUALQUIER
archivo con la fecha de hoy (cron_failure_*, sleeve_return_anomaly_*,
health_check_warning_*, bench_indices_stale_*, netx360_download_*, etc.)
-- el mismo criterio que ya usa la regla de MEMORY.md para el chequeo de
inicio de sesion, pero disparado automaticamente en vez de depender de
que alguien abra una sesion de Claude Code.

Uso (desde el yml, al final, con `if: always()`):
    python scripts/send_failure_alert.py

Env vars requeridos (ya configurados como secrets para weekly_digest.py):
    GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_LUCAS, MAIL_FER
Si faltan, imprime warning y no manda nada (no rompe el job).
"""
import json
import os
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).parent.parent
ALERTS_DIR = ROOT / "data" / "_alerts"

# last_run.json no es una alerta -- se escribe siempre, exito o no.
IGNORE_FILES = {"last_run.json"}


def find_today_alerts(today_iso: str) -> list[Path]:
    if not ALERTS_DIR.exists():
        return []
    out = []
    for p in sorted(ALERTS_DIR.glob("*.json")):
        if p.name in IGNORE_FILES:
            continue
        if today_iso in p.name:
            out.append(p)
    return out


def build_body(alert_files: list[Path], today_iso: str) -> tuple[str, str]:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None

    lines_txt = [f"El cron diario de BIG dejo {len(alert_files)} alerta(s) el {today_iso}:", ""]
    blocks_html = []
    for p in alert_files:
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            payload = {"raw": p.read_text(encoding="utf-8", errors="replace")}
        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        lines_txt.append(f"--- {p.name} ---")
        lines_txt.append(pretty)
        lines_txt.append("")
        blocks_html.append(
            f'<h3 style="margin:18px 0 6px;font-family:sans-serif;color:#1F2937">{p.name}</h3>'
            f'<pre style="background:#f5f2ea;padding:12px;border-radius:6px;font-size:12px;'
            f'white-space:pre-wrap;overflow-x:auto">{pretty}</pre>'
        )

    if run_url:
        lines_txt.append(f"Ver logs completos: {run_url}")

    text_body = "\n".join(lines_txt)
    html_body = f"""<html><body style="font-family:sans-serif;color:#1F2937">
<h2 style="color:#1F2937">Alerta cron BIG — {today_iso}</h2>
<p>El cron diario dejo <b>{len(alert_files)}</b> alerta(s) hoy:</p>
{''.join(blocks_html)}
{f'<p><a href="{run_url}">Ver logs completos del run</a></p>' if run_url else ''}
<div style="font-size:11px;color:#888;text-align:center;margin-top:24px;padding-top:14px;border-top:1px solid #e0d8c8">
Pampa Capital · Routine automatizada · Generado por GitHub Actions
</div>
</body></html>"""
    return html_body, text_body


def send_mail(html_body: str, text_body: str, today_iso: str, n_alerts: int):
    user = os.environ["GMAIL_USER"]
    pwd = os.environ["GMAIL_APP_PASSWORD"]
    to_lucas = os.environ["MAIL_LUCAS"]

    # 2026-08-28, pedido de Lucas: las alertas de FALLA van SOLO a el.
    # Antes se mandaban tambien a Fer, que no las necesita -- son ruido
    # tecnico (cron que no corrio, scrape que fallo), no informacion del
    # fondo. El digest semanal de weekly_digest.py SI le sigue llegando:
    # eso es un reporte, no una alerta.

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 BIG · Alerta cron ({n_alerts}) · {today_iso}"
    msg["From"] = f"Pampa BIG Bot <{user}>"
    msg["To"] = to_lucas

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as smtp:
        smtp.login(user, pwd)
        smtp.sendmail(user, [to_lucas], msg.as_string())

    print(f"OK: alerta mandada a {to_lucas}")


def main():
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    alert_files = find_today_alerts(today_iso)

    if not alert_files:
        print(f"[send_failure_alert] Sin alertas para {today_iso}, no se manda mail.")
        return

    print(f"[send_failure_alert] {len(alert_files)} alerta(s) encontradas: {[p.name for p in alert_files]}")
    html, text = build_body(alert_files, today_iso)

    if all(os.environ.get(k) for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "MAIL_LUCAS", "MAIL_FER")):
        send_mail(html, text, today_iso, len(alert_files))
    else:
        print("WARN: faltan secrets de SMTP (GMAIL_USER/GMAIL_APP_PASSWORD/MAIL_LUCAS/MAIL_FER), mail no enviado.")


if __name__ == "__main__":
    main()
