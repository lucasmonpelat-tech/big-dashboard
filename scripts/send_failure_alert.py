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
    GMAIL_USER, GMAIL_APP_PASSWORD, MAIL_LUCAS
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


MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def nombre_fondo(ticker: str) -> str:
    """Nombre legible del fondo, desde su ficha en data/funds/.

    La ficha es la unica fuente de datos por fondo (ver build_funds_index.py).
    `name` es la descripcion de Pershing -- en mayusculas y cortada, sirve para
    matchear y no para leer --, asi que se usa `nombre_corto` y se cae al ticker
    si el fondo no lo tiene cargado.
    """
    p = ROOT / "data" / "funds" / f"{ticker}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("nombre_corto") or ticker
    except Exception:
        return ticker


def _cierre(fecha_iso: str) -> str:
    """'2026-08-31' -> 'al cierre de agosto'."""
    try:
        a, m, _ = fecha_iso.split("-")
        return f"al cierre de {MESES[int(m) - 1]}"
    except Exception:
        return ""


def render_alts_remarcado(payload: dict) -> tuple[str, str, str] | None:
    """(titulo, html, texto) de una re-marca de NAV, en criollo.

    POR QUE (2026-09-22, pedido de Lucas)
    -------------------------------------
    El mail pegaba el JSON crudo de la alerta. Ese JSON esta pensado para que lo
    lea un script, no una persona: ticker, claves en ingles y numeros sin
    contexto. Lucas lo pidio al reves -- que diga "actualizacion de precios
    Hamilton Lane al cierre de agosto", con el precio de antes, el de ahora y
    cuanto vario.

    Ademas una re-marca NO es una falla: es una novedad. El asunto del mail lo
    refleja cuando es lo unico que hay (ver asunto_para()).
    """
    detalle = payload.get("detalle") or []
    if not detalle:
        return None

    nombres = [nombre_fondo(d.get("ticker", "")) for d in detalle]
    cierre = _cierre((detalle[0].get("price_date_ahora") or ""))
    titulo = "Actualización de precios · " + ", ".join(nombres)

    filas_txt, filas_html = [], []
    for d, nom in zip(detalle, nombres):
        var = d.get("var_pct")
        signo = "+" if (var or 0) >= 0 else ""
        color = "#15803d" if (var or 0) >= 0 else "#b91c1c"
        antes, ahora = d.get("antes"), d.get("ahora")
        mva, mvd = d.get("mv_antes"), d.get("mv_ahora")
        es_precio = d.get("senal") == "precio"
        etiqueta = "Precio" if es_precio else "Valor estimado"

        filas_txt += [
            f"{nom}",
            f"  {etiqueta}: {antes} -> {ahora}   ({signo}{var}%)",
        ]
        if mva is not None and mvd is not None:
            filas_txt.append(f"  Valuacion: ${mva:,.2f} -> ${mvd:,.2f} "
                             f"({signo}${mvd - mva:,.2f})")
        if d.get("price_date_antes") and d.get("price_date_ahora"):
            filas_txt.append(f"  Precio valuado al: {d['price_date_antes']} -> "
                             f"{d['price_date_ahora']}")
        filas_txt.append("")

        mv_html = ""
        if mva is not None and mvd is not None:
            mv_html = (f'<tr><td style="padding:4px 14px 4px 0;color:#6b7280">Valuación</td>'
                       f'<td style="padding:4px 0">${mva:,.2f} → <b>${mvd:,.2f}</b> '
                       f'<span style="color:{color}">({signo}${mvd - mva:,.2f})</span></td></tr>')
        fecha_html = ""
        if d.get("price_date_antes") and d.get("price_date_ahora"):
            fecha_html = (f'<tr><td style="padding:4px 14px 4px 0;color:#6b7280">Valuado al</td>'
                          f'<td style="padding:4px 0">{d["price_date_antes"]} → '
                          f'<b>{d["price_date_ahora"]}</b></td></tr>')
        filas_html.append(
            f'<div style="margin:0 0 18px">'
            f'<div style="font-size:15px;font-weight:700;margin-bottom:6px">{nom}</div>'
            f'<table style="border-collapse:collapse;font-size:13px">'
            f'<tr><td style="padding:4px 14px 4px 0;color:#6b7280">{etiqueta}</td>'
            f'<td style="padding:4px 0">{antes} → <b>{ahora}</b> '
            f'<span style="color:{color};font-weight:700">({signo}{var}%)</span></td></tr>'
            f'{mv_html}{fecha_html}</table></div>'
        )

    encabezado = f"Pershing actualizó el precio {cierre}." if cierre else \
                 "Pershing actualizó el precio."
    texto = f"{titulo}\n{encabezado}\n\n" + "\n".join(filas_txt)
    html = (f'<h2 style="margin:0 0 4px">{titulo}</h2>'
            f'<p style="margin:0 0 16px;color:#6b7280">{encabezado}</p>'
            + "".join(filas_html))
    return titulo, html, texto


# tipo de alerta -> funcion que la escribe en criollo. Lo que no este aca cae al
# JSON crudo: es preferible un mail feo a uno que se come informacion.
RENDERERS = {"alts_nav_remarcado": render_alts_remarcado}


