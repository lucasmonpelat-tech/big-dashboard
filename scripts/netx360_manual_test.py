"""
netx360_manual_test.py
=======================
Test manual: abre Chrome visible en NetX360+, autocompleta user+pass desde el
keyring (sin typos), y VOS solo tenes que:
  1) Meter el OTP que llega a tu Gmail
  2) Navegar a Positions y Transactions y descargar los CSVs
  3) Cerrar Chrome

Yo loggeo cada URL/download para armar el automation.
"""
import json
from datetime import datetime
from pathlib import Path
import keyring
from playwright.sync_api import sync_playwright

SESSION_DIR = Path("C:/Users/lmonp/OneDrive/Desktop/Code/big-dashboard/data/netx360_session")
SESSION_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR = SESSION_DIR / "downloads"
DOWNLOAD_DIR.mkdir(exist_ok=True)

URL_LOG = SESSION_DIR / "url_log.txt"
COOKIES_FILE = SESSION_DIR / "cookies.json"

START_URL = "https://www2.netx360.com/plus/my-practice/details/activity-transactions-account"


def try_autofill_login(page):
    """Intenta encontrar campos de user/pass y autofillearlos."""
    user = keyring.get_password("big-netx360", "user")
    pw = keyring.get_password("big-netx360", "pass")
    if not user or not pw:
        print("  ! No hay credenciales en keyring")
        return False

    # Selectores comunes de Pershing/NetX360 - probamos varios
    selectors_user = ['input[name="user"]', 'input[name="userid"]', 'input[name="username"]',
                      'input[id="user"]', 'input[id="userid"]', 'input[id="username"]',
                      'input[type="text"]', 'input[autocomplete="username"]']
    selectors_pass = ['input[name="password"]', 'input[id="password"]',
                      'input[type="password"]', 'input[autocomplete="current-password"]']

    filled_user = False
    for sel in selectors_user:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(user)
                print(f"  [autofill] user en {sel!r}")
                filled_user = True
                break
        except Exception:
            continue

    filled_pass = False
    for sel in selectors_pass:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=2000):
                el.fill(pw)
                print(f"  [autofill] pass en {sel!r}")
                filled_pass = True
                break
        except Exception:
            continue

    return filled_user and filled_pass


def main():
    url_events = []

    print("=" * 60)
    print("TEST MANUAL NetX360+ (con autofill)")
    print("=" * 60)
    print()
    print("Plan:")
    print("  1) Se abre Chrome en NetX360+")
    print("  2) YO autocompleto user + password (los que tenemos guardados)")
    print("  3) VOS solo apretas el boton de Login y meter el OTP del Gmail")
    print("  4) Navegas a Positions -> Export CSV")
    print("  5) Navegas a Transactions -> Export CSV")
    print("  6) Cerras el Chrome")
    print()
    print("Yo voy a loggear cada URL y descarga.")
    print()
    input("Enter para arrancar...")

    with sync_playwright() as pw_ctx:
        browser = pw_ctx.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_DIR / "chrome_profile"),
            headless=False,
            accept_downloads=True,
            downloads_path=str(DOWNLOAD_DIR),
            channel="chrome",
        )

        def log_frame_nav(frame):
            if frame.parent_frame is None:
                url = frame.url
                if url and url != "about:blank":
                    ts = datetime.now().isoformat(timespec='seconds')
                    print(f"  [{ts}] URL: {url}")
                    url_events.append({"time": ts, "url": url})

        def log_download(download):
            fn = download.suggested_filename
            path = DOWNLOAD_DIR / fn
            try:
                download.save_as(str(path))
                ts = datetime.now().isoformat(timespec='seconds')
                print(f"  [{ts}] DOWNLOAD: {fn}")
                url_events.append({"time": ts, "url": f"DOWNLOAD:{fn}", "path": str(path)})
            except Exception as e:
                print(f"  DOWNLOAD FAIL: {e}")

        page = browser.pages[0] if browser.pages else browser.new_page()
        page.on("framenavigated", log_frame_nav)
        page.on("download", log_download)

        print(f"\nAbriendo {START_URL}...")
        try:
            page.goto(START_URL, timeout=30000)
        except Exception as e:
            print(f"  (nav inicial: {e})")

        # Esperar un poco para que cargue login form, e intentar autofill
        print("\nEsperando 3s para que cargue el form de login...")
        page.wait_for_timeout(3000)

        print("\nIntentando autofillear user + password...")
        ok = try_autofill_login(page)
        if ok:
            print("  [OK] Campos completados. Apretá 'Login' vos.")
        else:
            print("  [WARN] No se pudieron detectar los campos automaticamente.")
            print("         Tipealos a mano con cuidado.")

        print("\n" + "=" * 60)
        print("CHROME ABIERTO. HACE EL LOGIN Y NAVEGA.")
        print("Cuando termines, CERRA el Chrome.")
        print("=" * 60)

        try:
            while True:
                page.wait_for_timeout(1000)
                if not browser.pages:
                    break
        except Exception:
            pass

        cookies = browser.cookies()
        COOKIES_FILE.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\nCookies guardadas: {len(cookies)} en {COOKIES_FILE.name}")
        browser.close()

    URL_LOG.write_text(
        "\n".join(f"{e['time']}  {e['url']}" for e in url_events),
        encoding="utf-8",
    )
    print(f"\nLog navegacion: {URL_LOG.name}")
    print(f"Downloads folder: {DOWNLOAD_DIR}")
    print(f"\nURLs unicas: {len(set(e['url'] for e in url_events))}")
    downloads = [e for e in url_events if e['url'].startswith('DOWNLOAD:')]
    print(f"Downloads capturados: {len(downloads)}")
    for d in downloads:
        print(f"  - {d['url']}")


if __name__ == "__main__":
    main()
