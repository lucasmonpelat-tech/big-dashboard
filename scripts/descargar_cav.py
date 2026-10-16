"""Baja el CAV File mensual de Lynk desde Gmail (IMAP) a la carpeta de fees.

Lo pide la tarea programada `cav-mensual-lynk` (dia 1 habil); Nico F (Lynk) lo
manda como adjunto xlsx a monpelatlucas@gmail.com, normalmente en menos de 1 hora.

Uso:
    python scripts/descargar_cav.py            # mes anterior, guarda en Dropbox
    python scripts/descargar_cav.py --mes 9 --anio 2026
    python scripts/descargar_cav.py --out C:\\tmp   # carpeta de prueba

Exit: 0 = descargado (o ya estaba), 2 = todavia no llego, 1 = error.
Imprime la ruta final en la ultima linea ("CAV_OK <ruta>").
"""
import argparse
import email
import imaplib
import sys
from datetime import date, timedelta
from email.header import decode_header
from pathlib import Path

import keyring

CARPETA_CAV = Path(r"C:\Users\lmonp\Dropbox\Maximus BIG\2026"
                   r"\Luiquidacion Comisiones BIG\Pro Capital Desgloze Fees")
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
REMITENTE = "lynkmarkets.com"


def _dec(s):
    return "".join(t.decode(c or "utf-8") if isinstance(t, bytes) else t
                   for t, c in decode_header(s or ""))


def main():
    hoy = date.today()
    ant = hoy.replace(day=1) - timedelta(days=1)
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes", type=int, default=ant.month)
    ap.add_argument("--anio", type=int, default=ant.year)
    ap.add_argument("--out", default=str(CARPETA_CAV))
    a = ap.parse_args()

    mes = MESES[a.mes - 1]
    destino = Path(a.out) / f"ProCapital_XS3037627794_LS104 - {mes} {a.anio}.xlsx"
    if destino.exists():
        print(f"Ya existe: {destino.name}")
        print(f"CAV_OK {destino}")
        return 0

    user = keyring.get_password("big-gmail-otp", "email")
    pw = keyring.get_password("big-gmail-otp", "apppass")
    if not user or not pw:
        print("ERROR: faltan credenciales Gmail en keyring (big-gmail-otp)")
        return 1

    # Solo mails posteriores al cierre del mes pedido
    desde = date(a.anio, a.mes, 1)
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    m.login(user, pw)
    m.select('INBOX', readonly=True)
    typ, ids = m.search(None, "FROM", f'"{REMITENTE}"', "SUBJECT", '"CAV"',
                        "SINCE", desde.strftime("%d-%b-%Y"))
    ids = ids[0].split()
    # del mas nuevo al mas viejo; el CAV "historico" del mes cerrado es el que sirve
    for i in reversed(ids):
        typ, data = m.fetch(i, "(RFC822)")
        msg = email.message_from_bytes(data[0][1])
        # El CAV de un mes se manda dentro de los primeros dias del mes siguiente
        fecha = email.utils.parsedate_to_datetime(msg["Date"]).date()
        siguiente = date(a.anio + (a.mes == 12), a.mes % 12 + 1, 1)
        if fecha < siguiente:
            continue
        for part in msg.walk():
            nombre = _dec(part.get_filename())
            if nombre.lower().endswith(".xlsx"):
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(part.get_payload(decode=True))
                print(f"Descargado de '{_dec(msg['Subject'])}' ({fecha}): {nombre}")
                print(f"CAV_OK {destino}")
                return 0
    print(f"Todavia no llego el CAV de {mes} {a.anio}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
