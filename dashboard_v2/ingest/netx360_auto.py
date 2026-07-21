"""
netx360_auto.py
================
Layer 1 (ingest) del dashboard_v2.

Automation Playwright + OTP desde Gmail IMAP:
1. Lee credenciales del Windows Credential Manager (keyring)
2. Login NetX360+ con user+pass autofillados
3. Detecta el paso OTP -> lee ultimo email de Pershing en Gmail
4. Extrae codigo (regex "One-Time Passcode: NNNNNN")
5. Ingresa OTP en el form y submit
6. Descarga los 4 XLSX:
   - Positions
   - Transactions (last 30 days para daily, o last 2 years para bootstrap)
   - Unrealized Gain/Loss
   - Realized Gain/Loss
7. Guarda snapshots inmutables en data/raw/YYYY-MM-DD/netx360/
8. En caso de error, escribe alerta en data/_alerts/

Uso:
    # Automation daily normal
    python dashboard_v2/ingest/netx360_auto.py

    # Bootstrap (primera vez, con 2 anios de history)
    python dashboard_v2/ingest/netx360_auto.py --bootstrap
"""
import argparse
import email
import imaplib
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from email.header import decode_header
from pathlib import Path

try:
    import keyring
except ImportError:
    # keyring solo requerido en local (Windows Credential Manager).
    # En CI (GitHub Actions) usamos env vars — keyring innecesario.
    keyring = None
from playwright.sync_api import sync_playwright


def _get_secret(env_var: str, keyring_service: str, keyring_key: str) -> str | None:
    """Fallback: env var (para GitHub Actions/CI) → Windows Credential Manager (local).
    Deja a Windows encriptar en local + permite CI con Secrets sin exponer nada."""
    v = os.environ.get(env_var)
    if v:
        return v
    if keyring is None:
        return None
    try:
        return keyring.get_password(keyring_service, keyring_key)
    except Exception:
        return None

# ============================================================
# CONFIG
# ============================================================
# Dinámico — dashboard_v2/ingest/netx360_auto.py → parents[2] = repo root
ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
ALERTS_DIR = ROOT / "data" / "_alerts"
ALERTS_DIR.mkdir(parents=True, exist_ok=True)

# Session storage (cookies + Chrome profile)
SESSION_DIR = ROOT / "data" / "netx360_session"
SESSION_DIR.mkdir(parents=True, exist_ok=True)

START_URL = "https://www2.netx360.com/plus/my-practice/details/activity-transactions-account"

# Selectores de campos (validados por test manual)
LOGIN_SELECTORS_USER = [
    'input[name="user"]', 'input[name="userid"]', 'input[name="username"]',
    'input[id="user"]', 'input[id="userid"]', 'input[id="username"]',
    'input[type="text"]', 'input[autocomplete="username"]',
]
LOGIN_SELECTORS_PASS = [
    'input[name="password"]', 'input[id="password"]',
    'input[type="password"]', 'input[autocomplete="current-password"]',
]
LOGIN_SELECTORS_BUTTON = [
    'button[type="submit"]', 'input[type="submit"]',
    'button:has-text("Login")', 'button:has-text("Log In")',
    'button:has-text("Sign In")', 'button:has-text("Sign in")',
    'a:has-text("Login")', 'a:has-text("Sign In")',
    'button:has-text("Continue")', 'button:has-text("Submit")',
    'button:has-text("Enter")',
    '[role="button"]:has-text("Login")',
    '[role="button"]:has-text("Sign in")',
    'button.login', '.login-button', '#loginButton', '#login-button',
    'input[value="Login" i]', 'input[value="Sign In" i]',
    'button[name="submit"]', 'button[name="login"]',
]
OTP_SELECTORS = [
    'input[name="otp"]', 'input[name="code"]', 'input[name="passcode"]',
    'input[id="otp"]', 'input[id="passcode"]', 'input[maxlength="6"]',
]

# Selectores del flow "Use another authentication method"
OTP_CHANGE_METHOD_SELECTORS = [
    'a:has-text("Use another authentication method")',
    'button:has-text("Use another authentication method")',
    'span:has-text("Use another authentication method")',
    'div:has-text("Use another authentication method")',
    'text="Use another authentication method"',
    '[role="link"]:has-text("Use another")',
    'a:has-text("Use another")',
    'button:has-text("Use another")',
    ':text("Use another authentication method")',
]
OTP_METHOD_DROPDOWN = ['select', '[role="combobox"]', 'input[role="combobox"]']
OTP_LUCAS_OPTION_TEXT = "Lucas by Email"
OTP_SEND_BUTTON = [
    'button:has-text("Send OTP")',
    'button:has-text("Send")',
    '[role="button"]:has-text("Send OTP")',
]

# Gmail
GMAIL_SEARCH_FROM = "netexchangeproducts@pershing.com"
OTP_REGEX = re.compile(r"One-Time Passcode:\s*(\d{6})", re.IGNORECASE)


