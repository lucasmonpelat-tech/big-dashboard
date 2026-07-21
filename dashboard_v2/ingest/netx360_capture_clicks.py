"""
netx360_capture_clicks.py
==========================
Auxiliar de dev: hace login auto, y despues deja Chrome abierto para que
vos hagas los clicks a Positions/Transactions/UGL/RGL y descargues cada XLSX.
Yo loggeo cada click con su selector CSS asi los uso en el automation final.

Uso:
    python dashboard_v2/ingest/netx360_capture_clicks.py
"""
import json
import sys
from datetime import datetime
from pathlib import Path

# Reutilizar las funciones del automation
sys.path.insert(0, str(Path(__file__).parent))
from netx360_auto import login_flow, SESSION_DIR

from playwright.sync_api import sync_playwright

CAPTURE_LOG = SESSION_DIR / "click_capture_log.txt"
DOWNLOADS_DIR = SESSION_DIR / "captured_downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)


def main():
    events = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(accept_downloads=True, viewport=None)
        page = context.new_page()

        # Auto login (ya sabemos que funciona)
        print("=" * 60)
        print("  Auto-login...")
        print("=" * 60)
        if not login_flow(page):
            print("[FAIL] Login abortado. Cerrando.")
            browser.close()
            return

        print("\n" + "=" * 60)
        print("  CHROME ABIERTO - HACE LOS CLICKS QUE QUERES CAPTURAR")
        print("=" * 60)
        print()
        print("  Vos:")
        print("  1) Navega a Positions -> Export CSV/XLSX")
        print("  2) Navega a Transactions -> Export")
        print("  3) Unrealized Gain/Loss -> Export")
        print("  4) Realized Gain/Loss -> Export")
        print("  5) Cerra Chrome cuando termines")
        print()
        print("  Yo estoy grabando cada URL y cada download.")
        print()

        # Grabar cada click en el DOM
        page.evaluate("""() => {
            document.addEventListener('click', (e) => {
                const t = e.target;
                const info = {
                    tag: t.tagName.toLowerCase(),
                    id: t.id || '',
                    cls: (t.className || '').toString().slice(0, 100),
                    text: (t.innerText || t.textContent || '').trim().slice(0, 60),
                    href: t.href || '',
                    dataAttrs: {},
                };
                for (const attr of t.attributes || []) {
                    if (attr.name.startsWith('data-')) info.dataAttrs[attr.name] = attr.value;
                }
                window.__lastClick = info;
                console.log('CAPTURED_CLICK:' + JSON.stringify(info));
            }, true);
        }""")

        # Log consola para ver los clicks
        def on_console(msg):
            text = msg.text
            if text.startswith("CAPTURED_CLICK:"):
                data = text[len("CAPTURED_CLICK:"):]
                try:
                    click = json.loads(data)
                    ts = datetime.now().isoformat(timespec='seconds')
                    print(f"  [{ts}] CLICK: tag={click['tag']!r} text={click['text']!r} id={click['id']!r} cls={click['cls'][:40]!r}")
                    events.append({"time": ts, "type": "click", **click})
                except Exception:
                    pass

        page.on("console", on_console)

        # Log frame nav
        def on_nav(frame):
            if frame.parent_frame is None and frame.url and frame.url != "about:blank":
                ts = datetime.now().isoformat(timespec='seconds')
                print(f"  [{ts}] URL: {frame.url}")
                events.append({"time": ts, "type": "nav", "url": frame.url})
        page.on("framenavigated", on_nav)

        # Log downloads
        def on_download(dl):
            fn = dl.suggested_filename
            path = DOWNLOADS_DIR / fn
            try:
                dl.save_as(str(path))
                ts = datetime.now().isoformat(timespec='seconds')
                print(f"  [{ts}] DOWNLOAD: {fn}")
                events.append({"time": ts, "type": "download", "filename": fn, "path": str(path)})
            except Exception as e:
                print(f"  DOWNLOAD FAIL: {e}")
        page.on("download", on_download)

        # Esperar que se cierre Chrome
        try:
            while True:
                page.wait_for_timeout(1000)
                if not context.pages:
                    break
        except Exception:
            pass

        browser.close()

    # Guardar log
    CAPTURE_LOG.write_text(
        json.dumps(events, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nLog capturado: {CAPTURE_LOG}")
    print(f"Total events: {len(events)}")
    downloads = [e for e in events if e['type'] == 'download']
    print(f"Downloads: {len(downloads)}")


if __name__ == "__main__":
    main()