def asunto_para(payloads: list[dict], today_iso: str, n: int) -> str:
    """Una re-marca de NAV no es una falla: no va con 🚨."""
    tipos = {p.get("tipo") for p in payloads}
    if tipos == {"alts_nav_remarcado"}:
        fondos = [nombre_fondo(d.get("ticker", ""))
                  for p in payloads for d in (p.get("detalle") or [])]
        return f"📈 BIG · Actualización de precios · {', '.join(fondos)}"
    return f"🚨 BIG · Alerta cron ({n}) · {today_iso}"


def build_body(alert_files: list[Path], today_iso: str) -> tuple[str, str]:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else None

    lines_txt, blocks_html, payloads = [], [], []
    for p in alert_files:
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            payload = {"raw": p.read_text(encoding="utf-8", errors="replace")}
        payloads.append(payload)

        # Si sabemos escribir este tipo de alerta, va en criollo. Si no, el JSON
        # crudo: mejor un mail feo que uno que se come informacion.
        render = RENDERERS.get(payload.get("tipo"))
        hecho = render(payload) if render else None
        if hecho:
            _, html, texto = hecho
            lines_txt += [texto, ""]
            blocks_html.append(html)
            continue

        pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        lines_txt += [f"--- {p.name} ---", pretty, ""]
        blocks_html.append(
            f'<h3 style="margin:18px 0 6px;font-family:sans-serif;color:#1F2937">{p.name}</h3>'
            f'<pre style="background:#f5f2ea;padding:12px;border-radius:6px;font-size:12px;'
            f'white-space:pre-wrap;overflow-x:auto">{pretty}</pre>'
        )

    # Encabezado: si todo lo de hoy se pudo escribir en criollo, no hace falta
    # anunciar "el cron dejo N alertas" -- cada bloque ya dice lo suyo.
    todo_legible = all(p.get("tipo") in RENDERERS for p in payloads)
    if not todo_legible:
        cabecera = f"El cron diario de BIG dejo {len(alert_files)} alerta(s) el {today_iso}:"
        lines_txt.insert(0, "")
        lines_txt.insert(0, cabecera)
        cabecera_html = (f'<h2 style="color:#1F2937">Alerta cron BIG — {today_iso}</h2>'
                         f'<p>El cron diario dejo <b>{len(alert_files)}</b> alerta(s) hoy:</p>')
    else:
        cabecera_html = ""

    if run_url:
        lines_txt.append(f"Ver logs completos: {run_url}")

    text_body = "\n".join(lines_txt)
    html_body = f"""<html><body style="font-family:sans-serif;color:#1F2937">
{cabecera_html}
{''.join(blocks_html)}
{f'<p style="font-size:12px"><a href="{run_url}">Ver logs completos del run</a></p>' if run_url else ''}
<div style="font-size:11px;color:#888;text-align:center;margin-top:24px;padding-top:14px;border-top:1px solid #e0d8c8">
Pampa Capital · Routine automatizada · Generado por GitHub Actions
</div>
</body></html>"""
    return html_body, text_body


def send_mail(html_body: str, text_body: str, today_iso: str, n_alerts: int,
              asunto: str | None = None):
    user = os.environ["GMAIL_USER"]
    pwd = os.environ["GMAIL_APP_PASSWORD"]
    to_lucas = os.environ["MAIL_LUCAS"]

    # SOLO LUCAS. Pedido suyo el 2026-08-28 para las alertas, y confirmado el
    # 2026-09-10 para TODO lo que sale automatico de este repo.
    #
    # Antes iban tambien a Fer. La distincion que se usaba era "alerta vs
    # reporte": las alertas son ruido tecnico (cron que no corrio, scrape que
    # fallo) y no le sirven, pero el digest semanal si le llegaba. Lucas cerro
    # esa distincion: le llega todo solo a el. weekly_digest.py tambien.

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto or f"🚨 BIG · Alerta cron ({n_alerts}) · {today_iso}"
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
    payloads = []
    for a in alert_files:
        try:
            payloads.append(json.loads(a.read_text(encoding='utf-8')))
        except Exception:
            payloads.append({})
    asunto = asunto_para(payloads, today_iso, len(alert_files))

    # MAIL_FER NO va en esta lista, aunque el secret siga existiendo.
    #
    # El mail va solo a Lucas desde que el lo pidio (2026-09-04, sobre las alertas
    # de cron: "eso que no se lo manden a Fer, solo a mi"). Pero la guarda seguia
    # EXIGIENDO que MAIL_FER estuviera seteado para mandar. O sea: el dia que
    # alguien borrara ese secret -- que es lo natural despues de decidir no
    # mandarle nada a Fer -- el mail dejaba de salir EN SILENCIO. La unica senal
    # habria sido un WARN en el log de una corrida que igual termina en verde.
    #
    # Se pide solo lo que realmente se usa para enviar.
    faltan = [k for k in ("GMAIL_USER", "GMAIL_APP_PASSWORD", "MAIL_LUCAS")
              if not os.environ.get(k)]
    if not faltan:
        send_mail(html, text, today_iso, len(alert_files), asunto)
    else:
        print("WARN: faltan secrets de SMTP (%s), mail no enviado." % ", ".join(faltan))


if __name__ == "__main__":
    main()