# ============================================================
# ALERTS
# ============================================================
def write_alert(alert_type: str, detail: str, action: str = "Revisar netx360_auto.py"):
    """Escribe alerta en data/_alerts/ para que la skill la lea al inicio."""
    today = date.today().isoformat()
    alert = {
        "type": alert_type,
        "date": today,
        "timestamp": datetime.now().isoformat(),
        "detail": detail,
        "accion": action,
        "source": "netx360_auto",
    }
    fp = ALERTS_DIR / f"netx360_{alert_type}_{today}.json"
    fp.write_text(json.dumps(alert, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [ALERT] {alert_type}: {detail}")


# ============================================================
# GMAIL OTP READER
# ============================================================
def read_otp_from_gmail(max_wait_seconds: int = 60, min_timestamp: datetime = None) -> str | None:
    """Conecta a Gmail IMAP, busca ultimo email de Pershing enviado despues de
    min_timestamp (default: 3 min atras). Retry con espera."""
    email_addr = _get_secret("GMAIL_USER", "big-gmail-otp", "email")
    apppass = _get_secret("GMAIL_APP_PASSWORD", "big-gmail-otp", "apppass")
    if not email_addr or not apppass:
        write_alert("gmail_credentials_missing",
                    "Faltan credenciales Gmail: env GMAIL_USER+GMAIL_APP_PASSWORD o keyring big-gmail-otp")
        return None

    # Si no se paso min_timestamp, usar 3 minutos atras
    if min_timestamp is None:
        from datetime import timezone
        min_timestamp = datetime.now(timezone.utc) - timedelta(minutes=3)

    print(f"  Conectando a Gmail IMAP ({email_addr})...")
    print(f"  Solo aceptando OTPs enviados despues de: {min_timestamp.isoformat()}")

    deadline = time.time() + max_wait_seconds
    last_otp = None
    last_ts = None

    while time.time() < deadline:
        try:
            m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
            m.login(email_addr, apppass)
            m.select("INBOX")

            # Buscar ultimos emails del sender
            typ, ids = m.search(None, "FROM", f'"{GMAIL_SEARCH_FROM}"')
            ids_list = ids[0].split()
            # Recent emails (last 10)
            recent_ids = ids_list[-10:]

            for eid in reversed(recent_ids):  # mas nuevo primero
                typ, msg_data = m.fetch(eid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                # Fecha del email
                date_str = msg.get("Date")
                if not date_str:
                    continue
                try:
                    from email.utils import parsedate_to_datetime
                    msg_dt = parsedate_to_datetime(date_str)
                except Exception:
                    continue

                # Skip si es mas viejo que min_timestamp (evita OTPs viejos ya usados)
                if msg_dt < min_timestamp:
                    continue

                # Extraer cuerpo: probar text/plain primero, despues text/html
                body = ""
                body_html = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct == "text/plain" and not body:
                            body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        elif ct == "text/html" and not body_html:
                            body_html = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True) or b""
                    body = payload.decode("utf-8", errors="ignore")

                # Si no hay text/plain, usar el HTML (regex de "One-Time Passcode: NNNNNN")
                combined_body = body + "\n" + body_html

                # Tambien buscar en el subject
                subject = ""
                if msg.get("Subject"):
                    decoded = decode_header(msg["Subject"])
                    subject = "".join(
                        (d.decode(c or "utf-8") if isinstance(d, bytes) else d)
                        for d, c in decoded
                    )

                combined = subject + "\n" + combined_body
                match = OTP_REGEX.search(combined)
                if match:
                    otp = match.group(1)
                    if not last_ts or msg_dt > last_ts:
                        last_otp = otp
                        last_ts = msg_dt

            m.logout()

            if last_otp:
                print(f"  [OK] OTP encontrado: {last_otp} (email de {last_ts})")
                return last_otp

            # No hay OTP fresh, esperar 3s y reintentar
            print(f"  ... esperando OTP (max {int(deadline - time.time())}s)")
            time.sleep(3)
        except Exception as e:
            print(f"  [ERR IMAP] {e}")
            time.sleep(3)

    write_alert("otp_timeout", f"No se encontro OTP fresh en {max_wait_seconds}s")
    return None


# ============================================================
# PLAYWRIGHT LOGIN
# ============================================================
def fill_and_verify(page, selectors, value, label: str, timeout=3000):
    """Fill un input, verifica que el value quedo. Si esta corrupto (autocomplete),
    hace clear explicito con Ctrl+A + Delete y retype."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if not el.is_visible(timeout=timeout):
                continue
            # Fill inicial (.fill hace clear + type)
            el.fill(value)
            time.sleep(0.3)
            # Verificar que quedo
            try:
                actual = el.input_value()
            except Exception:
                actual = None
            if actual == value:
                return sel
            # No matcheo — retry con clear explicito
            print(f"    [WARN] {label} quedo mal (esperado len={len(value)}, actual={actual!r}). Retry...")
            el.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            time.sleep(0.3)
            el.type(value, delay=50)
            time.sleep(0.3)
            try:
                actual2 = el.input_value()
            except Exception:
                actual2 = None
            if actual2 == value:
                print(f"    [OK] {label} corregido en retry")
                return sel
            print(f"    [FAIL] {label} sigue mal despues del retry: {actual2!r}")
            return None
        except Exception:
            continue
    return None


def try_selectors(page, selectors, action, value=None, timeout=3000):
    """Intenta encontrar un elemento con lista de selectores. Ejecuta action."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=timeout):
                if action == "fill":
                    el.fill(value)
                    return sel
                elif action == "click":
                    el.click()
                    return sel
        except Exception:
            continue
    return None


def dismiss_cookie_banner(page):
    """Cierra el banner de OneTrust cookies que bloquea clicks."""
    cookie_selectors = [
        '#onetrust-accept-btn-handler',
        '#onetrust-reject-all-handler',
        'button:has-text("Accept All Cookies")',
    ]
    for sel in cookie_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1500):
                el.click()
                print(f"  Cookie banner cerrado (via {sel})")
                time.sleep(1)
                return True
        except Exception:
            continue
    return False


def login_flow(page, verbose=True):
    """Ejecuta el flow completo de login: user+pass, submit, OTP, submit."""
    user = _get_secret("NETX360_USER", "big-netx360", "user")
    pw = _get_secret("NETX360_PASSWORD", "big-netx360", "pass")
    if not user or not pw:
        write_alert("credentials_missing",
                    "Faltan credenciales NetX360+: env NETX360_USER+NETX360_PASSWORD o keyring big-netx360")
        return False

    # Ir a la pagina protegida (redirige a login)
    if verbose:
        print(f"\nNavegando a {START_URL}...")
    try:
        page.goto(START_URL, timeout=30000)
    except Exception as e:
        write_alert("navigation_failed", f"No pude ir a {START_URL}: {e}")
        return False

    # Esperar carga inicial
    time.sleep(3)

    # Cerrar banner de cookies si esta (bloquea clicks al form)
    dismiss_cookie_banner(page)

    # Esperar login form
    time.sleep(2)

    # Detectar "session no longer valid" y refrescar (evita form corrupto con user cacheado)
    SESSION_EXPIRED_SELECTORS = [
        'text=/session is no longer valid/i',
        'text=/session expired/i',
        'text=/please login again/i',
    ]
    for sel in SESSION_EXPIRED_SELECTORS:
        try:
            if page.locator(sel).first.is_visible(timeout=1000):
                print("  [WARN] Session expired detected — refrescando...")
                page.goto(START_URL, timeout=30000)
                time.sleep(3)
                dismiss_cookie_banner(page)
                time.sleep(2)
                break
        except Exception:
            continue

    # Fill user (con verificacion + retry si NetX360+ auto-completa)
    sel_user = fill_and_verify(page, LOGIN_SELECTORS_USER, user, "user")
    if not sel_user:
        write_alert("login_form_not_found", "No encontre input de usuario en la pagina")
        return False
    print(f"  Usuario ingresado en {sel_user}")

    # Fill password
    sel_pass = fill_and_verify(page, LOGIN_SELECTORS_PASS, pw, "password")
    if not sel_pass:
        write_alert("login_form_not_found", "No encontre input de password")
        return False
    print(f"  Password ingresado en {sel_pass}")

    # Antes de intentar el botón, guardamos el HTML del form para debug offline
    try:
        html_dump = page.content()
        (SESSION_DIR / "login_page_debug.html").write_text(html_dump, encoding="utf-8")
        print(f"  [DEBUG] HTML dump: {SESSION_DIR / 'login_page_debug.html'}")
    except Exception:
        pass

    # Screenshot del form para debug visual
    try:
        page.screenshot(path=str(SESSION_DIR / "login_page.png"), full_page=True)
        print(f"  [DEBUG] Screenshot: {SESSION_DIR / 'login_page.png'}")
    except Exception:
        pass

    # Buscar el botón: primero en la page principal, después en iframes
    def find_button_in_scope(scope, scope_name="page"):
        for sel in LOGIN_SELECTORS_BUTTON:
            try:
                el = scope.locator(sel).first
                if el.is_visible(timeout=1500):
                    return sel, scope_name
            except Exception:
                continue
        return None, None

    # Click submit
    sel_btn, sel_scope = find_button_in_scope(page)
    if sel_btn:
        try:
            page.locator(sel_btn).first.click()
        except Exception:
            pass
    else:
        # Buscar dentro de iframes
        for i, frame in enumerate(page.frames):
            if frame == page.main_frame:
                continue
            sel_btn, sel_scope = find_button_in_scope(frame, f"iframe#{i}")
            if sel_btn:
                try:
                    frame.locator(sel_btn).first.click()
                    print(f"  Botón encontrado en {sel_scope}: {sel_btn}")
                    break
                except Exception:
                    pass

    if not sel_btn:
        # Fallback 1: enumerar todos los elementos clickables para debug
        print("  No hay boton visible con selectores conocidos.")
        print("  DIAGNOSTIC: enumerando elementos clickables del form...")
        try:
            clickables = page.evaluate("""() => {
                const results = [];
                const sels = ['button', 'input[type="submit"]', 'input[type="button"]',
                              'a[href]', '[role="button"]', 'div[onclick]', 'span[onclick]'];
                for (const sel of sels) {
                    document.querySelectorAll(sel).forEach(el => {
                        const rect = el.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) {
                            results.push({
                                tag: el.tagName.toLowerCase(),
                                type: el.type || '',
                                id: el.id || '',
                                name: el.name || '',
                                cls: el.className.toString().slice(0, 60),
                                text: (el.innerText || el.value || '').trim().slice(0, 40),
                                role: el.getAttribute('role') || '',
                            });
                        }
                    });
                }
                return results.slice(0, 20);
            }""")
            for c in clickables:
                print(f"    {c}")
        except Exception as e:
            print(f"    (error enumerando: {e})")

        # Fallback 2: apretar Enter en el campo password
        print("  Intentando Enter en password...")
        try:
            page.locator(sel_pass).press("Enter")
            print(f"  Enter apretado en {sel_pass}")
            time.sleep(2)
        except Exception:
            pass

        # NO usar form.submit() JS — riesgo de exponer credenciales en URL con GET
        # En su lugar, esperamos que el Enter haga su trabajo
    else:
        print(f"  Submit clickeado ({sel_btn}) en {sel_scope}")

    # Esperar OTP page o dashboard
    time.sleep(4)
    current_url = page.url
    print(f"  URL post-login: {current_url}")

    # Chequear si hay error de invalid password
    body_text = page.locator("body").inner_text()
    if "invalid User ID" in body_text or "invalid" in body_text.lower():
        write_alert("invalid_credentials", "Pershing rechazo user/pass. Verificar en keyring.")
        return False

    # Si redirige a otp page, procesar
    if "otp" in current_url.lower() or try_selectors(page, OTP_SELECTORS, "fill", "test-check-only", timeout=1500):
        print("  OTP required")
        # Limpiar el campo si lo llenamos con test
        for sel in OTP_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1000):
                    el.fill("")
                    break
            except Exception:
                pass

        # Debug: guardar HTML y screenshot de la pagina OTP (forzado, sin try suave)
        try:
            html_content = page.content()
            (SESSION_DIR / "otp_page_debug.html").write_text(html_content, encoding="utf-8")
            print(f"  [DEBUG] HTML OTP guardado ({len(html_content)} bytes)")
        except Exception as e:
            print(f"  [DEBUG] HTML dump fallo: {e}")
        try:
            page.screenshot(path=str(SESSION_DIR / "otp_page.png"), full_page=True)
            print(f"  [DEBUG] Screenshot OTP guardado")
        except Exception as e:
            print(f"  [DEBUG] screenshot fallo: {e}")

        # PASO IMPORTANTE: por default NetX360+ envia el OTP a Sol/Jennifer,
        # no a Lucas. Necesitamos cambiar el metodo a "Lucas by Email".
        # El elemento en Pershing es un <div class="text-link"><b>Use another...</b></div>
        # Angular componente — click requiere target correcto o force=True.
        print("  Buscando 'Use another authentication method' para cambiar destinatario...")
        change_method_ok = False

        # Guardar HTML antes del click para comparar despues
        html_before = page.content()

        # Estrategia 1: click en el <b> interior
        try:
            el = page.locator('b:has-text("Use another authentication method")').first
            if el.is_visible(timeout=2000):
                el.click()
                time.sleep(2)
                html_after = page.content()
                if html_after != html_before:
                    print(f"  Click OK en <b> (DOM cambio)")
                    change_method_ok = True
        except Exception:
            pass

        # Estrategia 2: click con force=True en el div padre
        if not change_method_ok:
            try:
                el = page.locator('div.text-link:has-text("Use another authentication method")').first
                if el.is_visible(timeout=2000):
                    el.click(force=True)
                    time.sleep(2)
                    html_after = page.content()
                    if html_after != html_before:
                        print(f"  Click OK en div.text-link con force (DOM cambio)")
                        change_method_ok = True
            except Exception:
                pass

        # Estrategia 3: dispatch click event via JS al elemento
        if not change_method_ok:
            try:
                clicked = page.evaluate("""() => {
                    const bs = document.querySelectorAll('b');
                    for (const b of bs) {
                        if (b.textContent.trim() === 'Use another authentication method') {
                            // Click el div padre
                            let target = b.parentElement || b;
                            target.click();
                            return {ok: true, tag: target.tagName, cls: target.className};
                        }
                    }
                    return {ok: false};
                }""")
                print(f"  JS click result: {clicked}")
                time.sleep(2)
                html_after = page.content()
                if html_after != html_before:
                    print(f"  Click OK via JS (DOM cambio)")
                    change_method_ok = True
            except Exception as e:
                print(f"  JS click fallo: {e}")

        if change_method_ok:
            # Debug: dump del HTML DESPUES del click "Use another authentication method"
            time.sleep(2)
            try:
                (SESSION_DIR / "otp_method_page_debug.html").write_text(page.content(), encoding="utf-8")
                page.screenshot(path=str(SESSION_DIR / "otp_method_page.png"), full_page=True)
                print(f"  [DEBUG] HTML select-method guardado")
            except Exception as e:
                print(f"  [DEBUG] fallo: {e}")

            # Ahora estamos en "Select Contact Method" — elegir "Lucas by Email"
            print(f"  Seleccionando '{OTP_LUCAS_OPTION_TEXT}'...")
            selected = False
            # Intento 1: si es <select> nativo, usar select_option
            for sel in OTP_METHOD_DROPDOWN:
                try:
                    dd = page.locator(sel).first
                    if dd.is_visible(timeout=2000):
                        # abrir el dropdown
                        dd.click()
                        time.sleep(1)
                        # click en la opcion Lucas
                        try:
                            page.locator(f'text="{OTP_LUCAS_OPTION_TEXT}"').first.click(timeout=3000)
                            print(f"  '{OTP_LUCAS_OPTION_TEXT}' seleccionado")
                            selected = True
                            break
                        except Exception:
                            # Alternativa: select_option para <select>
                            try:
                                dd.select_option(label=OTP_LUCAS_OPTION_TEXT)
                                print(f"  '{OTP_LUCAS_OPTION_TEXT}' seleccionado (select_option)")
                                selected = True
                                break
                            except Exception:
                                pass
                except Exception:
                    continue

            if not selected:
                write_alert("otp_method_change_failed",
                            f"No pude seleccionar '{OTP_LUCAS_OPTION_TEXT}' en el dropdown")
                return False

            time.sleep(1)

            # IMPORTANTE: registrar timestamp ANTES del Send OTP para que el reader
            # ignore OTPs viejos de tests anteriores
            from datetime import timezone
            otp_request_time = datetime.now(timezone.utc)
            print(f"  [T0] Request time: {otp_request_time.isoformat()}")

            # Click "Send OTP"
            sent = False
            for sel in OTP_SEND_BUTTON:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        print(f"  'Send OTP' clickeado ({sel})")
                        sent = True
                        time.sleep(3)
                        break
                except Exception:
                    continue

            if not sent:
                write_alert("send_otp_button_failed", "No encontre boton 'Send OTP'")
                return False

            # Guardar T0 para usar en read_otp_from_gmail
            login_flow._otp_request_time = otp_request_time

        # Leer OTP del Gmail (ahora deberia llegar a Lucas)
        # En debug mode con --skip-otp saltamos el read para no gastar tiempo
        if getattr(main, '_skip_otp', False):
            print("  [SKIP OTP] modo debug - salteando lectura")
            return True
        otp = read_otp_from_gmail(
            max_wait_seconds=90,
            min_timestamp=getattr(login_flow, "_otp_request_time", None),
        )
        if not otp:
            return False

        # Ingresar OTP
        sel_otp = try_selectors(page, OTP_SELECTORS, "fill", otp)
        if not sel_otp:
            write_alert("otp_form_not_found", "No encontre campo OTP")
            return False
        print(f"  OTP ingresado en {sel_otp}")

        # Dispatch input event para que Angular Material habilite el boton Verify
        try:
            page.locator(sel_otp).press("Tab")  # dispara blur/change events
            time.sleep(1)
        except Exception:
            pass

        # Submit OTP - buscar boton "Verify" (Pershing usa "Verify")
        OTP_VERIFY_SELECTORS = [
            'button:has-text("Verify")',
            'button[type="submit"]:not(:disabled)',
            'button[type="submit"]',
        ] + LOGIN_SELECTORS_BUTTON

        verify_clicked = False
        for sel in OTP_VERIFY_SELECTORS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    # Chequear que no este disabled
                    is_disabled = el.get_attribute("disabled")
                    if is_disabled is not None:
                        continue
                    el.click()
                    print(f"  'Verify' clickeado ({sel})")
                    verify_clicked = True
                    time.sleep(4)
                    break
            except Exception:
                continue

        if not verify_clicked:
            # Fallback: Enter en el campo OTP
            print("  Boton Verify no encontrado, intentando Enter en OTP field...")
            try:
                page.locator(sel_otp).press("Enter")
                time.sleep(4)
            except Exception:
                pass

        # POST-OTP: puede aparecer pantalla "Active session" pidiendo Continue
        # para desconectar la otra sesion (Sol, tab viejo, etc.)
        time.sleep(2)
        # Guardar HTML para debug si esta esta pantalla
        try:
            (SESSION_DIR / "post_otp_page_debug.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path=str(SESSION_DIR / "post_otp_page.png"), full_page=True)
        except Exception:
            pass

        active_session_selectors = [
            'button:has-text("Continue")',
            'button:has-text("End Other Session")',
            'button:has-text("End Session")',
            'button:has-text("Sign Off Other")',
            'button:has-text("Log Off Other")',
            'button:has-text("Proceed")',
            'button:has-text("Yes")',
            'button[type="submit"]:not(:disabled)',
        ]

        # Verificar si estamos en una pantalla que menciona "session"
        body_text = ""
        try:
            body_text = page.locator("body").inner_text().lower()
        except Exception:
            pass

        if "active session" in body_text or "another session" in body_text or "session" in body_text:
            print("  Detectada pantalla 'Active session' — buscando Continue...")
            for sel in active_session_selectors:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=2000):
                        is_disabled = el.get_attribute("disabled")
                        if is_disabled is not None:
                            continue
                        el.click()
                        print(f"  Click Continue OK ({sel})")
                        time.sleep(4)
                        break
                except Exception:
                    continue

    # POST-CONTINUE: puede aparecer una pantalla /login/duplicate con otro boton
    # Guardar HTML/screenshot para debug
    time.sleep(3)
    try:
        (SESSION_DIR / "duplicate_page_debug.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(SESSION_DIR / "duplicate_page.png"), full_page=True)
        print(f"  [DEBUG] duplicate page HTML guardado")
    except Exception:
        pass

    # Si estamos en /login/duplicate, buscar boton para continuar
    if "/login/duplicate" in page.url:
        print(f"  En /login/duplicate — buscando boton para continuar...")
        duplicate_selectors = [
            'button:has-text("Continue")',
            'button:has-text("OK")',
            'button:has-text("Proceed")',
            'button:has-text("Go to")',
            'button:has-text("Sign On")',
            'a:has-text("Continue")',
            'button[type="submit"]',
        ]
        for sel in duplicate_selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    is_disabled = el.get_attribute("disabled")
                    if is_disabled is not None:
                        continue
                    el.click()
                    print(f"  Click en duplicate page ({sel})")
                    time.sleep(4)
                    break
            except Exception:
                continue

    # Verificar que estamos logueados (esperar redirect al dashboard real)
    for i in range(15):  # 15s max
        current_url = page.url
        # Si ya salio de las paginas de login/otp/duplicate → login OK
        if "/my-practice" in current_url or "/details" in current_url:
            print(f"  [OK] Login exitoso. URL: {current_url}")
            return True
        # Si sigue en /login raiz plano → fallo
        if current_url.rstrip("/").endswith("/plus/login"):
            write_alert("login_failed", f"Sigue en pagina de login: {current_url}")
            return False
        time.sleep(1)

    write_alert("login_final_check_failed",
                f"Despues de 15s sigue en URL: {page.url}")
    return False


# ============================================================
# DOWNLOAD FLOW
# ============================================================
BASE_URL = "https://www2.netx360.com/plus"

# Cuenta de BIG Fund (LSERIES DAC). Post-login la cuenta default es otra,
# hay que navegar y elegir esta explicitamente.
BIG_ACCOUNT_ID = "JXD101380"


def select_account(page, account_id: str = BIG_ACCOUNT_ID) -> bool:
    """
    Cambia la cuenta activa a account_id.
    Flow (segun Lucas):
      1. Click en "ACCOUNTS" del nav superior
      2. Click en "Accounts" del submenu
      3. Click en la cuenta (primera de la lista para BIG)
    """
    print(f"\n  Seleccionando cuenta {account_id}...")

    # Approach A: click ACCOUNTS del nav + click Accounts del mega-menu
    # Approach B (fallback): navegar directo a la URL de All Accounts
    NAV_ACCOUNTS = [
        'a.nav-item:has-text("ACCOUNTS")',
        'nav a:has-text("ACCOUNTS")',
        'button:has-text("ACCOUNTS")',
        '[role="menuitem"]:has-text("ACCOUNTS")',
        'a:has-text("ACCOUNTS")',
    ]

    # Approach A: intentar click + submenu
    submenu_ok = False
    for sel in NAV_ACCOUNTS:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                print(f"    OK: click nav ACCOUNTS ({sel})")
                break
        except Exception:
            continue
    time.sleep(2)

    # Buscar "Accounts" (exacto, sin CAPS) — con force=True bypass visibility check
    SUBMENU_ACCOUNTS_EXACT = [
        'a:text-is("Accounts")',
        'button:text-is("Accounts")',
        '[role="menuitem"]:text-is("Accounts")',
    ]
    for sel in SUBMENU_ACCOUNTS_EXACT:
        try:
            el = page.locator(sel).first
            # No requiere is_visible — usamos force click para bypass Angular hidden states
            if el.count() > 0:
                el.click(force=True, timeout=3000)
                print(f"    OK: submenu Accounts clickeado ({sel})")
                submenu_ok = True
                break
        except Exception:
            continue

    # Approach B (fallback): navegar directo a la URL de All Accounts.
    # URL confirmada por Lucas 2026-07-16.
    ALL_ACCOUNTS_URLS = [
        f"{BASE_URL}/my-practice/allaccounts/allbalances-ibdoffip",
        f"{BASE_URL}/my-practice/allaccounts/allbalances",
        f"{BASE_URL}/my-practice/allaccounts/accounts",
    ]
    if not submenu_ok:
        print("    [FALLBACK] Mega-menu no abrio — navegando URL directa a All Accounts")
        # Screenshot del estado con el mega-menu (o no) abierto para debug
        try:
            debug_png = SESSION_DIR / "mega_menu_debug.png"
            page.screenshot(path=str(debug_png), full_page=True)
            print(f"    [DEBUG] Screenshot mega-menu: {debug_png}")
        except Exception:
            pass
        for url in ALL_ACCOUNTS_URLS:
            try:
                page.goto(url, timeout=15000)
                # Wait more agresivo para que la tabla ag-Grid renderice
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except Exception:
                    pass
                time.sleep(4)
                print(f"    Navegado a {url} (URL actual: {page.url})")
                submenu_ok = True
                break
            except Exception as e:
                print(f"    Nav a {url} fallo: {e}")
                continue

    if not submenu_ok:
        write_alert("account_selector_submenu_not_found",
                    "No pude llegar a la lista de All Accounts (ni por menu ni por URL)")
        return False

    # Espera larga: la tabla All Accounts tiene 188 records y tarda en renderizar
    print("    Esperando que cargue la tabla All Accounts...")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(4)

    # Paso 3: click en el LINK <a> con texto exacto del account_id via JavaScript.
    # Playwright's is_visible falla con celdas de tabla Angular; JS DOM click es mas robusto.
    url_before = page.url
    link_clicked = False

    # Click con Playwright NATIVO (simula mouseover -> mousedown -> mouseup -> click,
    # que es lo que Angular/ag-Grid necesita para triggering listeners de cell renderer).
    # El elemento es <span class="label text-link"> con text_content = account_id.
    try:
        locator = page.locator('span.text-link', has_text=account_id).first
        if locator.count() > 0:
            locator.scroll_into_view_if_needed(timeout=5000)
            time.sleep(0.5)
            locator.click(timeout=5000)
            print(f"    OK: click Playwright nativo en span.text-link con '{account_id}'")
            link_clicked = True
    except Exception as e:
        print(f"    Click Playwright fallo: {e}")

    # Fallback 1: JS click con dispatchEvent MouseEvent (mas fiel que .click())
    if not link_clicked:
        try:
            result = page.evaluate(f"""() => {{
                const target = "{account_id}";
                const spans = document.querySelectorAll('span.text-link');
                for (const el of spans) {{
                    if ((el.textContent || '').trim() === target) {{
                        // Dispatch MouseEvents en cascada (mas fiel al mouse real)
                        const rect = el.getBoundingClientRect();
                        const opts = {{
                            bubbles: true, cancelable: true, view: window,
                            clientX: rect.left + rect.width/2,
                            clientY: rect.top + rect.height/2,
                        }};
                        el.dispatchEvent(new MouseEvent('mouseover', opts));
                        el.dispatchEvent(new MouseEvent('mousedown', opts));
                        el.dispatchEvent(new MouseEvent('mouseup', opts));
                        el.dispatchEvent(new MouseEvent('click', opts));
                        return {{ ok: true }};
                    }}
                }}
                return {{ ok: false }};
            }}""")
            if result.get("ok"):
                print(f"    OK (fallback JS dispatchEvent)")
                link_clicked = True
        except Exception as e:
            print(f"    Fallback JS fallo: {e}")

    # Fallback 2: buscar <a> hidden asociado (a veces ag-Grid tiene href oculto)
    if not link_clicked:
        try:
            href = page.evaluate(f"""() => {{
                const spans = document.querySelectorAll('span.text-link');
                for (const el of spans) {{
                    if ((el.textContent || '').trim() === "{account_id}") {{
                        // Buscar <a> parent o vecino
                        const a = el.closest('a') || el.parentElement.querySelector('a[href]');
                        if (a && a.href) return a.href;
                    }}
                }}
                return null;
            }}""")
            if href:
                print(f"    Fallback: navegando a href asociado: {href}")
                page.goto(href, timeout=15000)
                link_clicked = True
        except Exception as e:
            print(f"    Fallback href fallo: {e}")

    if not link_clicked:
        # Guardar screenshot + HTML para diagnostico
        try:
            debug_png = SESSION_DIR / "account_list_debug.png"
            debug_html = SESSION_DIR / "account_list_debug.html"
            page.screenshot(path=str(debug_png), full_page=True)
            debug_html.write_text(page.content(), encoding="utf-8", errors="ignore")
            print(f"  [DEBUG] Screenshot: {debug_png}")
            print(f"  [DEBUG] HTML: {debug_html}")
        except Exception:
            pass

        # Diagnostico broad: buscar en TODO el DOM texto con JXD o LSERIES
        print("  Diagnostic — elementos con 'JXD', 'LSERIES', o '101380':")
        try:
            accts = page.evaluate("""() => {
                const items = [];
                const seen = new Set();
                document.querySelectorAll('a, button, tr, td, li, div, span').forEach(el => {
                    const text = (el.innerText || el.textContent || '').trim();
                    if (!text || text.length > 150) return;
                    if (/JXD\\s*\\d{4,7}|LSERIES|101380/i.test(text)) {
                        const key = el.tagName + '|' + text.slice(0, 50);
                        if (seen.has(key)) return;
                        seen.add(key);
                        items.push({
                            tag: el.tagName.toLowerCase(),
                            text: text.slice(0, 80),
                            cls: (el.className || '').toString().slice(0, 60),
                        });
                    }
                });
                return items.slice(0, 25);
            }""")
            for a in accts:
                print(f"    {a}")
            if not accts:
                print("    (nada encontrado — la lista quizas no se abrio)")
                # Dump URL actual
                print(f"    URL actual: {page.url}")
        except Exception as e:
            print(f"    Diagnostic fallo: {e}")

        write_alert("account_selector_account_not_found",
                    f"No pude encontrar {account_id} en la lista de cuentas. Ver {SESSION_DIR}/account_list_debug.png")
        return False

    # Wait for account switch — la data tarda en cargar
    print(f"    Esperando navegacion + carga de data de la cuenta...")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    time.sleep(4)

    # Verificar que el chip "Account" arriba muestra el account_id (Angular SPA
    # no siempre cambia page.url, pero el chip es fuente de verdad).
    account_active = False
    try:
        # Buscar el account_id en cualquier parte del DOM cerca del chip de Account
        chip_text = page.evaluate(f"""() => {{
            // Buscar textos con "{account_id}" cerca del label "Account"
            const body = document.body.innerText || '';
            return body.includes("{account_id}");
        }}""")
        account_active = bool(chip_text)
    except Exception:
        pass

    if not account_active:
        print(f"    [ABORT] El chip Account NO muestra {account_id}. Click no aplico.")
        print(f"    URL actual: {page.url}")
        try:
            page.screenshot(path=str(SESSION_DIR / "account_click_failed.png"), full_page=True)
        except Exception:
            pass
        write_alert("account_link_no_nav",
                    f"Cuenta {account_id} no quedo activa despues del click.")
        return False

    print(f"    URL final: {page.url}")
    print(f"  Cuenta {account_id} seleccionada correctamente (verificado en DOM)")
    return True


def try_click_first_visible(page, selectors, label: str) -> bool:
    """Helper: prueba cada selector; clickea el primero visible. Retorna True si logro clickear."""
    for sel in selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                print(f"    OK: {label} clickeado ({sel})")
                return True
        except Exception:
            continue
    print(f"    FAIL: {label} no encontrado")
    return False

# URLs capturadas del test manual (2026-07-16)
DOWNLOAD_TABS = [
    {
        "name": "Positions",
        "url": f"{BASE_URL}/my-practice/details/positions-account",
        "wait_load": 4,
    },
    {
        "name": "Transactions",
        "url": f"{BASE_URL}/my-practice/details/activity-transactions-account",
        "wait_load": 5,
    },
    {
        "name": "UGL",
        "url": f"{BASE_URL}/my-practice/details/ugl-account",
        "wait_load": 4,
    },
    {
        "name": "RGL",
        "url": f"{BASE_URL}/my-practice/details/rgl-account",
        "wait_load": 4,
    },
]

# Selectores del icono download (confirmados via DevTools inspect el 2026-07-16)
# HTML: <i class="mat-menu-trigger fas fa-download padding-left-5 fa-lg text-link"
#       aria-haspopup="menu"></i>
# Container padre: .grid-Controller_Download
EXPORT_ICON_SELECTORS = [
    'i.mat-menu-trigger.fa-download',
    'i.fa-download.mat-menu-trigger',
    '.grid-Controller_Download i.fa-download',
    '.grid-Controller_Download i.mat-menu-trigger',
    'i.fa-download.text-link',
]

# Opciones dentro del mat-menu que se abre al clickear el icono.
# NetX360+ tiene 2 variantes:
#  Tipo A (Positions, Transactions): items directos "Excel", "CSV", "PDF"
#  Tipo B (UGL, RGL):                items "Export all data", "Export data on this page"
# Ordenamos: Excel primero (Tipo A), despues "Export all data" (Tipo B, toda la data no solo pagina visible)
EXPORT_MENU_OPTIONS = [
    'button.mat-menu-item:has-text("Excel")',
    'button.mat-menu-item:has-text("XLSX")',
    '[role="menuitem"]:has-text("Excel")',
    '[role="menuitem"]:has-text("XLSX")',
    'button.mat-menu-item:has-text("Export all data")',
    '[role="menuitem"]:has-text("Export all data")',
    'button.mat-menu-item:has-text("Export data on this page")',  # fallback si no hay "all"
    '.mat-menu-item:has-text("Excel")',
    '.mat-menu-item:has-text("XLS")',
]


def download_from_tab(page, tab_config, out_dir: Path) -> bool:
    """Navega a un tab, click en icono download -> click en opcion Excel -> captura download."""
    name = tab_config["name"]
    url = tab_config["url"]
    wait = tab_config.get("wait_load", 4)

    print(f"\n  [{name}] Navegando a {url}")
    try:
        page.goto(url, timeout=30000)
    except Exception as e:
        print(f"  [{name}] Nav fallo: {e}")
        write_alert(f"nav_failed_{name.lower()}", str(e))
        return False

    time.sleep(wait)

    # PASO 1: click en el icono download (abre el mat-menu, no descarga aun)
    icon_clicked = False
    for sel in EXPORT_ICON_SELECTORS:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.click()
                print(f"  [{name}] Icono download clickeado ({sel})")
                icon_clicked = True
                break
        except Exception:
            continue

    if not icon_clicked:
        print(f"  [{name}] No encontre icono download.")
        write_alert(f"download_icon_not_found_{name.lower()}",
                    f"No pude encontrar icono download en {url}")
        return False

    # Esperar que el mat-menu se abra
    time.sleep(1)

    # PASO 2: click en la opcion Excel/XLSX del menu (dispara el download)
    with page.expect_download(timeout=30000) as dl_info:
        opt_clicked = False
        clicked_sel = None
        for sel in EXPORT_MENU_OPTIONS:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.click()
                    print(f"  [{name}] Opcion menu clickeada ({sel})")
                    opt_clicked = True
                    clicked_sel = sel
                    break
            except Exception:
                continue

        # Si clickeamos "Export all data" / "Export data on this page",
        # probablemente se abre un sub-menu con formato (Excel/CSV/PDF).
        # Intentamos clickear Excel del sub-menu (silencioso si no aparece).
        if opt_clicked and clicked_sel and 'Export' in clicked_sel and 'data' in clicked_sel:
            time.sleep(1)
            SUBMENU_EXCEL = [
                'button.mat-menu-item:has-text("Excel")',
                'button.mat-menu-item:has-text("XLSX")',
                '[role="menuitem"]:has-text("Excel")',
                '[role="menuitem"]:has-text("XLSX")',
            ]
            for sel in SUBMENU_EXCEL:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1500):
                        el.click()
                        print(f"  [{name}] Sub-menu Excel clickeado ({sel})")
                        break
                except Exception:
                    continue

        if not opt_clicked:
            print(f"  [{name}] No encontre opcion Excel. Items del mat-menu:")
            try:
                items = page.evaluate("""() => {
                    const items = [];
                    document.querySelectorAll(
                        '.mat-menu-item, .mat-mdc-menu-item, [role="menuitem"]'
                    ).forEach(el => {
                        const text = (el.innerText || '').trim();
                        if (text) items.push({
                            tag: el.tagName.toLowerCase(),
                            text: text.slice(0, 40),
                            cls: (el.className || '').toString().slice(0, 80),
                        });
                    });
                    return items.slice(0, 15);
                }""")
                for it in items:
                    print(f"    {it}")
            except Exception:
                pass
            write_alert(f"export_option_not_found_{name.lower()}",
                        f"El mat-menu abrio pero no encontre opcion Excel en {url}")
            return False

    try:
        download = dl_info.value
        fn = download.suggested_filename
        target = out_dir / fn
        download.save_as(str(target))
        size = target.stat().st_size
        print(f"  [{name}] Descargado: {fn} ({size} bytes)")
        return True
    except Exception as e:
        print(f"  [{name}] Download fallo: {e}")
        write_alert(f"download_failed_{name.lower()}", str(e))
        return False


def download_all(page, out_dir: Path) -> dict:
    """Descarga los 4 XLSX. Retorna dict con status por tab."""
    results = {}
    for tab in DOWNLOAD_TABS:
        ok = download_from_tab(page, tab, out_dir)
        results[tab["name"]] = ok
    return results


# ============================================================
# MAIN
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bootstrap", action="store_true",
                    help="Descarga history completa (Last 2 Years). Sino, ultimo mes.")
    ap.add_argument("--headed", action="store_true", help="Ver Chrome (debug)")
    ap.add_argument("--skip-otp", action="store_true",
                    help="Debug: no espera OTP, solo llega hasta el form")
    ap.add_argument("--keep-open", action="store_true",
                    help="Despues del login, deja Chrome abierto y graba tus clicks")
    args = ap.parse_args()
    main._skip_otp = args.skip_otp

    today = date.today().isoformat()
    out_dir = RAW_DIR / today / "netx360"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{datetime.now().isoformat(timespec='seconds')}] NetX360+ auto-download")
    print(f"  Output: {out_dir}")
    print(f"  Mode: {'BOOTSTRAP (2y)' if args.bootstrap else 'DAILY (30d)'}")

    with sync_playwright() as pw:
        # Usar Chromium bundled (NO Chrome del sistema) para evitar conflicto de perfil
        # con Chromes ya abiertos del usuario.
        browser = pw.chromium.launch(
            headless=not args.headed,
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            accept_downloads=True,
            viewport=None,  # usar tamano nativo de la ventana
        )
        page = context.new_page()

        # Login
        login_ok = login_flow(page)
        download_results = None

        # Modo automatico: descargar los 4 XLSX
        if login_ok and not args.keep_open:
            print()
            print("=" * 60)
            print("  LOGIN OK - Cambiando a cuenta BIG y descargando")
            print("=" * 60)

            # Cambiar a la cuenta BIG antes de descargar
            account_ok = select_account(page, BIG_ACCOUNT_ID)
            if not account_ok:
                print("  [ABORT] No pude cambiar de cuenta. No descargo nada.")
                download_results = {"account_switch": False}
            else:
                download_results = download_all(page, out_dir)

            # Filtro Transactions: en daily = Last 30 Days (default de NetX360+),
            # en bootstrap = Last 2 Years (requiere click extra).
            # NOTA: por ahora usamos default de la pagina. Si NetX360+ recuerda
            # el ultimo filtro de la sesion previa, esto funciona (test manual OK).

        # Modo captura: dejar Chrome abierto y grabar clicks
        if login_ok and args.keep_open:
            import json
            events = []
            capture_log = SESSION_DIR / "click_capture_log.json"

            print()
            print("=" * 60)
            print("  LOGIN OK - CHROME QUEDA ABIERTO PARA GRABAR TUS CLICKS")
            print("=" * 60)
            print()
            print("  Vos ahora:")
            print("  1) Positions -> Export CSV")
            print("  2) Transactions -> filtro 'Last 30 Days' -> Export")
            print("  3) Unrealized Gain/Loss -> Export")
            print("  4) Realized Gain/Loss -> Export (YTD default)")
            print("  5) Cerra Chrome cuando termines")
            print()

            # Inyectar grabador de clicks
            page.evaluate("""() => {
                document.addEventListener('click', (e) => {
                    const t = e.target;
                    const rect = t.getBoundingClientRect();
                    const info = {
                        tag: t.tagName.toLowerCase(),
                        id: t.id || '',
                        cls: (t.className || '').toString().slice(0, 120),
                        text: (t.innerText || t.textContent || '').trim().slice(0, 80),
                        href: t.href || '',
                    };
                    console.log('CAPTURED_CLICK:' + JSON.stringify(info));
                }, true);
            }""")

            def on_console(msg):
                text = msg.text
                if text.startswith("CAPTURED_CLICK:"):
                    try:
                        click = json.loads(text[len("CAPTURED_CLICK:"):])
                        ts = datetime.now().isoformat(timespec='seconds')
                        print(f"  [{ts}] CLICK tag={click['tag']} text={click['text']!r:50} cls={click['cls'][:50]!r}")
                        events.append({"time": ts, "type": "click", **click})
                    except Exception:
                        pass

            page.on("console", on_console)

            def on_nav(frame):
                if frame.parent_frame is None and frame.url and frame.url != "about:blank":
                    ts = datetime.now().isoformat(timespec='seconds')
                    print(f"  [{ts}] URL: {frame.url}")
                    events.append({"time": ts, "type": "nav", "url": frame.url})
            page.on("framenavigated", on_nav)

            def on_download(dl):
                fn = dl.suggested_filename
                path = out_dir / fn
                try:
                    dl.save_as(str(path))
                    ts = datetime.now().isoformat(timespec='seconds')
                    print(f"  [{ts}] DOWNLOAD: {fn}")
                    events.append({"time": ts, "type": "download", "filename": fn})
                except Exception as e:
                    print(f"  DOWNLOAD FAIL: {e}")
            page.on("download", on_download)

            # Esperar a que se cierre Chrome
            try:
                while context.pages:
                    page.wait_for_timeout(1000)
            except Exception:
                pass

            capture_log.write_text(
                json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"\n  Log capturado: {capture_log}")
            print(f"  Downloads en: {out_dir}")

        # Cerrar limpio
        try:
            context.close()
            browser.close()
        except Exception:
            pass

    # ===================== VEREDICTO FINAL =====================
    print()
    print("=" * 60)
    if login_ok:
        if download_results is not None:
            ok_count = sum(1 for v in download_results.values() if v)
            total = len(download_results)
            print(f"  RESULTADO: {ok_count}/{total} XLSX descargados")
            print("=" * 60)
            print()
            for name, ok in download_results.items():
                status = "OK" if ok else "FAIL"
                print(f"  {name:15s} {status}")
            print()
            print(f"  Output dir: {out_dir}")
            if ok_count < total:
                print()
                print("  Revisar data/_alerts/ para detalle de los fallos.")
                sys.exit(1)
        else:
            print("  RESULTADO: LOGIN OK (sin descargas, modo keep-open)")
            print("=" * 60)
    else:
        print("  RESULTADO: FALLO EL LOGIN AUTOMATICO")
        print("=" * 60)
        print()
        print("  Revisar carpeta data/_alerts/ para detalle del error.")
        print("  El script escribio una alerta con la causa.")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
